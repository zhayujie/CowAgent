# encoding:utf-8

import base64
import json
import re
import time
from typing import Optional

import requests

from models.baidu.baidu_wenxin_session import BaiduWenxinSession
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf

# Optional OpenAI image support
try:
    from models.openai.open_ai_image import OpenAIImage
    _openai_image_available = True
except Exception as e:
    logger.warning(f"OpenAI image support not available: {e}")
    _openai_image_available = False
    OpenAIImage = object  # Fallback to object

user_session = dict()


# OpenAI对话模型API (可用)
class ClaudeAPIBot(Bot, OpenAIImage):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(BaiduWenxinSession, model=conf().get("model") or "text-davinci-003")

    @property
    def api_key(self):
        return conf().get("claude_api_key")

    @property
    def api_base(self):
        return conf().get("claude_api_base") or "https://api.anthropic.com/v1"

    @property
    def proxy(self):
        return conf().get("proxy", None)

    def reply(self, query, context=None):
        # acquire reply content
        if context and context.type:
            if context.type == ContextType.TEXT:
                logger.info("[CLAUDE_API] query={}".format(query))
                session_id = context["session_id"]
                reply = None
                if query == "#清除记忆":
                    self.sessions.clear_session(session_id)
                    reply = Reply(ReplyType.INFO, "记忆已清除")
                elif query == "#清除所有":
                    self.sessions.clear_all_session()
                    reply = Reply(ReplyType.INFO, "所有人记忆已清除")
                else:
                    session = self.sessions.session_query(query, session_id)
                    result = self.reply_text(session)
                    logger.info(result)
                    total_tokens, completion_tokens, reply_content = (
                        result["total_tokens"],
                        result["completion_tokens"],
                        result["content"],
                    )
                    logger.debug(
                        "[CLAUDE_API] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(str(session), session_id, reply_content, completion_tokens)
                    )

                    if total_tokens == 0:
                        reply = Reply(ReplyType.ERROR, reply_content)
                    else:
                        self.sessions.session_reply(reply_content, session_id, total_tokens)
                        reply = Reply(ReplyType.TEXT, reply_content)
                return reply
            elif context.type == ContextType.IMAGE_CREATE:
                ok, retstring = self.create_img(query, 0)
                reply = None
                if ok:
                    reply = Reply(ReplyType.IMAGE_URL, retstring)
                else:
                    reply = Reply(ReplyType.ERROR, retstring)
                return reply

    def reply_text(self, session: BaiduWenxinSession, retry_count=0, tools=None):
        try:
            actual_model = self._model_mapping(conf().get("model"))

            # Prepare headers
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            # Extract system prompt if present and prepare Claude-compatible messages
            system_prompt = conf().get("character_desc", "")
            claude_messages = []

            for msg in session.messages:
                if msg.get("role") == "system":
                    system_prompt = msg["content"]
                else:
                    claude_messages.append(msg)

            # Prepare request data
            data = {
                "model": actual_model,
                "messages": claude_messages,
                "max_tokens": self._get_max_tokens(actual_model)
            }

            if system_prompt:
                data["system"] = system_prompt

            if tools:
                data["tools"] = tools

            # Make HTTP request
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=data,
                proxies=proxies
            )

            if response.status_code != 200:
                raise Exception(f"API request failed: {response.status_code} - {response.text}")

            claude_response = response.json()
            # Handle response content and tool calls
            res_content = ""
            tool_calls = []

            content_blocks = claude_response.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    res_content += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {})
                    })

            res_content = res_content.strip().replace("<|endoftext|>", "")
            usage = claude_response.get("usage", {})
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            logger.info("[CLAUDE_API] reply={}".format(res_content))
            if tool_calls:
                logger.info("[CLAUDE_API] tool_calls={}".format(tool_calls))

            result = {
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "content": res_content,
            }

            if tool_calls:
                result["tool_calls"] = tool_calls

            return result
        except Exception as e:
            need_retry = retry_count < 2
            result = {"total_tokens": 0, "completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

            # Handle different types of errors
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                logger.warn("[CLAUDE_API] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif "timeout" in error_str:
                logger.warn("[CLAUDE_API] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif "connection" in error_str or "network" in error_str:
                logger.warn("[CLAUDE_API] APIConnectionError: {}".format(e))
                need_retry = False
                result["content"] = "我连接不到你的网络"
            else:
                logger.warn("[CLAUDE_API] Exception: {}".format(e))
                need_retry = False
                self.sessions.clear_session(session.session_id)

            if need_retry:
                logger.warn("[CLAUDE_API] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session, retry_count + 1, tools)
            else:
                return result

    def _model_mapping(self, model) -> str:
        if model == "claude-3-opus":
            return const.CLAUDE_3_OPUS
        elif model == "claude-3-sonnet":
            return const.CLAUDE_3_SONNET
        elif model == "claude-3-haiku":
            return const.CLAUDE_3_HAIKU
        elif model == "claude-3.5-sonnet":
            return const.CLAUDE_35_SONNET
        return model

    def _get_max_tokens(self, model: str) -> int:
        """
        Get max_tokens for the model.
        Reference from pi-mono:
        - Claude 3.5/3.7: 8192
        - Claude 3 Opus: 4096
        - Default: 8192
        """
        if model and (model.startswith("claude-3-5") or model.startswith("claude-3-7")):
            return 8192
        elif model and model.startswith("claude-3") and "opus" in model:
            return 4096
        elif model and (model.startswith("claude-sonnet-4") or model.startswith("claude-opus-4")):
            return 64000
        return 8192

    @staticmethod
    def _parse_data_url(data_url: str):
        """Parse a data:<mime>;base64,<data> URL into (media_type, base64_data)."""
        m = re.match(r"^data:([^;]+);base64,(.+)$", data_url, re.DOTALL)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using Claude Messages API (native image blocks)."""
        try:
            actual_model = model or self._model_mapping(conf().get("model"))

            # Build Claude-native image content block
            if image_url.startswith("data:"):
                media_type, b64_data = self._parse_data_url(image_url)
                if not b64_data:
                    return {"error": True, "message": "Invalid base64 data URL"}
                image_block = {
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": media_type or "image/jpeg",
                               "data": b64_data},
                }
            else:
                image_block = {
                    "type": "image",
                    "source": {"type": "url", "url": image_url},
                }

            data = {
                "model": actual_model,
                "max_tokens": max_tokens,
                "messages": [{
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": question},
                    ],
                }],
            }

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            resp = requests.post(f"{self.api_base}/messages",
                                 headers=headers, json=data, proxies=proxies)

            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

            body = resp.json()
            text_parts = [b.get("text", "") for b in body.get("content", [])
                          if b.get("type") == "text"]
            usage = body.get("usage", {})
            return {
                "model": actual_model,
                "content": "".join(text_parts),
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[CLAUDE] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call Claude API with tool support for agent integration

        Args:
            messages: List of messages
            tools: List of tool definitions
            stream: Whether to use streaming
            **kwargs: Additional parameters
            
        Returns:
            Formatted response compatible with OpenAI format or generator for streaming
        """
        actual_model = self._model_mapping(conf().get("model"))

        # Extract system prompt from messages if present
        system_prompt = kwargs.get("system", conf().get("character_desc", ""))
        claude_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                claude_messages.append(self._sanitize_message(msg))

        request_params = {
            "model": actual_model,
            "max_tokens": kwargs.get("max_tokens", self._get_max_tokens(actual_model)),
            "messages": claude_messages,
            "stream": stream
        }

        if system_prompt:
            request_params["system"] = system_prompt

        if tools:
            request_params["tools"] = tools

        try:
            if stream:
                return self._handle_stream_response(request_params)
            else:
                return self._handle_sync_response(request_params)
        except Exception as e:
            logger.error(f"Claude API call error: {e}")
            if stream:
                # Return error generator for stream
                def error_generator():
                    yield {
                        "error": True,
                        "message": str(e),
                        "status_code": 500
                    }

                return error_generator()
            else:
                # Return error response for sync
                return {
                    "error": True,
                    "message": str(e),
                    "status_code": 500
                }

    @staticmethod
    def _sanitize_message(msg: dict) -> dict:
        """Strip thinking blocks without a ``signature`` from assistant messages.

        When the session switches from another model (e.g. MiniMax) to Claude,
        the in-memory history may contain thinking blocks that lack the
        ``signature`` field required by the Anthropic API, causing 400 errors.
        We create a shallow copy so the original history is not mutated.
        """
        if msg.get("role") != "assistant":
            return msg
        content = msg.get("content")
        if not isinstance(content, list):
            return msg
        cleaned = [
            block for block in content
            if not (isinstance(block, dict)
                    and block.get("type") == "thinking"
                    and "signature" not in block)
        ]
        if len(cleaned) == len(content):
            return msg
        return {**msg, "content": cleaned}

    def _handle_sync_response(self, request_params):
        """Handle synchronous Claude API response"""
        # Prepare headers
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Make HTTP request
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        response = requests.post(
            f"{self.api_base}/messages",
            headers=headers,
            json=request_params,
            proxies=proxies
        )

        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")

        claude_response = response.json()

        # Extract content blocks
        text_content = ""
        tool_calls = []

        content_blocks = claude_response.get("content", [])
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })

        # Build message in OpenAI format
        message = {
            "role": "assistant",
            "content": text_content
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Format response to match OpenAI structure
        usage = claude_response.get("usage", {})
        formatted_response = {
            "id": claude_response.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": claude_response.get("model", request_params["model"]),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": claude_response.get("stop_reason", "stop")
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        }

        return formatted_response

    def _handle_stream_response(self, request_params):
        """Handle streaming Claude API response using HTTP requests"""
        # Prepare headers
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Add stream parameter
        request_params["stream"] = True

        # Track tool use state
        tool_uses_map = {}  # {index: {id, name, input}}
        current_tool_use_index = -1
        stop_reason = None  # Track stop reason from Claude

        try:
            # Make streaming HTTP request
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=request_params,
                proxies=proxies,
                stream=True
            )

            if response.status_code != 200:
                error_text = response.text
                try:
                    error_data = json.loads(error_text)
                    error_msg = error_data.get("error", {}).get("message", error_text)
                except Exception:
                    error_msg = error_text or "Unknown error"

                yield {
                    "error": True,
                    "status_code": response.status_code,
                    "message": error_msg
                }
                return

            # Process streaming response
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        if line == '[DONE]':
                            break
                        try:
                            event = json.loads(line)
                            event_type = event.get("type")

                            if event_type == "content_block_start":
                                # New content block
                                block = event.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    current_tool_use_index = event.get("index", 0)
                                    tool_uses_map[current_tool_use_index] = {
                                        "id": block.get("id", ""),
                                        "name": block.get("name", ""),
                                        "input": ""
                                    }

                            elif event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                delta_type = delta.get("type")

                                if delta_type == "thinking_delta":
                                    thinking_text = delta.get("thinking", "")
                                    if thinking_text:
                                        yield {
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "role": "assistant",
                                                    "reasoning_content": thinking_text
                                                },
                                                "finish_reason": None
                                            }]
                                        }

                                elif delta_type == "text_delta":
                                    content = delta.get("text", "")
                                    yield {
                                        "id": event.get("id", ""),
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": request_params["model"],
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": content},
                                            "finish_reason": None
                                        }]
                                    }

                                elif delta_type == "input_json_delta":
                                    # Tool input accumulation
                                    if current_tool_use_index >= 0:
                                        tool_uses_map[current_tool_use_index]["input"] += delta.get("partial_json", "")

                            elif event_type == "message_delta":
                                # Extract stop_reason from delta
                                delta = event.get("delta", {})
                                if "stop_reason" in delta:
                                    stop_reason = delta.get("stop_reason")
                                    logger.info(f"[Claude] Stream stop_reason: {stop_reason}")
                                
                                # Message complete - yield tool calls if any
                                if tool_uses_map:
                                    for idx in sorted(tool_uses_map.keys()):
                                        tool_data = tool_uses_map[idx]
                                        yield {
                                            "id": event.get("id", ""),
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": request_params["model"],
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "tool_calls": [{
                                                        "index": idx,
                                                        "id": tool_data["id"],
                                                        "type": "function",
                                                        "function": {
                                                            "name": tool_data["name"],
                                                            "arguments": tool_data["input"]
                                                        }
                                                    }]
                                                },
                                                "finish_reason": stop_reason
                                            }]
                                        }
                            
                            elif event_type == "message_stop":
                                # Final event - log completion
                                logger.debug(f"[Claude] Stream completed with stop_reason: {stop_reason}")

                        except json.JSONDecodeError:
                            continue

        except requests.RequestException as e:
            logger.error(f"Claude streaming request error: {e}")
            yield {
                "error": True,
                "message": f"Connection error: {str(e)}",
                "status_code": 0
            }
        except Exception as e:
            logger.error(f"Claude streaming error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
