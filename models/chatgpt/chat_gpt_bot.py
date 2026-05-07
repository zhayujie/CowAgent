# encoding:utf-8

import time
import json

from models.openai.openai_compat import (
    error as openai_error,
    RateLimitError,
    Timeout,
    APIError,
    APIConnectionError,
    wrap_http_error,
)
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError
import requests
from common import const
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.chatgpt.chat_gpt_session import ChatGPTSession
from models.openai.open_ai_image import OpenAIImage
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.token_bucket import TokenBucket
from config import conf, load_config
from models.baidu.baidu_wenxin_session import BaiduWenxinSession

# OpenAI对话模型API (可用)
class ChatGPTBot(Bot, OpenAIImage, OpenAICompatibleBot):
    def __init__(self):
        super().__init__()
        # Resolve api key / base from config (no global SDK state anymore).
        if conf().get("bot_type") == "custom":
            self._api_key = conf().get("custom_api_key", "")
            self._api_base = conf().get("custom_api_base") or None
        else:
            self._api_key = conf().get("open_ai_api_key")
            self._api_base = conf().get("open_ai_api_base") or None
        self._proxy = conf().get("proxy") or None
        self._http_client = OpenAIHTTPClient(
            api_key=self._api_key,
            api_base=self._api_base,
            proxy=self._proxy,
        )
        if conf().get("rate_limit_chatgpt"):
            self.tb4chatgpt = TokenBucket(conf().get("rate_limit_chatgpt", 20))
        conf_model = conf().get("model") or "gpt-3.5-turbo"
        self.sessions = SessionManager(ChatGPTSession, model=conf().get("model") or "gpt-3.5-turbo")
        # o1相关模型不支持system prompt，暂时用文心模型的session

        self.args = {
            "model": conf_model,  # 对话模型的名称
            "temperature": conf().get("temperature", 0.9),  # 值在[0,1]之间，越大表示回复越具有不确定性
            # "max_tokens":4096,  # 回复最大的字符数
            "top_p": conf().get("top_p", 1),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "request_timeout": conf().get("request_timeout", None),  # 请求超时时间，openai接口默认设置为600，对于难问题一般需要较长时间
            "timeout": conf().get("request_timeout", None),  # 重试超时时间，在这个时间内，将会自动重试
        }
        # 部分模型暂不支持一些参数，特殊处理
        if conf_model in [const.O1, const.O1_MINI, const.GPT_5, const.GPT_5_MINI, const.GPT_5_NANO]:
            remove_keys = ["temperature", "top_p", "frequency_penalty", "presence_penalty"]
            for key in remove_keys:
                self.args.pop(key, None)  # 如果键不存在，使用 None 来避免抛出错、
            if conf_model in [const.O1, const.O1_MINI]:  # o1系列模型不支持系统提示词，使用文心模型的session
                self.sessions = SessionManager(BaiduWenxinSession, model=conf().get("model") or const.O1_MINI)

    def get_api_config(self):
        """Get API configuration for OpenAI-compatible base class"""
        is_custom = conf().get("bot_type") == "custom"
        return {
            'api_key': conf().get("custom_api_key") if is_custom else conf().get("open_ai_api_key"),
            'api_base': conf().get("custom_api_base") if is_custom else conf().get("open_ai_api_base"),
            'model': conf().get("model", "gpt-3.5-turbo"),
            'default_temperature': conf().get("temperature", 0.9),
            'default_top_p': conf().get("top_p", 1.0),
            'default_frequency_penalty': conf().get("frequency_penalty", 0.0),
            'default_presence_penalty': conf().get("presence_penalty", 0.0),
        }

    def _get_http_client(self) -> OpenAIHTTPClient:
        """Override the default HTTP client to reuse our pre-configured one."""
        return self._http_client
    
    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[CHATGPT] query={}".format(query))

            session_id = context["session_id"]
            reply = None
            clear_memory_commands = conf().get("clear_memory_commands", ["#清除记忆"])
            if query in clear_memory_commands:
                self.sessions.clear_session(session_id)
                reply = Reply(ReplyType.INFO, "记忆已清除")
            elif query == "#清除所有":
                self.sessions.clear_all_session()
                reply = Reply(ReplyType.INFO, "所有人记忆已清除")
            elif query == "#更新配置":
                load_config()
                reply = Reply(ReplyType.INFO, "配置已更新")
            if reply:
                return reply
            session = self.sessions.session_query(query, session_id)
            logger.debug("[CHATGPT] session query={}".format(session.messages))

            api_key = context.get("openai_api_key")
            model = context.get("gpt_model")
            new_args = None
            if model:
                new_args = self.args.copy()
                new_args["model"] = model
            # if context.get('stream'):
            #     # reply in stream
            #     return self.reply_text_stream(query, new_query, session_id)

            reply_content = self.reply_text(session, api_key, args=new_args)
            logger.debug(
                "[CHATGPT] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages,
                    session_id,
                    reply_content["content"],
                    reply_content["completion_tokens"],
                )
            )
            if reply_content["completion_tokens"] == 0 and len(reply_content["content"]) > 0:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
            elif reply_content["completion_tokens"] > 0:
                self.sessions.session_reply(reply_content["content"], session_id, reply_content["total_tokens"])
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[CHATGPT] reply {} used 0 tokens.".format(reply_content))
            return reply

        elif context.type == ContextType.IMAGE_CREATE:
            ok, retstring = self.create_img(query, 0)
            reply = None
            if ok:
                reply = Reply(ReplyType.IMAGE_URL, retstring)
            else:
                reply = Reply(ReplyType.ERROR, retstring)
            return reply
        elif context.type == ContextType.IMAGE:
            logger.info("[CHATGPT] Image message received")
            reply = self.reply_image(context)
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_image(self, context):
        """
        Process image message using OpenAI Vision API
        """
        import base64
        import os
        
        try:
            image_path = context.content
            logger.info(f"[CHATGPT] Processing image: {image_path}")
            
            # Check if file exists
            if not os.path.exists(image_path):
                logger.error(f"[CHATGPT] Image file not found: {image_path}")
                return Reply(ReplyType.ERROR, "图片文件不存在")
            
            # Read and encode image
            with open(image_path, "rb") as f:
                image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode("utf-8")
            
            # Detect image format
            extension = os.path.splitext(image_path)[1].lower()
            mime_type_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", 
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp"
            }
            mime_type = mime_type_map.get(extension, "image/jpeg")
            
            # Get model and API config
            is_custom = conf().get("bot_type") == "custom"
            model = context.get("gpt_model") or conf().get("model", "gpt-4o")
            api_key = context.get("openai_api_key") or (conf().get("custom_api_key") if is_custom else conf().get("open_ai_api_key"))
            api_base = conf().get("custom_api_base") if is_custom else conf().get("open_ai_api_base")
            
            # Build vision request
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请描述这张图片的内容"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]
            
            logger.info(f"[CHATGPT] Calling vision API with model: {model}")
            
            # Call OpenAI-compatible API via HTTP
            response = self._http_client.chat_completions(
                api_key=api_key or None,
                api_base=api_base or None,
                model=model,
                messages=messages,
                max_tokens=1000,
            )

            content = response["choices"][0]["message"]["content"]
            logger.info(f"[CHATGPT] Vision API response: {content[:100]}...")
            
            # Clean up temp file
            try:
                os.remove(image_path)
                logger.debug(f"[CHATGPT] Removed temp image file: {image_path}")
            except Exception:
                pass
            
            return Reply(ReplyType.TEXT, content)
            
        except Exception as e:
            logger.error(f"[CHATGPT] Image processing error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return Reply(ReplyType.ERROR, f"图片识别失败: {str(e)}")

    def reply_text(self, session: ChatGPTSession, api_key=None, args=None, retry_count=0) -> dict:
        """
        call openai's ChatCompletion to get the answer
        :param session: a conversation session
        :param session_id: session id
        :param retry_count: retry count
        :return: {}
        """
        try:
            if conf().get("rate_limit_chatgpt") and not self.tb4chatgpt.get_token():
                raise RateLimitError("RateLimitError: rate limit exceeded")
            # If api_key is None, the per-instance default key will be used.
            if args is None:
                args = self.args
            # Translate old SDK kwargs to HTTP client params:
            # - request_timeout / timeout -> per-call timeout
            call_args = dict(args)
            timeout = call_args.pop("request_timeout", None) or call_args.pop("timeout", None)
            response = self._http_client.chat_completions(
                api_key=api_key or None,
                timeout=timeout,
                messages=session.messages,
                **call_args,
            )
            logger.info("[ChatGPT] reply={}, total_tokens={}".format(
                response["choices"][0]["message"]["content"],
                response["usage"]["total_tokens"]
            ))
            return {
                "total_tokens": response["usage"]["total_tokens"],
                "completion_tokens": response["usage"]["completion_tokens"],
                "content": response["choices"][0]["message"]["content"],
            }
        except OpenAIHTTPError as http_err:
            return self._handle_reply_error(
                wrap_http_error(http_err), session, api_key, args, retry_count
            )
        except Exception as e:
            return self._handle_reply_error(e, session, api_key, args, retry_count)

    def _handle_reply_error(self, e, session, api_key, args, retry_count):
        """Map exception to user-facing reply with retry/backoff (mirrors SDK behavior)."""
        need_retry = retry_count < 2
        result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
        if isinstance(e, RateLimitError):
            logger.warn("[CHATGPT] RateLimitError: {}".format(e))
            result["content"] = "提问太快啦，请休息一下再问我吧"
            if need_retry:
                time.sleep(20)
        elif isinstance(e, Timeout):
            logger.warn("[CHATGPT] Timeout: {}".format(e))
            result["content"] = "我没有收到你的消息"
            if need_retry:
                time.sleep(5)
        elif isinstance(e, APIConnectionError):
            logger.warn("[CHATGPT] APIConnectionError: {}".format(e))
            result["content"] = "我连接不到你的网络"
            if need_retry:
                time.sleep(5)
        elif isinstance(e, APIError):
            logger.warn("[CHATGPT] Bad Gateway: {}".format(e))
            result["content"] = "请再问我一次"
            if need_retry:
                time.sleep(10)
        else:
            logger.exception("[CHATGPT] Exception: {}".format(e))
            need_retry = False
            self.sessions.clear_session(session.session_id)

        if need_retry:
            logger.warn("[CHATGPT] 第{}次重试".format(retry_count + 1))
            return self.reply_text(session, api_key, args, retry_count + 1)
        return result

class AzureChatGPTBot(ChatGPTBot):
    """Azure OpenAI variant.

    Azure's HTTP shape differs from public OpenAI:
      URL    : {endpoint}/openai/deployments/{deployment}/chat/completions
      Auth   : api-key header (not Bearer)
      Query  : ?api-version={version}
    We model that with a dedicated HTTP client and override _get_http_client
    so the OpenAICompatibleBot streaming/tool path uses it transparently.
    """

    def __init__(self):
        super().__init__()
        self._azure_api_version = conf().get("azure_api_version", "2023-06-01-preview")
        self._azure_deployment_id = conf().get("azure_deployment_id")
        # Drop legacy SDK kwarg; Azure deployment is encoded in the URL now.
        self.args.pop("deployment_id", None)

        endpoint = (self._api_base or "").rstrip("/")
        deployment = self._azure_deployment_id or ""
        # Build a base that already includes /openai/deployments/{deployment}.
        # /chat/completions will be appended by the client.
        azure_base = (
            f"{endpoint}/openai/deployments/{deployment}" if endpoint and deployment else endpoint
        )
        self._http_client = _AzureChatHTTPClient(
            api_key=self._api_key,
            api_base=azure_base,
            api_version=self._azure_api_version,
            proxy=self._proxy,
        )

    def create_img(self, query, retry_count=0, api_key=None):
        text_to_image_model = conf().get("text_to_image")
        if text_to_image_model == "dall-e-2":
            api_version = "2023-06-01-preview"
            endpoint = conf().get("azure_openai_dalle_api_base","open_ai_api_base")
            # 检查endpoint是否以/结尾
            if not endpoint.endswith("/"):
                endpoint = endpoint + "/"
            url = "{}openai/images/generations:submit?api-version={}".format(endpoint, api_version)
            api_key = conf().get("azure_openai_dalle_api_key","open_ai_api_key")
            headers = {"api-key": api_key, "Content-Type": "application/json"}
            try:
                body = {"prompt": query, "size": conf().get("image_create_size", "256x256"),"n": 1}
                submission = requests.post(url, headers=headers, json=body)
                operation_location = submission.headers['operation-location']
                status = ""
                while (status != "succeeded"):
                    if retry_count > 3:
                        return False, "图片生成失败"
                    response = requests.get(operation_location, headers=headers)
                    status = response.json()['status']
                    retry_count += 1
                image_url = response.json()['result']['data'][0]['url']
                return True, image_url
            except Exception as e:
                logger.error("create image error: {}".format(e))
                return False, "图片生成失败"
        elif text_to_image_model == "dall-e-3":
            api_version = conf().get("azure_api_version", "2024-02-15-preview")
            endpoint = conf().get("azure_openai_dalle_api_base","open_ai_api_base")
            # 检查endpoint是否以/结尾
            if not endpoint.endswith("/"):
                endpoint = endpoint + "/"
            url = "{}openai/deployments/{}/images/generations?api-version={}".format(endpoint, conf().get("azure_openai_dalle_deployment_id","text_to_image"),api_version)
            api_key = conf().get("azure_openai_dalle_api_key","open_ai_api_key")
            headers = {"api-key": api_key, "Content-Type": "application/json"}
            try:
                body = {"prompt": query, "size": conf().get("image_create_size", "1024x1024"), "quality": conf().get("dalle3_image_quality", "standard")}
                response = requests.post(url, headers=headers, json=body)
                response.raise_for_status()  # 检查请求是否成功
                data = response.json()

                # 检查响应中是否包含图像 URL
                if 'data' in data and len(data['data']) > 0 and 'url' in data['data'][0]:
                    image_url = data['data'][0]['url']
                    return True, image_url
                else:
                    error_message = "响应中没有图像 URL"
                    logger.error(error_message)
                    return False, "图片生成失败"

            except requests.exceptions.RequestException as e:
                # 捕获所有请求相关的异常
                try:
                    error_detail = response.json().get('error', {}).get('message', str(e))
                except ValueError:
                    error_detail = str(e)
                error_message = f"{error_detail}"
                logger.error(error_message)
                return False, error_message

            except Exception as e:
                # 捕获所有其他异常
                error_message = f"生成图像时发生错误: {e}"
                logger.error(error_message)
                return False, "图片生成失败"
        else:
            return False, "图片生成失败，未配置text_to_image参数"


class _AzureChatHTTPClient(OpenAIHTTPClient):
    """Subclass that injects Azure's ``api-version`` query param and ``api-key``
    header on every chat-completion request, and accepts the deployment-scoped
    base URL set by :class:`AzureChatGPTBot`.
    """

    def __init__(self, api_key, api_base, api_version, proxy=None, timeout=None):
        super().__init__(
            api_key=api_key, api_base=api_base, proxy=proxy, timeout=timeout
        )
        self._api_version = api_version

    def _build_headers(self, api_key, extra_headers):
        # Azure uses api-key header, not Bearer token.
        key = api_key if api_key is not None else self.api_key
        headers = {"Content-Type": "application/json"}
        if key:
            headers["api-key"] = key
        if self.extra_headers:
            headers.update(self.extra_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def chat_completions(self, **kwargs):
        # Always force api-version query param for Azure.
        eq = dict(kwargs.get("extra_query") or {})
        eq.setdefault("api-version", self._api_version)
        kwargs["extra_query"] = eq
        return super().chat_completions(**kwargs)
