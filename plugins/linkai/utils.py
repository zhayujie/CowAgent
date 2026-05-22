import requests
from common.log import logger
from config import global_config
from bridge.reply import Reply, ReplyType
from plugins.event import EventContext, EventAction
from config import conf

class Util:
    @staticmethod
    def is_admin(e_context: EventContext) -> bool:
        """
        判断消息是否由管理员用户发送
        :param e_context: 消息上下文
        :return: True: 是, False: 否
        """
        context = e_context["context"]
        if context["isgroup"]:
            actual_user_id = context.kwargs.get("msg").actual_user_id
            for admin_user in global_config["admin_users"]:
                if actual_user_id and actual_user_id in admin_user:
                    return True
            return False
        else:
            return context["receiver"] in global_config["admin_users"]

    @staticmethod
    def set_reply_text(content: str, e_context: EventContext, level: ReplyType = ReplyType.ERROR):
        reply = Reply(level, content)
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    @staticmethod
    def fetch_app_plugin(app_code: str, plugin_name: str) -> bool:
        try:
            headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}
            # do http request
            base_url = conf().get("linkai_api_base", "https://api.link-ai.tech")
            params = {"app_code": app_code}
            res = requests.get(url=base_url + "/v1/app/info", params=params, headers=headers, timeout=(5, 10))
            if res.status_code == 200:
                plugins = res.json().get("data").get("plugins")
                for plugin in plugins:
                    if plugin.get("name") and plugin.get("name") == plugin_name:
                        return True
                return False
            else:
                logger.warning(f"[LinkAI] find app info exception, res={res}")
                return False
        except Exception as e:
            return False
