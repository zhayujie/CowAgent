# encoding:utf-8

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from plugins import *


@plugins.register(
    name="Finish",
    desire_priority=-999,
    hidden=True,
    desc="A plugin that check unknown command",
    version="1.0",
    author="js00000",
)
class Finish(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.debug("[Finish] inited")

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content
        logger.debug("[Finish] on_handle_context. content: %s" % content)
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        if content.startswith(trigger_prefix):
            reply = Reply()
            reply.type = ReplyType.ERROR
            reply.content = "未知插件命令\n查看插件命令列表请输入#help 插件名\n"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑

    def get_help_text(self, **kwargs):
        return ""
