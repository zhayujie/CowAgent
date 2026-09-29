# encoding:utf-8

import json
import os
import requests
from urllib.parse import urlparse
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import state_dir
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
                logger.debug(f"[keyword] config file not found: {config_path}")
                conf = {"keyword": {}}
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(conf, f, indent=4)
            else:
                logger.debug(f"[keyword] loading config file: {config_path}")
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
            parsed_url = urlparse(reply_text)
            is_http_url = parsed_url.scheme in ("http", "https") and bool(parsed_url.netloc)
            url_path = parsed_url.path.lower()

            # 判断匹配内容的类型
            if is_http_url and url_path.endswith((".jpg", ".webp", ".jpeg", ".png", ".gif", ".img")):
            # 如果是以 http:// 或 https:// 开头，且".jpg", ".jpeg", ".png", ".gif", ".img"结尾，则认为是图片 URL。
                reply = Reply()
                reply.type = ReplyType.IMAGE_URL
                reply.content = reply_text
                
            elif is_http_url and url_path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")):
            # 如果是以 http:// 或 https:// 开头，且".pdf", ".doc", ".docx", ".xls", "xlsx",".zip", ".rar"结尾，则下载文件到tmp目录并发送给用户
                file_name = os.path.basename(parsed_url.path)
                # 下载到 Agent 受管的 tmp 目录。不要自己拼 "tmp"：那是相对进程 CWD
                # 解析的，打包后的桌面端控制不了 CWD，甚至可能没有写权限——
                # 原来那句 makedirs 会直接抛错，被外层 except 吞掉后关键词静默不回复。
                file_path = state_dir.tmp_dir() / file_name
                # Bound the request. The reply is built on the thread handling
                # this message, and requests with no timeout waits forever, so a
                # file host that accepts the connection and then stalls would
                # hold the turn open with nothing raised and nothing logged.
                #
                # Both failure modes are reported to the user rather than left to
                # the worker: an exception here reaches only
                # chat_channel._fail_callback, which logs it, so the keyword would
                # go quiet instead of answering.
                failure = None
                try:
                    response = requests.get(reply_text, timeout=(5, 60))
                    if response.status_code != 200:
                        # A gateway's error page is not the document the keyword
                        # points at. Saving it under `report.pdf` and handing it
                        # to the user as their file is worse than saying so.
                        failure = f"HTTP {response.status_code}"
                except requests.RequestException as e:
                    # requests puts the whole URL in its error text and a keyword
                    # URL may carry a token in its query string, so report the
                    # kind of failure instead of echoing the exception.
                    failure = e.__class__.__name__

                if failure:
                    logger.info(f"[keyword] Failed to download {reply_text}: {failure}")
                    reply = Reply()
                    reply.type = ReplyType.ERROR
                    reply.content = f"下载失败：{failure}"
                else:
                    file_path.write_bytes(response.content)
                    reply = Reply()
                    reply.type = ReplyType.FILE
                    reply.content = str(file_path)
            
            elif is_http_url and url_path.endswith(".mp4"):
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
