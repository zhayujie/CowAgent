"""
钉钉通道接入

@author huiwen
@Date 2023/11/28
"""
import copy
import json
# -*- coding=utf-8 -*-
import logging
import os
import time
import requests

import dingtalk_stream
from dingtalk_stream import AckMessage
from dingtalk_stream.card_replier import AICardReplier
from dingtalk_stream.card_replier import AICardStatus
from dingtalk_stream.card_replier import CardReplier

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from common.utils import expand_path
from channel.dingtalk.dingtalk_message import DingTalkMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from config import conf


class CustomAICardReplier(CardReplier):
    def __init__(self, dingtalk_client, incoming_message):
        super(AICardReplier, self).__init__(dingtalk_client, incoming_message)

    def start(
            self,
            card_template_id: str,
            card_data: dict,
            recipients: list = None,
            support_forward: bool = True,
    ) -> str:
        """
        AI卡片的创建接口
        :param support_forward:
        :param recipients:
        :param card_template_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.PROCESSING
        return self.create_and_send_card(
            card_template_id,
            card_data_with_status,
            at_sender=True,
            at_all=False,
            recipients=recipients,
            support_forward=support_forward,
        )


# 对 AICardReplier 进行猴子补丁
AICardReplier.start = CustomAICardReplier.start


def _check(func):
    def wrapper(self, cmsg: DingTalkMessage):
        msgId = cmsg.msg_id
        if msgId in self.receivedMsgs:
            logger.info("DingTalk message {} already received, ignore".format(msgId))
            return
        self.receivedMsgs[msgId] = True
        create_time = cmsg.create_time  # 消息时间戳
        if conf().get("hot_reload") == True and int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[DingTalk] History message {} skipped".format(msgId))
            return
        if cmsg.my_msg and not cmsg.is_group:
            logger.debug("[DingTalk] My message {} skipped".format(msgId))
            return
        return func(self, cmsg)

    return wrapper


@singleton
class DingTalkChanel(ChatChannel, dingtalk_stream.ChatbotHandler):
    dingtalk_client_id = conf().get('dingtalk_client_id')
    dingtalk_client_secret = conf().get('dingtalk_client_secret')

    def setup_logger(self):
        # Suppress verbose logs from dingtalk_stream SDK
        logging.getLogger("dingtalk_stream").setLevel(logging.WARNING)
        return logging.getLogger("DingTalk")

    def __init__(self):
        super().__init__()
        super(dingtalk_stream.ChatbotHandler, self).__init__()
        self.logger = self.setup_logger()
        # 历史消息id暂存，用于幂等控制
        self.receivedMsgs = ExpiredDict(conf().get("expires_in_seconds", 3600))
        self._stream_client = None
        self._running = False
        self._event_loop = None
        logger.debug("[DingTalk] client_id={}, client_secret={} ".format(
            self.dingtalk_client_id, self.dingtalk_client_secret))
        # 无需群校验和前缀
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        # 单聊无需前缀
        conf()["single_chat_prefix"] = [""]
        # Access token cache
        self._access_token = None
        self._access_token_expires_at = 0
        # Robot code cache (extracted from incoming messages)
        self._robot_code = None

    def _open_connection(self, client):
        """
        Open a DingTalk stream connection directly, bypassing SDK's internal error-swallowing.
        Returns (connection_dict, error_str). On success error_str is empty; on failure
        connection_dict is None and error_str contains a human-readable message.
        """
        try:
            resp = requests.post(
                "https://api.dingtalk.com/v1.0/gateway/connections/open",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "clientId": client.credential.client_id,
                    "clientSecret": client.credential.client_secret,
                    "subscriptions": [{"type": "CALLBACK",
                                       "topic": dingtalk_stream.chatbot.ChatbotMessage.TOPIC}],
                    "ua": "dingtalk-sdk-python/cow",
                    "localIp": "",
                },
                timeout=10,
            )
            body = resp.json()
            if not resp.ok:
                code = body.get("code", resp.status_code)
                message = body.get("message", resp.reason)
                return None, f"open connection failed: [{code}] {message}"
            return body, ""
        except Exception as e:
            return None, f"open connection failed: {e}"

    def startup(self):
        import asyncio
        self.dingtalk_client_id = conf().get('dingtalk_client_id')
        self.dingtalk_client_secret = conf().get('dingtalk_client_secret')
        self._running = True
        credential = dingtalk_stream.Credential(self.dingtalk_client_id, self.dingtalk_client_secret)
        client = dingtalk_stream.DingTalkStreamClient(credential)
        self._stream_client = client
        client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, self)
        logger.info("[DingTalk] ✅ Stream client initialized, ready to receive messages")

        # Run the connection loop ourselves instead of delegating to client.start(),
        # so we can get detailed error messages and respond to stop() quickly.
        import urllib.parse as _urlparse
        import websockets as _ws
        import json as _json
        client.pre_start()
        _first_connect = True
        while self._running:
            # Open connection using our own request so we get detailed error info.
            connection, err_msg = self._open_connection(client)

            if connection is None:
                if _first_connect:
                    logger.warning(f"[DingTalk] {err_msg}")
                    self.report_startup_error(err_msg)
                    _first_connect = False
                else:
                    logger.warning(f"[DingTalk] {err_msg}, retrying in 10s...")

                # Interruptible sleep: checks _running every 100ms.
                for _ in range(100):
                    if not self._running:
                        break
                    time.sleep(0.1)
                continue

            if _first_connect:
                logger.info("[DingTalk] ✅ Connected to DingTalk stream")
                self.report_startup_success()
                _first_connect = False
            else:
                logger.info("[DingTalk] Reconnected to DingTalk stream")

            # Run the WebSocket session in an asyncio loop.
            uri = '%s?ticket=%s' % (
                connection['endpoint'],
                _urlparse.quote_plus(connection['ticket'])
            )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._event_loop = loop
            try:
                async def _session():
                    async with _ws.connect(uri) as websocket:
                        client.websocket = websocket
                        async for raw_message in websocket:
                            json_message = _json.loads(raw_message)
                            result = await client.route_message(json_message)
                            if result == dingtalk_stream.DingTalkStreamClient.TAG_DISCONNECT:
                                break

                loop.run_until_complete(_session())
            except (KeyboardInterrupt, SystemExit):
                logger.info("[DingTalk] Session loop received stop signal, exiting")
                break
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"[DingTalk] Stream session error: {e}, reconnecting in 3s...")
                for _ in range(30):
                    if not self._running:
                        break
                    time.sleep(0.1)
            finally:
                self._event_loop = None
                try:
                    loop.close()
                except Exception:
                    pass

        logger.info("[DingTalk] Startup loop exited")

    def stop(self):
        logger.info("[DingTalk] stop() called, setting _running=False")
        self._running = False
        loop = self._event_loop
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
                logger.info("[DingTalk] Sent stop signal to event loop")
            except Exception as e:
                logger.warning(f"[DingTalk] Error stopping event loop: {e}")
        self._stream_client = None
        logger.info("[DingTalk] stop() completed")
    
    def get_access_token(self):
        """
        获取企业内部应用的 access_token
        文档: https://open.dingtalk.com/document/orgapp/obtain-orgapp-token
        """
        current_time = time.time()
        
        # 如果 token 还没过期，直接返回缓存的 token
        if self._access_token and current_time < self._access_token_expires_at:
            return self._access_token
        
        # 获取新的 access_token
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        headers = {"Content-Type": "application/json"}
        data = {
            "appKey": self.dingtalk_client_id,
            "appSecret": self.dingtalk_client_secret
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200 and "accessToken" in result:
                self._access_token = result["accessToken"]
                # Token 有效期为 2 小时，提前 5 分钟刷新
                self._access_token_expires_at = current_time + result.get("expireIn", 7200) - 300
                logger.info("[DingTalk] Access token refreshed successfully")
                return self._access_token
            else:
                logger.error(f"[DingTalk] Failed to get access token: {result}")
                return None
        except Exception as e:
            logger.error(f"[DingTalk] Error getting access token: {e}")
            return None
    
    def send_single_message(self, user_id: str, content: str, robot_code: str) -> bool:
        """
        Send message to single user (private chat)
        API: https://open.dingtalk.com/document/orgapp/chatbots-send-one-on-one-chat-messages-in-batches
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("[DingTalk] Failed to send single message: Access token not available.")
            return False

        if not robot_code:
            logger.error("[DingTalk] Cannot send single message: robot_code is required")
            return False

        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json"
        }
        data = {
            "msgParam": json.dumps({"content": content}),
            "msgKey": "sampleText",
            "userIds": [user_id],
            "robotCode": robot_code
        }

        logger.info(f"[DingTalk] Sending single message to user {user_id} with robot_code {robot_code}")
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200 and result.get("processQueryKey"):
                logger.info(f"[DingTalk] Single message sent successfully to {user_id}")
                return True
            else:
                logger.error(f"[DingTalk] Failed to send single message: {result}")
                return False
        except Exception as e:
            logger.error(f"[DingTalk] Error sending single message: {e}")
            return False
    
    def send_group_message(self, conversation_id: str, content: str, robot_code: str = None):
        """
        主动发送群消息
        文档: https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message
        
        Args:
            conversation_id: 会话ID (openConversationId)
            content: 消息内容
            robot_code: 机器人编码，默认使用 dingtalk_client_id
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("[DingTalk] Cannot send group message: no access token")
            return False
        
        # Validate robot_code
        if not robot_code:
            logger.error("[DingTalk] Cannot send group message: robot_code is required")
            return False
        
        url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json"
        }
        data = {
            "msgParam": json.dumps({"content": content}),
            "msgKey": "sampleText",
            "openConversationId": conversation_id,
            "robotCode": robot_code
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200:
                logger.info(f"[DingTalk] Group message sent successfully to {conversation_id}")
                return True
            else:
                logger.error(f"[DingTalk] Failed to send group message: {result}")
                return False
        except Exception as e:
            logger.error(f"[DingTalk] Error sending group message: {e}")
            return False
    
    def upload_media(self, file_path: str, media_type: str = "image") -> str:
        """
        上传媒体文件到钉钉
        
        Args:
            file_path: 本地文件路径或URL
            media_type: 媒体类型 (image, video, voice, file)
        
        Returns:
            media_id，如果上传失败返回 None
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("[DingTalk] Cannot upload media: no access token")
            return None
        
        # 处理 file:// URL
        if file_path.startswith("file://"):
            file_path = file_path[7:]
        
        # 如果是 HTTP URL，先下载
        if file_path.startswith("http://") or file_path.startswith("https://"):
            try:
                import uuid
                response = requests.get(file_path, timeout=(5, 60))
                if response.status_code != 200:
                    logger.error(f"[DingTalk] Failed to download file from URL: {file_path}")
                    return None
                
                # 保存到临时文件
                file_name = os.path.basename(file_path) or f"media_{uuid.uuid4()}"
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                tmp_dir = os.path.join(workspace_root, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                temp_file = os.path.join(tmp_dir, file_name)
                
                with open(temp_file, "wb") as f:
                    f.write(response.content)
                
                file_path = temp_file
                logger.info(f"[DingTalk] Downloaded file to {file_path}")
            except Exception as e:
                logger.error(f"[DingTalk] Error downloading file: {e}")
                return None
        
        if not os.path.exists(file_path):
            logger.error(f"[DingTalk] File not found: {file_path}")
            return None
        
        # 上传到钉钉
        # 钉钉上传媒体文件 API: https://open.dingtalk.com/document/orgapp/upload-media-files
        url = "https://oapi.dingtalk.com/media/upload"
        params = {
            "access_token": access_token,
            "type": media_type
        }
        
        try:
            with open(file_path, "rb") as f:
                files = {"media": (os.path.basename(file_path), f)}
                response = requests.post(url, params=params, files=files, timeout=(5, 60))
                result = response.json()
                
                if result.get("errcode") == 0:
                    media_id = result.get("media_id")
                    logger.info(f"[DingTalk] Media uploaded successfully, media_id={media_id}")
                    return media_id
                else:
                    logger.error(f"[DingTalk] Failed to upload media: {result}")
                    return None
        except Exception as e:
            logger.error(f"[DingTalk] Error uploading media: {e}")
            return None
    
    def send_image_with_media_id(self, access_token: str, media_id: str, incoming_message, is_group: bool) -> bool:
        """
        发送图片消息（使用 media_id）
        
        Args:
            access_token: 访问令牌
            media_id: 媒体ID
            incoming_message: 钉钉消息对象
            is_group: 是否为群聊
        
        Returns:
            是否发送成功
        """
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            'Content-Type': 'application/json'
        }
        
        msg_param = {
            "photoURL": media_id  # 钉钉图片消息使用 photoURL 字段
        }
        
        body = {
            "robotCode": incoming_message.robot_code,
            "msgKey": "sampleImageMsg",
            "msgParam": json.dumps(msg_param),
        }
        
        if is_group:
            # 群聊
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            body["openConversationId"] = incoming_message.conversation_id
        else:
            # 单聊
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            body["userIds"] = [incoming_message.sender_staff_id]
        
        try:
            response = requests.post(url=url, headers=headers, json=body, timeout=10)
            result = response.json()
            
            logger.info(f"[DingTalk] Image send result: {response.text}")
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"[DingTalk] Send image error: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[DingTalk] Send image exception: {e}")
            return False

    def send_image_message(self, receiver: str, media_id: str, is_group: bool, robot_code: str) -> bool:
        """
        发送图片消息
        
        Args:
            receiver: 接收者ID (user_id 或 conversation_id)
            media_id: 媒体ID
            is_group: 是否为群聊
            robot_code: 机器人编码
        
        Returns:
            是否发送成功
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("[DingTalk] Cannot send image: no access token")
            return False
        
        if not robot_code:
            logger.error("[DingTalk] Cannot send image: robot_code is required")
            return False
        
        if is_group:
            # 发送群聊图片
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            headers = {
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json"
            }
            data = {
                "msgParam": json.dumps({"mediaId": media_id}),
                "msgKey": "sampleImageMsg",
                "openConversationId": receiver,
                "robotCode": robot_code
            }
        else:
            # 发送单聊图片
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            headers = {
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json"
            }
            data = {
                "msgParam": json.dumps({"mediaId": media_id}),
                "msgKey": "sampleImageMsg",
                "userIds": [receiver],
                "robotCode": robot_code
            }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200:
                logger.info(f"[DingTalk] Image message sent successfully")
                return True
            else:
                logger.error(f"[DingTalk] Failed to send image message: {result}")
                return False
        except Exception as e:
            logger.error(f"[DingTalk] Error sending image message: {e}")
            return False
    
    def get_image_download_url(self, download_code: str) -> str:
        """
        获取图片下载地址
        返回一个特殊的 URL 格式：dingtalk://download/{robot_code}:{download_code}
        后续会在 download_image_file 中使用新版 API 下载
        """
        # 获取 robot_code
        if not hasattr(self, '_robot_code_cache'):
            self._robot_code_cache = None
        
        robot_code = self._robot_code_cache
        
        if not robot_code:
            logger.error("[DingTalk] robot_code not available for image download")
            return None
        
        # 返回一个特殊的 URL，包含 robot_code 和 download_code
        logger.info(f"[DingTalk] Successfully got image download URL for code: {download_code}")
        return f"dingtalk://download/{robot_code}:{download_code}"

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

            # 缓存 robot_code，用于后续图片下载
            if hasattr(incoming_message, 'robot_code'):
                self._robot_code_cache = incoming_message.robot_code

            # Filter out stale messages from before channel startup (offline backlog)
            create_at = getattr(incoming_message, 'create_at', None)
            if create_at:
                msg_age_s = time.time() - int(create_at) / 1000
                if msg_age_s > 60:
                    logger.warning(f"[DingTalk] stale msg filtered (age={msg_age_s:.0f}s), "
                                   f"msg_id={getattr(incoming_message, 'message_id', 'N/A')}")
                    return AckMessage.STATUS_OK, 'OK'

            image_download_handler = self
            dingtalk_msg = DingTalkMessage(incoming_message, image_download_handler)

            if dingtalk_msg.is_group:
                self.handle_group(dingtalk_msg)
            else:
                self.handle_single(dingtalk_msg)
            return AckMessage.STATUS_OK, 'OK'
        except Exception as e:
            logger.error(f"[DingTalk] process error: {e}", exc_info=True)
            return AckMessage.STATUS_SYSTEM_EXCEPTION, 'ERROR'

    @time_checker
    @_check
    def handle_single(self, cmsg: DingTalkMessage):
        # 处理单聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive text msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        
        # 处理文件缓存逻辑
        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()
        
        # 单聊的 session_id 就是 sender_id
        session_id = cmsg.from_user_id
        
        # 如果是单张图片消息，缓存起来
        if cmsg.ctype == ContextType.IMAGE:
            if hasattr(cmsg, 'image_path') and cmsg.image_path:
                file_cache.add(session_id, cmsg.image_path, file_type='image')
                logger.info(f"[DingTalk] Image cached for session {session_id}, waiting for user query...")
            # 单张图片不直接处理，等待用户提问
            return
        
        # 如果是文本消息，检查是否有缓存的文件
        if cmsg.ctype == ContextType.TEXT:
            cached_files = file_cache.get(session_id)
            if cached_files:
                # 将缓存的文件附加到文本消息中
                file_refs = []
                for file_info in cached_files:
                    file_path = file_info['path']
                    file_type = file_info['type']
                    if file_type == 'image':
                        file_refs.append(f"[图片: {file_path}]")
                    elif file_type == 'video':
                        file_refs.append(f"[视频: {file_path}]")
                    else:
                        file_refs.append(f"[文件: {file_path}]")
                
                cmsg.content = cmsg.content + "\n" + "\n".join(file_refs)
                logger.info(f"[DingTalk] Attached {len(cached_files)} cached file(s) to user query")
                # 清除缓存
                file_cache.clear(session_id)
        
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            self.produce(context)


    @time_checker
    @_check
    def handle_group(self, cmsg: DingTalkMessage):
        # 处理群聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive text msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        
        # 处理文件缓存逻辑
        from channel.file_cache import get_file_cache
        file_cache = get_file_cache()
        
        # 群聊的 session_id
        if conf().get("group_shared_session", True):
            session_id = cmsg.other_user_id  # conversation_id
        else:
            session_id = cmsg.from_user_id + "_" + cmsg.other_user_id
        
        # 如果是单张图片消息，缓存起来
        if cmsg.ctype == ContextType.IMAGE:
            if hasattr(cmsg, 'image_path') and cmsg.image_path:
                file_cache.add(session_id, cmsg.image_path, file_type='image')
                logger.info(f"[DingTalk] Image cached for session {session_id}, waiting for user query...")
            # 单张图片不直接处理，等待用户提问
            return
        
        # 如果是文本消息，检查是否有缓存的文件
        if cmsg.ctype == ContextType.TEXT:
            cached_files = file_cache.get(session_id)
            if cached_files:
                # 将缓存的文件附加到文本消息中
                file_refs = []
                for file_info in cached_files:
                    file_path = file_info['path']
                    file_type = file_info['type']
                    if file_type == 'image':
                        file_refs.append(f"[图片: {file_path}]")
                    elif file_type == 'video':
                        file_refs.append(f"[视频: {file_path}]")
                    else:
                        file_refs.append(f"[文件: {file_path}]")
                
                cmsg.content = cmsg.content + "\n" + "\n".join(file_refs)
                logger.info(f"[DingTalk] Attached {len(cached_files)} cached file(s) to user query")
                # 清除缓存
                file_cache.clear(session_id)
        
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
        context['no_need_at'] = True
        if context:
            self.produce(context)


    def send(self, reply: Reply, context: Context):
        logger.debug(f"[DingTalk] send() called with reply.type={reply.type}, content_length={len(str(reply.content))}")
        receiver = context["receiver"]
        
        # Check if msg exists (for scheduled tasks, msg might be None)
        msg = context.kwargs.get('msg')
        if msg is None:
            # 定时任务场景：使用主动发送 API
            is_group = context.get("isgroup", False)
            logger.info(f"[DingTalk] Sending scheduled task message to {receiver} (is_group={is_group})")
            
            # 使用缓存的 robot_code 或配置的值
            robot_code = self._robot_code or conf().get("dingtalk_robot_code")
            logger.info(f"[DingTalk] Using robot_code: {robot_code}, cached: {self._robot_code}, config: {conf().get('dingtalk_robot_code')}")
            
            if not robot_code:
                logger.error(f"[DingTalk] Cannot send scheduled task: robot_code not available. Please send at least one message to the bot first, or configure dingtalk_robot_code in config.json")
                return
            
            # 根据是否群聊选择不同的 API
            if is_group:
                success = self.send_group_message(receiver, reply.content, robot_code)
            else:
                # 单聊场景：尝试从 context 中获取 dingtalk_sender_staff_id
                sender_staff_id = context.get("dingtalk_sender_staff_id")
                if not sender_staff_id:
                    logger.error(f"[DingTalk] Cannot send single chat scheduled message: sender_staff_id not available in context")
                    return
                
                logger.info(f"[DingTalk] Sending single message to staff_id: {sender_staff_id}")
                success = self.send_single_message(sender_staff_id, reply.content, robot_code)
            
            if not success:
                logger.error(f"[DingTalk] Failed to send scheduled task message")
            return
        
        # 从正常消息中提取并缓存 robot_code
        if hasattr(msg, 'robot_code'):
            robot_code = msg.robot_code
            if robot_code and robot_code != self._robot_code:
                self._robot_code = robot_code
                logger.debug(f"[DingTalk] Cached robot_code: {robot_code}")
        
        isgroup = msg.is_group
        incoming_message = msg.incoming_message
        robot_code = self._robot_code or conf().get("dingtalk_robot_code")
        
        # 处理图片和视频发送
        if reply.type == ReplyType.IMAGE_URL:
            logger.info(f"[DingTalk] Sending image: {reply.content}")
            
            # 如果有附加的文本内容，先发送文本
            if hasattr(reply, 'text_content') and reply.text_content:
                self.reply_text(reply.text_content, incoming_message)
                import time
                time.sleep(0.3)  # 短暂延迟，确保文本先到达
            
            media_id = self.upload_media(reply.content, media_type="image")
            if media_id:
                # 使用主动发送 API 发送图片
                access_token = self.get_access_token()
                if access_token:
                    success = self.send_image_with_media_id(
                        access_token,
                        media_id,
                        incoming_message,
                        isgroup
                    )
                    if not success:
                        logger.error("[DingTalk] Failed to send image message")
                        self.reply_text("抱歉，图片发送失败", incoming_message)
                else:
                    logger.error("[DingTalk] Cannot get access token")
                    self.reply_text("抱歉，图片发送失败（无法获取token）", incoming_message)
            else:
                logger.error("[DingTalk] Failed to upload image")
                self.reply_text("抱歉，图片上传失败", incoming_message)
            return
        
        elif reply.type == ReplyType.FILE:
            # 如果有附加的文本内容，先发送文本
            if hasattr(reply, 'text_content') and reply.text_content:
                self.reply_text(reply.text_content, incoming_message)
                import time
                time.sleep(0.3)  # 短暂延迟，确保文本先到达
            
            # 判断是否为视频文件
            file_path = reply.content
            if file_path.startswith("file://"):
                file_path = file_path[7:]
            
            is_video = file_path.lower().endswith(('.mp4', '.avi', '.mov', '.wmv', '.flv'))
            
            access_token = self.get_access_token()
            if not access_token:
                logger.error("[DingTalk] Cannot get access token")
                self.reply_text("抱歉，文件发送失败（无法获取token）", incoming_message)
                return
            
            if is_video:
                logger.info(f"[DingTalk] Sending video: {reply.content}")
                media_id = self.upload_media(reply.content, media_type="video")
                if media_id:
                    # 发送视频消息
                    msg_param = {
                        "duration": "30",  # TODO: 获取实际视频时长
                        "videoMediaId": media_id,
                        "videoType": "mp4",
                        "height": "400",
                        "width": "600",
                    }
                    success = self._send_file_message(
                        access_token,
                        incoming_message,
                        "sampleVideo",
                        msg_param,
                        isgroup
                    )
                    if not success:
                        self.reply_text("抱歉，视频发送失败", incoming_message)
                else:
                    logger.error("[DingTalk] Failed to upload video")
                    self.reply_text("抱歉，视频上传失败", incoming_message)
            else:
                # 其他文件类型
                logger.info(f"[DingTalk] Sending file: {reply.content}")
                media_id = self.upload_media(reply.content, media_type="file")
                if media_id:
                    file_name = os.path.basename(file_path)
                    file_base, file_extension = os.path.splitext(file_name)
                    msg_param = {
                        "mediaId": media_id,
                        "fileName": file_name,
                        "fileType": file_extension[1:] if file_extension else "file"
                    }
                    success = self._send_file_message(
                        access_token,
                        incoming_message,
                        "sampleFile",
                        msg_param,
                        isgroup
                    )
                    if not success:
                        self.reply_text("抱歉，文件发送失败", incoming_message)
                else:
                    logger.error("[DingTalk] Failed to upload file")
                    self.reply_text("抱歉，文件上传失败", incoming_message)
            return
        
        # 处理文本消息
        elif reply.type == ReplyType.TEXT:
            logger.info(f"[DingTalk] Sending text message, length={len(reply.content)}")
            if conf().get("dingtalk_card_enabled"):
                logger.info("[Dingtalk] sendMsg={}, receiver={}".format(reply, receiver))
                def reply_with_text():
                    self.reply_text(reply.content, incoming_message)
                def reply_with_at_text():
                    self.reply_text("📢 您有一条新的消息，请查看。", incoming_message)
                def reply_with_ai_markdown():
                    button_list, markdown_content = self.generate_button_markdown_content(context, reply)
                    self.reply_ai_markdown_button(incoming_message, markdown_content, button_list, "", "📌 内容由AI生成", "",[incoming_message.sender_staff_id])

                if reply.type in [ReplyType.IMAGE_URL, ReplyType.IMAGE, ReplyType.TEXT]:
                    if isgroup:
                        reply_with_ai_markdown()
                        reply_with_at_text()
                    else:
                        reply_with_ai_markdown()
                else:
                    # 暂不支持其它类型消息回复
                    reply_with_text()
            else:
                self.reply_text(reply.content, incoming_message)
            return
    
    def _send_file_message(self, access_token: str, incoming_message, msg_key: str, msg_param: dict, is_group: bool) -> bool:
        """
        发送文件/视频消息的通用方法
        
        Args:
            access_token: 访问令牌
            incoming_message: 钉钉消息对象
            msg_key: 消息类型 (sampleFile, sampleVideo, sampleAudio)
            msg_param: 消息参数
            is_group: 是否为群聊
        
        Returns:
            是否发送成功
        """
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            'Content-Type': 'application/json'
        }
        
        body = {
            "robotCode": incoming_message.robot_code,
            "msgKey": msg_key,
            "msgParam": json.dumps(msg_param),
        }
        
        if is_group:
            # 群聊
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            body["openConversationId"] = incoming_message.conversation_id
        else:
            # 单聊
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            body["userIds"] = [incoming_message.sender_staff_id]
        
        try:
            response = requests.post(url=url, headers=headers, json=body, timeout=10)
            result = response.json()
            
            logger.info(f"[DingTalk] File send result: {response.text}")
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"[DingTalk] Send file error: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[DingTalk] Send file exception: {e}")
            return False

    def generate_button_markdown_content(self, context, reply):
        image_url = context.kwargs.get("image_url")
        promptEn = context.kwargs.get("promptEn")
        reply_text = reply.content
        button_list = []
        markdown_content = f"""
{reply.content}
                                """
        if image_url is not None and promptEn is not None:
            button_list = [
                {"text": "查看原图", "url": image_url, "iosUrl": image_url, "color": "blue"}
            ]
            markdown_content = f"""
{promptEn}

!["图片"]({image_url})

{reply_text}

                                """
        logger.debug(f"[Dingtalk] generate_button_markdown_content, button_list={button_list} , markdown_content={markdown_content}")

        return button_list, markdown_content
