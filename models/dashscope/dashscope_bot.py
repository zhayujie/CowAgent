# encoding:utf-8

import json
from typing import Optional

from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from .dashscope_session import DashscopeSession
import os
import dashscope
from dashscope import MultiModalConversation
from http import HTTPStatus



# Legacy model name mapping for older dashscope SDK constants.
# New models don't need to be added here — they use their name string directly.
dashscope_models = {
    "qwen-turbo": dashscope.Generation.Models.qwen_turbo,
    "qwen-plus": dashscope.Generation.Models.qwen_plus,
    "qwen-max": dashscope.Generation.Models.qwen_max,
    "qwen-bailian-v1": dashscope.Generation.Models.bailian_v1,
}

# Model name prefixes that require MultiModalConversation API instead of Generation API.
# Qwen3.5+ series are omni models that only support MultiModalConversation.
MULTIMODAL_MODEL_PREFIXES = ("qwen3.5-", "qwen3.6-")


# Qwen对话模型API
class DashscopeBot(Bot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(DashscopeSession, model=conf().get("model") or "qwen3.6-plus")
        self.model_name = conf().get("model") or "qwen3.6-plus"
        self.client = dashscope.Generation
        api_key = conf().get("dashscope_api_key")
        if api_key:
            os.environ["DASHSCOPE_API_KEY"] = api_key

    @property
    def api_key(self):
        return conf().get("dashscope_api_key")

    @staticmethod
    def _is_multimodal_model(model_name: str) -> bool:
        """Check if the model requires MultiModalConversation API"""
        return model_name.startswith(MULTIMODAL_MODEL_PREFIXES)

    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[DASHSCOPE] query={}".format(query))

            session_id = context["session_id"]
            reply = None
            clear_memory_commands = conf().get("clear_memory_commands", ["#清除记忆"])
            if query in clear_memory_commands:
                self.sessions.clear_session(session_id)
                reply = Reply(ReplyType.INFO, "记忆已清除")
            elif query == "#清除所有":
                self.sessions.clear_all_session()
                reply = Reply(ReplyType.INFO, "所有人记忆已清除")
            elif query == "#更新配置":
                load_config()
                reply = Reply(ReplyType.INFO, "配置已更新")
            if reply:
                return reply
            session = self.sessions.session_query(query, session_id)
            logger.debug("[DASHSCOPE] session query={}".format(session.messages))

            reply_content = self.reply_text(session)
            logger.debug(
                "[DASHSCOPE] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages,
                    session_id,
                    reply_content["content"],
                    reply_content["completion_tokens"],
                )
            )
            if reply_content["completion_tokens"] == 0 and len(reply_content["content"]) > 0:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
            elif reply_content["completion_tokens"] > 0:
                self.sessions.session_reply(reply_content["content"], session_id, reply_content["total_tokens"])
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[DASHSCOPE] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: DashscopeSession, retry_count=0) -> dict:
        """
        call openai's ChatCompletion to get the answer
        :param session: a conversation session
        :param session_id: session id
        :param retry_count: retry count
        :return: {}
        """
        try:
            dashscope.api_key = self.api_key
            model = dashscope_models.get(self.model_name, self.model_name)
            if self._is_multimodal_model(self.model_name):
                mm_messages = self._prepare_messages_for_multimodal(session.messages)
                response = MultiModalConversation.call(
                    model=model,
                    messages=mm_messages,
                    result_format="message"
                )
            else:
                response = self.client.call(
                    model,
                    messages=session.messages,
                    result_format="message"
                )
            if response.status_code == HTTPStatus.OK:
                resp_dict = self._response_to_dict(response)
                choice = resp_dict["output"]["choices"][0]
                content = choice.get("message", {}).get("content", "")
                # Multimodal models may return content as a list of blocks
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                usage = resp_dict.get("usage", {})
                return {
                    "total_tokens": usage.get("total_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "content": content,
                }
            else:
                logger.error('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
                    response.request_id, response.status_code,
                    response.code, response.message
                ))
                result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
                need_retry = retry_count < 2
                result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
                if need_retry:
                    return self.reply_text(session, retry_count + 1)
                else:
                    return result
        except Exception as e:
            logger.exception(e)
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if need_retry:
                return self.reply_text(session, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using DashScope MultiModalConversation API."""
        try:
            dashscope.api_key = self.api_key
            vision_model = model or "qwen-vl-max"

            # DashScope multimodal format: {"image": url} + {"text": question}
            messages = [{
                "role": "user",
                "content": [
                    {"image": image_url},
                    {"text": question},
                ],
            }]

            response = MultiModalConversation.call(
                model=vision_model,
                messages=messages,
                max_tokens=max_tokens,
            )

            if response.status_code != HTTPStatus.OK:
                return {
                    "error": True,
                    "message": f"{response.code} - {response.message}",
                }

            resp_dict = self._response_to_dict(response)
            choice = resp_dict["output"]["choices"][0]
            content = choice.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            usage = resp_dict.get("usage", {})
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[DASHSCOPE] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call DashScope API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → DashScope format)
        2. System prompt injection
        3. API calling with DashScope SDK
        4. Thinking mode support (enable_thinking for Qwen3)
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response or generator for streaming
        """
        try:
            # Convert messages from Claude format to DashScope format
            messages = self._convert_messages_to_dashscope_format(messages)
            
            # Convert tools from Claude format to DashScope format
            if tools:
                tools = self._convert_tools_to_dashscope_format(tools)
            
            # Handle system prompt
            system_prompt = kwargs.get('system')
            if system_prompt:
                # Add system message at the beginning if not already present
                if not messages or messages[0].get('role') != 'system':
                    messages = [{"role": "system", "content": system_prompt}] + messages
                else:
                    # Replace existing system message
                    messages[0] = {"role": "system", "content": system_prompt}
            
            # Build request parameters
            model_name = kwargs.get("model", self.model_name)
            
            parameters = {
                "result_format": "message",  # Required for tool calling
                "temperature": kwargs.get("temperature", conf().get("temperature", 0.85)),
                "top_p": kwargs.get("top_p", conf().get("top_p", 0.8)),
            }
            
            # Add max_tokens if specified
            if kwargs.get("max_tokens"):
                parameters["max_tokens"] = kwargs["max_tokens"]
            
            # Add tools if provided
            if tools:
                parameters["tools"] = tools
                # Add tool_choice if specified
                if kwargs.get("tool_choice"):
                    parameters["tool_choice"] = kwargs["tool_choice"]
            
            # Add thinking parameters for Qwen3/QwQ models
            if "qwen3" in model_name.lower() or "qwq" in model_name.lower():
                thinking = kwargs.get("thinking", {"type": "enabled"})
                if thinking.get("type") == "enabled":
                    parameters["enable_thinking"] = True
                    if kwargs.get("thinking_budget"):
                        parameters["thinking_budget"] = kwargs["thinking_budget"]
                    if stream:
                        parameters["incremental_output"] = True
                else:
                    parameters["enable_thinking"] = False
            
            # Always use incremental_output for streaming (for better token-by-token streaming)
            # This is especially important for tool calling to avoid incomplete responses
            if stream:
                parameters["incremental_output"] = True
            
            # Make API call with DashScope SDK
            if stream:
                return self._handle_stream_response(model_name, messages, parameters)
            else:
                return self._handle_sync_response(model_name, messages, parameters)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[DASHSCOPE] call_with_tools error: {error_msg}")
            if stream:
                def error_generator():
                    yield {
                        "error": True,
                        "message": error_msg,
                        "status_code": 500
                    }
                return error_generator()
            else:
                return {
                    "error": True,
                    "message": error_msg,
                    "status_code": 500
                }
    
    def _handle_sync_response(self, model_name, messages, parameters):
        """Handle synchronous DashScope API response"""
        try:
            # Set API key before calling
            dashscope.api_key = self.api_key
            model = dashscope_models.get(model_name, model_name)

            if self._is_multimodal_model(model_name):
                messages = self._prepare_messages_for_multimodal(messages)
                response = MultiModalConversation.call(
                    model=model,
                    messages=messages,
                    **parameters
                )
            else:
                response = dashscope.Generation.call(
                    model=model,
                    messages=messages,
                    **parameters
                )

            if response.status_code == HTTPStatus.OK:
                # Convert response to dict to avoid DashScope object KeyError issues
                resp_dict = self._response_to_dict(response)
                choice = resp_dict["output"]["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "")
                # Multimodal models may return content as a list of blocks
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                usage = resp_dict.get("usage", {})
                return {
                    "id": resp_dict.get("request_id"),
                    "object": "chat.completion",
                    "created": 0,
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": message.get("role", "assistant"),
                            "content": content,
                            "tool_calls": self._convert_tool_calls_to_openai_format(
                                message.get("tool_calls")
                            )
                        },
                        "finish_reason": choice.get("finish_reason")
                    }],
                    "usage": {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)
                    }
                }
            else:
                logger.error(f"[DASHSCOPE] API error: {response.code} - {response.message}")
                return {
                    "error": True,
                    "message": response.message,
                    "status_code": response.status_code
                }

        except Exception as e:
            logger.error(f"[DASHSCOPE] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _handle_stream_response(self, model_name, messages, parameters):
        """Handle streaming DashScope API response"""
        try:
            # Set API key before calling
            dashscope.api_key = self.api_key
            model = dashscope_models.get(model_name, model_name)

            if self._is_multimodal_model(model_name):
                messages = self._prepare_messages_for_multimodal(messages)
                responses = MultiModalConversation.call(
                    model=model,
                    messages=messages,
                    stream=True,
                    **parameters
                )
            else:
                responses = dashscope.Generation.call(
                    model=model,
                    messages=messages,
                    stream=True,
                    **parameters
                )
            
            # Stream chunks to caller, converting to OpenAI format
            for response in responses:
                # Convert to dict first to avoid DashScope proxy object KeyError
                resp_dict = self._response_to_dict(response)
                status_code = resp_dict.get("status_code", 200)

                if status_code != HTTPStatus.OK:
                    err_code = resp_dict.get("code", "")
                    err_msg = resp_dict.get("message", "Unknown error")
                    logger.error(f"[DASHSCOPE] Stream error: {err_code} - {err_msg}")
                    yield {
                        "error": True,
                        "message": err_msg,
                        "status_code": status_code
                    }
                    continue

                choices = resp_dict.get("output", {}).get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                finish_reason = choice.get("finish_reason")
                message = choice.get("message", {})

                # Convert to OpenAI-compatible format
                openai_chunk = {
                    "id": resp_dict.get("request_id"),
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason
                    }]
                }

                # Add role
                role = message.get("role")
                if role:
                    openai_chunk["choices"][0]["delta"]["role"] = role

                # Add reasoning_content (thinking process from models like qwen3.5)
                reasoning_content = message.get("reasoning_content")
                if reasoning_content:
                    openai_chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_content

                # Add content (multimodal models may return list of blocks)
                content = message.get("content")
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                if content:
                    openai_chunk["choices"][0]["delta"]["content"] = content

                # Add tool_calls
                tool_calls = message.get("tool_calls")
                if tool_calls:
                    openai_chunk["choices"][0]["delta"]["tool_calls"] = self._convert_tool_calls_to_openai_format(tool_calls)

                yield openai_chunk

        except Exception as e:
            logger.error(f"[DASHSCOPE] stream response error: {e}", exc_info=True)
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    @staticmethod
    def _response_to_dict(response) -> dict:
        """
        Convert DashScope response object to a plain dict.

        DashScope SDK wraps responses in proxy objects whose __getattr__
        delegates to __getitem__, raising KeyError (not AttributeError)
        when an attribute is missing.  Standard hasattr / getattr only
        catch AttributeError, so we must use try-except everywhere.
        """
        _SENTINEL = object()

        def _safe_getattr(obj, name, default=_SENTINEL):
            """getattr that also catches KeyError from DashScope proxy objects."""
            try:
                return getattr(obj, name)
            except (AttributeError, KeyError, TypeError):
                return default

        def _has_attr(obj, name):
            return _safe_getattr(obj, name) is not _SENTINEL

        def _to_dict(obj):
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            if isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_to_dict(i) for i in obj]
            # DashScope response objects behave like dicts (have .keys())
            if _has_attr(obj, "keys"):
                try:
                    return {k: _to_dict(obj[k]) for k in obj.keys()}
                except Exception:
                    pass
            return obj

        result = {}
        # Extract known top-level fields safely
        for attr in ("request_id", "status_code", "code", "message", "output", "usage"):
            val = _safe_getattr(response, attr)
            if val is _SENTINEL:
                try:
                    val = response[attr]
                except (KeyError, TypeError, IndexError):
                    continue
            result[attr] = _to_dict(val)
        return result

    def _convert_tools_to_dashscope_format(self, tools):
        """
        Convert tools from Claude format to DashScope format
        
        Claude format: {name, description, input_schema}
        DashScope format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        dashscope_tools = []
        for tool in tools:
            # Check if already in DashScope/OpenAI format
            if 'type' in tool and tool['type'] == 'function':
                dashscope_tools.append(tool)
            else:
                # Convert from Claude format
                dashscope_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return dashscope_tools
    
    @staticmethod
    def _prepare_messages_for_multimodal(messages: list) -> list:
        """
        Ensure messages are compatible with MultiModalConversation API.

        MultiModalConversation._preprocess_messages iterates every message
        with ``content = message["content"]; for elem in content: ...``,
        which means:
          1. Every message MUST have a 'content' key.
          2. 'content' MUST be an iterable (list), not a plain string.
             The expected format is [{"text": "..."}, ...].

        Meanwhile the DashScope API requires role='tool' messages to follow
        assistant tool_calls, so we must NOT convert them to role='user'.
        We just ensure they have a list-typed 'content'.
        """
        result = []
        for msg in messages:
            msg = dict(msg)  # shallow copy

            # Normalize content to list format [{"text": "..."}]
            content = msg.get("content")
            if content is None or (isinstance(content, str) and content == ""):
                msg["content"] = [{"text": ""}]
            elif isinstance(content, str):
                msg["content"] = [{"text": content}]
            # If content is already a list, keep as-is (already in multimodal format)

            result.append(msg)
        return result

    def _convert_messages_to_dashscope_format(self, messages):
        """
        Convert messages from Claude format to DashScope format
        
        Claude uses content blocks with types like 'tool_use', 'tool_result'
        DashScope uses 'tool_calls' in assistant messages and 'tool' role for results
        """
        if not messages:
            return []
        
        dashscope_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # Handle string content (already in correct format)
            if isinstance(content, str):
                dashscope_messages.append(msg)
                continue
            
            # Handle list content (Claude format with content blocks)
            if isinstance(content, list):
                # Check if this is a tool result message (user role with tool_result blocks)
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # Convert each tool_result block to a separate tool message
                    for block in content:
                        if block.get("type") == "tool_result":
                            dashscope_messages.append({
                                "role": "tool",
                                "content": block.get("content", ""),
                                "tool_call_id": block.get("tool_use_id")  # DashScope uses 'tool_call_id'
                            })
                
                # Check if this is an assistant message with tool_use blocks
                elif role == "assistant":
                    # Separate text content and tool_use blocks
                    text_parts = []
                    tool_calls = []
                    
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })
                    
                    # Build DashScope format assistant message
                    dashscope_msg = {
                        "role": "assistant"
                    }
                    
                    # Add content only if there is actual text
                    # DashScope API: when tool_calls exist, content should be None or omitted if empty
                    if text_parts:
                        dashscope_msg["content"] = " ".join(text_parts)
                    elif not tool_calls:
                        # If no tool_calls and no text, set empty string (rare case)
                        dashscope_msg["content"] = ""
                    # If there are tool_calls but no text, don't set content field at all
                    
                    if tool_calls:
                        dashscope_msg["tool_calls"] = tool_calls
                    
                    dashscope_messages.append(dashscope_msg)
                else:
                    # Other list content, keep as is
                    dashscope_messages.append(msg)
            else:
                # Other formats, keep as is
                dashscope_messages.append(msg)
        
        return dashscope_messages
    
    def _convert_tool_calls_to_openai_format(self, tool_calls):
        """Convert DashScope tool_calls to OpenAI format"""
        if not tool_calls:
            return None
        
        openai_tool_calls = []
        for tool_call in tool_calls:
            # DashScope format is already similar to OpenAI
            if isinstance(tool_call, dict):
                openai_tool_calls.append(tool_call)
            else:
                # Handle object format
                openai_tool_calls.append({
                    "id": getattr(tool_call, 'id', None),
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })
        
        return openai_tool_calls
