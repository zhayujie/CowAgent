"""
Agent Stream Execution Module - Multi-turn reasoning based on tool-call

Provides streaming output, event system, and complete tool-call loop
"""
import json
import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.message_utils import sanitize_claude_messages, compress_turn_to_text_only
from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


# Maximum number of characters of model "reasoning / thinking" content to persist
# in conversation history. The full reasoning is still streamed to the UI in real
# time (subject to its own SSE / rendering limits); this bound only controls what
# is stored in DB and replayed in history. Long reasoning is not useful for later
# context (the LLM never sees thinking blocks anyway) and bloats DB.
# Keep aligned with the frontend REASONING_RENDER_CAP and the SSE
# MAX_REASONING_STREAM_CHARS so that storage / stream / display all match.
MAX_STORED_REASONING_CHARS = 4 * 1024  # 4 KB

# Marker inserted between head and tail when reasoning is truncated.
_REASONING_TRUNCATE_MARKER = "\n\n... [reasoning truncated, {omitted} chars omitted] ...\n\n"


def _truncate_reasoning_for_storage(text: str) -> str:
    """Trim long reasoning to head + tail with an omission marker.

    Keeps the first and last halves of MAX_STORED_REASONING_CHARS so both the
    initial chain-of-thought and the final conclusions are preserved for UI
    replay, without storing the entire (often very large) middle.
    """
    if not text:
        return text
    if len(text) <= MAX_STORED_REASONING_CHARS:
        return text
    half = MAX_STORED_REASONING_CHARS // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - len(head) - len(tail)
    return head + _REASONING_TRUNCATE_MARKER.format(omitted=omitted) + tail


class AgentStreamExecutor:
    """
    Agent Stream Executor
    
    Handles multi-turn reasoning loop based on tool-call:
    1. LLM generates response (may include tool calls)
    2. Execute tools
    3. Return results to LLM
    4. Repeat until no more tool calls
    """

    def __init__(
            self,
            agent,  # Agent instance
            model: LLMModel,
            system_prompt: str,
            tools: List[BaseTool],
            max_turns: int = 50,
            on_event: Optional[Callable] = None,
            messages: Optional[List[Dict]] = None,
            max_context_turns: int = 30
    ):
        """
        Initialize stream executor
        
        Args:
            agent: Agent instance (for accessing context)
            model: LLM model
            system_prompt: System prompt
            tools: List of available tools
            max_turns: Maximum number of turns
            on_event: Event callback function
            messages: Optional existing message history (for persistent conversations)
            max_context_turns: Maximum number of conversation turns to keep in context
        """
        self.agent = agent
        self.model = model
        self.system_prompt = system_prompt
        # Convert tools list to dict
        self.tools = {tool.name: tool for tool in tools} if isinstance(tools, list) else tools
        self.max_turns = max_turns
        self.on_event = on_event
        self.max_context_turns = max_context_turns

        # Message history - use provided messages or create new list
        self.messages = messages if messages is not None else []
        
        # Tool failure tracking for retry protection
        self.tool_failure_history = []  # List of (tool_name, args_hash, success) tuples
        
        # Track files to send (populated by read tool)
        self.files_to_send = []  # List of file metadata dicts

    def _emit_event(self, event_type: str, data: dict = None):
        """Emit event"""
        if self.on_event:
            try:
                self.on_event({
                    "type": event_type,
                    "timestamp": time.time(),
                    "data": data or {}
                })
            except Exception as e:
                logger.error(f"Event callback error: {e}")
    
    def _is_thinking_enabled(self) -> bool:
        """Whether deep-thinking mode is on at the model layer.

        Mirrors the global toggle used by ``bridge.agent_bridge`` when deciding
        whether to send ``thinking={"type": "enabled"}`` to the model. Used for
        logging and reasoning-update event emission across all channels.
        """
        from config import conf
        return bool(conf().get("enable_thinking", False))

    def _should_render_thinking_inline(self) -> bool:
        """Whether ``<think>...</think>`` blocks embedded directly in ``content``
        (MiniMax, some third-party proxies) should be surfaced to the channel.

        Only the Web console can render them in a collapsible panel. IM channels
        (WeChat/WeCom/DingTalk/Feishu) must strip them, otherwise users see raw
        XML tags in their chat.
        """
        from config import conf
        channel_type = getattr(self.model, 'channel_type', '') or ''
        return conf().get("enable_thinking", False) and channel_type == 'web'

    def _filter_think_tags(self, text: str) -> str:
        """
        Handle <think>...</think> blocks in content returned by some LLM providers
        (e.g., MiniMax).

        - When inline thinking rendering is allowed (Web + thinking enabled):
          remove only the tags, keep the content inside.
        - Otherwise (IM channels, or thinking disabled globally): remove both
          the tags and the content entirely.
        """
        if not text:
            return text
        import re
        if self._should_render_thinking_inline():
            text = re.sub(r'<think>', '', text)
            text = re.sub(r'</think>', '', text)
        else:
            text = re.sub(r'<think>[\s\S]*?</think>', '', text)
            # Also strip unclosed <think> tag at the end (streaming partial)
            text = re.sub(r'<think>[\s\S]*$', '', text)
        return text

    def _hash_args(self, args: dict) -> str:
        """Generate a simple hash for tool arguments"""
        import hashlib
        # Sort keys for consistent hashing
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]
    
    def _check_consecutive_failures(self, tool_name: str, args: dict) -> Tuple[bool, str, bool]:
        """
        Check if tool has failed too many times consecutively or called repeatedly with same args
        
        Returns:
            (should_stop, reason, is_critical)
            - should_stop: Whether to stop tool execution
            - reason: Reason for stopping
            - is_critical: Whether to abort entire conversation (True for 8+ failures)
        """
        args_hash = self._hash_args(args)
        
        # Count consecutive calls (both success and failure) for same tool + args
        # This catches infinite loops where tool succeeds but LLM keeps calling it
        same_args_calls = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                same_args_calls += 1
            else:
                break  # Different tool or args, stop counting
        
        # Stop at 5 consecutive calls with same args (whether success or failure)
        if same_args_calls >= 5:
            return True, f"工具 '{tool_name}' 使用相同参数已被调用 {same_args_calls} 次，停止执行以防止无限循环。如果需要查看配置，结果已在之前的调用中返回。", False
        
        # Count consecutive failures for same tool + args
        same_args_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                if not success:
                    same_args_failures += 1
                else:
                    break  # Stop at first success
            else:
                break  # Different tool or args, stop counting
        
        if same_args_failures >= 3:
            return True, f"工具 '{tool_name}' 使用相同参数连续失败 {same_args_failures} 次，停止执行以防止无限循环", False
        
        # Count consecutive failures for same tool (any args)
        same_tool_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name:
                if not success:
                    same_tool_failures += 1
                else:
                    break  # Stop at first success
            else:
                break  # Different tool, stop counting
        
        # Hard stop at 8 failures - abort with critical message
        if same_tool_failures >= 8:
            return True, f"抱歉，我没能完成这个任务。可能是我理解有误或者当前方法不太合适。\n\n建议你：\n• 换个方式描述需求试试\n• 把任务拆分成更小的步骤\n• 或者换个思路来解决", True
        
        # Warning at 6 failures
        if same_tool_failures >= 6:
            return True, f"工具 '{tool_name}' 连续失败 {same_tool_failures} 次（使用不同参数），停止执行以防止无限循环", False
        
        return False, "", False
    
    def _record_tool_result(self, tool_name: str, args: dict, success: bool):
        """Record tool execution result for failure tracking"""
        args_hash = self._hash_args(args)
        self.tool_failure_history.append((tool_name, args_hash, success))
        # Keep only last 50 records to avoid memory bloat
        if len(self.tool_failure_history) > 50:
            self.tool_failure_history = self.tool_failure_history[-50:]

    def run_stream(self, user_message: str) -> str:
        """
        Execute streaming reasoning loop
        
        Args:
            user_message: User message
            
        Returns:
            Final response text
        """
        # Log user message with model info
        
        thinking_enabled = self._is_thinking_enabled()
        thinking_label = " | 💭 thinking" if thinking_enabled else ""
        logger.info(f"🤖 {self.model.model}{thinking_label} | 👤 {user_message}")        
        
        # Add user message (Claude format - use content blocks for consistency)
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_message
                }
            ]
        })

        # Trim context ONCE before the agent loop starts, not during tool steps.
        # This ensures tool_use/tool_result chains created during the current run
        # are never stripped mid-execution (which would cause LLM loops).
        self._trim_messages()

        # Validate after trimming: trimming may leave orphaned tool_use at the
        # boundary (e.g. the last kept turn ends with an assistant tool_use whose
        # tool_result was in a discarded turn).
        self._validate_and_fix_messages()

        self._emit_event("agent_start")

        final_response = ""
        turn = 0

        try:
            while turn < self.max_turns:
                turn += 1
                logger.info(f"[Agent] 第 {turn} 轮")
                self._emit_event("turn_start", {"turn": turn})

                # Call LLM (enable retry_on_empty for better reliability)
                assistant_msg, tool_calls = self._call_llm_stream(retry_on_empty=True)
                final_response = assistant_msg

                # No tool calls, end loop
                if not tool_calls:
                    # 检查是否返回了空响应
                    if not assistant_msg:
                        logger.warning(f"[Agent] LLM returned empty response after retry (no content and no tool calls)")
                        logger.info(f"[Agent] This usually happens when LLM thinks the task is complete after tool execution")
                        
                        # 如果之前有工具调用，强制要求 LLM 生成文本回复
                        if turn > 1:
                            logger.info(f"[Agent] Requesting explicit response from LLM...")
                            
                            # Remember position so we can remove the injected prompt later
                            prompt_insert_idx = len(self.messages)
                            
                            # 添加一条消息，明确要求回复用户
                            self.messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "text",
                                    "text": "请向用户说明刚才工具执行的结果或回答用户的问题。"
                                }]
                            })
                            
                            # 再调用一次 LLM
                            assistant_msg, tool_calls = self._call_llm_stream(retry_on_empty=False)
                            final_response = assistant_msg
                            
                            # Remove the injected prompt from history so it doesn't
                            # appear as a user message in persisted conversations.
                            # _call_llm_stream may have appended an assistant message
                            # after the prompt, so we locate and remove only the prompt.
                            if (prompt_insert_idx < len(self.messages)
                                    and self.messages[prompt_insert_idx].get("role") == "user"):
                                self.messages.pop(prompt_insert_idx)
                                logger.debug("[Agent] Removed injected explicit-response prompt from message history")
                            
                            # If LLM responded with tool_calls instead of text, fall through
                            # to the tool execution path below (don't break the loop).
                            if tool_calls:
                                logger.info(
                                    f"[Agent] LLM returned tool_calls in explicit-response retry, "
                                    f"continuing to execute tools instead of breaking"
                                )
                            elif not assistant_msg:
                                # Still empty (no text and no tool_calls): use fallback
                                logger.warning(f"[Agent] Still empty after explicit request")
                                final_response = (
                                    "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。"
                                )
                                logger.info(f"Generated fallback response for empty LLM output")
                        else:
                            # 第一轮就空回复，直接 fallback
                            final_response = (
                                "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。"
                            )
                            logger.info(f"Generated fallback response for empty LLM output")
                    else:
                        logger.info(f"💭 {assistant_msg[:150]}{'...' if len(assistant_msg) > 150 else ''}")
                    
                    # If the explicit-response retry produced tool_calls, skip the break
                    # and continue down to the tool execution branch in this same iteration.
                    if not tool_calls:
                        logger.debug(f"✅ 完成 (无工具调用)")
                        self._emit_event("turn_end", {
                            "turn": turn,
                            "has_tool_calls": False
                        })
                        break

                # Log tool calls with arguments (truncate long values like base64)
                tool_calls_str = []
                for tc in tool_calls:
                    args = tc.get('arguments') or {}
                    if isinstance(args, dict):
                        parts = []
                        for k, v in args.items():
                            v_str = str(v)
                            if len(v_str) > 200:
                                v_str = v_str[:200] + f"...({len(v_str)} chars)"
                            parts.append(f"{k}={v_str}")
                        args_str = ', '.join(parts)
                        if args_str:
                            tool_calls_str.append(f"{tc['name']}({args_str})")
                        else:
                            tool_calls_str.append(tc['name'])
                    else:
                        tool_calls_str.append(tc['name'])
                logger.info(f"🔧 {', '.join(tool_calls_str)}")

                # Execute tools
                tool_results = []
                tool_result_blocks = []

                try:
                    for tool_call in tool_calls:
                        result = self._execute_tool(tool_call)
                        tool_results.append(result)
                        
                        # Debug: Check if tool is being called repeatedly with same args
                        if turn > 2:
                            # Check last N tool calls for repeats
                            repeat_count = sum(
                                1 for name, ahash, _ in self.tool_failure_history[-10:]
                                if name == tool_call["name"] and ahash == self._hash_args(tool_call["arguments"])
                            )
                            if repeat_count >= 3:
                                logger.warning(
                                    f"⚠️  Tool '{tool_call['name']}' has been called {repeat_count} times "
                                    f"with same arguments. This may indicate a loop."
                                )
                        
                        # Check if this is a file to send
                        if result.get("status") == "success" and isinstance(result.get("result"), dict):
                            result_data = result.get("result")
                            if result_data.get("type") == "file_to_send":
                                self.files_to_send.append(result_data)
                                logger.info(f"📎 检测到待发送文件: {result_data.get('file_name', result_data.get('path'))}")
                                self._emit_event("file_to_send", result_data)
                        
                        # Check for critical error - abort entire conversation
                        if result.get("status") == "critical_error":
                            logger.error(f"💥 检测到严重错误，终止对话")
                            final_response = result.get('result', '任务执行失败')
                            return final_response
                        
                        # Log tool result in compact format
                        status_emoji = "✅" if result.get("status") == "success" else "❌"
                        result_data = result.get('result', '')
                        # Format result string with proper Chinese character support
                        if isinstance(result_data, (dict, list)):
                            result_str = json.dumps(result_data, ensure_ascii=False)
                        else:
                            result_str = str(result_data)
                        logger.info(f"  {status_emoji} {tool_call['name']} ({result.get('execution_time', 0):.2f}s): {result_str[:200]}{'...' if len(result_str) > 200 else ''}")

                        # Build tool result block (Claude format)
                        # Format content in a way that's easy for LLM to understand
                        is_error = result.get("status") == "error"

                        if is_error:
                            # For errors, provide clear error message
                            result_content = f"Error: {result.get('result', 'Unknown error')}"
                        elif isinstance(result.get('result'), dict):
                            # For dict results, use JSON format
                            result_content = json.dumps(result.get('result'), ensure_ascii=False)
                        elif isinstance(result.get('result'), str):
                            # For string results, use directly
                            result_content = result.get('result')
                        else:
                            # Fallback to full JSON
                            result_content = json.dumps(result, ensure_ascii=False)

                        # Truncate excessively large tool results for the current turn
                        # Historical turns will be further truncated in _trim_messages()
                        MAX_CURRENT_TURN_RESULT_CHARS = 50000
                        if len(result_content) > MAX_CURRENT_TURN_RESULT_CHARS:
                            truncated_len = len(result_content)
                            result_content = result_content[:MAX_CURRENT_TURN_RESULT_CHARS] + \
                                f"\n\n[Output truncated: {truncated_len} chars total, showing first {MAX_CURRENT_TURN_RESULT_CHARS} chars]"
                            logger.info(f"📎 Truncated tool result for '{tool_call['name']}': {truncated_len} -> {MAX_CURRENT_TURN_RESULT_CHARS} chars")

                        tool_result_block = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": result_content
                        }
                        
                        # Add is_error field for Claude API (helps model understand failures)
                        if is_error:
                            tool_result_block["is_error"] = True
                        
                        tool_result_blocks.append(tool_result_block)
                
                finally:
                    # CRITICAL: Always add tool_result to maintain message history integrity
                    # Even if tool execution fails, we must add error results to match tool_use
                    if tool_result_blocks:
                        # Add tool results to message history as user message (Claude format)
                        self.messages.append({
                            "role": "user",
                            "content": tool_result_blocks
                        })
                        
                        # Detect potential infinite loop: same tool called multiple times with success
                        # If detected, add a hint to LLM to stop calling tools and provide response
                        if turn >= 3 and len(tool_calls) > 0:
                            tool_name = tool_calls[0]["name"]
                            args_hash = self._hash_args(tool_calls[0]["arguments"])
                            
                            # Count recent successful calls with same tool+args
                            recent_success_count = 0
                            for name, ahash, success in reversed(self.tool_failure_history[-10:]):
                                if name == tool_name and ahash == args_hash and success:
                                    recent_success_count += 1
                            
                            # If tool was called successfully 3+ times with same args, add hint to stop loop
                            if recent_success_count >= 3:
                                logger.warning(
                                    f"⚠️  Detected potential loop: '{tool_name}' called {recent_success_count} times "
                                    f"with same args. Adding hint to LLM to provide final response."
                                )
                                # Add a gentle hint message to guide LLM to respond
                                self.messages.append({
                                    "role": "user",
                                    "content": [{
                                        "type": "text",
                                        "text": "工具已成功执行并返回结果。请基于这些信息向用户做出回复，不要重复调用相同的工具。"
                                    }]
                                })
                    elif tool_calls:
                        # If we have tool_calls but no tool_result_blocks (unexpected error),
                        # create error results for all tool calls to maintain message integrity
                        logger.warning("⚠️ Tool execution interrupted, adding error results to maintain message history")
                        emergency_blocks = []
                        for tool_call in tool_calls:
                            emergency_blocks.append({
                                "type": "tool_result",
                                "tool_use_id": tool_call["id"],
                                "content": "Error: Tool execution was interrupted",
                                "is_error": True
                            })
                        self.messages.append({
                            "role": "user",
                            "content": emergency_blocks
                        })

                self._emit_event("turn_end", {
                    "turn": turn,
                    "has_tool_calls": True,
                    "tool_count": len(tool_calls)
                })

            if turn >= self.max_turns:
                logger.warning(f"⚠️  已达到最大决策步数限制: {self.max_turns}")
                
                # Force model to summarize without tool calls
                logger.info(f"[Agent] Requesting summary from LLM after reaching max steps...")
                
                # Remember position before injecting the prompt so we can remove it later
                prompt_insert_idx = len(self.messages)
                
                # Add a temporary prompt to force summary
                self.messages.append({
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": f"你已经执行了{turn}个决策步骤，达到了单次运行的最大步数限制。请总结一下你目前的执行过程和结果，告诉用户当前的进展情况。不要再调用工具，直接用文字回复。"
                    }]
                })
                
                # Call LLM one more time to get summary (without retry to avoid loops)
                try:
                    summary_response, summary_tools = self._call_llm_stream(retry_on_empty=False)
                    if summary_response:
                        final_response = summary_response
                        logger.info(f"💭 Summary: {summary_response[:150]}{'...' if len(summary_response) > 150 else ''}")
                    else:
                        # Fallback if model still doesn't respond
                        final_response = (
                            f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。"
                            "任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。"
                        )
                except Exception as e:
                    logger.warning(f"Failed to get summary from LLM: {e}")
                    final_response = (
                        f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。"
                        "任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。"
                    )
                finally:
                    # Remove the injected user prompt from history to avoid polluting
                    # persisted conversation records. The assistant summary (if any)
                    # was already appended by _call_llm_stream and is kept.
                    if (prompt_insert_idx < len(self.messages)
                            and self.messages[prompt_insert_idx].get("role") == "user"):
                        self.messages.pop(prompt_insert_idx)
                        logger.debug("[Agent] Removed injected max-steps prompt from message history")

        except Exception as e:
            logger.error(f"❌ Agent执行错误: {e}")
            self._emit_event("error", {"error": str(e)})
            raise

        finally:
            final_response = final_response.strip() if final_response else final_response
            logger.info(f"[Agent] 🏁 完成 ({turn}轮)")
            self._emit_event("agent_end", {"final_response": final_response})

        return final_response

    def _call_llm_stream(self, retry_on_empty=True, retry_count=0, max_retries=3,
                         _overflow_retry: bool = False) -> Tuple[str, List[Dict]]:
        """
        Call LLM with streaming and automatic retry on errors
        
        Args:
            retry_on_empty: Whether to retry once if empty response is received
            retry_count: Current retry attempt (internal use)
            max_retries: Maximum number of retries for API errors
            _overflow_retry: Internal flag indicating this is a retry after context overflow
        
        Returns:
            (response_text, tool_calls)
        """
        # Validate and fix message history (e.g. orphaned tool_result blocks).
        # Context trimming is done once in run_stream() before the loop starts,
        # NOT here — trimming mid-execution would strip the current run's
        # tool_use/tool_result chains and cause LLM loops.
        self._validate_and_fix_messages()

        # Prepare messages
        messages = self._prepare_messages()
        turns = self._identify_complete_turns()
        logger.info(f"Sending {len(messages)} messages ({len(turns)} turns) to LLM")

        # Pull in any MCP tools that finished loading since this turn started.
        # Cheap dict reconciliation (microseconds) — lets the agent pick up
        # newly available MCP tools mid-conversation without a session restart.
        try:
            from agent.tools import ToolManager
            ToolManager().sync_mcp_into_agent(self)
        except Exception as e:
            logger.debug(f"[Agent] MCP sync skipped: {e}")

        # Prepare tool definitions (OpenAI/Claude format)
        tools_schema = None
        if self.tools:
            tools_schema = []
            for tool in self.tools.values():
                tools_schema.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.params  # Claude uses input_schema
                })

        # Create request
        request = LLMRequest(
            messages=messages,
            temperature=0,
            stream=True,
            tools=tools_schema,
            system=self.system_prompt  # Pass system prompt separately for Claude API
        )

        self._emit_event("message_start", {"role": "assistant"})

        # Streaming response
        full_content = ""
        full_reasoning = ""
        tool_calls_buffer = {}  # {index: {id, name, arguments}}
        gemini_raw_parts = None  # Preserve Gemini thoughtSignature for round-trip
        stop_reason = None  # Track why the stream stopped

        try:
            stream = self.model.call_stream(request)

            for chunk in stream:
                # Check for errors
                if isinstance(chunk, dict) and chunk.get("error"):
                    # Extract error message from nested structure
                    error_data = chunk.get("error", {})
                    if isinstance(error_data, dict):
                        error_msg = error_data.get("message", chunk.get("message", "Unknown error"))
                        error_code = error_data.get("code", "")
                        error_type = error_data.get("type", "")
                    else:
                        error_msg = chunk.get("message", str(error_data))
                        error_code = ""
                        error_type = ""
                    
                    status_code = chunk.get("status_code", "N/A")
                    
                    # Log error with all available information
                    logger.error(f"🔴 Stream API Error:")
                    logger.error(f"   Message: {error_msg}")
                    logger.error(f"   Status Code: {status_code}")
                    logger.error(f"   Error Code: {error_code}")
                    logger.error(f"   Error Type: {error_type}")
                    logger.error(f"   Full chunk: {chunk}")
                    
                    # Check if this is a context overflow error (keyword-based, works for all models)
                    # Don't rely on specific status codes as different providers use different codes
                    error_msg_lower = error_msg.lower()
                    is_overflow = any(keyword in error_msg_lower for keyword in [
                        'context length exceeded', 'maximum context length', 'prompt is too long',
                        'context overflow', 'context window', 'too large', 'exceeds model context',
                        'request_too_large', 'request exceeds the maximum size', 'tokens exceed'
                    ])
                    
                    if is_overflow:
                        # Mark as context overflow for special handling
                        raise Exception(f"[CONTEXT_OVERFLOW] {error_msg} (Status: {status_code})")
                    else:
                        # Raise exception with full error message for retry logic
                        raise Exception(f"{error_msg} (Status: {status_code}, Code: {error_code}, Type: {error_type})")

                # Parse chunk
                if isinstance(chunk, dict) and chunk.get("choices"):
                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    
                    # Capture finish_reason if present
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        stop_reason = finish_reason

                    reasoning_delta = delta.get("reasoning_content") or ""
                    if reasoning_delta:
                        full_reasoning += reasoning_delta
                        if self._is_thinking_enabled():
                            self._emit_event("reasoning_update", {"delta": reasoning_delta})

                    # Handle text content
                    content_delta = delta.get("content") or ""
                    if content_delta:
                        # Filter out <think> tags from content
                        filtered_delta = self._filter_think_tags(content_delta)
                        full_content += filtered_delta
                        if filtered_delta:  # Only emit if there's content after filtering
                            self._emit_event("message_update", {"delta": filtered_delta})

                    # Handle tool calls
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_delta in delta["tool_calls"]:
                            index = tc_delta.get("index", 0)

                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }

                            if tc_delta.get("id"):
                                tool_calls_buffer[index]["id"] = tc_delta["id"]

                            if "function" in tc_delta:
                                func = tc_delta["function"]
                                if func.get("name"):
                                    tool_calls_buffer[index]["name"] = func["name"]
                                if func.get("arguments"):
                                    tool_calls_buffer[index]["arguments"] += func["arguments"]

                    # Preserve _gemini_raw_parts for Gemini thoughtSignature round-trip
                    # (direct Gemini: list of parts; LinkAI proxy: base64 string of JSON parts)
                    if "_gemini_raw_parts" in delta:
                        gemini_raw_parts = delta["_gemini_raw_parts"]
                    elif isinstance(choice, dict) and choice.get("_gemini_raw_parts"):
                        gemini_raw_parts = choice["_gemini_raw_parts"]

        except Exception as e:
            error_str = str(e)
            error_str_lower = error_str.lower()
            
            # Check if error is context overflow (non-retryable, needs session reset)
            # Method 1: Check for special marker (set in stream error handling above)
            is_context_overflow = '[context_overflow]' in error_str_lower
            
            # Method 2: Fallback to keyword matching for non-stream errors
            if not is_context_overflow:
                is_context_overflow = any(keyword in error_str_lower for keyword in [
                    'context length exceeded', 'maximum context length', 'prompt is too long',
                    'context overflow', 'context window', 'too large', 'exceeds model context',
                    'request_too_large', 'request exceeds the maximum size'
                ])
            
            # Check if error is message format error (incomplete tool_use/tool_result pairs)
            # This happens when previous conversation had tool failures or context trimming
            # broke tool_use/tool_result pairs.
            # Note: MiniMax returns error 2013 "tool result's tool id(...) not found" for
            # tool_call_id mismatches — the keywords below are intentionally broad to catch
            # both standard (Claude/OpenAI) and provider-specific (MiniMax) variants.
            is_message_format_error = any(keyword in error_str_lower for keyword in [
                'tool_use', 'tool_result', 'tool result', 'without', 'immediately after',
                'corresponding', 'must have', 'each',
                'tool_call_id', 'tool id', 'is not found', 'not found', 'tool_calls',
                'must be a response to a preceeding message',
                '2013',  # MiniMax error code for tool_call_id mismatch
            ]) and ('400' in error_str_lower or 'status: 400' in error_str_lower
                     or 'invalid_request' in error_str_lower
                     or 'invalidparameter' in error_str_lower)
            
            if is_context_overflow or is_message_format_error:
                error_type = "context overflow" if is_context_overflow else "message format error"
                logger.error(f"💥 {error_type} detected: {e}")

                # Flush memory before trimming to preserve context that will be lost
                if is_context_overflow and self.agent.memory_manager:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    self.agent.memory_manager.flush_memory(
                        messages=self.messages, user_id=user_id,
                        reason="overflow", max_messages=0
                    )

                # Strategy: try aggressive trimming first, only clear as last resort
                if is_context_overflow and not _overflow_retry:
                    trimmed = self._aggressive_trim_for_overflow()
                    if trimmed:
                        logger.warning("🔄 Aggressively trimmed context, retrying...")
                        return self._call_llm_stream(
                            retry_on_empty=retry_on_empty,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            _overflow_retry=True
                        )

                # Aggressive trim didn't help or this is a message format error
                # -> clear everything and also purge DB to prevent reload of dirty data
                logger.warning("🔄 Clearing conversation history to recover")
                self.messages.clear()
                self._clear_session_db()
                if is_context_overflow:
                    raise Exception(
                        "抱歉，对话历史过长导致上下文溢出。我已清空历史记录，请重新描述你的需求。"
                    )
                else:
                    raise Exception(
                        "抱歉，之前的对话出现了问题。我已清空历史记录，请重新发送你的消息。"
                    )
            
            # Check if error is rate limit (429)
            is_rate_limit = '429' in error_str_lower or 'rate limit' in error_str_lower
            
            # Check if error is retryable (timeout, connection, server busy, etc.)
            is_retryable = any(keyword in error_str_lower for keyword in [
                'timeout', 'timed out', 'connection', 'network', 
                'rate limit', 'overloaded', 'unavailable', 'busy', 'retry',
                '429', '500', '502', '503', '504', '512'
            ])
            
            if is_retryable and retry_count < max_retries:
                # Rate limit needs longer wait time
                if is_rate_limit:
                    wait_time = 30 + (retry_count * 15)  # 30s, 45s, 60s for rate limit
                else:
                    wait_time = (retry_count + 1) * 2  # 2s, 4s, 6s for other errors
                
                logger.warning(f"⚠️ LLM API error (attempt {retry_count + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                return self._call_llm_stream(
                    retry_on_empty=retry_on_empty, 
                    retry_count=retry_count + 1,
                    max_retries=max_retries
                )
            else:
                if retry_count >= max_retries:
                    logger.error(f"❌ LLM API error after {max_retries} retries: {e}", exc_info=True)
                else:
                    logger.error(f"❌ LLM call error (non-retryable): {e}", exc_info=True)
                raise

        # Parse tool calls
        tool_calls = []
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]

            # Ensure tool call has a valid ID (some providers return empty/None IDs)
            tool_id = tc.get("id") or ""
            if not tool_id:
                import uuid
                tool_id = f"call_{uuid.uuid4().hex[:24]}"

            try:
                # Safely get arguments, handle None case
                args_str = tc.get("arguments") or ""
                arguments = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError as e:
                # Handle None or invalid arguments safely
                args_str = tc.get('arguments') or ""
                args_preview = args_str[:200] if len(args_str) > 200 else args_str
                logger.error(f"Failed to parse tool arguments for {tc['name']}")
                logger.error(f"Arguments length: {len(args_str)} chars")
                logger.error(f"Arguments preview: {args_preview}...")
                logger.error(f"JSON decode error: {e}")

                # Return a clear error message to the LLM instead of empty dict
                # This helps the LLM understand what went wrong
                tool_calls.append({
                    "id": tool_id,
                    "name": tc["name"],
                    "arguments": {},
                    "_parse_error": f"Invalid JSON in tool arguments: {args_preview}... Error: {str(e)}. Tip: For large content, consider splitting into smaller chunks or using a different approach."
                })
                continue

            tool_calls.append({
                "id": tool_id,
                "name": tc["name"],
                "arguments": arguments
            })

        # Check for empty response and retry once if enabled
        if retry_on_empty and not full_content and not tool_calls:
            logger.warning(f"⚠️  LLM returned empty response (stop_reason: {stop_reason}), retrying once...")
            self._emit_event("message_end", {
                "content": "",
                "tool_calls": [],
                "empty_retry": True,
                "stop_reason": stop_reason
            })
            # Retry without retry flag to avoid infinite loop
            return self._call_llm_stream(
                retry_on_empty=False, 
                retry_count=retry_count,
                max_retries=max_retries
            )

        # Filter full_content one more time (in case tags were split across chunks)
        full_content = self._filter_think_tags(full_content)
        
        # Add assistant message to history (Claude format uses content blocks)
        assistant_msg = {"role": "assistant", "content": []}

        if full_reasoning:
            stored_reasoning = _truncate_reasoning_for_storage(full_reasoning)
            if len(stored_reasoning) < len(full_reasoning):
                logger.info(
                    f"[reasoning] truncated for storage: "
                    f"{len(full_reasoning)} -> {len(stored_reasoning)} chars"
                )
            assistant_msg["content"].append({
                "type": "thinking",
                "thinking": stored_reasoning
            })

        if full_content:
            assistant_msg["content"].append({
                "type": "text",
                "text": full_content
            })

        # Add tool_use blocks if present
        if tool_calls:
            for tc in tool_calls:
                assistant_msg["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("arguments", {})
                })
        
        if gemini_raw_parts:
            assistant_msg["_gemini_raw_parts"] = gemini_raw_parts

        # Only append if content is not empty
        if assistant_msg["content"]:
            self.messages.append(assistant_msg)

        self._emit_event("message_end", {
            "content": full_content,
            "tool_calls": tool_calls
        })

        return full_content, tool_calls

    def _execute_tool(self, tool_call: Dict) -> Dict[str, Any]:
        """
        Execute tool
        
        Args:
            tool_call: {"id": str, "name": str, "arguments": dict}
            
        Returns:
            Tool execution result
        """
        tool_name = tool_call["name"]
        tool_id = tool_call["id"]
        arguments = tool_call["arguments"]

        # Check if there was a JSON parse error
        if "_parse_error" in tool_call:
            parse_error = tool_call["_parse_error"]
            logger.error(f"Skipping tool execution due to parse error: {parse_error}")
            result = {
                "status": "error",
                "result": f"Failed to parse tool arguments. {parse_error}. Please ensure your tool call uses valid JSON format with all required parameters.",
                "execution_time": 0
            }
            self._record_tool_result(tool_name, arguments, False)
            return result

        # Check for consecutive failures (retry protection)
        should_stop, stop_reason, is_critical = self._check_consecutive_failures(tool_name, arguments)
        if should_stop:
            logger.error(f"🛑 {stop_reason}")
            self._record_tool_result(tool_name, arguments, False)
            
            if is_critical:
                # Critical failure - abort entire conversation
                result = {
                    "status": "critical_error",
                    "result": stop_reason,
                    "execution_time": 0
                }
            else:
                # Normal failure - let LLM try different approach
                result = {
                    "status": "error",
                    "result": f"{stop_reason}\n\n当前方法行不通，请尝试完全不同的方法或向用户询问更多信息。",
                    "execution_time": 0
                }
            return result

        self._emit_event("tool_execution_start", {
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments": arguments
        })

        try:
            tool = self.tools.get(tool_name)
            if not tool:
                raise ValueError(self._build_tool_not_found_message(tool_name))

            # Set tool context
            tool.model = self.model
            tool.context = self.agent

            # Execute tool
            start_time = time.time()
            result: ToolResult = tool.execute_tool(arguments)
            execution_time = time.time() - start_time

            result_dict = {
                "status": result.status,
                "result": result.result,
                "execution_time": execution_time
            }

            # Record tool result for failure tracking
            success = result.status == "success"
            self._record_tool_result(tool_name, arguments, success)

            # Auto-refresh skills after skill creation
            if tool_name == "bash" and result.status == "success":
                command = arguments.get("command", "")
                if "init_skill.py" in command and self.agent.skill_manager:
                    logger.info("Detected skill creation, refreshing skills...")
                    self.agent.refresh_skills()
                    logger.info(f"Skills refreshed! Now have {len(self.agent.skill_manager.skills)} skills")

            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **result_dict
            })

            return result_dict

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            error_result = {
                "status": "error",
                "result": str(e),
                "execution_time": 0
            }
            # Record failure
            self._record_tool_result(tool_name, arguments, False)
            
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **error_result
            })
            return error_result

    def _build_tool_not_found_message(self, tool_name: str) -> str:
        """Build a helpful error message when a tool is not found.

        If a skill with the same name exists in skill_manager, read its
        SKILL.md and include the content so the LLM knows how to use it.
        """
        available_tools = list(self.tools.keys())
        base_msg = f"Tool '{tool_name}' not found. Available tools: {available_tools}"

        skill_manager = getattr(self.agent, 'skill_manager', None)
        if not skill_manager:
            return base_msg

        skill_entry = skill_manager.get_skill(tool_name)
        if not skill_entry:
            return base_msg

        skill = skill_entry.skill
        skill_md_path = skill.file_path
        skill_content = ""
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                skill_content = f.read()
        except Exception:
            skill_content = skill.description

        logger.info(
            f"[Agent] Tool '{tool_name}' not found, but matched skill '{skill.name}'. "
            f"Guiding LLM to use the skill instead."
        )

        return (
            f"Tool '{tool_name}' is not a built-in tool, but a matching skill "
            f"'{skill.name}' is available. You should use existing tools (e.g. bash with curl) "
            f"to accomplish this task following the skill instructions below:\n\n"
            f"--- SKILL: {skill.name} (path: {skill_md_path}) ---\n"
            f"{skill_content}\n"
            f"--- END SKILL ---\n\n"
            f"Available tools: {available_tools}"
        )

    def _validate_and_fix_messages(self):
        """Delegate to the shared sanitizer (see message_sanitizer.py)."""
        sanitize_claude_messages(self.messages)

    def _identify_complete_turns(self) -> List[Dict]:
        """
        识别完整的对话轮次
        
        一个完整轮次包括：
        1. 用户消息（text）
        2. AI 回复（可能包含 tool_use）
        3. 工具结果（tool_result，如果有）
        4. 后续 AI 回复（如果有）
        
        Returns:
            List of turns, each turn is a dict with 'messages' list
        """
        turns = []
        current_turn = {'messages': []}
        
        for msg in self.messages:
            role = msg.get('role')
            content = msg.get('content', [])
            
            if role == 'user':
                # Determine if this is a real user query (not a tool_result injection
                # or an internal hint message injected by the agent loop).
                is_user_query = False
                has_tool_result = False
                if isinstance(content, list):
                    has_text = any(
                        isinstance(block, dict) and block.get('type') == 'text'
                        for block in content
                    )
                    has_tool_result = any(
                        isinstance(block, dict) and block.get('type') == 'tool_result'
                        for block in content
                    )
                    # A message with tool_result is always internal, even if it
                    # also contains text blocks (shouldn't happen, but be safe).
                    is_user_query = has_text and not has_tool_result
                elif isinstance(content, str):
                    is_user_query = True
                
                if is_user_query:
                    if current_turn['messages']:
                        turns.append(current_turn)
                    current_turn = {'messages': [msg]}
                else:
                    current_turn['messages'].append(msg)
            else:
                # AI 回复，属于当前轮次
                current_turn['messages'].append(msg)
        
        # 添加最后一个轮次
        if current_turn['messages']:
            turns.append(current_turn)
        
        return turns
    
    def _estimate_turn_tokens(self, turn: Dict) -> int:
        """估算一个轮次的 tokens"""
        return sum(
            self.agent._estimate_message_tokens(msg) 
            for msg in turn['messages']
        )

    def _truncate_historical_tool_results(self):
        """
        Truncate tool_result content in historical messages to reduce context size.

        Current turn results are kept at 30K chars (truncated at creation time).
        Historical turn results are further truncated to 10K chars here.
        This runs before token-based trimming so that we first shrink oversized
        results, potentially avoiding the need to drop entire turns.
        """
        MAX_HISTORY_RESULT_CHARS = 20000

        if len(self.messages) < 2:
            return

        # Find where the last user text message starts (= current turn boundary)
        # We skip the current turn's messages to preserve their full content
        current_turn_start = len(self.messages)
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "text" for b in content
                ):
                    current_turn_start = i
                    break
                elif isinstance(content, str):
                    current_turn_start = i
                    break

        truncated_count = 0
        for i in range(current_turn_start):
            msg = self.messages[i]
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                result_str = block.get("content", "")
                if isinstance(result_str, str) and len(result_str) > MAX_HISTORY_RESULT_CHARS:
                    original_len = len(result_str)
                    block["content"] = result_str[:MAX_HISTORY_RESULT_CHARS] + \
                        f"\n\n[Historical output truncated: {original_len} -> {MAX_HISTORY_RESULT_CHARS} chars]"
                    truncated_count += 1

        if truncated_count > 0:
            logger.info(f"📎 Truncated {truncated_count} historical tool result(s) to {MAX_HISTORY_RESULT_CHARS} chars")

    def _aggressive_trim_for_overflow(self) -> bool:
        """
        Aggressively trim context when a real overflow error is returned by the API.

        This method goes beyond normal _trim_messages by:
        1. Truncating all tool results (including current turn) to a small limit
        2. Keeping only the last 5 complete conversation turns
        3. Truncating overly long user messages

        Returns:
            True if messages were trimmed (worth retrying), False if nothing left to trim
        """
        if not self.messages:
            return False

        original_count = len(self.messages)

        # Step 1: Aggressively truncate ALL tool results to 5K chars
        AGGRESSIVE_LIMIT = 10000
        truncated = 0
        for msg in self.messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                # Truncate tool_result blocks
                if block.get("type") == "tool_result":
                    result_str = block.get("content", "")
                    if isinstance(result_str, str) and len(result_str) > AGGRESSIVE_LIMIT:
                        block["content"] = (
                            result_str[:AGGRESSIVE_LIMIT]
                            + f"\n\n[Truncated for context recovery: "
                            f"{len(result_str)} -> {AGGRESSIVE_LIMIT} chars]"
                        )
                        truncated += 1
                # Truncate tool_use input blocks (e.g. large write content)
                if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                    input_str = json.dumps(block["input"], ensure_ascii=False)
                    if len(input_str) > AGGRESSIVE_LIMIT:
                        # Keep only a summary of the input
                        for key, val in block["input"].items():
                            if isinstance(val, str) and len(val) > 1000:
                                block["input"][key] = (
                                    val[:1000]
                                    + f"... [truncated {len(val)} chars]"
                                )
                        truncated += 1

        # Step 2: Truncate overly long user text messages (e.g. pasted content)
        USER_MSG_LIMIT = 10000
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if len(text) > USER_MSG_LIMIT:
                            block["text"] = (
                                text[:USER_MSG_LIMIT]
                                + f"\n\n[Message truncated for context recovery: "
                                f"{len(text)} -> {USER_MSG_LIMIT} chars]"
                            )
                            truncated += 1
            elif isinstance(content, str) and len(content) > USER_MSG_LIMIT:
                msg["content"] = (
                    content[:USER_MSG_LIMIT]
                    + f"\n\n[Message truncated for context recovery: "
                    f"{len(content)} -> {USER_MSG_LIMIT} chars]"
                )
                truncated += 1

        # Step 3: Keep only the last 5 complete turns
        turns = self._identify_complete_turns()
        if len(turns) > 5:
            kept_turns = turns[-5:]
            new_messages = []
            for turn in kept_turns:
                new_messages.extend(turn["messages"])
            removed = len(turns) - 5
            self.messages[:] = new_messages
            logger.info(
                f"🔧 Aggressive trim: removed {removed} old turns, "
                f"truncated {truncated} large blocks, "
                f"{original_count} -> {len(self.messages)} messages"
            )
            return True

        if truncated > 0:
            logger.info(
                f"🔧 Aggressive trim: truncated {truncated} large blocks "
                f"(no turns removed, only {len(turns)} turn(s) left)"
            )
            return True

        # Nothing left to trim
        logger.warning("🔧 Aggressive trim: nothing to trim, will clear history")
        return False

    def _build_context_summary_callback(self, discarded_turns: list, kept_turns: list):
        """
        Build a callback that injects an LLM summary into the first user
        message of *kept_turns*. Returns None if no valid injection target.

        The callback is passed to flush_from_messages so that the same LLM
        call that writes daily memory also provides the in-context summary.
        """
        if not kept_turns:
            return None

        # Find the first user text block in kept_turns as injection target
        target_block = None
        for turn in kept_turns:
            for msg in turn["messages"]:
                if msg.get("role") == "user":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                target_block = block
                                break
                    if target_block:
                        break
            if target_block:
                break

        if not target_block:
            return None

        turn_count = len(discarded_turns)
        original_text = target_block["text"]

        def _on_summary_ready(summary: str):
            if not summary or not summary.strip():
                return
            target_block["text"] = (
                f"[System: Previous conversation summary — "
                f"{turn_count} turns were compacted]\n\n"
                f"{summary.strip()}\n\n"
                f"The recent conversation continues below.\n\n---\n\n"
                f"{original_text}"
            )
            logger.info(
                f"📝 Context summary injected "
                f"({len(summary)} chars, {turn_count} turns)"
            )

        return _on_summary_ready

    def _trim_messages(self):
        """
        智能清理消息历史，保持对话完整性

        使用完整轮次作为清理单位，确保：
        1. 不会在对话中间截断
        2. 工具调用链（tool_use + tool_result）保持完整
        3. 每轮对话都是完整的（用户消息 + AI回复 + 工具调用）
        """
        if not self.messages or not self.agent:
            return

        # Step 0: Truncate large tool results in historical turns (30K -> 10K)
        self._truncate_historical_tool_results()

        # Step 1: 识别完整轮次
        turns = self._identify_complete_turns()
        
        if not turns:
            return
        
        # Step 2: 轮次限制 - 超出时移除前一半，保留后一半
        if len(turns) > self.max_context_turns:
            removed_count = len(turns) // 2
            keep_count = len(turns) - removed_count
            
            discarded_turns = turns[:removed_count]
            turns = turns[-keep_count:]

            logger.info(
                f"💾 上下文轮次超限: {keep_count + removed_count} > {self.max_context_turns}，"
                f"裁剪至 {keep_count} 轮（移除 {removed_count} 轮）"
            )

            # Flush to daily memory + inject context summary (single async LLM call)
            if self.agent.memory_manager:
                discarded_messages = []
                for turn in discarded_turns:
                    discarded_messages.extend(turn["messages"])
                if discarded_messages:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    cb = self._build_context_summary_callback(discarded_turns, turns)
                    self.agent.memory_manager.flush_memory(
                        messages=discarded_messages, user_id=user_id,
                        reason="trim", max_messages=0,
                        context_summary_callback=cb,
                    )

        # Step 3: Token 限制 - 保留完整轮次
        # Get context window from agent (based on model)
        context_window = self.agent._get_model_context_window()

        # Use configured max_context_tokens if available
        if hasattr(self.agent, 'max_context_tokens') and self.agent.max_context_tokens:
            max_tokens = self.agent.max_context_tokens
        else:
            # Reserve 10% for response generation
            reserve_tokens = int(context_window * 0.1)
            max_tokens = context_window - reserve_tokens

        # Estimate system prompt tokens
        system_tokens = self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt})
        available_tokens = max_tokens - system_tokens

        # Calculate current tokens
        current_tokens = sum(self._estimate_turn_tokens(turn) for turn in turns)
        
        # If under limit, reconstruct messages and return
        if current_tokens + system_tokens <= max_tokens:
            # Reconstruct message list from turns
            new_messages = []
            for turn in turns:
                new_messages.extend(turn['messages'])
            
            old_count = len(self.messages)
            self.messages = new_messages
            
            # Log if we removed messages due to turn limit
            if old_count > len(self.messages):
                logger.info(f"   重建消息列表: {old_count} -> {len(self.messages)} 条消息")
            return

        # Token limit exceeded — tiered strategy based on turn count:
        #
        #   Few turns (<5):  Compress ALL turns to text-only (strip tool chains,
        #                    keep user query + final reply).  Never discard turns
        #                    — losing even one is too painful when context is thin.
        #
        #   Many turns (>=5): Directly discard the first half of turns.
        #                     With enough turns the oldest ones are less
        #                     critical, and keeping the recent half intact
        #                     (with full tool chains) is more useful.

        COMPRESS_THRESHOLD = 5

        if len(turns) < COMPRESS_THRESHOLD:
            # --- Few turns: compress ALL turns to text-only, never discard ---
            compressed_turns = []
            for t in turns:
                compressed = compress_turn_to_text_only(t)
                if compressed["messages"]:
                    compressed_turns.append(compressed)

            new_messages = []
            for turn in compressed_turns:
                new_messages.extend(turn["messages"])

            new_tokens = sum(self._estimate_turn_tokens(t) for t in compressed_turns)
            old_count = len(self.messages)
            self.messages = new_messages

            logger.info(
                f"📦 上下文tokens超限(轮次<{COMPRESS_THRESHOLD}): "
                f"~{current_tokens + system_tokens} > {max_tokens}，"
                f"压缩全部 {len(turns)} 轮为纯文本 "
                f"({old_count} -> {len(self.messages)} 条消息，"
                f"~{current_tokens + system_tokens} -> ~{new_tokens + system_tokens} tokens)"
            )
            return

        # --- Many turns (>=5): discard the older half, keep the newer half ---
        removed_count = len(turns) // 2
        keep_count = len(turns) - removed_count
        discarded_turns = turns[:removed_count]
        kept_turns = turns[-keep_count:]
        kept_tokens = sum(self._estimate_turn_tokens(t) for t in kept_turns)

        logger.info(
            f"🔄 上下文tokens超限: ~{current_tokens + system_tokens} > {max_tokens}，"
            f"裁剪至 {keep_count} 轮（移除 {removed_count} 轮）"
        )

        if self.agent.memory_manager:
            discarded_messages = []
            for turn in discarded_turns:
                discarded_messages.extend(turn["messages"])
            if discarded_messages:
                user_id = getattr(self.agent, '_current_user_id', None)
                cb = self._build_context_summary_callback(discarded_turns, kept_turns)
                self.agent.memory_manager.flush_memory(
                    messages=discarded_messages, user_id=user_id,
                    reason="trim", max_messages=0,
                    context_summary_callback=cb,
                )

        new_messages = []
        for turn in kept_turns:
            new_messages.extend(turn['messages'])

        old_count = len(self.messages)
        self.messages = new_messages

        logger.info(
            f"   移除了 {removed_count} 轮对话 "
            f"({old_count} -> {len(self.messages)} 条消息，"
            f"~{current_tokens + system_tokens} -> ~{kept_tokens + system_tokens} tokens)"
        )

    def _clear_session_db(self):
        """
        Clear the current session's persisted messages from SQLite DB.

        This prevents dirty data (broken tool_use/tool_result pairs) from being
        reloaded on the next request or after a restart.
        """
        try:
            session_id = getattr(self.agent, '_current_session_id', None)
            if not session_id:
                return
            from agent.memory import get_conversation_store
            store = get_conversation_store()
            store.clear_session(session_id)
            logger.info(f"🗑️ Cleared dirty session data from DB: {session_id}")
        except Exception as e:
            logger.warning(f"Failed to clear session DB: {e}")

    def _prepare_messages(self) -> List[Dict[str, Any]]:
        """
        Prepare messages to send to LLM
        
        Note: For Claude API, system prompt should be passed separately via system parameter,
        not as a message. The AgentLLMModel will handle this.
        """
        # Don't add system message here - it will be handled separately by the LLM adapter
        return self.messages