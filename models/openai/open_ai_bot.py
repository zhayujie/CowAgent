# encoding:utf-8

import time

from models.openai.openai_compat import (
    RateLimitError,
    Timeout,
    APIConnectionError,
    APIError,
    wrap_http_error,
)
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError

from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.openai.open_ai_image import OpenAIImage
from models.openai.open_ai_session import OpenAISession
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf

user_session = dict()


# OpenAI对话模型API (可用)
class OpenAIBot(Bot, OpenAIImage, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        self._api_key = conf().get("open_ai_api_key")
        self._api_base = conf().get("open_ai_api_base") or None
        self._proxy = conf().get("proxy") or None
        self._http_client = OpenAIHTTPClient(
            api_key=self._api_key,
            api_base=self._api_base,
            proxy=self._proxy,
        )

        self.sessions = SessionManager(OpenAISession, model=conf().get("model") or "text-davinci-003")
        self.args = {
            "model": conf().get("model") or "text-davinci-003",  # 对话模型的名称
            "temperature": conf().get("temperature", 0.9),  # 值在[0,1]之间，越大表示回复越具有不确定性
            "max_tokens": 1200,  # 回复最大的字符数
            "top_p": 1,
            "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "request_timeout": conf().get("request_timeout", None),  # 请求超时时间，openai接口默认设置为600，对于难问题一般需要较长时间
            "timeout": conf().get("request_timeout", None),  # 重试超时时间，在这个时间内，将会自动重试
            "stop": ["\n\n\n"],
        }
    
    def get_api_config(self):
        """Get API configuration for OpenAI-compatible base class"""
        return {
            'api_key': conf().get("open_ai_api_key"),
            'api_base': conf().get("open_ai_api_base"),
            'model': conf().get("model", "text-davinci-003"),
            'default_temperature': conf().get("temperature", 0.9),
            'default_top_p': conf().get("top_p", 1.0),
            'default_frequency_penalty': conf().get("frequency_penalty", 0.0),
            'default_presence_penalty': conf().get("presence_penalty", 0.0),
        }

    def _get_http_client(self) -> OpenAIHTTPClient:
        """Reuse the per-instance HTTP client for the streaming/tool path."""
        return self._http_client

    def reply(self, query, context=None):
        # acquire reply content
        if context and context.type:
            if context.type == ContextType.TEXT:
                logger.info("[OPEN_AI] query={}".format(query))
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
                    total_tokens, completion_tokens, reply_content = (
                        result["total_tokens"],
                        result["completion_tokens"],
                        result["content"],
                    )
                    logger.debug(
                        "[OPEN_AI] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(str(session), session_id, reply_content, completion_tokens)
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

    def reply_text(self, session: OpenAISession, retry_count=0):
        try:
            call_args = dict(self.args)
            timeout = call_args.pop("request_timeout", None) or call_args.pop("timeout", None)
            response = self._http_client.completions(
                timeout=timeout,
                prompt=str(session),
                **call_args,
            )
            res_content = response["choices"][0]["text"].strip().replace("<|endoftext|>", "")
            total_tokens = response["usage"]["total_tokens"]
            completion_tokens = response["usage"]["completion_tokens"]
            logger.info("[OPEN_AI] reply={}".format(res_content))
            return {
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "content": res_content,
            }
        except OpenAIHTTPError as http_err:
            return self._handle_legacy_error(wrap_http_error(http_err), session, retry_count)
        except Exception as e:
            return self._handle_legacy_error(e, session, retry_count)

    def _handle_legacy_error(self, e, session, retry_count):
        """Map exception -> reply for the legacy /completions endpoint."""
        need_retry = retry_count < 2
        result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
        if isinstance(e, RateLimitError):
            logger.warn("[OPEN_AI] RateLimitError: {}".format(e))
            result["content"] = "提问太快啦，请休息一下再问我吧"
            if need_retry:
                time.sleep(20)
        elif isinstance(e, Timeout):
            logger.warn("[OPEN_AI] Timeout: {}".format(e))
            result["content"] = "我没有收到你的消息"
            if need_retry:
                time.sleep(5)
        elif isinstance(e, APIConnectionError):
            logger.warn("[OPEN_AI] APIConnectionError: {}".format(e))
            need_retry = False
            result["content"] = "我连接不到你的网络"
        else:
            logger.warn("[OPEN_AI] Exception: {}".format(e))
            need_retry = False
            self.sessions.clear_session(session.session_id)

        if need_retry:
            logger.warn("[OPEN_AI] 第{}次重试".format(retry_count + 1))
            return self.reply_text(session, retry_count + 1)
        return result

    # NOTE: Tool-call routing is delegated to OpenAICompatibleBot.call_with_tools,
    # which calls /chat/completions via our shared HTTP client. The previous
    # bespoke implementation here bypassed Claude->OpenAI message/tool conversion
    # and was effectively broken for agent flows; we now inherit the correct
    # implementation from the base class.
