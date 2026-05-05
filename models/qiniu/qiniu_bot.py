# encoding:utf-8

"""
Qiniu Bot — OpenAI-compatible chat at api.qnaigc.com; uses dedicated API key / base config.
"""

import time

import requests
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf, load_config
from .qiniu_session import QiniuSession

DEFAULT_API_BASE = "https://api.qnaigc.com/v1"


class QiniuBot(Bot, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        _m = conf().get("model") or const.QINIU_DEFAULT_MODEL
        self.sessions = SessionManager(
            QiniuSession,
            model=_m,
        )
        conf_model = conf().get("model") or const.QINIU_DEFAULT_MODEL
        self.args = {
            "model": conf_model,
            "temperature": conf().get("temperature", 0.7),
            "top_p": conf().get("top_p", 1.0),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),
            "presence_penalty": conf().get("presence_penalty", 0.0),
        }

    @property
    def api_key(self):
        return conf().get("qiniu_api_key") or conf().get("open_ai_api_key")

    @property
    def api_base(self):
        url = (
            conf().get("qiniu_api_base")
            or conf().get("open_ai_api_base")
            or DEFAULT_API_BASE
        )
        return url.rstrip("/")

    def get_api_config(self):
        """OpenAICompatibleBot interface — used by call_with_tools()."""
        return {
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": conf().get("model", const.QINIU_DEFAULT_MODEL),
            "default_temperature": conf().get("temperature", 0.7),
            "default_top_p": conf().get("top_p", 1.0),
            "default_frequency_penalty": conf().get("frequency_penalty", 0.0),
            "default_presence_penalty": conf().get("presence_penalty", 0.0),
        }

    def reply(self, query, context=None):
        if context.type == ContextType.TEXT:
            logger.info("[QINIU] query={}".format(query))

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
            logger.debug("[QINIU] session query={}".format(session.messages))

            new_args = self.args.copy()
            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[QINIU] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[QINIU] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session, args=None, retry_count: int = 0) -> dict:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            }
            body = args.copy()
            body["messages"] = session.messages

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
                except Exception:
                    response = {}
                error = response.get("error", {})
                logger.error(
                    f"[QINIU] chat failed, status_code={res.status_code}, "
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
