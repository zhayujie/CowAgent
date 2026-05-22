# encoding:utf-8

import json
import os
import requests
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *


@plugins.register(
    name="Keyword",
    desire_priority=900,
    hidden=True,
    desc="关键词匹配过滤",
    version="0.1",
    author="fengyege.top",
)
class Keyword(Plugin):
    def __init__(self):
        super().__init__()
        try:
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            conf = None
            if not os.path.exists(config_path):
                logger.debug(f"[keyword]不存在配置文件{config_path}")
                conf = {"keyword": {}}
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(conf, f, indent=4)
            else:
                logger.debug(f"[keyword]加载配置文件{config_path}")
                with open(config_path, "r", encoding="utf-8") as f:
                    conf = json.load(f)
            # 加载关键词
            self.keyword = conf["keyword"]

            logger.debug("[keyword] {}".format(self.keyword))
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            logger.debug("[keyword] inited.")
        except Exception as e:
            logger.warn("[keyword] init failed, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/keyword .")
            raise e

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content.strip()
        logger.debug("[keyword] on_handle_context. content: %s" % content)
        if content in self.keyword:
            logger.info(f"[keyword] 匹配到关键字【{content}】")
            reply_text = self.keyword[content]

            # 判断匹配内容的类型
            if (reply_text.startswith("http://") or reply_text.startswith("https://")) and any(reply_text.endswith(ext) for ext in [".jpg", ".webp", ".jpeg", ".png", ".gif", ".img"]):
            # 如果是以 http:// 或 https:// 开头，且".jpg", ".jpeg", ".png", ".gif", ".img"结尾，则认为是图片 URL。
                reply = Reply()
                reply.type = ReplyType.IMAGE_URL
                reply.content = reply_text
                
            elif (reply_text.startswith("http://") or reply_text.startswith("https://")) and any(reply_text.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", "xlsx",".zip", ".rar"]):
            # 如果是以 http:// 或 https:// 开头，且".pdf", ".doc", ".docx", ".xls", "xlsx",".zip", ".rar"结尾，则下载文件到tmp目录并发送给用户
                file_path = "tmp"
                if not os.path.exists(file_path):
                    os.makedirs(file_path)
                file_name = reply_text.split("/")[-1]  # 获取文件名
                file_path = os.path.join(file_path, file_name)
                response = requests.get(reply_text)
                with open(file_path, "wb") as f:
                    f.write(response.content)
                reply = Reply()
                reply.type = ReplyType.FILE
                reply.content = file_path
            
            elif (reply_text.startswith("http://") or reply_text.startswith("https://")) and any(reply_text.endswith(ext) for ext in [".mp4"]):
            # 如果是以 http:// 或 https:// 开头，且".mp4"结尾，则下载视频到tmp目录并发送给用户
                reply = Reply()
                reply.type = ReplyType.VIDEO_URL
                reply.content = reply_text
                
            else:
            # 否则认为是普通文本
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = reply_text
            
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            
    def get_help_text(self, **kwargs):
        help_text = "关键词过滤"
        return help_text
