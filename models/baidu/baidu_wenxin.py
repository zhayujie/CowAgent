# encoding:utf-8

import requests
import json
from common import const
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from models.baidu.baidu_wenxin_session import BaiduWenxinSession

BAIDU_API_KEY = conf().get("baidu_wenxin_api_key")
BAIDU_SECRET_KEY = conf().get("baidu_wenxin_secret_key")

class BaiduWenxinBot(Bot):

    def __init__(self):
        super().__init__()
        wenxin_model = conf().get("baidu_wenxin_model")
        self.prompt_enabled = conf().get("baidu_wenxin_prompt_enabled")
        if self.prompt_enabled:
            self.prompt = conf().get("character_desc", "")
            if self.prompt == "":
                logger.warn("[BAIDU] Although you enabled model prompt, character_desc is not specified.")
        if wenxin_model is not None:
            wenxin_model = conf().get("baidu_wenxin_model") or "eb-instant"
        else:
            if conf().get("model") and conf().get("model") == const.WEN_XIN:
                wenxin_model = "completions"
            elif conf().get("model") and conf().get("model") == const.WEN_XIN_4:
                wenxin_model = "completions_pro"

        self.sessions = SessionManager(BaiduWenxinSession, model=wenxin_model)

    def reply(self, query, context=None):
        # acquire reply content
        if context and context.type:
            if context.type == ContextType.TEXT:
                logger.info("[BAIDU] query={}".format(query))
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
                        "[BAIDU] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(session.messages, session_id, reply_content, completion_tokens)
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

    def reply_text(self, session: BaiduWenxinSession, retry_count=0):
        try:
            logger.info("[BAIDU] model={}".format(session.model))
            access_token = self.get_access_token()
            if access_token == 'None':
                logger.warn("[BAIDU] access token 获取失败")
                return {
                    "total_tokens": 0,
                    "completion_tokens": 0,
                    "content": 0,
                    }
            url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/" + session.model + "?access_token=" + access_token
            headers = {
                'Content-Type': 'application/json'
            }
            payload = {'messages': session.messages, 'system': self.prompt} if self.prompt_enabled else {'messages': session.messages}
            response = requests.request("POST", url, headers=headers, data=json.dumps(payload))
            response_text = json.loads(response.text)
            logger.info(f"[BAIDU] response text={response_text}")
            res_content = response_text["result"]
            total_tokens = response_text["usage"]["total_tokens"]
            completion_tokens = response_text["usage"]["completion_tokens"]
            logger.info("[BAIDU] reply={}".format(res_content))
            return {
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "content": res_content,
            }
        except Exception as e:
            need_retry = retry_count < 2
            logger.warn("[BAIDU] Exception: {}".format(e))
            need_retry = False
            self.sessions.clear_session(session.session_id)
            result = {"total_tokens": 0, "completion_tokens": 0, "content": "出错了: {}".format(e)}
            return result

    def get_access_token(self):
        """
        使用 AK，SK 生成鉴权签名（Access Token）
        :return: access_token，或是None(如果错误)
        """
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {"grant_type": "client_credentials", "client_id": BAIDU_API_KEY, "client_secret": BAIDU_SECRET_KEY}
        return str(requests.post(url, params=params).json().get("access_token"))
