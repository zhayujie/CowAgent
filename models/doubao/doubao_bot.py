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
from .doubao_session import DoubaoSession


# Doubao (火山方舟 / Volcengine Ark) API Bot
class DoubaoBot(Bot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(DoubaoSession, model=conf().get("model") or "doubao-seed-2-0-pro-260215")
        model = conf().get("model") or "doubao-seed-2-0-pro-260215"
        self.args = {
            "model": model,
            "temperature": conf().get("temperature", 0.8),
            "top_p": conf().get("top_p", 1.0),
        }

    @property
    def api_key(self):
        return conf().get("ark_api_key")

    @property
    def base_url(self):
        url = conf().get("ark_base_url", "https://ark.cn-beijing.volces.com/api/v3")
        if url.endswith("/chat/completions"):
            url = url.rsplit("/chat/completions", 1)[0]
        return url.rstrip("/")

    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[DOUBAO] query={}".format(query))

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
            logger.debug("[DOUBAO] session query={}".format(session.messages))

            model = context.get("doubao_model")
            new_args = self.args.copy()
            if model:
                new_args["model"] = model

            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[DOUBAO] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[DOUBAO] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: DoubaoSession, args=None, retry_count: int = 0) -> dict:
        """
        Call Doubao chat completion API to get the answer
        :param session: a conversation session
        :param args: model args
        :param retry_count: retry count
        :return: {}
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key
            }
            body = args.copy()
            body["messages"] = session.messages
            # Disable thinking by default for better efficiency
            body["thinking"] = {"type": "disabled"}
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
                error = response.get("error", {})
                logger.error(f"[DOUBAO] chat failed, status_code={res.status_code}, "
                             f"msg={error.get('message')}, type={error.get('type')}")

                result = {"completion_tokens": 0, "content": "提问太快啦，请休息一下再问我吧"}
                need_retry = False
                if res.status_code >= 500:
                    logger.warn(f"[DOUBAO] do retry, times={retry_count}")
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
        """Analyze an image using Doubao (Volcengine Ark) OpenAI-compatible API."""
        try:
            vision_model = model or self.args.get("model", "doubao-seed-2-0-pro-260215")
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
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
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
            logger.error(f"[DOUBAO] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    # ==================== Agent mode support ====================

    def call_with_tools(self, messages, tools=None, stream: bool = False, **kwargs):
        """
        Call Doubao API with tool support for agent integration.

        This method handles:
        1. Format conversion (Claude format -> OpenAI format)
        2. System prompt injection
        3. Streaming SSE response with tool_calls
        4. Thinking (reasoning) is disabled by default for efficiency

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
            # Don't pop temperature, just ignore it - let API use default
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

            request_body["thinking"] = kwargs.get("thinking", {"type": "enabled"})

            logger.debug(f"[DOUBAO] API call: model={model}, "
                         f"tools={len(converted_tools) if converted_tools else 0}, stream={stream}")

            if stream:
                return self._handle_stream_response(request_body)
            else:
                return self._handle_sync_response(request_body)

        except Exception as e:
            logger.error(f"[DOUBAO] call_with_tools error: {e}")
            import traceback
            logger.error(traceback.format_exc())

            def error_generator():
                yield {"error": True, "message": str(e), "status_code": 500}
            return error_generator()

    # -------------------- streaming --------------------

    def _handle_stream_response(self, request_body: dict):
        """Handle streaming SSE response from Doubao API and yield OpenAI-format chunks."""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, stream=True, timeout=120)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[DOUBAO] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            current_tool_calls = {}
            finish_reason = None

            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Remove "data: " prefix
                if data_str.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"[DOUBAO] JSON decode error: {e}, data: {data_str[:200]}")
                    continue

                # Check for error in chunk
                if chunk.get("error"):
                    error_data = chunk["error"]
                    error_msg = error_data.get("message", "Unknown error") if isinstance(error_data, dict) else str(error_data)
                    logger.error(f"[DOUBAO] stream error: {error_msg}")
                    yield {"error": True, "message": error_msg, "status_code": 500}
                    return

                if not chunk.get("choices"):
                    continue

                choice = chunk["choices"][0]
                delta = choice.get("delta", {})

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

                # Capture finish_reason
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

            # Final chunk with finish_reason
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason
                }]
            }

        except requests.exceptions.Timeout:
            logger.error("[DOUBAO] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[DOUBAO] stream response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- sync --------------------

    def _handle_sync_response(self, request_body: dict):
        """Handle synchronous API response and yield a single result dict."""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            request_body.pop("stream", None)
            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, timeout=120)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[DOUBAO] API error: status={response.status_code}, msg={error_msg}")
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
            logger.error("[DOUBAO] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[DOUBAO] sync response error: {e}")
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

            # Already a simple string - pass through
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

                if text_parts:
                    openai_msg["content"] = "\n".join(text_parts)
                elif not tool_calls:
                    openai_msg["content"] = ""

                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls
                    if not text_parts:
                        openai_msg["content"] = None

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
