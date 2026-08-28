"""
Agent Stream Execution Module - Multi-turn reasoning based on tool-call

Provides streaming output, event system, and complete tool-call loop
"""
import contextvars
import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable, Tuple

from agent.protocol.cancel import AgentCancelledError
from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.message_utils import (
    sanitize_claude_messages,
    compress_turn_to_text_only,
    identify_complete_turns,
    build_compaction_summary_text,
    find_first_user_text_block,
)
from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available, renders_own_cards
from common.log import logger
from common.i18n import t as _t

# Optional: repair malformed JSON args from non-strict providers (e.g. unescaped quotes in long content).
try:
    from json_repair import repair_json as _repair_json
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False


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

# --------------------------------------------------------------------------
# Fatal-error classification.
#
# Both branches below drop the whole in-memory context, so a false positive
# costs the user their working conversation. Every marker must therefore be
# specific enough that it cannot appear in an unrelated failure: generic words
# ("without", "each", "must have", "not found") matched far too much, and a
# bare "400" substring also matched token counts such as 4000.
# --------------------------------------------------------------------------

# Word-bounded so "4000" / "40096" are not read as HTTP 400.
_RE_HTTP_400 = re.compile(r"\b400\b")

_CONTEXT_OVERFLOW_MARKERS = (
    "context length exceeded", "maximum context length", "prompt is too long",
    "context overflow", "context window", "exceeds model context",
    "request_too_large", "request exceeds the maximum size",
    "too many tokens", "input is too long", "tokens exceed",
)

# Structural tool_use/tool_result pairing complaints only.
_MESSAGE_FORMAT_MARKERS = (
    "tool_use", "tool_result", "tool_call_id", "tool_calls",
    "tool result", "tool id",
    "must be a response to a preceeding message",
)


def _is_context_overflow(error_str_lower: str) -> bool:
    if "[context_overflow]" in error_str_lower:
        return True
    return any(m in error_str_lower for m in _CONTEXT_OVERFLOW_MARKERS)


def _is_message_format_error(error_str_lower: str) -> bool:
    """Detect broken tool_use/tool_result pairing rejected by the provider.

    Requires both a structural marker and a 400-class signal, so an unrelated
    400 (bad model name, missing parameter, oversized upload) never qualifies.
    """
    if not any(m in error_str_lower for m in _MESSAGE_FORMAT_MARKERS):
        return False
    return bool(
        _RE_HTTP_400.search(error_str_lower)
        or "invalid_request" in error_str_lower
        or "invalidparameter" in error_str_lower
    )


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


# Cap for the 429 incremental backoff. The base curve is 30 + retry_count*15,
# which without a cap crosses the web channel's 600s SSE idle timeout by the
# 8th retry; capping each wait at 60s keeps the cumulative sleep in bounds.
RATE_LIMIT_MAX_WAIT = 60  # seconds


# Appended only for the file-writing tools, where "send less" needs to say how.
_SPLIT_WRITE_ADVICE = (
    "To change an existing file, use edit rather than rewriting the whole file. "
    "To create a large file, write the first part, then append each remaining part "
    "with edit using an empty oldText (calling write again would overwrite what you "
    "just wrote)."
)


def _cut_off_message(cause: str, tool_name: Optional[str]) -> str:
    message = (
        f"Your tool call was cut off by {cause}, so it did not run and nothing was written. "
        "Repeating the same call will be cut off again - send less in one call instead."
    )
    if tool_name in ("write", "edit"):
        message += " " + _SPLIT_WRITE_ADVICE
    return message


def _parse_tool_args(args_str: str, finish_reason: Optional[str],
                     tool_name: Optional[str] = None) -> Tuple[dict, Optional[str]]:
    """Parse tool args JSON. Returns (args, error_msg); error_msg is None on success.

    On JSONDecodeError: detect truncation first (skip repair, surface max_tokens hint);
    otherwise try json-repair for escape issues; finally fall back to the raw decoder error.
    """
    truncated_by_limit = finish_reason in ("length", "max_tokens")
    if not args_str:
        # No arguments at all is valid for tools that take none, so only the
        # finish reason can convict here. _execute_tool catches the rest by
        # checking the call against the tool's required parameters.
        if truncated_by_limit:
            return {}, _cut_off_message("the output token limit", tool_name)
        return {}, None
    try:
        return json.loads(args_str), None
    except json.JSONDecodeError as e:
        if truncated_by_limit or not args_str.rstrip().endswith("}"):
            cause = "the output token limit" if truncated_by_limit else "arguments ending mid-JSON"
            return {}, _cut_off_message(cause, tool_name)
        if _HAS_JSON_REPAIR:
            try:
                repaired = _repair_json(args_str, return_objects=True)
                if isinstance(repaired, dict):
                    logger.warning(f"Tool args JSON repaired ({len(args_str)} chars)")
                    return repaired, None
            except Exception:
                pass
        return {}, f"Invalid JSON in tool arguments: {e.msg}"


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
            max_context_turns: int = 30,
            cancel_event=None,
            steer_inbox=None,
            allow_empty_response: bool = False,
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
            cancel_event: Optional threading.Event used to signal user cancel.
                Checked at every safe point (turn boundary, before tool execution,
                during LLM streaming). When set, raises AgentCancelledError which
                run_stream catches to gracefully wind down.
            steer_inbox: Optional SteerInbox for explicit instructions sent to
                this active run. Drained only at message-safe checkpoints.
            allow_empty_response: When True, an empty final answer is a valid
                outcome and is returned as-is instead of being replaced with
                fallback text. Set for runs with no human waiting on a reply
                (scheduled tasks), where silence can be the intended result.
        """
        self.agent = agent
        self.model = model
        self.system_prompt = system_prompt
        # Convert tools list to dict
        self.tools = {tool.name: tool for tool in tools} if isinstance(tools, list) else tools
        self.max_turns = max_turns
        self.on_event = on_event
        self.max_context_turns = max_context_turns
        self.cancel_event = cancel_event
        self.steer_inbox = steer_inbox
        self.allow_empty_response = allow_empty_response

        # Message history - use provided messages or create new list
        self.messages = messages if messages is not None else []
        
        # Tool failure tracking for retry protection
        self.tool_failure_history = []  # List of (tool_name, args_hash, success) tuples
        
        # Track files to send (populated by read tool)
        self.files_to_send = []  # List of file metadata dicts

        # Absolute paths already reported as artifacts, so a write-then-edit
        # sequence on the same file only surfaces one card in the UI.
        self._emitted_artifacts = set()

    def _check_cancelled(self) -> None:
        """Raise AgentCancelledError if the user requested cancellation.

        Called at safe points (turn start, between tool calls, between LLM
        chunks). Cheap to call: just an Event.is_set() probe.
        """
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AgentCancelledError("agent cancelled by user")

    def _drain_steering(self) -> List[str]:
        if self.steer_inbox is None:
            return []
        return self.steer_inbox.drain()

    def _explicit_response_prompt(self) -> str:
        """Prompt that asks a silent model for its final answer.

        When silence is a valid outcome the model has to be told so, or it
        writes filler text just to satisfy the request.
        """
        if self.allow_empty_response:
            return (
                "请说明刚才工具执行的结果。如果本次无需向用户发送任何内容"
                "（例如任务只要求在满足特定条件时才通知，而当前条件不满足），"
                "直接返回空即可，不要输出任何文字。"
            )
        return "请向用户说明刚才工具执行的结果或回答用户的问题。"

    def _empty_response_fallback(self) -> str:
        """Text to return when the model produced no answer at all.

        Stays empty for runs that allow silence, so a scheduled task whose
        notify condition wasn't met delivers nothing instead of an apology
        addressed to a user who never asked anything.
        """
        if self.allow_empty_response:
            logger.info("[Agent] Empty response kept as-is (silence allowed for this run)")
            return ""
        logger.info("Generated fallback response for empty LLM output")
        return _t(
            "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。",
            "Sorry, I can't generate a reply right now. Please try rephrasing your request, or try again later.",
        )

    @staticmethod
    def _steering_text(updates: List[str]) -> str:
        if len(updates) == 1:
            body = updates[0]
        else:
            body = "\n".join(f"{idx}. {text}" for idx, text in enumerate(updates, 1))
        return (
            "[Steering update for the active task]\n"
            "Use this new instruction for the current task before continuing.\n\n"
            f"{body}"
        )

    def _append_steering(
        self,
        updates: List[str],
        pending_tool_calls: Optional[List[Dict]] = None,
        content_blocks: Optional[List[Dict]] = None,
    ) -> None:
        """Append guidance, closing any tool_use blocks that will be skipped."""
        if not updates:
            return
        blocks = content_blocks if content_blocks is not None else []
        for tool_call in pending_tool_calls or []:
            blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": "Skipped because the user redirected the active task.",
                "is_error": True,
            })
        blocks.append({"type": "text", "text": self._steering_text(updates)})
        if content_blocks is None:
            self.messages.append({"role": "user", "content": blocks})
        self._emit_event("agent_steered", {"count": len(updates)})
        logger.info(f"[Agent] Applied {len(updates)} steering update(s)")

    def _close_or_apply_final_steering(self) -> bool:
        """Return True only when the run can finish without losing a steer."""
        updates = self._drain_steering()
        if updates:
            self._append_steering(updates)
            return False
        if self.steer_inbox is None:
            return True
        if self.steer_inbox.close_if_empty():
            return True
        updates = self._drain_steering()
        if updates:
            self._append_steering(updates)
        return False

    def _drain_and_close_steering(self) -> None:
        """Preserve any final guidance before the max-step summary call."""
        if self.steer_inbox is None:
            return
        while True:
            updates = self._drain_steering()
            if updates:
                self._append_steering(updates)
            if self.steer_inbox.close_if_empty():
                return

    def _handle_cancelled(self, partial_response: str) -> None:
        """Wind down ``self.messages`` after a user-initiated cancel.

        The messages list may be in any of these states when we get here:
          (a) Last message is an assistant message containing tool_use
              blocks but the matching tool_result has not been appended yet.
          (b) Last message is an assistant text-only reply (cancel happened
              right before the next turn started).
          (c) Last message is a user tool_result message and we cancelled
              between turns.

        For (a) we MUST synthesise tool_result blocks, otherwise the next
        request will fail Claude/OpenAI's strict pairing validation. For
        (b)/(c) the state is already valid and we just append a small
        cancellation note so the user/LLM both see the boundary clearly.
        """
        try:
            # Step 1: close any orphaned tool_use in the trailing assistant
            # message by injecting matching tool_result blocks.
            if self.messages and isinstance(self.messages[-1], dict) \
                    and self.messages[-1].get("role") == "assistant":
                last = self.messages[-1]
                content = last.get("content")
                if isinstance(content, list):
                    pending_tool_use_ids = [
                        block.get("id")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "tool_use"
                    ]
                    pending_tool_use_ids = [tid for tid in pending_tool_use_ids if tid]
                    if pending_tool_use_ids:
                        tool_result_blocks = [
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": "Cancelled by user before this tool finished.",
                                "is_error": True,
                            }
                            for tid in pending_tool_use_ids
                        ]
                        self.messages.append({
                            "role": "user",
                            "content": tool_result_blocks,
                        })
                        logger.info(
                            f"[Agent] Injected {len(tool_result_blocks)} cancellation "
                            f"tool_result blocks to keep message history valid"
                        )

            # Step 2: append a stable "interrupted" marker so the LLM sees a
            # clear stop boundary on the next turn.
            self.messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": self._cancellation_marker()}],
            })
        except Exception as e:
            logger.warning(f"[Agent] _handle_cancelled cleanup failed: {e}")

    @staticmethod
    def _cancellation_marker() -> str:
        """Stop-boundary note, listing background jobs a cancel does not kill."""
        marker = "_(Cancelled by user)_"
        try:
            from agent.tools.bash import background
            running = [job for job in background.list_jobs() if job["running"]]
        except Exception:
            return marker
        if not running:
            return marker
        lines = "\n".join(
            f"- {job['id']}: {job['command']} ({job['elapsed']}s elapsed)"
            for job in running
        )
        return (
            f"{marker}\nBackground commands are still running - cancelling does not "
            f"stop them. Use bash(bash_id=..., kill=true) to stop one.\n{lines}"
        )

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

    # Tools whose successful execution may have produced a user-facing file.
    _ARTIFACT_TOOLS = ("write", "edit")

    def _maybe_emit_artifact(self, tool_call: dict, result: dict) -> None:
        """Report a file written by `write`/`edit` so clients can preview it."""
        if not self.on_event:
            return
        if tool_call.get("name") not in self._ARTIFACT_TOOLS:
            return
        if result.get("status") != "success":
            return

        data = result.get("result")
        path = data.get("path") if isinstance(data, dict) else None
        if not path:
            path = (tool_call.get("arguments") or {}).get("path")
        if not path:
            return

        from agent.protocol.artifact import safe_build_artifact

        # Anchor artifact detection to the session's working dir. In project mode
        # this is the project dir, so files written there surface as cards; the
        # default state_root is used when no project is open.
        art_root = None
        try:
            eff = getattr(self.agent, "effective_cwd", None)
            if callable(eff):
                art_root = eff()
        except Exception:
            art_root = None
        artifact = safe_build_artifact(path, art_root)
        if not artifact:
            return
        if artifact["path"] in self._emitted_artifacts:
            return
        self._emitted_artifacts.add(artifact["path"])
        logger.info(f"🗂  Artifact: {artifact['rel_path']} ({artifact['kind']})")
        self._emit_event("artifact", artifact)

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

    @staticmethod
    def _split_content_blocks(content) -> Tuple[str, str]:
        """Split a content-blocks list into (visible_text, reasoning_text).

        Some providers (Anthropic-shaped adapters, MiMo sync wrappers) stream
        ``content`` as a list of blocks instead of a string. Thinking/reasoning
        blocks must never be treated as the visible reply — that is what leaked
        CoT into IM channels as an "Agent Reply". A plain string passes through
        unchanged as visible text.
        """
        if isinstance(content, str):
            return content, ""
        if not isinstance(content, list):
            return "", ""
        text_parts = []
        reasoning_parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype in ("thinking", "reasoning"):
                thinking_text = (
                    block.get("thinking")
                    or block.get("reasoning")
                    or block.get("text")
                    or ""
                )
                if thinking_text:
                    reasoning_parts.append(thinking_text)
                continue
            if btype in ("text", "text_delta", None):
                text_parts.append(block.get("text") or "")
        return "".join(text_parts), "".join(reasoning_parts)

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
            return True, _t(
                "抱歉，我没能完成这个任务。可能是我理解有误或者当前方法不太合适。\n\n建议你：\n• 换个方式描述需求试试\n• 把任务拆分成更小的步骤\n• 或者换个思路来解决",
                "Sorry, I couldn't complete this task. I may have misunderstood, or my current approach isn't quite right.\n\nYou could try:\n• Rephrasing your request\n• Breaking the task into smaller steps\n• Taking a different approach",
            ), True
        
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
        # Log user message with model info. Truncate very long messages (e.g.
        # injected transcripts / large prompts) so logs stay readable.
        thinking_enabled = self._is_thinking_enabled()
        thinking_label = " | 💭 thinking" if thinking_enabled else ""
        # When deep thinking is on, also surface the resolved reasoning effort
        # (per-model aware) so the operator can confirm the effective intensity.
        effort_label = ""
        if thinking_enabled:
            try:
                effort = self.model._normalized_reasoning_effort()
                if effort:
                    effort_label = f" | effort={effort}"
            except Exception:
                effort_label = ""
        _log_msg = user_message if len(user_message) <= 500 else (
            user_message[:500] + f" …(+{len(user_message) - 500} chars)"
        )
        logger.info(f"🤖 {self.model.model}{thinking_label}{effort_label} | 👤 {_log_msg}")
        
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

        # Reset the run-scoped MCP tool-retrieval accumulator. On-demand tool
        # retrieval only grows this set within a run, so a tool that already
        # produced a tool_use never disappears from the schema mid-run (which
        # would make Claude/MiniMax raise a message-format error).
        self._retrieved_mcp_names = set()

        final_response = ""
        turn = 0

        # Respect a run id an outer scope already set (a subagent spawn or a
        # delegated task passes one down); only mint a fresh one when this turn
        # is the top of its own run. Writing through set_agent_run_id keeps the
        # outbound header-tagging path and RuntimeIdentity on the same id.
        import uuid as _uuid
        from common.utils import set_agent_run_id, clear_agent_run_id, current_agent_run_id
        _run_token = None
        if not current_agent_run_id():
            _run_token = set_agent_run_id(_uuid.uuid4().hex)
        cancelled = False
        try:
            while turn < self.max_turns:
                # Check at the very top of every turn so a cancel arriving
                # between turns short-circuits cleanly.
                self._check_cancelled()

                steering_updates = self._drain_steering()
                if steering_updates:
                    self._append_steering(steering_updates)

                turn += 1
                logger.info(f"[Agent] Turn {turn}")
                self._emit_event("turn_start", {"turn": turn})

                # Call LLM (enable retry_on_empty for better reliability)
                assistant_msg, tool_calls, stop_reason = self._call_llm_stream(retry_on_empty=True)
                final_response = assistant_msg

                # A steer that arrived while the model was streaming takes
                # precedence over its proposed continuation. Tool calls have
                # already been written to history, so close every one with a
                # synthetic result before asking the model to reconsider.
                steering_updates = self._drain_steering()
                if steering_updates:
                    self._append_steering(
                        steering_updates,
                        pending_tool_calls=tool_calls,
                    )
                    self._emit_event("turn_end", {
                        "turn": turn,
                        "has_tool_calls": bool(tool_calls),
                        "tool_count": len(tool_calls),
                        "stop_reason": stop_reason,
                        "steered": True,
                    })
                    continue

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
                                    "text": self._explicit_response_prompt()
                                }]
                            })
                            
                            # 再调用一次 LLM
                            assistant_msg, tool_calls, stop_reason = self._call_llm_stream(retry_on_empty=False)
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
                                final_response = self._empty_response_fallback()
                        else:
                            # First-turn empty reply, fall back directly
                            final_response = self._empty_response_fallback()
                    else:
                        logger.info(f"💭 {assistant_msg[:150]}{'...' if len(assistant_msg) > 150 else ''}")
                    
                    # If the explicit-response retry produced tool_calls, skip the break
                    # and continue down to the tool execution branch in this same iteration.
                    if not tool_calls:
                        steering_updates = self._drain_steering()
                        if steering_updates:
                            self._append_steering(steering_updates)
                            self._emit_event("turn_end", {
                                "turn": turn,
                                "has_tool_calls": False,
                                "stop_reason": stop_reason,
                                "steered": True,
                            })
                            continue
                        if not self._close_or_apply_final_steering():
                            self._emit_event("turn_end", {
                                "turn": turn,
                                "has_tool_calls": False,
                                "stop_reason": stop_reason,
                                "steered": True,
                            })
                            continue
                        logger.debug(f"✅ Done (no tool calls, stop_reason={stop_reason or 'none'})")
                        self._emit_event("turn_end", {
                            "turn": turn,
                            "has_tool_calls": False,
                            "stop_reason": stop_reason
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
                    already_run = self._run_parallel_calls(tool_calls)
                    for tool_index, tool_call in enumerate(tool_calls):
                        # Honour cancel between tool invocations within the same turn
                        self._check_cancelled()
                        steering_updates = self._drain_steering()
                        if steering_updates:
                            self._append_steering(
                                steering_updates,
                                pending_tool_calls=tool_calls[tool_index:],
                                content_blocks=tool_result_blocks,
                            )
                            break
                        if tool_call["id"] in already_run:
                            result = already_run[tool_call["id"]]
                        else:
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
                                logger.info(f"📎 File queued for sending: {result_data.get('file_name', result_data.get('path'))}")
                                self._emit_event("file_to_send", result_data)

                        # Surface user-facing files written by the agent
                        self._maybe_emit_artifact(tool_call, result)
                        
                        # Check for critical error - abort entire conversation
                        if result.get("status") == "critical_error":
                            logger.error(f"💥 Fatal error detected, aborting conversation")
                            final_response = result.get('result') or _t("任务执行失败", "Task execution failed")
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
                    "tool_count": len(tool_calls),
                    "stop_reason": stop_reason
                })

            if turn >= self.max_turns:
                logger.warning(f"⚠️  Reached max decision step limit: {self.max_turns}")
                self._drain_and_close_steering()
                
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
                    summary_response, summary_tools, _ = self._call_llm_stream(retry_on_empty=False)
                    if summary_response:
                        final_response = summary_response
                        logger.info(f"💭 Summary: {summary_response[:150]}{'...' if len(summary_response) > 150 else ''}")
                    else:
                        # Fallback if model still doesn't respond
                        final_response = _t(
                            f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。",
                            f"I've taken {turn} decision steps and reached the per-run limit. The task may not be fully complete — try breaking it into smaller steps, or describe your request differently.",
                        )
                except Exception as e:
                    logger.warning(f"Failed to get summary from LLM: {e}")
                    final_response = _t(
                        f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。",
                        f"I've taken {turn} decision steps and reached the per-run limit. The task may not be fully complete — try breaking it into smaller steps, or describe your request differently.",
                    )
                finally:
                    # Remove the injected user prompt from history to avoid polluting
                    # persisted conversation records. The assistant summary (if any)
                    # was already appended by _call_llm_stream and is kept.
                    if (prompt_insert_idx < len(self.messages)
                            and self.messages[prompt_insert_idx].get("role") == "user"):
                        self.messages.pop(prompt_insert_idx)
                        logger.debug("[Agent] Removed injected max-steps prompt from message history")

        except AgentCancelledError:
            # User-initiated stop: wind down message history cleanly so the
            # next turn is unaffected; channels emit a "cancelled" UI event.
            cancelled = True
            logger.info(f"[Agent] 🛑 Cancelled by user (turn {turn})")
            self._handle_cancelled(final_response)
            if not final_response or not final_response.strip():
                final_response = "_(Cancelled)_"

        except Exception as e:
            logger.error(f"❌ Agent execution error: {e}")
            self._emit_event("error", {"error": str(e)})
            raise

        finally:
            if _run_token is not None:
                clear_agent_run_id(_run_token)
            if self.steer_inbox is not None:
                self.steer_inbox.close()
            final_response = final_response.strip() if final_response else final_response
            if cancelled:
                # Emit before agent_end so channels can mark UI as cancelled
                self._emit_event("agent_cancelled", {"final_response": final_response})
            logger.info(f"[Agent] 🏁 Done ({turn} turns)" + (" [cancelled]" if cancelled else ""))
            self._emit_event("agent_end", {"final_response": final_response, "cancelled": cancelled})

        return final_response

    def _select_tools_for_injection(self) -> list:
        """Decide which tools to inject into the current LLM turn.

        A tool behind a setting is left out while that setting is off, and
        picked up again on the turn after it is switched back on.

        Built-in tools are ALWAYS injected in full (skills and core flows hard
        depend on them). MCP tools are also injected in full UNLESS on-demand
        retrieval is enabled AND the MCP tool count exceeds the configured
        threshold — then only the most relevant MCP tools are injected, unioned
        with those already selected earlier in this run (only-grows, so a tool
        that already produced a tool_use never vanishes from the schema).

        Degrades safely: disabled feature, no embedding provider, embedding
        failure, count below threshold, or any error → inject all tools. Tools
        are never silently dropped.
        """
        all_tools = [tool for tool in self.tools.values() if is_tool_available(tool)]
        try:
            from config import conf
            if not conf().get("mcp_tool_retrieval_enabled", False):
                return all_tools

            from agent.tools.mcp.mcp_tool import McpTool
            mcp_tools = [t for t in all_tools if isinstance(t, McpTool)]
            builtin_tools = [t for t in all_tools if not isinstance(t, McpTool)]

            threshold = int(conf().get("mcp_tool_retrieval_threshold", 20) or 20)
            if len(mcp_tools) <= threshold:
                return all_tools

            top_k = int(conf().get("mcp_tool_retrieval_top_k", 10) or 10)

            from agent.tools import ToolManager
            from agent.tools.mcp.tool_retrieval import (
                build_retrieval_query,
                select_mcp_tools,
            )

            tm = ToolManager()
            tool_vectors = tm.get_mcp_tool_vectors()
            query = build_retrieval_query(self.messages)
            query_vector = tm.embed_query(query)

            selected = select_mcp_tools(
                query_vector,
                tool_vectors,
                top_k,
                getattr(self, "_retrieved_mcp_names", set()),
            )
            if selected is None:
                # No provider / empty index / error → full injection.
                return all_tools

            # Persist the accumulated selection for subsequent turns.
            self._retrieved_mcp_names = selected

            selected_mcp = [t for t in mcp_tools if t.name in selected]
            logger.info(
                f"[ToolRetrieval] Injecting {len(builtin_tools)} built-in + "
                f"{len(selected_mcp)}/{len(mcp_tools)} MCP tool(s) (top_k={top_k})"
            )
            return builtin_tools + selected_mcp
        except Exception as e:
            logger.debug(f"[ToolRetrieval] full injection (retrieval skipped): {e}")
            return all_tools

    def _call_llm_stream(self, retry_on_empty=True, retry_count=0, max_retries=3,
                         _overflow_stage: int = 0) -> Tuple[str, List[Dict], Optional[str]]:
        """
        Call LLM with streaming and automatic retry on errors

        Args:
            retry_on_empty: Whether to retry once if empty response is received
            retry_count: Current retry attempt (internal use)
            max_retries: Maximum number of retries for API errors
            _overflow_stage: Context-overflow recovery escalation level (internal):
                0 = first hit, 1 = after aggressive trim, 2 = after hard compaction.

        Returns:
            (response_text, tool_calls, stop_reason), where stop_reason is the
            provider's finish_reason for this generation, or None when it
            reported none. A turn that returns text and no tool calls looks
            finished either way, so stop_reason is the only thing separating a
            model that chose to stop from one cut off at the output token limit
            ("length" / "max_tokens").
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

        # Prepare tool definitions. Prefer get_json_schema() when it yields
        # real properties (lets tools augment schema at runtime), otherwise
        # fall back to the static `tool.params` (MCP tools rely on this).
        tools_schema = None
        if self.tools:
            tools_schema = []
            for tool in self._select_tools_for_injection():
                input_schema = tool.params
                try:
                    dynamic = (tool.get_json_schema() or {}).get("parameters") or {}
                    if dynamic.get("properties"):
                        input_schema = dynamic
                except Exception:
                    pass
                tools_schema.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": input_schema,
                })

        # Debug: dump the full system prompt and messages sent to the LLM.
        # Gated behind `debug` config to avoid flooding normal logs.
        # try:
        #     from config import conf
        #     if conf().get("debug", False):
        #         logger.debug(
        #             "[Agent][debug] system_prompt sent to LLM "
        #             f"({len(self.system_prompt or '')} chars):\n"
        #             "================ SYSTEM PROMPT BEGIN ================\n"
        #             f"{self.system_prompt}\n"
        #             "================ SYSTEM PROMPT END =================="
        #         )
        #         logger.info(f"[Agent][debug] messages sent to LLM: {messages}")
        # except Exception:
        #     pass

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

            # Probe cancel every N chunks to bound reaction time without
            # checking on every token.
            _cancel_probe_counter = 0
            _CANCEL_PROBE_EVERY = 8

            for chunk in stream:
                _cancel_probe_counter += 1
                if _cancel_probe_counter >= _CANCEL_PROBE_EVERY:
                    _cancel_probe_counter = 0
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        # Persist partial text only; tool_use args may be
                        # truncated mid-stream and would fail validation.
                        logger.info("[Agent] cancel detected mid-stream, aborting LLM call")
                        if full_content:
                            partial_msg = {
                                "role": "assistant",
                                "content": [{"type": "text", "text": full_content}],
                            }
                            self.messages.append(partial_msg)
                        self._emit_event("message_end", {
                            "content": full_content,
                            "tool_calls": [],
                            "cancelled": True,
                        })
                        raise AgentCancelledError("cancelled during LLM streaming")

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
                    
                    # Check if this is a context overflow error. Use the single
                    # shared classifier (_is_context_overflow) so the markers stay
                    # in one place and never drift. Deliberately NOT a bare
                    # "too large": an oversized upload (413 "file too large" /
                    # "image too large") must NOT be treated as context overflow,
                    # or we would compact/clear a healthy conversation to "recover"
                    # from a problem that has nothing to do with context length.
                    # Don't rely on specific status codes — providers differ.
                    error_msg_lower = error_msg.lower()
                    is_overflow = _is_context_overflow(error_msg_lower)

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

                    # Handle text content. Some providers (Anthropic-shaped
                    # adapters, MiMo sync wrappers) stream a list of content
                    # blocks instead of a string. Thinking/reasoning blocks
                    # must never be treated as the visible reply — that is
                    # what leaked CoT into WeChat as "Agent Reply".
                    content_delta = delta.get("content") or ""
                    if isinstance(content_delta, list):
                        content_delta, thinking_text = self._split_content_blocks(content_delta)
                        if thinking_text:
                            full_reasoning += thinking_text
                            if self._is_thinking_enabled():
                                self._emit_event("reasoning_update", {"delta": thinking_text})
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

        except AgentCancelledError:
            # Must propagate untouched; never treat as a retryable error.
            raise

        except Exception as e:
            error_str = str(e)
            error_str_lower = error_str.lower()
            
            # Context overflow is non-retryable and needs the working context reset.
            is_context_overflow = _is_context_overflow(error_str_lower)

            # Incomplete tool_use/tool_result pairs rejected by the provider.
            # MiniMax's "tool result's tool id(...) not found" (code 2013) is
            # covered by the "tool result" / "tool id" markers.
            is_message_format_error = _is_message_format_error(error_str_lower)
            
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

                # Smart-compaction recovery — reuse the same strategy as the
                # proactive _trim_messages (discard the older half + inject an
                # LLM summary, or compress to text-only when turns are few),
                # but drive it by the real limit the provider reported so we
                # shrink toward the exact ceiling instead of hammering the same
                # oversized request (the loop the user saw on the LinkAI backend).
                # Message-format errors have no token budget to hit, so they skip
                # straight to the context reset below.
                if is_context_overflow and _overflow_stage == 0:
                    if self._smart_compact_to_budget(error_str):
                        logger.warning("🔄 Smart-compacted context to fit the reported limit, retrying...")
                        return self._call_llm_stream(
                            retry_on_empty=retry_on_empty,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            _overflow_stage=1,
                        )

                # Trimming exhausted, or this is a message format error.
                # Reset the working context only: the persisted history is
                # irreplaceable, and it can never reintroduce broken tool pairs
                # because every load path strips tool_use/tool_result blocks.
                logger.warning("🔄 Resetting in-memory context to recover (stored history kept)")
                self.messages.clear()
                if is_context_overflow:
                    raise Exception(_t(
                        "抱歉，对话历史过长导致上下文溢出。我已重置当前上下文（历史记录仍然保留），请重新描述你的需求。",
                        "Sorry, the conversation history got too long and overflowed the context. I've reset the current context (your history is kept) — please describe your request again.",
                    ))
                else:
                    raise Exception(_t(
                        "抱歉，之前的对话出现了问题。我已重置当前上下文（历史记录仍然保留），请重新发送你的消息。",
                        "Sorry, something went wrong with the earlier conversation. I've reset the current context (your history is kept) — please send your message again.",
                    ))
            
            # Check if error is rate limit (429)
            is_rate_limit = '429' in error_str_lower or 'rate limit' in error_str_lower
            
            # Check if error is retryable (timeout, connection, server busy, etc.)
            is_retryable = any(keyword in error_str_lower for keyword in [
                'timeout', 'timed out', 'connection', 'network', 
                'rate limit', 'overloaded', 'unavailable', 'busy', 'retry',
                '429', '500', '502', '503', '504', '512'
            ])
            
            if is_retryable and retry_count < max_retries:
                # Rate limit needs longer wait time, but capped so the cumulative
                # backoff stays within the web stream's idle timeout (see the
                # RATE_LIMIT_MAX_WAIT note above).
                if is_rate_limit:
                    wait_time = min(30 + (retry_count * 15), RATE_LIMIT_MAX_WAIT)  # 30s..60s
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

            args_str = tc.get("arguments") or ""
            arguments, parse_err = _parse_tool_args(args_str, stop_reason, tc["name"])
            if parse_err:
                logger.error(
                    f"Tool args parse failed for {tc['name']} ({len(args_str)} chars): {parse_err}"
                )
                tool_calls.append({
                    "id": tool_id,
                    "name": tc["name"],
                    "arguments": {},
                    "_parse_error": parse_err,
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
            "tool_calls": tool_calls,
            "stop_reason": stop_reason
        })

        return full_content, tool_calls, stop_reason

    def _required_params(self, tool_name: str) -> list:
        """Parameter names a tool's schema declares as required."""
        tool = self.tools.get(tool_name)
        params = getattr(tool, "params", None)
        required = params.get("required") if isinstance(params, dict) else None
        return list(required) if isinstance(required, list) else []

    def _run_parallel_calls(self, tool_calls: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Start every parallel-safe call of this turn at once, keyed by call id.

        Tools otherwise run strictly in the order the model asked for them.
        That is the right default, but a model that splits independent work
        across several calls - the usual way of expressing it - would then have
        the second wait out the first. For a tool that declares itself
        parallel_safe the wait buys nothing, so those calls are run together
        here and the loop below picks up the finished results in place.

        Each call gets its own copy of the tool: the loop drives tools by
        assigning `cancel_event` and `progress_callback` before a call and
        clearing them after, which two concurrent calls on one instance would
        do to each other.
        """
        eligible = [
            call for call in tool_calls
            if getattr(self.tools.get(call["name"]), "parallel_safe", False)
        ]
        if len(eligible) < 2:
            return {}

        logger.info(f"[Agent] Running {len(eligible)} tool calls in parallel")
        pool = ThreadPoolExecutor(
            max_workers=len(eligible), thread_name_prefix="parallel-tool"
        )
        try:
            futures = {}
            for call in eligible:
                # copy_context carries the runtime identity - which agent, which
                # session - into the worker thread, so anything the tool writes
                # lands where the same call would have landed on this thread.
                ctx = contextvars.copy_context()
                futures[call["id"]] = pool.submit(
                    ctx.run, self._execute_tool, call, copy.copy(self.tools[call["name"]])
                )
            return {call_id: future.result() for call_id, future in futures.items()}
        finally:
            pool.shutdown(wait=False)

    def _execute_tool(self, tool_call: Dict, tool_override: Optional[BaseTool] = None) -> Dict[str, Any]:
        """
        Execute tool

        Args:
            tool_call: {"id": str, "name": str, "arguments": dict}
            tool_override: run against this instance instead of the shared one

        Returns:
            Tool execution result
        """
        tool_name = tool_call["name"]
        tool_id = tool_call["id"]
        arguments = tool_call["arguments"]

        if "_parse_error" in tool_call:
            result = {
                "status": "error",
                "result": tool_call["_parse_error"],
                "execution_time": 0,
            }
            self._record_tool_result(tool_name, arguments, False)
            return result

        # A call whose arguments never arrived parses into an empty dict, which
        # would otherwise reach the tool and be reported as one missing field -
        # sending the model off to fix a parameter it never got to send.
        missing = self._required_params(tool_name) if not arguments else []
        if missing:
            result = {
                "status": "error",
                "result": (
                    f"Your {tool_name} call arrived with no arguments at all, so it did not "
                    f"run and nothing was written. It requires: {', '.join(missing)}. "
                    "The arguments were most likely cut off before they were sent."
                    + (" " + _SPLIT_WRITE_ADVICE if tool_name in ("write", "edit") else "")
                ),
                "execution_time": 0,
            }
            logger.error(f"Tool {tool_name} called with no arguments (required: {missing})")
            self._record_tool_result(tool_name, arguments, False)
            return result

        # Permission gate. Resolved per call so switching mode mid-conversation
        # applies to the very next tool call. A refusal is reported as a normal
        # tool error: the model reads why, and can either take an allowed route
        # or tell the user which mode the task needs.
        denial = self._permission_denial(tool_name, arguments)
        if denial:
            logger.info(f"🔐 Permission denied for tool {tool_name}: {denial}")
            result = {"status": "error", "result": denial, "execution_time": 0}
            self._emit_event("tool_execution_start", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                "arguments": arguments,
            })
            # Flag this as a permission refusal (not an ordinary tool error) and
            # carry the mode that refused, so the UI can render an actionable
            # "switch permission" hint instead of a generic failure.
            try:
                denied_mode = self.agent.effective_permission_mode()
            except Exception:
                denied_mode = None
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                "permission_denied": True,
                "permission_mode": denied_mode,
                **result,
            })
            # Deliberately not recorded as a tool failure: a refusal is not the
            # tool misbehaving, and it must not count toward the consecutive
            # failure limit that aborts the conversation.
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

        tool = tool_override or self.tools.get(tool_name)
        start_event = {
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments": arguments,
        }
        # A call that puts up its own cards gets no card of its own, or the
        # same work is on screen twice. Trust but verify: a tool that turns
        # back at its own front door - a setting is off, an argument is out of
        # range - emits nothing, and its refusal has to appear somewhere.
        own_cards = renders_own_cards(tool, arguments)
        emitted_own = False

        def emit_from_tool(event_type, data):
            nonlocal emitted_own
            if event_type == "tool_execution_start":
                emitted_own = True
            self._emit_event(event_type, data)

        if not own_cards:
            self._emit_event("tool_execution_start", start_event)

        try:
            if not tool:
                raise ValueError(self._build_tool_not_found_message(tool_name))

            # Set tool context
            tool.model = self.model
            tool.context = self.agent
            tool.cancel_event = self.cancel_event
            tool.progress_callback = lambda message: self._emit_event(
                "tool_execution_progress",
                {
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "message": message,
                }
            )
            tool.event_callback = emit_from_tool if own_cards else self._emit_event
            tool.tool_call_id = tool_id

            # Execute tool
            start_time = time.time()
            try:
                result: ToolResult = tool.execute_tool(arguments)
            finally:
                tool.progress_callback = None
                tool.cancel_event = None
                tool.event_callback = None
                tool.tool_call_id = None
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

            # `display` rides on the event only: result_dict becomes the
            # tool_result the model reads, and a second rendering of the same
            # outcome there would just cost context.
            end_event = {"tool_call_id": tool_id, "tool_name": tool_name, **result_dict}
            if getattr(result, "display", None):
                end_event["display"] = result.display
            if not own_cards:
                self._emit_event("tool_execution_end", end_event)
            elif not emitted_own:
                self._emit_event("tool_execution_start", start_event)
                self._emit_event("tool_execution_end", end_event)

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

            # The tool was trusted to put up its own cards and then threw.
            # Whatever it had already drawn is now stranded mid-spin, so a
            # card saying what went wrong is worth the small duplication.
            if own_cards:
                self._emit_event("tool_execution_start", start_event)
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **error_result
            })
            return error_result

    def _permission_denial(self, tool_name: str, arguments: Dict) -> Optional[str]:
        """Reason this call is not allowed, or None when it may run.

        Never raises: a broken permission check must not take the conversation
        down with it, so an error here falls through to the historical
        unrestricted behavior.
        """
        agent = self.agent
        if agent is None:
            return None
        try:
            from agent.permission import FULL_ACCESS, check_tool_call

            mode = agent.effective_permission_mode()
            if mode == FULL_ACCESS:
                return None
            decision = check_tool_call(
                mode,
                tool_name,
                arguments,
                cwd=agent.effective_cwd(),
                write_roots=agent.write_roots(),
            )
            return None if decision.allowed else decision.reason
        except Exception as e:
            logger.warning(f"[Permission] Check skipped for {tool_name}: {e}")
            return None

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
        return identify_complete_turns(self.messages)
    
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

    # Parse "... maximum context length is 1048576 tokens. However, you requested
    # 1276733 tokens (892733 in the messages, 384000 in the completion) ..." so
    # the retry aims at the real numbers the provider reported rather than a guess.
    _RE_OVERFLOW_LIMIT = re.compile(r"maximum context length is\s+(\d+)\s*tokens", re.I)
    _RE_OVERFLOW_COMPLETION = re.compile(r"(\d+)\s+in the completion", re.I)

    def _overflow_input_budget(self, error_str: str) -> int:
        """
        Compute the input-token budget to compact toward after an overflow.

        Prefer the concrete numbers the provider reported in the error
        ("maximum context length is X ... N in the completion"); fall back to
        the model window minus our output reserve. A 10% safety margin absorbs
        the gap between our estimate and the provider's real tokenizer.
        """
        window = self.agent._get_model_context_window()
        limit_match = self._RE_OVERFLOW_LIMIT.search(error_str or "")
        if limit_match:
            window = int(limit_match.group(1))

        completion = None
        comp_match = self._RE_OVERFLOW_COMPLETION.search(error_str or "")
        if comp_match:
            completion = int(comp_match.group(1))
        if completion is None:
            completion = self.agent._get_output_reserve_tokens()

        system_tokens = self.agent._estimate_message_tokens(
            {"role": "system", "content": self.system_prompt}
        )
        budget = int((window - completion - system_tokens) * 0.9)
        return max(2000, budget)

    def _smart_compact_to_budget(self, error_str: str) -> bool:
        """
        Compact the working context toward the provider's reported limit using
        the SAME smart strategy as the proactive _trim_messages, just repeated
        until the estimate fits:

          - Many turns (>= COMPRESS_THRESHOLD): discard the older half and flush
            them to daily memory + inject an LLM summary into the kept turns.
          - Few turns (< COMPRESS_THRESHOLD): compress every turn to text-only
            (strip tool chains, keep user query + final reply), never discard.

        Keeps at least the most recent turn so the user's latest request is not
        lost. Returns True if it reduced the context (worth retrying), else
        False (nothing left to shrink -> caller resets).
        """
        COMPRESS_THRESHOLD = 5

        input_budget = self._overflow_input_budget(error_str)
        original_count = len(self.messages)

        turns = self._identify_complete_turns()
        if not turns:
            return False

        current = sum(self._estimate_turn_tokens(t) for t in turns)
        logger.warning(
            f"🔄 Context overflow recovery: compacting toward ~{input_budget} "
            f"input tokens (currently ~{current} over {len(turns)} turns)"
        )

        # Repeatedly apply the smart strategy until we fit or can't shrink more.
        # Each iteration removes the older half (with summary) when there are
        # enough turns, otherwise compresses the survivors to plain text.
        guard = 0
        while turns and guard < 32:
            guard += 1
            current = sum(self._estimate_turn_tokens(t) for t in turns)
            if current <= input_budget:
                break

            if len(turns) >= COMPRESS_THRESHOLD:
                # Discard older half + summarize, mirroring _trim_messages.
                removed_count = len(turns) // 2
                discarded_turns = turns[:removed_count]
                kept_turns = turns[removed_count:]

                if self.agent.memory_manager:
                    discarded_messages = []
                    for turn in discarded_turns:
                        discarded_messages.extend(turn["messages"])
                    if discarded_messages:
                        user_id = getattr(self.agent, "_current_user_id", None)
                        cb = self._build_context_summary_callback(discarded_turns, kept_turns)
                        self.agent.memory_manager.flush_memory(
                            messages=discarded_messages, user_id=user_id,
                            reason="overflow", max_messages=0,
                            context_summary_callback=cb,
                        )
                turns = kept_turns
            else:
                # Few turns: compress all to text-only. If that still doesn't
                # fit, drop the oldest one but always keep the last turn.
                compressed = []
                for t in turns:
                    c = compress_turn_to_text_only(t)
                    if c["messages"]:
                        compressed.append(c)
                if compressed and sum(self._estimate_turn_tokens(t) for t in compressed) < current:
                    turns = compressed
                elif len(turns) > 1:
                    turns = turns[1:]
                else:
                    # A single turn that still overflows even as plain text —
                    # nothing more this strategy can do.
                    turns = compressed or turns
                    break

        new_messages = []
        for turn in turns:
            new_messages.extend(turn["messages"])

        if not new_messages or len(new_messages) >= original_count:
            # Couldn't reduce anything (single oversized turn) -> let caller reset.
            if not new_messages:
                logger.warning("🧹 Smart compaction produced no messages, will clear history")
                return False
            if len(new_messages) >= original_count:
                logger.warning("🧹 Smart compaction could not reduce the context, will clear history")
                return False

        self.messages[:] = new_messages
        new_tokens = sum(self._estimate_turn_tokens(t) for t in turns)
        logger.info(
            f"🔄 Smart compaction: {original_count} -> {len(self.messages)} messages "
            f"(~{new_tokens} tokens, target ~{input_budget})"
        )
        return True

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
        target_block = find_first_user_text_block(kept_turns)
        if not target_block:
            return None

        turn_count = len(discarded_turns)
        original_text = target_block["text"]

        def _on_summary_ready(summary: str):
            if not summary or not summary.strip():
                return
            target_block["text"] = build_compaction_summary_text(
                summary, turn_count, original_text
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
                f"💾 Context turns exceeded: {keep_count + removed_count} > {self.max_context_turns}, "
                f"trimmed to {keep_count} turns (removed {removed_count})"
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

        # The window is shared by prompt + completion. Always keep the input
        # budget below (window - output reserve) so a full prompt plus the
        # provider's default completion budget can't overflow the window and
        # trigger the "maximum context length ... you requested N tokens" 400
        # (which otherwise loops). This cap applies even when the user
        # configured a large agent_max_context_tokens.
        output_reserve = self.agent._get_output_reserve_tokens()
        input_ceiling = max(1, context_window - output_reserve)

        # Use configured max_context_tokens if available, but never above the
        # input ceiling that leaves room for the completion.
        if hasattr(self.agent, 'max_context_tokens') and self.agent.max_context_tokens:
            max_tokens = min(self.agent.max_context_tokens, input_ceiling)
        else:
            max_tokens = input_ceiling

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
                logger.info(f"   Rebuilt message list: {old_count} -> {len(self.messages)} messages")
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
                f"📦 Context tokens exceeded (turns<{COMPRESS_THRESHOLD}): "
                f"~{current_tokens + system_tokens} > {max_tokens}, "
                f"compressed all {len(turns)} turns to plain text "
                f"({old_count} -> {len(self.messages)} messages, "
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
            f"🔄 Context tokens exceeded: ~{current_tokens + system_tokens} > {max_tokens}, "
            f"trimmed to {keep_count} turns (removed {removed_count})"
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
            f"   Removed {removed_count} turns "
            f"({old_count} -> {len(self.messages)} messages, "
            f"~{current_tokens + system_tokens} -> ~{kept_tokens + system_tokens} tokens)"
        )

    def _prepare_messages(self) -> List[Dict[str, Any]]:
        """
        Prepare messages to send to LLM
        
        Note: For Claude API, system prompt should be passed separately via system parameter,
        not as a message. The AgentLLMModel will handle this.
        """
        # Don't add system message here - it will be handled separately by the LLM adapter
        return self.messages
