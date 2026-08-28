# encoding:utf-8

"""
AI/ML API Bot — fully OpenAI-compatible, unified access to 1,000+ models
from every major provider (OpenAI, Anthropic, Google, DeepSeek, and more)
behind a single API key. Model ids are namespaced "<vendor>/<model>", e.g.
"openai/gpt-5-5" or "anthropic/claude-opus-5".

Agent-mode tool calling is handled entirely by the OpenAICompatibleBot base
class (get_api_config() is all it needs); this module only adds classic
(non-agent) chat replies.
"""

from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf, load_config
from .aimlapi_session import AimlapiSession

DEFAULT_API_BASE = "https://api.aimlapi.com/v1"


class AimlapiBot(Bot, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(
            AimlapiSession,
            model=conf().get("model") or const.AIMLAPI_GPT_5_5,
        )
        self.args = {
            "model": conf().get("model") or const.AIMLAPI_GPT_5_5,
            "temperature": conf().get("temperature", 0.7),
            "top_p": conf().get("top_p", 1.0),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),
            "presence_penalty": conf().get("presence_penalty", 0.0),
        }

    @property
    def api_key(self):
        return conf().get("aimlapi_api_key")

    @property
    def api_base(self):
        url = conf().get("aimlapi_api_base") or DEFAULT_API_BASE
        return url.rstrip("/")

    def get_api_config(self):
        """OpenAICompatibleBot interface — used by call_with_tools()."""
        return {
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": conf().get("model", const.AIMLAPI_GPT_5_5),
            "default_temperature": conf().get("temperature", 0.7),
            "default_top_p": conf().get("top_p", 1.0),
            "default_frequency_penalty": conf().get("frequency_penalty", 0.0),
            "default_presence_penalty": conf().get("presence_penalty", 0.0),
        }

    def reply(self, query, context=None):
        if context.type != ContextType.TEXT:
            return Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))

        logger.info("[AIMLAPI] query={}".format(query))
        session_id = context["session_id"]
        clear_memory_commands = conf().get("clear_memory_commands", ["#清除记忆"])
        if query in clear_memory_commands:
            self.sessions.clear_session(session_id)
            return Reply(ReplyType.INFO, "记忆已清除")
        if query == "#清除所有":
            self.sessions.clear_all_session()
            return Reply(ReplyType.INFO, "所有人记忆已清除")
        if query == "#更新配置":
            load_config()
            return Reply(ReplyType.INFO, "配置已更新")

        session = self.sessions.session_query(query, session_id)
        reply_content = self._reply_text(session)
        if reply_content["completion_tokens"] > 0:
            self.sessions.session_reply(reply_content["content"], session_id, reply_content["total_tokens"])
            return Reply(ReplyType.TEXT, reply_content["content"])
        return Reply(ReplyType.ERROR, reply_content["content"])

    def _reply_text(self, session, retry_count: int = 0) -> dict:
        try:
            body = dict(self.args)
            body["messages"] = session.messages
            client = self._get_http_client()
            response = client.chat_completions(
                api_key=self.api_key,
                api_base=self.api_base,
                timeout=conf().get("request_timeout", 180),
                **body,
            )
            return {
                "total_tokens": response["usage"]["total_tokens"],
                "completion_tokens": response["usage"]["completion_tokens"],
                "content": response["choices"][0]["message"]["content"],
            }
        except Exception as e:
            from models.openai.openai_http_client import OpenAIHTTPError
            if isinstance(e, OpenAIHTTPError):
                logger.error(
                    f"[AIMLAPI] chat failed, status_code={e.status_code}, msg={e.message}"
                )
                result = {"completion_tokens": 0, "content": "提问太快啦，请休息一下再问我吧"}
                need_retry = False
                if e.status_code and e.status_code >= 500:
                    need_retry = retry_count < 2
                elif e.status_code == 401:
                    result["content"] = "授权失败，请检查API Key是否正确"
                elif e.status_code == 429:
                    result["content"] = "请求过于频繁，请稍后再试"
                    need_retry = retry_count < 2
                if need_retry:
                    return self._reply_text(session, retry_count + 1)
                return result
            logger.exception(e)
            if retry_count < 2:
                return self._reply_text(session, retry_count + 1)
            return {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
