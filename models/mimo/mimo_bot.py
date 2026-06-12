# encoding:utf-8

"""
小米 MiMo Bot —— OpenAI 兼容协议，使用独立 API key / base 配置。

支持模型：
- mimo-v2.5-pro     (旗舰，长上下文，默认开启思考)
- mimo-v2.5         (多模态：文/图/音/视频，默认开启思考)
- mimo-v2-pro       (V2 Pro，默认开启思考)
- mimo-v2-omni      (V2 多模态，默认开启思考)
- mimo-v2-flash     (V2 极速版，默认关闭思考)

思考模式说明：
- 开关参数：``{"thinking": {"type": "enabled" | "disabled"}}``
- mimo-v2.5-pro / mimo-v2.5 在思考模式下 ``temperature`` 会被强制为 1.0，
  本地直接剥离 ``temperature`` / ``top_p`` 等参数避免歧义。
- 多轮工具调用过程中，若历史包含 tool_calls，所有后续 assistant 消息必须回传
  ``reasoning_content``，否则 API 返回 400 错误。
- 文档：https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/passing-back-reasoning_content
"""

import json
import time
from typing import Optional

import requests

from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf, load_config
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from .mimo_session import MimoSession

DEFAULT_API_BASE = "https://api.xiaomimimo.com/v1"
DEFAULT_MODEL = const.MIMO_V2_5_PRO

# 支持多模态输入（图/音/视频）的模型
MULTIMODAL_MODELS = {const.MIMO_V2_5_PRO, const.MIMO_V2_5, const.MIMO_V2_OMNI}


class MimoBot(Bot, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(
            MimoSession,
            model=conf().get("model") or DEFAULT_MODEL,
        )
        conf_model = conf().get("model") or DEFAULT_MODEL
        self.args = {
            "model": conf_model,
            "temperature": conf().get("temperature", 1.0),
            "top_p": conf().get("top_p", 0.95),
        }

    # ---------- config helpers ----------

    @property
    def api_key(self):
        return conf().get("mimo_api_key")

    @property
    def api_base(self):
        url = conf().get("mimo_api_base") or DEFAULT_API_BASE
        return url.rstrip("/")

    def get_api_config(self):
        """OpenAICompatibleBot 接口 —— 供 call_with_tools() 使用。"""
        return {
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": conf().get("model", DEFAULT_MODEL),
            "default_temperature": conf().get("temperature", 1.0),
            "default_top_p": conf().get("top_p", 0.95),
        }

    @property
    def supports_vision(self) -> bool:
        """主模型为多模态模型时，允许 vision tool 走主 bot 通道。"""
        model_name = (conf().get("model") or "").lower()
        return model_name in MULTIMODAL_MODELS

    @staticmethod
    def _model_supports_thinking(model_name: str) -> bool:
        """全部 mimo 系列模型都支持 thinking 开关。"""
        if not model_name:
            return False
        return model_name.lower().startswith("mimo-")

    @staticmethod
    def _thinking_default_enabled(model_name: str) -> bool:
        """各模型的思考模式默认值。mimo-v2-flash 默认关闭，其他默认开启。"""
        if not model_name:
            return False
        return model_name.lower() != const.MIMO_V2_FLASH

    def _build_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ---------- simple chat (non-agent mode) ----------

    def reply(self, query, context=None):
        if context.type == ContextType.TEXT:
            logger.info("[MIMO] query={}".format(query))

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
            logger.debug("[MIMO] session query={}".format(session.messages))

            new_args = self.args.copy()
            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[MIMO] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[MIMO] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session, args=None, retry_count: int = 0) -> dict:
        try:
            headers = self._build_headers()
            body = dict(args) if args else dict(self.args)
            body["messages"] = session.messages

            model_name = str(body.get("model", ""))
            # 思考模式下 mimo-v2.5-pro / mimo-v2.5 不支持自定义 temperature/top_p,
            # 简单起见，所有支持思考的模型按默认配置走，剥离这些参数。
            if self._model_supports_thinking(model_name) and self._thinking_default_enabled(model_name):
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
                try:
                    response = res.json()
                    error = response.get("error", {})
                except Exception:
                    error = {"message": res.text[:300]}
                logger.error(
                    f"[MIMO] chat failed, status_code={res.status_code}, "
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
        带工具调用支持的 MiMo API 调用 (供 agent 集成使用)。

        处理逻辑：
        - Claude 格式 → OpenAI 格式 转换（含 reasoning_content 全量回传）
        - System prompt 注入
        - SSE 流式响应（包含 tool_calls 与 reasoning_content 增量）
        - 思考模式开关传递
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
                # MiMo 使用 max_completion_tokens 命名（含可见输出 + 推理 token）
                request_body["max_completion_tokens"] = max_tokens

            if converted_tools:
                request_body["tools"] = converted_tools
                request_body["tool_choice"] = kwargs.pop("tool_choice", "auto")

            # 思考模式：默认遵循各模型的官方默认值；caller 可显式覆盖
            thinking_param = kwargs.pop("thinking", None)
            thinking_active = False

            if self._model_supports_thinking(model):
                if thinking_param is None:
                    default_on = self._thinking_default_enabled(model)
                    thinking_param = {"type": "enabled" if default_on else "disabled"}
                request_body["thinking"] = thinking_param
                thinking_active = thinking_param.get("type") == "enabled"

            # 思考模式下 v2.5-pro / v2.5 不支持自定义 temperature；干脆全部剥离避免被静默忽略
            if thinking_active:
                for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                    request_body.pop(k, None)
                    kwargs.pop(k, None)
            else:
                temperature = kwargs.pop("temperature", None)
                if temperature is not None:
                    request_body["temperature"] = temperature
                top_p = kwargs.pop("top_p", None)
                if top_p is not None:
                    request_body["top_p"] = top_p

            logger.debug(
                f"[MIMO] API call: model={model}, "
                f"tools={len(converted_tools) if converted_tools else 0}, "
                f"stream={stream}, thinking={thinking_active}"
            )

            if stream:
                return self._handle_stream_response(request_body)
            else:
                return self._handle_sync_response(request_body)

        except Exception as e:
            logger.error(f"[MIMO] call_with_tools error: {e}")
            import traceback
            logger.error(traceback.format_exc())

            def error_generator():
                yield {"error": True, "message": str(e), "status_code": 500}
            return error_generator()

    # -------------------- streaming --------------------

    def _handle_stream_response(self, request_body: dict):
        """SSE 流式 chunk 转为 OpenAI 标准 delta 输出（含 reasoning_content）。"""
        try:
            headers = self._build_headers()
            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, stream=True, timeout=180)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MIMO] API error: status={response.status_code}, msg={error_msg}")
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
                    logger.warning(f"[MIMO] JSON decode error: {e}, data: {data_str[:200]}")
                    continue

                if chunk.get("error"):
                    error_data = chunk["error"]
                    error_msg = error_data.get("message", "Unknown error") if isinstance(error_data, dict) else str(error_data)
                    logger.error(f"[MIMO] stream error: {error_msg}")
                    yield {"error": True, "message": error_msg, "status_code": 500}
                    return

                if not chunk.get("choices"):
                    continue
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                # 推理内容（思考模式）：单独 delta 透传给 agent_stream
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
            logger.error("[MIMO] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MIMO] stream response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- sync --------------------

    def _handle_sync_response(self, request_body: dict):
        """非流式响应；统一 yield 一份 Claude 格式 dict 与流式路径对齐。"""
        try:
            headers = self._build_headers()
            request_body.pop("stream", None)
            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, timeout=180)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MIMO] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            result = response.json()
            message = result["choices"][0]["message"]
            finish_reason = result["choices"][0]["finish_reason"]

            response_data = {"role": "assistant", "content": []}

            # 推理内容包装成 thinking block，便于 agent 层持久化并在工具调用时回传
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
            logger.error("[MIMO] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MIMO] sync response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    # -------------------- format conversion --------------------

    def _convert_messages_to_openai_format(self, messages):
        """
        将 Claude 格式（content blocks）转为 OpenAI 格式。

        关键约束：MiMo 思考模式下，一旦历史包含 tool_calls 的 assistant 轮次，
        所有后续 assistant 消息（含工具调用轮）必须回传 reasoning_content，
        否则 API 返回 400。本地无 trace 时用空字符串回填，MiMo 接受字段存在
        即可。
        """
        if not messages:
            return []

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
                    # 多模态原样保留（image_url / input_audio / video_url 等 block）
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

                if reasoning_parts:
                    openai_msg["reasoning_content"] = "\n".join(reasoning_parts)
                elif has_tool_call_history:
                    openai_msg["reasoning_content"] = ""

                converted.append(openai_msg)
            else:
                converted.append(msg)

        return converted

    def _convert_tools_to_openai_format(self, tools):
        """工具定义 Claude 格式 → OpenAI 格式。"""
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
        """通过 MiMo OpenAI 兼容的 /chat/completions 端点进行图像理解。"""
        try:
            # 主模型若不支持视觉（如 mimo-v2-flash），自动切到 mimo-v2.5-pro
            vision_model = model
            if not vision_model:
                cur = self.args.get("model") or DEFAULT_MODEL
                vision_model = cur if cur in MULTIMODAL_MODELS else const.MIMO_V2_5_PRO

            payload = {
                "model": vision_model,
                "max_completion_tokens": max_tokens,
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
                headers=headers, json=payload, timeout=180,
            )
            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            if "error" in data:
                return {"error": True, "message": data["error"].get("message", str(data["error"]))}
            choice = data.get("choices", [{}])[0].get("message", {})
            # 部分模型在多模态下会把答案塞在 reasoning_content 而非 content
            content = choice.get("content") or choice.get("reasoning_content") or ""
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
            logger.error(f"[MIMO] call_vision error: {e}")
            return {"error": True, "message": str(e)}
