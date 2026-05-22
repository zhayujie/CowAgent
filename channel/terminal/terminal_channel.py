import sys

from bridge.context import *
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.chat_message import ChatMessage
from common.log import logger
from config import conf


class TerminalMessage(ChatMessage):
    def __init__(
        self,
        msg_id,
        content,
        ctype=ContextType.TEXT,
        from_user_id="User",
        to_user_id="Chatgpt",
        other_user_id="Chatgpt",
    ):
        self.msg_id = msg_id
        self.ctype = ctype
        self.content = content
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.other_user_id = other_user_id


class TerminalChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]

    def send(self, reply: Reply, context: Context):
        print("\nBot:")
        if reply.type == ReplyType.IMAGE:
            from PIL import Image

            image_storage = reply.content
            image_storage.seek(0)
            img = Image.open(image_storage)
            print("<IMAGE>")
            img.show()
        elif reply.type == ReplyType.IMAGE_URL:  # 从网络下载图片
            import io

            import requests
            from PIL import Image

            img_url = reply.content
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            for block in pic_res.iter_content(1024):
                image_storage.write(block)
            image_storage.seek(0)
            img = Image.open(image_storage)
            print(img_url)
            img.show()
        else:
            print(reply.content)
        print("\nUser:", end="")
        sys.stdout.flush()
        return

    def startup(self):
        context = Context()
        logger.setLevel("WARN")
        print("\nPlease input your question:\nUser:", end="")
        sys.stdout.flush()
        msg_id = 0
        while True:
            try:
                prompt = self.get_input()
            except KeyboardInterrupt:
                print("\nExiting...")
                sys.exit()
            msg_id += 1
            trigger_prefixs = conf().get("single_chat_prefix", [""])
            if check_prefix(prompt, trigger_prefixs) is None:
                prompt = trigger_prefixs[0] + prompt  # 给没触发的消息加上触发前缀

            context = self._compose_context(ContextType.TEXT, prompt, msg=TerminalMessage(msg_id, prompt))
            context["isgroup"] = False
            if context:
                self.produce(context)
            else:
                raise Exception("context is None")

    def get_input(self):
        """
        Multi-line input function
        """
        sys.stdout.flush()
        line = input()
        return line
