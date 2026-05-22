# encoding:utf-8

import json
import time
from typing import Optional

import requests
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from .moonshot_session import MoonshotSession


# Moonshot (Kimi) API Bot
class MoonshotBot(Bot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(MoonshotSession, model=conf().get("model") or "moonshot-v1-128k")
        model = conf().get("model") or "moonshot-v1-128k"
        if model == "moonshot":
            model = "moonshot-v1-32k"
        self.args = {
            "model": model,
            "temperature": conf().get("temperature", 0.3),
            "top_p": conf().get("top_p", 1.0),
        }

    @property
    def api_key(self):
        return conf().get("moonshot_api_key")

    @property
    def base_url(self):
        url = conf().get("moonshot_base_url", "https://api.moonshot.cn/v1")
        if url.endswith("/chat/completions"):
            url = url.rsplit("/chat/completions", 1)[0]
        return url.rstrip("/")

    @property
    def _is_kimi_coding_plan(self) -> bool:
        """Detect Kimi Coding Plan by model name or API base URL."""
        model = str(conf().get("model", ""))
        base = str(conf().get("moonshot_base_url", ""))
        return model == "kimi-for-coding" or "api.kimi.com/coding" in base

    @staticmethod
    def _model_supports_thinking(model_name: str) -> bool:
        """Return True if the model supports the ``thinking`` request parameter."""
        m = model_name.lower()
        return m.startswith("kimi-k2") or m.startswith("kimi-k1.5")

    def _build_headers(self) -> dict:
        """Build HTTP headers, adding Coding-Agent User-Agent for Kimi Coding Plan."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self._is_kimi_coding_plan:
            headers["User-Agent"] = "claude-cli/2.1.39"
        return headers

    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[MOONSHOT] query={}".format(query))

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
            logger.debug("[MOONSHOT] session query={}".format(session.messages))

            model = context.get("moonshot_model")
            new_args = self.args.copy()
            if model:
                new_args["model"] = model

            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[MOONSHOT] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[MOONSHOT] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: MoonshotSession, args=None, retry_count: int = 0) -> dict:
        """
        Call Moonshot chat completion API to get the answer
        :param session: a conversation session
        :param args: model args
        :param retry_count: retry count
        :return: {}
        """
        try:
            headers = self._build_headers()
            # Fallback to default args (e.g. when called by session title
            # generation which passes only the session). Always copy to avoid
            # mutating the shared self.args across calls.
            body = dict(args) if args else dict(self.args)
            body["messages"] = session.messages
            model_name = str(body.get("model", ""))
            # K2.x / Coding Plan enforce fixed temperature/top_p; strip them.
            if model_name.startswith("kimi-k2") or model_name == "kimi-for-coding":
                body.pop("temperature", None)
                body.pop("top_p", None)
            res = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body
            )
            if res.status_code == 200:
                response = res.json()
                return {
                    "total_tokens": response["usage"]["total_tokens"],
                    "completion_tokens": response["usage"]["completion_tokens"],
                    "content": response["choices"][0]["message"]["content"]
                }
            else:
                response = res.json()
                error = response.get("error")
                logger.error(f"[MOONSHOT] chat failed, status_code={res.status_code}, "
                             f"msg={error.get('message')}, type={error.get('type')}")

                result = {"completion_tokens": 0, "content": "提问太快啦，请休息一下再问我吧"}
                need_retry = False
                if res.status_code >= 500:
                    logger.warn(f"[MOONSHOT] do retry, times={retry_count}")
                    need_retry = retry_count < 2
                elif res.status_code == 401:
                    result["content"] = "授权失败，请检查API Key是否正确"
                elif res.status_code == 429:
                    result["content"] = "请求过于频繁，请稍后再试"
                    need_retry = retry_count < 2
                else:
                    need_retry = False

                if need_retry:
                    time.sleep(3)
                    return self.reply_text(session, args, retry_count + 1)
                else:
                    return result
        except Exception as e:
            logger.exception(e)
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if need_retry:
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using Moonshot (Kimi) OpenAI-compatible API."""
        try:
            vision_model = model or self.args.get("model", "kimi-k2.6")
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
            resp = requests.post(f"{self.base_url}/chat/completions",
                                 headers=headers, json=payload, timeout=60)
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
            logger.error(f"[MOONSHOT] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    # ==================== Agent mode support ====================

    def call_with_tools(self, messages, tools=None, stream: bool = False, **kwargs):
        """
        Call Moonshot API with tool support for agent integration.

        This method handles:
        1. Format conversion (Claude format -> OpenAI format)
        2. System prompt injection
        3. Streaming SSE response with tool_calls
        4. Thinking (reasoning) is disabled by default to avoid tool_choice conflicts

        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, model, etc.)

        Returns:
            Generator yielding OpenAI-format chunks (for streaming)
        """
        try:
            # Convert messages from Claude format to OpenAI format
            converted_messages = self._convert_messages_to_openai_format(messages)

            # Inject system prompt if provided
            system_prompt = kwargs.pop("system", None)
            if system_prompt:
                if not converted_messages or converted_messages[0].get("role") != "system":
                    converted_messages.insert(0, {"role": "system", "content": system_prompt})
                else:
                    converted_messages[0] = {"role": "system", "content": system_prompt}

            # Convert tools from Claude format to OpenAI format
            converted_tools = None
            if tools:
                converted_tools = self._convert_tools_to_openai_format(tools)

            # Resolve model / temperature
            model = kwargs.pop("model", None) or self.args["model"]
            max_tokens = kwargs.pop("max_tokens", None)
            # Don't pop temperature, just ignore it
            kwargs.pop("temperature", None)

            # Build request body (omit temperature, let the API use its own default)
            request_body = {
                "model": model,
                "messages": converted_messages,
                "stream": stream,
            }
            if max_tokens is not None:
                request_body["max_tokens"] = max_tokens

            # Add tools
            if converted_tools:
                request_body["tools"] = converted_tools
                request_body["tool_choice"] = "auto"

            # Kimi Coding Plan has built-in reasoning and ignores the thinking param.
            # For regular Kimi models, only K2/K1.5 series support the thinking param.
            # Respect the enable_thinking config passed from agent_bridge.
            if not self._is_kimi_coding_plan and self._model_supports_thinking(model):
                thinking = kwargs.get("thinking", {"type": "enabled"})
                request_body["thinking"] = thinking

            logger.debug(f"[MOONSHOT] API call: model={model}, "
                         f"tools={len(converted_tools) if converted_tools else 0}, stream={stream}")

            if stream:
                return self._handle_stream_response(request_body)
            else:
                return self._handle_sync_response(request_body)

        except Exception as e:
            logger.error(f"[MOONSHOT] call_with_tools error: {e}")
            import traceback
            logger.error(traceback.format_exc())

            def error_generator():
                yield {"error": True, "message": str(e), "status_code": 500}
            return error_generator()

    # -------------------- streaming --------------------

    def _handle_stream_response(self, request_body: dict):
        """Handle streaming SSE response from Moonshot API and yield OpenAI-format chunks."""
        try:
            headers = self._build_headers()

            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, stream=True, timeout=120)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MOONSHOT] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            current_tool_calls = {}
            finish_reason = None

            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode("utf-8")
                # Handle both "data: {...}" and "data:{...}" (Kimi Coding Plan omits the space)
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
                    logger.warning(f"[MOONSHOT] JSON decode error: {e}, data: {data_str[:200]}")
                    continue

                # Check for error in chunk
                if chunk.get("error"):
                    error_data = chunk["error"]
                    error_msg = error_data.get("message", "Unknown error") if isinstance(error_data, dict) else str(error_data)
                    logger.error(f"[MOONSHOT] stream error: {error_msg}")
                    yield {"error": True, "message": error_msg, "status_code": 500}
                    return

                if not chunk.get("choices"):
                    continue

                choices = chunk["choices"]
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})

                # Capture finish_reason early (it may arrive on any chunk type)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                if delta.get("reasoning_content"):
                    yield {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "reasoning_content": delta["reasoning_content"]
                            },
                            "finish_reason": None
                        }]
                    }
                    continue

                # Handle text content
                if "content" in delta and delta["content"]:
                    yield {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": delta["content"]
                            }
                        }]
                    }

                # Handle tool_calls (streamed incrementally)
                if "tool_calls" in delta:
                    for tool_call_chunk in delta["tool_calls"]:
                        index = tool_call_chunk.get("index", 0)
                        if index not in current_tool_calls:
                            current_tool_calls[index] = {
                                "id": tool_call_chunk.get("id", ""),
                                "type": "tool_use",
                                "name": tool_call_chunk.get("function", {}).get("name", ""),
                                "input": ""
                            }

                        # Accumulate arguments
                        if "function" in tool_call_chunk and "arguments" in tool_call_chunk["function"]:
                            current_tool_calls[index]["input"] += tool_call_chunk["function"]["arguments"]

                        # Yield OpenAI-format tool call delta
                        yield {
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "tool_calls": [tool_call_chunk]
                                }
                            }]
                        }

            # Final chunk with finish_reason
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason
                }]
            }

        except requests.exceptions.Timeout:
            logger.error("[MOONSHOT] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MOONSHOT] stream response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- sync --------------------

    def _handle_sync_response(self, request_body: dict):
        """Handle synchronous API response and yield a single result dict."""
        try:
            headers = self._build_headers()

            request_body.pop("stream", None)
            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, timeout=120)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MOONSHOT] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            result = response.json()
            message = result["choices"][0]["message"]
            finish_reason = result["choices"][0]["finish_reason"]

            response_data = {"role": "assistant", "content": []}

            # Add text content
            if message.get("content"):
                response_data["content"].append({
                    "type": "text",
                    "text": message["content"]
                })

            # Add tool calls
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    response_data["content"].append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": json.loads(tool_call["function"]["arguments"])
                    })

            # Map finish_reason
            if finish_reason == "tool_calls":
                response_data["stop_reason"] = "tool_use"
            elif finish_reason == "stop":
                response_data["stop_reason"] = "end_turn"
            else:
                response_data["stop_reason"] = finish_reason

            yield response_data

        except requests.exceptions.Timeout:
            logger.error("[MOONSHOT] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MOONSHOT] sync response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- format conversion --------------------

    def _convert_messages_to_openai_format(self, messages):
        """
        Convert messages from Claude format to OpenAI format.

        Claude format uses content blocks: tool_use / tool_result / text
        OpenAI format uses tool_calls in assistant, role=tool for results
        """
        if not messages:
            return []

        converted = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # Already a simple string – pass through
            if isinstance(content, str):
                converted.append(msg)
                continue

            if not isinstance(content, list):
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
                                "content": result_content
                            })

                    for tr in tool_results:
                        converted.append(tr)

                    if text_parts:
                        converted.append({"role": "user", "content": "\n".join(text_parts)})
                else:
                    # Keep as-is for multimodal content (e.g. image_url blocks)
                    converted.append(msg)

            elif role == "assistant":
                openai_msg = {"role": "assistant"}
                text_parts = []
                tool_calls = []
                reasoning_parts = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
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
                    elif block.get("type") == "thinking":
                        reasoning_parts.append(block.get("thinking", ""))

                if text_parts:
                    openai_msg["content"] = "\n".join(text_parts)
                elif not tool_calls:
                    openai_msg["content"] = ""

                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls
                    if not text_parts:
                        openai_msg["content"] = None

                # Kimi API requires reasoning_content in assistant messages
                # when thinking was active for that turn. The presence of
                # reasoning_parts means thinking was on, so always round-trip it.
                if reasoning_parts:
                    openai_msg["reasoning_content"] = "\n".join(reasoning_parts)

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
            # Already in OpenAI format
            if "type" in tool and tool["type"] == "function":
                converted.append(tool)
            else:
                converted.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })

        return converted
