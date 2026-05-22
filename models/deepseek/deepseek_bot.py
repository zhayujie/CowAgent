# encoding:utf-8

"""
DeepSeek Bot — fully OpenAI-compatible, uses its own API key / base config.

Supported models:
- deepseek-chat       (V3, no thinking)
- deepseek-reasoner   (R1, built-in reasoning, no `thinking` switch)
- deepseek-v4-flash   (V4, supports thinking mode + tool calls)
- deepseek-v4-flash   (V4 Flash, default; thinking mode + tool calls)
- deepseek-v4-pro     (V4 Pro, stronger on complex tasks)

Thinking mode notes (for V4 models):
- Toggle: ``{"thinking": {"type": "enabled" | "disabled"}}`` (default: enabled)
- Effort: ``reasoning_effort`` ∈ {"high", "max"} (low/medium → high, xhigh → max)
- In thinking mode, ``temperature``/``top_p``/``presence_penalty``/``frequency_penalty``
  are silently ignored by the server; we drop them locally to avoid confusion.
- ``reasoning_content`` is returned alongside ``content``. For turns that triggered
  tool calls, ``reasoning_content`` MUST be echoed back in subsequent requests, or
  the API returns 400.
"""

import json
import time
from typing import Optional

import requests
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf, load_config
from .deepseek_session import DeepSeekSession

DEFAULT_API_BASE = "https://api.deepseek.com/v1"


class DeepSeekBot(Bot, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(
            DeepSeekSession,
            model=conf().get("model") or const.DEEPSEEK_V4_FLASH,
        )
        conf_model = conf().get("model") or const.DEEPSEEK_V4_FLASH
        self.args = {
            "model": conf_model,
            "temperature": conf().get("temperature", 0.7),
            "top_p": conf().get("top_p", 1.0),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),
            "presence_penalty": conf().get("presence_penalty", 0.0),
        }

    # ---------- config helpers ----------

    @property
    def api_key(self):
        return conf().get("deepseek_api_key") or conf().get("open_ai_api_key")

    @property
    def api_base(self):
        url = (
            conf().get("deepseek_api_base")
            or conf().get("open_ai_api_base")
            or DEFAULT_API_BASE
        )
        return url.rstrip("/")

    def get_api_config(self):
        """OpenAICompatibleBot interface — used by call_with_tools()."""
        return {
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": conf().get("model", const.DEEPSEEK_V4_FLASH),
            "default_temperature": conf().get("temperature", 0.7),
            "default_top_p": conf().get("top_p", 1.0),
            "default_frequency_penalty": conf().get("frequency_penalty", 0.0),
            "default_presence_penalty": conf().get("presence_penalty", 0.0),
        }

    @staticmethod
    def _model_supports_thinking(model_name: str) -> bool:
        """V4 series models expose the explicit `thinking` switch."""
        if not model_name:
            return False
        m = model_name.lower()
        return m.startswith("deepseek-v4")

    @staticmethod
    def _is_reasoner_model(model_name: str) -> bool:
        """deepseek-reasoner (R1) always thinks internally; no toggle."""
        return bool(model_name) and "reasoner" in model_name.lower()

    def _build_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ---------- simple chat (non-agent mode) ----------

    def reply(self, query, context=None):
        if context.type == ContextType.TEXT:
            logger.info("[DEEPSEEK] query={}".format(query))

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
            logger.debug("[DEEPSEEK] session query={}".format(session.messages))

            new_args = self.args.copy()
            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[DEEPSEEK] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages, session_id,
                    reply_content["content"], reply_content["completion_tokens"],
                )
            )
            if reply_content["completion_tokens"] == 0 and len(reply_content["content"]) > 0:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
            elif reply_content["completion_tokens"] > 0:
                self.sessions.session_reply(
                    reply_content["content"], session_id, reply_content["total_tokens"],
                )
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[DEEPSEEK] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session, args=None, retry_count: int = 0) -> dict:
        try:
            headers = self._build_headers()
            body = dict(args) if args else dict(self.args)
            body["messages"] = session.messages

            # Thinking mode ignores temperature/top_p/penalties — strip to avoid noise.
            model_name = str(body.get("model", ""))
            if self._model_supports_thinking(model_name) or self._is_reasoner_model(model_name):
                for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                    body.pop(k, None)

            res = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers,
                json=body,
                timeout=180,
            )
            if res.status_code == 200:
                response = res.json()
                return {
                    "total_tokens": response["usage"]["total_tokens"],
                    "completion_tokens": response["usage"]["completion_tokens"],
                    "content": response["choices"][0]["message"]["content"],
                }
            else:
                response = res.json()
                error = response.get("error", {})
                logger.error(
                    f"[DEEPSEEK] chat failed, status_code={res.status_code}, "
                    f"msg={error.get('message')}, type={error.get('type')}"
                )
                result = {"completion_tokens": 0, "content": "提问太快啦，请休息一下再问我吧"}
                need_retry = False
                if res.status_code >= 500:
                    need_retry = retry_count < 2
                elif res.status_code == 401:
                    result["content"] = "授权失败，请检查API Key是否正确"
                elif res.status_code == 429:
                    result["content"] = "请求过于频繁，请稍后再试"
                    need_retry = retry_count < 2

                if need_retry:
                    time.sleep(3)
                    return self.reply_text(session, args, retry_count + 1)
                return result
        except Exception as e:
            logger.exception(e)
            if retry_count < 2:
                return self.reply_text(session, args, retry_count + 1)
            return {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

    # ==================== Agent mode support ====================

    def call_with_tools(self, messages, tools=None, stream: bool = False, **kwargs):
        """
        Call DeepSeek API with tool support for agent integration.

        Handles:
        - Claude → OpenAI message/tool format conversion (with reasoning_content round-trip)
        - System prompt injection
        - Streaming SSE with tool_calls + reasoning_content delta
        - Thinking mode toggle and reasoning_effort for V4 models
        """
        try:
            converted_messages = self._convert_messages_to_openai_format(messages)

            system_prompt = kwargs.pop("system", None)
            if system_prompt:
                if not converted_messages or converted_messages[0].get("role") != "system":
                    converted_messages.insert(0, {"role": "system", "content": system_prompt})
                else:
                    converted_messages[0] = {"role": "system", "content": system_prompt}

            converted_tools = None
            if tools:
                converted_tools = self._convert_tools_to_openai_format(tools)

            model = kwargs.pop("model", None) or self.args["model"]
            max_tokens = kwargs.pop("max_tokens", None)

            request_body = {
                "model": model,
                "messages": converted_messages,
                "stream": stream,
            }
            if max_tokens is not None:
                request_body["max_tokens"] = max_tokens

            if converted_tools:
                request_body["tools"] = converted_tools
                request_body["tool_choice"] = kwargs.pop("tool_choice", "auto")

            # Thinking mode (V4 only). Honour the toggle propagated by agent_bridge.
            thinking_param = kwargs.pop("thinking", None)
            reasoning_effort = kwargs.pop("reasoning_effort", None)
            thinking_active = False

            if self._model_supports_thinking(model):
                # Default to enabled per DeepSeek docs unless caller explicitly disables.
                thinking_param = thinking_param or {"type": "enabled"}
                request_body["thinking"] = thinking_param
                thinking_active = thinking_param.get("type") == "enabled"
                if thinking_active:
                    # Default to "high"; allow caller override (e.g. "max" for heavy agent loops).
                    request_body["reasoning_effort"] = reasoning_effort or "high"
            elif self._is_reasoner_model(model):
                # R1 thinks unconditionally — no `thinking` field, but reasoning_content still flows.
                thinking_active = True

            # Strip params silently ignored under thinking mode to keep the wire clean.
            if thinking_active:
                for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                    request_body.pop(k, None)
                    kwargs.pop(k, None)
            else:
                # Non-thinking path: forward standard sampling controls.
                temperature = kwargs.pop("temperature", None)
                if temperature is not None:
                    request_body["temperature"] = temperature
                top_p = kwargs.pop("top_p", None)
                if top_p is not None:
                    request_body["top_p"] = top_p

            logger.debug(
                f"[DEEPSEEK] API call: model={model}, "
                f"tools={len(converted_tools) if converted_tools else 0}, "
                f"stream={stream}, thinking={thinking_active}"
            )

            if stream:
                return self._handle_stream_response(request_body)
            else:
                return self._handle_sync_response(request_body)

        except Exception as e:
            logger.error(f"[DEEPSEEK] call_with_tools error: {e}")
            import traceback
            logger.error(traceback.format_exc())

            def error_generator():
                yield {"error": True, "message": str(e), "status_code": 500}
            return error_generator()

    # -------------------- streaming --------------------

    def _handle_stream_response(self, request_body: dict):
        """Stream SSE chunks from DeepSeek and yield OpenAI-format deltas (with reasoning_content)."""
        try:
            headers = self._build_headers()
            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, stream=True, timeout=180)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[DEEPSEEK] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            current_tool_calls = {}
            finish_reason = None

            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data_str = line[6:]
                elif line.startswith("data:"):
                    data_str = line[5:]
                else:
                    continue
                if data_str.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"[DEEPSEEK] JSON decode error: {e}, data: {data_str[:200]}")
                    continue

                if chunk.get("error"):
                    error_data = chunk["error"]
                    error_msg = error_data.get("message", "Unknown error") if isinstance(error_data, dict) else str(error_data)
                    logger.error(f"[DEEPSEEK] stream error: {error_msg}")
                    yield {"error": True, "message": error_msg, "status_code": 500}
                    return

                if not chunk.get("choices"):
                    continue
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                # Reasoning content (thinking mode). Forward as its own delta so
                # agent_stream.py can stitch it into a `thinking` block.
                if delta.get("reasoning_content"):
                    yield {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "reasoning_content": delta["reasoning_content"],
                            },
                            "finish_reason": None,
                        }]
                    }

                if delta.get("content"):
                    yield {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": delta["content"],
                            },
                        }]
                    }

                if "tool_calls" in delta and delta["tool_calls"]:
                    for tool_call_chunk in delta["tool_calls"]:
                        index = tool_call_chunk.get("index", 0)
                        if index not in current_tool_calls:
                            current_tool_calls[index] = {
                                "id": tool_call_chunk.get("id", ""),
                                "name": tool_call_chunk.get("function", {}).get("name", ""),
                                "arguments": "",
                            }
                        if "function" in tool_call_chunk and "arguments" in tool_call_chunk["function"]:
                            current_tool_calls[index]["arguments"] += tool_call_chunk["function"]["arguments"]

                        yield {
                            "choices": [{
                                "index": 0,
                                "delta": {"tool_calls": [tool_call_chunk]},
                            }]
                        }

            yield {
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason,
                }]
            }

        except requests.exceptions.Timeout:
            logger.error("[DEEPSEEK] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[DEEPSEEK] stream response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- sync --------------------

    def _handle_sync_response(self, request_body: dict):
        """Single-shot response. Yields a Claude-format dict for symmetry with stream path."""
        try:
            headers = self._build_headers()
            request_body.pop("stream", None)
            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, timeout=180)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[DEEPSEEK] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            result = response.json()
            message = result["choices"][0]["message"]
            finish_reason = result["choices"][0]["finish_reason"]

            response_data = {"role": "assistant", "content": []}

            # Surface reasoning as a `thinking` block so the agent layer can persist it
            # and round-trip it on tool-call turns (required by DeepSeek API).
            if message.get("reasoning_content"):
                response_data["content"].append({
                    "type": "thinking",
                    "thinking": message["reasoning_content"],
                })

            if message.get("content"):
                response_data["content"].append({
                    "type": "text",
                    "text": message["content"],
                })

            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    try:
                        tool_input = json.loads(tool_call["function"]["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                    response_data["content"].append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": tool_input,
                    })

            if finish_reason == "tool_calls":
                response_data["stop_reason"] = "tool_use"
            elif finish_reason == "stop":
                response_data["stop_reason"] = "end_turn"
            else:
                response_data["stop_reason"] = finish_reason

            yield response_data

        except requests.exceptions.Timeout:
            logger.error("[DEEPSEEK] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[DEEPSEEK] sync response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- format conversion --------------------

    def _convert_messages_to_openai_format(self, messages):
        """
        Convert Claude-format messages (content blocks) to OpenAI format.

        Crucially, once any assistant turn in the history triggered a tool
        call, DeepSeek requires `reasoning_content` on **every subsequent
        assistant message** (not just the tool-call one) until the next user
        turn — and in fact the API enforces this for the whole history when
        thinking mode is enabled. Missing `reasoning_content` on any
        assistant message returns 400. We back-fill an empty string when the
        trace was not captured (e.g. history recorded while thinking was
        disabled, or upstream proxy stripped the field).
        """
        if not messages:
            return []

        # Determine whether the history contains any tool-call assistant turn.
        # If so, every assistant message must carry `reasoning_content`.
        has_tool_call_history = False
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            if msg.get("tool_calls"):
                has_tool_call_history = True
                break
            content = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            ):
                has_tool_call_history = True
                break

        converted = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # Pass-through path for non-list content (e.g. plain string).
            # Back-fill `reasoning_content` on assistant messages whenever the
            # history contains any tool-call turn.
            if not isinstance(content, list):
                if (
                    role == "assistant"
                    and isinstance(msg, dict)
                    and has_tool_call_history
                    and "reasoning_content" not in msg
                ):
                    patched = dict(msg)
                    patched["reasoning_content"] = ""
                    converted.append(patched)
                else:
                    converted.append(msg)
                continue

            if role == "user":
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                )
                if has_tool_result:
                    text_parts = []
                    tool_results = []

                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            tool_call_id = block.get("tool_use_id") or ""
                            result_content = block.get("content", "")
                            if not isinstance(result_content, str):
                                result_content = json.dumps(result_content, ensure_ascii=False)
                            tool_results.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": result_content,
                            })

                    converted.extend(tool_results)

                    if text_parts:
                        converted.append({"role": "user", "content": "\n".join(text_parts)})
                else:
                    converted.append(msg)

            elif role == "assistant":
                openai_msg = {"role": "assistant"}
                text_parts = []
                tool_calls = []
                reasoning_parts = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
                    elif btype == "thinking":
                        reasoning_parts.append(block.get("thinking", ""))

                if text_parts:
                    openai_msg["content"] = "\n".join(text_parts)
                elif not tool_calls:
                    openai_msg["content"] = ""

                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls
                    if not text_parts:
                        openai_msg["content"] = None

                # Round-trip reasoning_content: required for every assistant
                # message once the history contains any tool-call turn (see
                # outer comment). Use empty string as fallback when the trace
                # was not captured — DeepSeek validates field presence, not
                # value; non-thinking backends silently ignore it.
                if reasoning_parts:
                    openai_msg["reasoning_content"] = "\n".join(reasoning_parts)
                elif has_tool_call_history:
                    openai_msg["reasoning_content"] = ""

                converted.append(openai_msg)
            else:
                converted.append(msg)

        return converted

    def _convert_tools_to_openai_format(self, tools):
        """
        Convert tools from Claude format to OpenAI format.

        Claude: {name, description, input_schema}
        OpenAI: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None

        converted = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                converted.append(tool)
            else:
                converted.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {}),
                    },
                })
        return converted

    # -------------------- vision --------------------

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyse an image via DeepSeek's OpenAI-compatible /chat/completions endpoint."""
        try:
            vision_model = model or self.args.get("model", const.DEEPSEEK_V4_FLASH)
            payload = {
                "model": vision_model,
                "max_tokens": max_tokens,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            }
            headers = self._build_headers()
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            if "error" in data:
                return {"error": True, "message": data["error"].get("message", str(data["error"]))}
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[DEEPSEEK] call_vision error: {e}")
            return {"error": True, "message": str(e)}
