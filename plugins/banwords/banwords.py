# encoding:utf-8

import json
import os

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *

from .lib.WordsSearch import WordsSearch


@plugins.register(
    name="Banwords",
    desire_priority=100,
    hidden=True,
    desc="判断消息中是否有敏感词、决定是否回复。",
    version="1.0",
    author="lanvent",
)
class Banwords(Plugin):
    def __init__(self):
        super().__init__()
        try:
            # load config
            conf = super().load_config()
            curdir = os.path.dirname(__file__)
            if not conf:
                # 配置不存在则写入默认配置
                config_path = os.path.join(curdir, "config.json")
                if not os.path.exists(config_path):
                    conf = {"action": "ignore"}
                    with open(config_path, "w") as f:
                        json.dump(conf, f, indent=4)

            self.searchr = WordsSearch()
            self.action = conf["action"]
            banwords_path = os.path.join(curdir, "banwords.txt")
            with open(banwords_path, "r", encoding="utf-8") as f:
                words = []
                for line in f:
                    word = line.strip()
                    if word:
                        words.append(word)
            self.searchr.SetKeywords(words)
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            if conf.get("reply_filter", True):
                self.handlers[Event.ON_DECORATE_REPLY] = self.on_decorate_reply
                self.reply_action = conf.get("reply_action", "ignore")
            logger.debug("[Banwords] inited")
        except Exception as e:
            logger.debug("[Banwords] init failed, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/banwords .")
            raise e

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type not in [
            ContextType.TEXT,
            ContextType.IMAGE_CREATE,
        ]:
            return

        content = e_context["context"].content
        logger.debug("[Banwords] on_handle_context. content: %s" % content)
        if self.action == "ignore":
            f = self.searchr.FindFirst(content)
            if f:
                logger.info("[Banwords] %s in message" % f["Keyword"])
                e_context.action = EventAction.BREAK_PASS
                return
        elif self.action == "replace":
            if self.searchr.ContainsAny(content):
                reply = Reply(ReplyType.INFO, "发言中包含敏感词，请重试: \n" + self.searchr.Replace(content))
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

    def on_decorate_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT]:
            return

        reply = e_context["reply"]
        content = reply.content
        if self.reply_action == "ignore":
            f = self.searchr.FindFirst(content)
            if f:
                logger.info("[Banwords] %s in reply" % f["Keyword"])
                e_context["reply"] = None
                e_context.action = EventAction.BREAK_PASS
                return
        elif self.reply_action == "replace":
            if self.searchr.ContainsAny(content):
                reply = Reply(ReplyType.INFO, "已替换回复中的敏感词: \n" + self.searchr.Replace(content))
                e_context["reply"] = reply
                e_context.action = EventAction.CONTINUE
                return

    def get_help_text(self, **kwargs):
        return "过滤消息中的敏感词。"
