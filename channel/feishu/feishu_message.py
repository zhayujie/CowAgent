from bridge.context import ContextType
from channel.chat_message import ChatMessage
import json
import os
import requests
from common.log import logger
from common.tmp_dir import TmpDir
from common import utils
from common.utils import expand_path
from config import conf


class FeishuMessage(ChatMessage):
    def __init__(self, event: dict, is_group=False, access_token=None):
        super().__init__(event)
        msg = event.get("message")
        sender = event.get("sender")
        self.access_token = access_token
        self.msg_id = msg.get("message_id")
        self.create_time = msg.get("create_time")
        self.is_group = is_group
        msg_type = msg.get("message_type")

        if msg_type == "text":
            self.ctype = ContextType.TEXT
            content = json.loads(msg.get('content'))
            self.content = content.get("text").strip()
        elif msg_type == "image":
            # 单张图片消息：下载并缓存，等待用户提问时一起发送
            self.ctype = ContextType.IMAGE
            content = json.loads(msg.get("content"))
            image_key = content.get("image_key")
            
            # 下载图片到工作空间临时目录
            workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
            tmp_dir = os.path.join(workspace_root, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            image_path = os.path.join(tmp_dir, f"{image_key}.png")
            
            # 下载图片
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{msg.get('message_id')}/resources/{image_key}"
            headers = {"Authorization": "Bearer " + access_token}
            params = {"type": "image"}
            response = requests.get(url=url, headers=headers, params=params)
            
            if response.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"[FeiShu] Downloaded single image, key={image_key}, path={image_path}")
                self.content = image_path
                self.image_path = image_path  # 保存图片路径
            else:
                logger.error(f"[FeiShu] Failed to download single image, key={image_key}, status={response.status_code}")
                self.content = f"[图片下载失败: {image_key}]"
                self.image_path = None
        elif msg_type == "post":
            # 富文本消息，可能包含图片、文本等多种元素
            content = json.loads(msg.get("content"))
            
            # 飞书富文本消息结构：content 直接包含 title 和 content 数组
            # 不是嵌套在 post 字段下
            title = content.get("title", "")
            content_list = content.get("content", [])
            
            logger.info(f"[FeiShu] Post message - title: '{title}', content_list length: {len(content_list)}")
            
            # 收集所有图片和文本
            image_keys = []
            text_parts = []
            
            if title:
                text_parts.append(title)
            
            for block in content_list:
                logger.debug(f"[FeiShu] Processing block: {block}")
                # block 本身就是元素列表
                if not isinstance(block, list):
                    continue
                    
                for element in block:
                    element_tag = element.get("tag")
                    logger.debug(f"[FeiShu] Element tag: {element_tag}, element: {element}")
                    if element_tag == "img":
                        # 找到图片元素
                        image_key = element.get("image_key")
                        if image_key:
                            image_keys.append(image_key)
                    elif element_tag == "text":
                        # 文本元素
                        text_content = element.get("text", "")
                        if text_content:
                            text_parts.append(text_content)
            
            logger.info(f"[FeiShu] Parsed - images: {len(image_keys)}, text_parts: {text_parts}")
            
            # 富文本消息统一作为文本消息处理
            self.ctype = ContextType.TEXT
            
            if image_keys:
                # 如果包含图片，下载并在文本中引用本地路径
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                tmp_dir = os.path.join(workspace_root, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                
                # 保存图片路径映射
                self.image_paths = {}
                for image_key in image_keys:
                    image_path = os.path.join(tmp_dir, f"{image_key}.png")
                    self.image_paths[image_key] = image_path
                
                def _download_images():
                    for image_key, image_path in self.image_paths.items():
                        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{self.msg_id}/resources/{image_key}"
                        headers = {"Authorization": "Bearer " + access_token}
                        params = {"type": "image"}
                        response = requests.get(url=url, headers=headers, params=params)
                        if response.status_code == 200:
                            with open(image_path, "wb") as f:
                                f.write(response.content)
                            logger.info(f"[FeiShu] Image downloaded from post message, key={image_key}, path={image_path}")
                        else:
                            logger.error(f"[FeiShu] Failed to download image from post, key={image_key}, status={response.status_code}")
                
                # 立即下载图片，不使用延迟下载
                # 因为 TEXT 类型消息不会调用 prepare()
                _download_images()
                
                # 构建消息内容：文本 + 图片路径
                content_parts = []
                if text_parts:
                    content_parts.append("\n".join(text_parts).strip())
                for image_key, image_path in self.image_paths.items():
                    content_parts.append(f"[图片: {image_path}]")
                
                self.content = "\n".join(content_parts)
                logger.info(f"[FeiShu] Received post message with {len(image_keys)} image(s) and text: {self.content}")
            else:
                # 纯文本富文本消息
                self.content = "\n".join(text_parts).strip() if text_parts else "[富文本消息]"
                logger.info(f"[FeiShu] Received post message (text only): {self.content}")
        elif msg_type == "file":
            self.ctype = ContextType.FILE
            content = json.loads(msg.get("content"))
            file_key = content.get("file_key")
            file_name = content.get("file_name")

            # 落到 agent_workspace/tmp 下（绝对路径），与图片处理一致；
            # 否则相对路径 ./tmp 在 agent 工作区里 read 时会找不到。
            workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
            tmp_dir = os.path.join(workspace_root, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            self.content = os.path.join(
                tmp_dir, f"{file_key}.{utils.get_path_suffix(file_name)}"
            )

            def _download_file():
                # 如果响应状态码是200，则将响应内容写入本地文件
                url = f"https://open.feishu.cn/open-apis/im/v1/messages/{self.msg_id}/resources/{file_key}"
                headers = {
                    "Authorization": "Bearer " + access_token,
                }
                params = {
                    "type": "file"
                }
                response = requests.get(url=url, headers=headers, params=params)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[FeiShu] Failed to download file, key={file_key}, res={response.text}")
            self._prepare_fn = _download_file
        elif msg_type == "audio":
            # 飞书用户发送的语音消息类型为 "audio"，文件为 opus 编码格式。
            # 映射为 ContextType.VOICE，交由 chat_channel 的语音转文字（STT）流程处理。
            # 文件通过 _prepare_fn 延迟下载，在 chat_channel 调用 cmsg.prepare() 时才执行。
            self.ctype = ContextType.VOICE
            content = json.loads(msg.get("content"))
            file_key = content.get("file_key")

            # 落到 agent_workspace/tmp 下（绝对路径），保证语音 STT 流程可读到
            workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
            tmp_dir = os.path.join(workspace_root, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            self.content = os.path.join(tmp_dir, f"{file_key}.opus")
            logger.info(f"[FeiShu] audio message: file_key={file_key}, save_path={self.content}")

            def _download_audio():
                logger.info(f"[FeiShu] downloading audio: file_key={file_key}, msg_id={self.msg_id}")
                url = f"https://open.feishu.cn/open-apis/im/v1/messages/{self.msg_id}/resources/{file_key}"
                headers = {
                    "Authorization": "Bearer " + access_token,
                }
                params = {
                    "type": "file"
                }
                try:
                    response = requests.get(url=url, headers=headers, params=params)
                    logger.info(f"[FeiShu] download audio response: status={response.status_code}, size={len(response.content)} bytes")
                    if response.status_code == 200:
                        with open(self.content, "wb") as f:
                            f.write(response.content)
                        logger.info(f"[FeiShu] audio saved to: {self.content}")
                    else:
                        logger.error(f"[FeiShu] Failed to download audio, key={file_key}, status={response.status_code}, res={response.text}")
                except Exception as e:
                    logger.error(f"[FeiShu] Exception downloading audio, key={file_key}: {e}", exc_info=True)
            self._prepare_fn = _download_audio
        else:
            raise NotImplementedError("Unsupported message type: Type:{} ".format(msg_type))

        self.from_user_id = sender.get("sender_id").get("open_id")
        self.to_user_id = event.get("app_id")
        if is_group:
            # 群聊
            self.other_user_id = msg.get("chat_id")
            self.actual_user_id = self.from_user_id
            self.content = self.content.replace("@_user_1", "").strip()
            self.actual_user_nickname = ""
        else:
            # 私聊
            self.other_user_id = self.from_user_id
            self.actual_user_id = self.from_user_id
