import os
import re

import requests
from dingtalk_stream import ChatbotMessage

from bridge.context import ContextType
from channel.chat_message import ChatMessage
# -*- coding=utf-8 -*-
from common.log import logger
from common.tmp_dir import TmpDir
from common.utils import expand_path
from config import conf


class DingTalkMessage(ChatMessage):
    def __init__(self, event: ChatbotMessage, image_download_handler):
        super().__init__(event)
        self.image_download_handler = image_download_handler
        self.msg_id = event.message_id
        self.message_type = event.message_type
        self.incoming_message = event
        self.sender_staff_id = event.sender_staff_id
        self.other_user_id = event.conversation_id
        self.create_time = event.create_at
        self.image_content = event.image_content
        self.rich_text_content = event.rich_text_content
        self.robot_code = event.robot_code  # 机器人编码
        if event.conversation_type == "1":
            self.is_group = False
        else:
            self.is_group = True

        if self.message_type == "text":
            self.ctype = ContextType.TEXT

            self.content = event.text.content.strip()
        elif self.message_type == "audio":
            # 钉钉支持直接识别语音，所以此处将直接提取文字，当文字处理
            self.content = event.extensions['content']['recognition'].strip()
            self.ctype = ContextType.TEXT
        elif (self.message_type == 'picture') or (self.message_type == 'richText'):
            # 钉钉图片类型或富文本类型消息处理
            image_list = event.get_image_list()
            
            if self.message_type == 'picture' and len(image_list) > 0:
                # 单张图片消息：下载到工作空间，用于文件缓存
                self.ctype = ContextType.IMAGE
                download_code = image_list[0]
                download_url = image_download_handler.get_image_download_url(download_code)
                
                # 下载到工作空间 tmp 目录
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                tmp_dir = os.path.join(workspace_root, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                
                image_path = download_image_file(download_url, tmp_dir)
                if image_path:
                    self.content = image_path
                    self.image_path = image_path  # 保存图片路径用于缓存
                    logger.info(f"[DingTalk] Downloaded single image to {image_path}")
                else:
                    self.content = "[图片下载失败]"
                    self.image_path = None
            
            elif self.message_type == 'richText' and len(image_list) > 0:
                # 富文本消息：下载所有图片并附加到文本中
                self.ctype = ContextType.TEXT
                
                # 下载到工作空间 tmp 目录
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                tmp_dir = os.path.join(workspace_root, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                
                # 提取富文本中的文本内容
                text_content = ""
                if self.rich_text_content:
                    # rich_text_content 是一个 RichTextContent 对象，需要从中提取文本
                    text_list = event.get_text_list()
                    if text_list:
                        text_content = "".join(text_list).strip()
                
                # 下载所有图片
                image_paths = []
                for download_code in image_list:
                    download_url = image_download_handler.get_image_download_url(download_code)
                    image_path = download_image_file(download_url, tmp_dir)
                    if image_path:
                        image_paths.append(image_path)
                
                # 构建消息内容：文本 + 图片路径
                content_parts = []
                if text_content:
                    content_parts.append(text_content)
                for img_path in image_paths:
                    content_parts.append(f"[图片: {img_path}]")
                
                self.content = "\n".join(content_parts) if content_parts else "[富文本消息]"
                logger.info(f"[DingTalk] Received richText with {len(image_paths)} image(s): {self.content}")
            else:
                self.ctype = ContextType.IMAGE
                self.content = "[未找到图片]"
                logger.debug(f"[DingTalk] messageType: {self.message_type}, imageList isEmpty")

        if self.is_group:
            self.from_user_id = event.conversation_id
            self.actual_user_id = event.sender_id
            self.is_at = True
        else:
            self.from_user_id = event.sender_id
            self.actual_user_id = event.sender_id
        self.to_user_id = event.chatbot_user_id
        self.other_user_nickname = event.conversation_title


def download_image_file(image_url, temp_dir):
    """
    下载图片文件
    支持两种方式：
    1. 普通 HTTP(S) URL
    2. 钉钉 downloadCode: dingtalk://download/{download_code}
    """
    # 检查临时目录是否存在，如果不存在则创建
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    # 处理钉钉 downloadCode
    if image_url.startswith("dingtalk://download/"):
        download_code = image_url.replace("dingtalk://download/", "")
        logger.info(f"[DingTalk] Downloading image with downloadCode: {download_code[:20]}...")
        
        # 需要从外部传入 access_token，这里先用一个临时方案
        # 从 config 获取 dingtalk_client_id 和 dingtalk_client_secret
        from config import conf
        client_id = conf().get("dingtalk_client_id")
        client_secret = conf().get("dingtalk_client_secret")
        
        if not client_id or not client_secret:
            logger.error("[DingTalk] Missing dingtalk_client_id or dingtalk_client_secret")
            return None
        
        # 解析 robot_code 和 download_code
        parts = download_code.split(":", 1)
        if len(parts) != 2:
            logger.error(f"[DingTalk] Invalid download_code format (expected robot_code:download_code): {download_code[:50]}")
            return None
        
        robot_code, actual_download_code = parts
        
        # 获取 access_token（使用新版 API）
        token_url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        token_headers = {
            "Content-Type": "application/json"
        }
        token_body = {
            "appKey": client_id,
            "appSecret": client_secret
        }
        
        try:
            token_response = requests.post(token_url, json=token_body, headers=token_headers, timeout=10)
            
            if token_response.status_code == 200:
                token_data = token_response.json()
                access_token = token_data.get("accessToken")
                
                if not access_token:
                    logger.error(f"[DingTalk] Failed to get access token: {token_data}")
                    return None
                
                # 获取下载 URL（使用新版 API）
                download_api_url = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
                download_headers = {
                    "x-acs-dingtalk-access-token": access_token,
                    "Content-Type": "application/json"
                }
                download_body = {
                    "downloadCode": actual_download_code,
                    "robotCode": robot_code
                }
                
                download_response = requests.post(download_api_url, json=download_body, headers=download_headers, timeout=10)
                
                if download_response.status_code == 200:
                    download_data = download_response.json()
                    download_url = download_data.get("downloadUrl")
                    
                    if not download_url:
                        logger.error(f"[DingTalk] No downloadUrl in response: {download_data}")
                        return None
                    
                    # 从 downloadUrl 下载实际图片
                    image_response = requests.get(download_url, stream=True, timeout=60)
                    
                    if image_response.status_code == 200:
                        # 生成文件名（使用 download_code 的 hash，避免特殊字符）
                        import hashlib
                        file_hash = hashlib.md5(actual_download_code.encode()).hexdigest()[:16]
                        file_name = f"{file_hash}.png"
                        file_path = os.path.join(temp_dir, file_name)
                        
                        with open(file_path, 'wb') as file:
                            file.write(image_response.content)
                        
                        logger.info(f"[DingTalk] Image downloaded successfully: {file_path}")
                        return file_path
                    else:
                        logger.error(f"[DingTalk] Failed to download image from URL: {image_response.status_code}")
                        return None
                else:
                    logger.error(f"[DingTalk] Failed to get download URL: {download_response.status_code}, {download_response.text}")
                    return None
            else:
                logger.error(f"[DingTalk] Failed to get access token: {token_response.status_code}, {token_response.text}")
                return None
        except Exception as e:
            logger.error(f"[DingTalk] Exception downloading image: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    # 普通 HTTP(S) URL
    else:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
        }
        
        try:
            response = requests.get(image_url, headers=headers, stream=True, timeout=60 * 5)
            if response.status_code == 200:
                # 生成文件名
                file_name = image_url.split("/")[-1].split("?")[0]
                
                # 将文件保存到临时目录
                file_path = os.path.join(temp_dir, file_name)
                with open(file_path, 'wb') as file:
                    file.write(response.content)
                return file_path
            else:
                logger.info(f"[Dingtalk] Failed to download image file, {response.content}")
                return None
        except Exception as e:
            logger.error(f"[Dingtalk] Exception downloading image: {e}")
            return None
