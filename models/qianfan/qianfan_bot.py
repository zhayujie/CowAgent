# encoding:utf-8

import time

import requests
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf, load_config
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from .qianfan_session import QianfanSession

DEFAULT_API_BASE = "https://qianfan.baidubce.com/v2"
DEFAULT_MODEL = const.ERNIE_5_1
DEFAULT_VISION_MODEL = const.ERNIE_45_TURBO_VL

# Qianfan models that natively understand images. Other ERNIE variants
# are text-only and must not receive image payloads.
_VISION_CAPABLE_MODELS = {
    const.ERNIE_5_1,
    const.ERNIE_5,
    const.ERNIE_X1_1,
    const.ERNIE_45_TURBO_VL,
    const.ERNIE_45_TURBO_VL_32K,
}


class QianfanBot(Bot, OpenAICompatibleBot):
    @property
    def supports_vision(self) -> bool:
        """Whether the configured main model is multimodal."""
        return (conf().get("model") or "").lower() in _VISION_CAPABLE_MODELS

    def __init__(self):
        super().__init__()
        model = self._resolve_model()
        self.sessions = SessionManager(QianfanSession, model=model)
        self.args = {
            "model": model,
            "temperature": conf().get("temperature", 0.7),
            "top_p": conf().get("top_p", 1.0),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),
            "presence_penalty": conf().get("presence_penalty", 0.0),
        }

    def _resolve_model(self):
        model = conf().get("model") or DEFAULT_MODEL
        if model == const.QIANFAN:
            return DEFAULT_MODEL
        return model

    @property
    def api_key(self):
        return conf().get("qianfan_api_key")

    @property
    def api_base(self):
        url = conf().get("qianfan_api_base") or DEFAULT_API_BASE
        url = url.rstrip("/")
        suffix = "/chat/completions"
        if url.endswith(suffix):
            url = url[:-len(suffix)]
        return url.rstrip("/")

    def get_api_config(self):
        return {
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": self._resolve_model(),
            "default_temperature": conf().get("temperature", 0.7),
            "default_top_p": conf().get("top_p", 1.0),
            "default_frequency_penalty": conf().get("frequency_penalty", 0.0),
            "default_presence_penalty": conf().get("presence_penalty", 0.0),
        }

    def _build_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.api_key),
        }

    def reply(self, query, context=None):
        if context.type == ContextType.TEXT:
            logger.info("[QIANFAN] query={}".format(query))

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
            logger.debug("[QIANFAN] session query={}".format(session.messages))

            reply_content = self.reply_text(session, args=self.args.copy())
            logger.debug(
                "[QIANFAN] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages,
                    session_id,
                    reply_content["content"],
                    reply_content["completion_tokens"],
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
                logger.debug("[QIANFAN] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session, args=None, retry_count=0):
        try:
            body = dict(args) if args else dict(self.args)
            body["messages"] = session.messages
            response = requests.post(
                "{}/chat/completions".format(self.api_base),
                headers=self._build_headers(),
                json=body,
                timeout=conf().get("request_timeout", 180),
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "total_tokens": data["usage"]["total_tokens"],
                    "completion_tokens": data["usage"]["completion_tokens"],
                    "content": data["choices"][0]["message"]["content"],
                }
            return self._error_result(response, session, args, retry_count)
        except Exception as e:
            logger.exception(e)
            if retry_count < 2:
                return self.reply_text(session, args, retry_count + 1)
            return {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

    def call_vision(self, image_url: str, question: str,
                    model: str = None, max_tokens: int = 1000) -> dict:
        vision_model = model or DEFAULT_VISION_MODEL
        payload = {
            "model": vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }

        try:
            response = requests.post(
                "{}/chat/completions".format(self.api_base),
                headers=self._build_headers(),
                json=payload,
                timeout=conf().get("request_timeout", 180),
            )
            if response.status_code != 200:
                err = self._error_result(response, None)
                return {
                    "error": True,
                    "message": err.get("content", "Qianfan vision request failed"),
                }

            data = response.json()
            choices = data.get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            usage = data.get("usage", {}) or {}
            return {
                "content": content,
                "model": data.get("model", vision_model),
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.exception(e)
            return {"error": True, "message": str(e)}

    def _error_result(self, response, session, args=None, retry_count=0):
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}

        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = error.get("message") or str(error)
        elif error:
            message = str(error)
        elif isinstance(body, dict) and body.get("raw") is not None:
            message = str(body.get("raw"))
        else:
            message = str(body)

        logger.error(
            "[QIANFAN] chat failed, status_code={}, msg={}".format(
                response.status_code, message
            )
        )

        if response.status_code >= 500 and retry_count < 2:
            time.sleep(3)
            return self.reply_text(session, args, retry_count + 1)

        if response.status_code == 401:
            content = "授权失败，请检查 Qianfan API Key 是否正确"
        elif response.status_code == 429:
            if retry_count < 2:
                time.sleep(3)
                return self.reply_text(session, args, retry_count + 1)
            content = "请求过于频繁，请稍后再试"
        else:
            content = "请求失败：{}".format(message)

        return {"completion_tokens": 0, "content": content}
