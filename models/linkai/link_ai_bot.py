# access LinkAI knowledge base platform
# docs: https://link-ai.tech/platform/link-app/wechat

import re
import time
import requests
import json
import config
from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.chatgpt.chat_gpt_session import ChatGPTSession
from models.session_manager import SessionManager
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, pconf
import threading
from common import memory, utils
import base64
import os

class LinkAIBot(Bot, OpenAICompatibleBot):
    # authentication failed
    AUTH_FAILED_CODE = 401
    NO_QUOTA_CODE = 406

    def __init__(self):
        super().__init__()
        self.sessions = LinkAISessionManager(LinkAISession, model=conf().get("model") or "gpt-3.5-turbo")
        self.args = {}
    
    def get_api_config(self):
        """Get API configuration for OpenAI-compatible base class"""
        return {
            'api_key': conf().get("open_ai_api_key"),  # LinkAI uses OpenAI-compatible key
            'api_base': conf().get("open_ai_api_base", "https://api.link-ai.tech/v1"),
            'model': conf().get("model", "gpt-3.5-turbo"),
            'default_temperature': conf().get("temperature", 0.9),
            'default_top_p': conf().get("top_p", 1.0),
            'default_frequency_penalty': conf().get("frequency_penalty", 0.0),
            'default_presence_penalty': conf().get("presence_penalty", 0.0),
        }

    def reply(self, query, context: Context = None) -> Reply:
        if context.type == ContextType.TEXT:
            return self._chat(query, context)
        elif context.type == ContextType.IMAGE_CREATE:
            if not conf().get("text_to_image"):
                logger.warn("[LinkAI] text_to_image is not enabled, ignore the IMAGE_CREATE request")
                return Reply(ReplyType.TEXT, "")
            ok, res = self.create_img(query, 0)
            if ok:
                reply = Reply(ReplyType.IMAGE_URL, res)
            else:
                reply = Reply(ReplyType.ERROR, res)
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def _chat(self, query, context, retry_count=0) -> Reply:
        """
        发起对话请求
        :param query: 请求提示词
        :param context: 对话上下文
        :param retry_count: 当前递归重试次数
        :return: 回复
        """
        if retry_count > 2:
            # exit from retry 2 times
            logger.warn("[LINKAI] failed after maximum number of retry times")
            return Reply(ReplyType.TEXT, "请再问我一次吧")

        try:
            # load config
            if context.get("generate_breaked_by"):
                logger.info(f"[LINKAI] won't set appcode because a plugin ({context['generate_breaked_by']}) affected the context")
                app_code = None
            else:
                plugin_app_code = self._find_group_mapping_code(context)
                app_code = context.kwargs.get("app_code") or plugin_app_code or conf().get("linkai_app_code")
            linkai_api_key = conf().get("linkai_api_key")

            session_id = context["session_id"]
            session_message = self.sessions.session_msg_query(query, session_id)
            logger.debug(f"[LinkAI] session={session_message}, session_id={session_id}")

            # image process
            img_cache = memory.USER_IMAGE_CACHE.get(session_id)
            if img_cache:
                messages = self._process_image_msg(app_code=app_code, session_id=session_id, query=query, img_cache=img_cache)
                if messages:
                    session_message = messages

            model = conf().get("model")
            # remove system message
            if session_message[0].get("role") == "system":
                if app_code or model == "wenxin":
                    session_message.pop(0)
            body = {
                "app_code": app_code,
                "messages": session_message,
                "model": model,     # 对话模型的名称, 支持 gpt-3.5-turbo, gpt-3.5-turbo-16k, gpt-4, wenxin, xunfei
                "temperature": conf().get("temperature"),
                "top_p": conf().get("top_p", 1),
                "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
                "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
                "session_id": session_id,
                "sender_id": session_id,
                "channel_type": context.get("channel_type") or conf().get("channel_type", "web")
            }
            try:
                from linkai import LinkAIClient
                client_id = LinkAIClient.fetch_client_id()
                if client_id:
                    body["client_id"] = client_id
                    # start: client info deliver
                    if context.kwargs.get("msg"):
                        body["session_id"] = context.kwargs.get("msg").from_user_id
                        if context.kwargs.get("msg").is_group:
                            body["is_group"] = True
                            body["group_name"] = context.kwargs.get("msg").from_user_nickname
                            body["sender_name"] = context.kwargs.get("msg").actual_user_nickname
                        else:
                            if body.get("channel_type") in ["wechatcom_app"]:
                                body["sender_name"] = context.kwargs.get("msg").from_user_id
                            else:
                                body["sender_name"] = context.kwargs.get("msg").from_user_nickname

            except Exception as e:
                pass
            file_id = context.kwargs.get("file_id")
            if file_id:
                body["file_id"] = file_id
            logger.info(f"[LINKAI] query={query}, app_code={app_code}, model={body.get('model')}, file_id={file_id}")
            headers = {"Authorization": "Bearer " + linkai_api_key}

            # do http request
            base_url = conf().get("linkai_api_base", "https://api.link-ai.tech")
            res = requests.post(url=base_url + "/v1/chat/completions", json=body, headers=headers,
                                timeout=conf().get("request_timeout", 180))
            if res.status_code == 200:
                # execute success
                response = res.json()
                reply_content = response["choices"][0]["message"]["content"]
                total_tokens = response["usage"]["total_tokens"]
                res_code = response.get('code')
                logger.info(f"[LINKAI] reply={reply_content}, total_tokens={total_tokens}, res_code={res_code}")
                if res_code == 429:
                    logger.warn(f"[LINKAI] 用户访问超出限流配置，sender_id={body.get('sender_id')}")
                else:
                    self.sessions.session_reply(reply_content, session_id, total_tokens, query=query)
                agent_suffix = self._fetch_agent_suffix(response)
                if agent_suffix:
                    reply_content += agent_suffix
                if not agent_suffix:
                    knowledge_suffix = self._fetch_knowledge_search_suffix(response)
                    if knowledge_suffix:
                        reply_content += knowledge_suffix
                # image process
                if response["choices"][0].get("img_urls"):
                    thread = threading.Thread(target=self._send_image, args=(context.get("channel"), context, response["choices"][0].get("img_urls")))
                    thread.start()
                    reply_content = response["choices"][0].get("text_content")
                if reply_content:
                    reply_content = self._process_url(reply_content)
                return Reply(ReplyType.TEXT, reply_content)

            else:
                response = res.json()
                error = response.get("error")
                logger.error(f"[LINKAI] chat failed, status_code={res.status_code}, "
                             f"msg={error.get('message')}, type={error.get('type')}")

                if res.status_code >= 500:
                    # server error, need retry
                    time.sleep(2)
                    logger.warn(f"[LINKAI] do retry, times={retry_count}")
                    return self._chat(query, context, retry_count + 1)

                error_reply = "提问太快啦，请休息一下再问我吧"
                if res.status_code == 409:
                    error_reply = "这个问题我还没有学会，请问我其它问题吧"
                return Reply(ReplyType.TEXT, error_reply)

        except Exception as e:
            logger.exception(e)
            # retry
            time.sleep(2)
            logger.warn(f"[LINKAI] do retry, times={retry_count}")
            return self._chat(query, context, retry_count + 1)

    def _process_image_msg(self, app_code: str, session_id: str, query:str, img_cache: dict):
        try:
            enable_image_input = False
            app_info = self._fetch_app_info(app_code)
            if not app_info:
                logger.debug(f"[LinkAI] not found app, can't process images, app_code={app_code}")
                return None
            plugins = app_info.get("data").get("plugins")
            for plugin in plugins:
                if plugin.get("input_type") and "IMAGE" in plugin.get("input_type"):
                    enable_image_input = True
            if not enable_image_input:
                return
            msg = img_cache.get("msg")
            path = img_cache.get("path")
            msg.prepare()
            logger.info(f"[LinkAI] query with images, path={path}")
            messages = self._build_vision_msg(query, path)
            memory.USER_IMAGE_CACHE[session_id] = None
            return messages
        except Exception as e:
            logger.exception(e)

    def _find_group_mapping_code(self, context):
        try:
            if context.kwargs.get("isgroup"):
                group_name = context.kwargs.get("msg").from_user_nickname
                if config.plugin_config and config.plugin_config.get("linkai"):
                    linkai_config = config.plugin_config.get("linkai")
                    group_mapping = linkai_config.get("group_app_map")
                    if group_mapping and group_name:
                        return group_mapping.get(group_name)
        except Exception as e:
            logger.exception(e)
            return None

    def _build_vision_msg(self, query: str, path: str):
        try:
            suffix = utils.get_path_suffix(path)
            with open(path, "rb") as file:
                base64_str = base64.b64encode(file.read()).decode('utf-8')
                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": query
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{suffix};base64,{base64_str}"
                            }
                        }
                    ]
                }]
                return messages
        except Exception as e:
            logger.exception(e)

    def reply_text(self, session: ChatGPTSession, app_code="", retry_count=0) -> dict:
        if retry_count >= 2:
            # exit from retry 2 times
            logger.warn("[LINKAI] failed after maximum number of retry times")
            return {
                "total_tokens": 0,
                "completion_tokens": 0,
                "content": "请再问我一次吧"
            }

        try:
            body = {
                "app_code": app_code,
                "messages": session.messages,
                "model": conf().get("model") or "gpt-3.5-turbo",  # 对话模型的名称, 支持 gpt-3.5-turbo, gpt-3.5-turbo-16k, gpt-4, wenxin, xunfei
                "temperature": conf().get("temperature"),
                "top_p": conf().get("top_p", 1),
                "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
                "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            }
            if self.args.get("max_tokens"):
                body["max_tokens"] = self.args.get("max_tokens")
            headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}

            # do http request
            base_url = conf().get("linkai_api_base", "https://api.link-ai.tech")
            res = requests.post(url=base_url + "/v1/chat/completions", json=body, headers=headers,
                                timeout=conf().get("request_timeout", 180))
            if res.status_code == 200:
                # execute success
                response = res.json()
                reply_content = response["choices"][0]["message"]["content"]
                total_tokens = response["usage"]["total_tokens"]
                logger.info(f"[LINKAI] reply={reply_content}, total_tokens={total_tokens}")
                return {
                    "total_tokens": total_tokens,
                    "completion_tokens": response["usage"]["completion_tokens"],
                    "content": reply_content,
                }

            else:
                response = res.json()
                error = response.get("error")
                logger.error(f"[LINKAI] chat failed, status_code={res.status_code}, "
                             f"msg={error.get('message')}, type={error.get('type')}")

                if res.status_code >= 500:
                    # server error, need retry
                    time.sleep(2)
                    logger.warn(f"[LINKAI] do retry, times={retry_count}")
                    return self.reply_text(session, app_code, retry_count + 1)

                return {
                    "total_tokens": 0,
                    "completion_tokens": 0,
                    "content": "提问太快啦，请休息一下再问我吧"
                }

        except Exception as e:
            logger.exception(e)
            # retry
            time.sleep(2)
            logger.warn(f"[LINKAI] do retry, times={retry_count}")
            return self.reply_text(session, app_code, retry_count + 1)

    def _fetch_app_info(self, app_code: str):
        headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}
        # do http request
        base_url = conf().get("linkai_api_base", "https://api.link-ai.tech")
        params = {"app_code": app_code}
        res = requests.get(url=base_url + "/v1/app/info", params=params, headers=headers, timeout=(5, 10))
        if res.status_code == 200:
            return res.json()
        else:
            logger.warning(f"[LinkAI] find app info exception, res={res}")

    def create_img(self, query, retry_count=0, api_key=None):
        try:
            logger.info("[LinkImage] image_query={}".format(query))
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {conf().get('linkai_api_key')}"
            }
            data = {
                "prompt": query,
                "n": 1,
                "model": conf().get("text_to_image") or "dall-e-2",
                "response_format": "url",
                "img_proxy": conf().get("image_proxy")
            }
            url = conf().get("linkai_api_base", "https://api.link-ai.tech") + "/v1/images/generations"
            res = requests.post(url, headers=headers, json=data, timeout=(5, 90))
            t2 = time.time()
            image_url = res.json()["data"][0]["url"]
            logger.info("[OPEN_AI] image_url={}".format(image_url))
            return True, image_url

        except Exception as e:
            logger.error(format(e))
            return False, "画图出现问题，请休息一下再问我吧"


    def _fetch_knowledge_search_suffix(self, response) -> str:
        try:
            if response.get("knowledge_base"):
                search_hit = response.get("knowledge_base").get("search_hit")
                first_similarity = response.get("knowledge_base").get("first_similarity")
                logger.info(f"[LINKAI] knowledge base, search_hit={search_hit}, first_similarity={first_similarity}")
                plugin_config = pconf("linkai")
                if plugin_config and plugin_config.get("knowledge_base") and plugin_config.get("knowledge_base").get("search_miss_text_enabled"):
                    search_miss_similarity = plugin_config.get("knowledge_base").get("search_miss_similarity")
                    search_miss_text = plugin_config.get("knowledge_base").get("search_miss_suffix")
                    if not search_hit:
                        return search_miss_text
                    if search_miss_similarity and float(search_miss_similarity) > first_similarity:
                        return search_miss_text
        except Exception as e:
            logger.exception(e)


    def _fetch_agent_suffix(self, response):
        try:
            plugin_list = []
            logger.debug(f"[LinkAgent] res={response}")
            if response.get("agent") and response.get("agent").get("chain") and response.get("agent").get("need_show_plugin"):
                chain = response.get("agent").get("chain")
                suffix = "\n\n- - - - - - - - - - - -"
                i = 0
                for turn in chain:
                    plugin_name = turn.get('plugin_name')
                    suffix += "\n"
                    need_show_thought = response.get("agent").get("need_show_thought")
                    if turn.get("thought") and plugin_name and need_show_thought:
                        suffix += f"{turn.get('thought')}\n"
                    if plugin_name:
                        plugin_list.append(turn.get('plugin_name'))
                        if turn.get('plugin_icon'):
                            suffix += f"{turn.get('plugin_icon')} "
                        suffix += f"{turn.get('plugin_name')}"
                        if turn.get('plugin_input'):
                            suffix += f"：{turn.get('plugin_input')}"
                    if i < len(chain) - 1:
                        suffix += "\n"
                    i += 1
                logger.info(f"[LinkAgent] use plugins: {plugin_list}")
                return suffix
        except Exception as e:
            logger.exception(e)

    def _process_url(self, text):
        try:
            url_pattern = re.compile(r'\[(.*?)\]\((http[s]?://.*?)\)')
            def replace_markdown_url(match):
                return f"{match.group(2)}"
            return url_pattern.sub(replace_markdown_url, text)
        except Exception as e:
            logger.error(e)

    def _send_image(self, channel, context, image_urls):
        if not image_urls:
            return
        max_send_num = conf().get("max_media_send_count")
        send_interval = conf().get("media_send_interval")
        file_type = (".pdf", ".doc", ".docx", ".csv", ".xls", ".xlsx", ".txt", ".rtf", ".ppt", ".pptx")
        try:
            i = 0
            for url in image_urls:
                if max_send_num and i >= max_send_num:
                    continue
                i += 1
                if url.endswith(".mp4"):
                    reply_type = ReplyType.VIDEO_URL
                elif url.endswith(file_type):
                    reply_type = ReplyType.FILE
                    url = _download_file(url)
                    if not url:
                        continue
                else:
                    reply_type = ReplyType.IMAGE_URL
                reply = Reply(reply_type, url)
                channel.send(reply, context)
                if send_interval:
                    time.sleep(send_interval)
        except Exception as e:
            logger.error(e)


def _download_file(url: str):
    try:
        file_path = "tmp"
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        file_name = url.split("/")[-1]  # 获取文件名
        file_path = os.path.join(file_path, file_name)
        response = requests.get(url)
        with open(file_path, "wb") as f:
            f.write(response.content)
        return file_path
    except Exception as e:
        logger.warn(e)


class LinkAISessionManager(SessionManager):
    def session_msg_query(self, query, session_id):
        session = self.build_session(session_id)
        messages = session.messages + [{"role": "user", "content": query}]
        return messages

    def session_reply(self, reply, session_id, total_tokens=None, query=None):
        session = self.build_session(session_id)
        if query:
            session.add_query(query)
        session.add_reply(reply)
        try:
            max_tokens = conf().get("conversation_max_tokens", 8000)
            tokens_cnt = session.discard_exceeding(max_tokens, total_tokens)
            logger.debug(f"[LinkAI] chat history, before tokens={total_tokens}, now tokens={tokens_cnt}")
        except Exception as e:
            logger.warning("Exception when counting tokens precisely for session: {}".format(str(e)))
        return session


class LinkAISession(ChatGPTSession):
    def calc_tokens(self):
        if not self.messages:
            return 0
        return len(str(self.messages))

    def discard_exceeding(self, max_tokens, cur_tokens=None):
        cur_tokens = self.calc_tokens()
        if cur_tokens > max_tokens:
            for i in range(0, len(self.messages)):
                if i > 0 and self.messages[i].get("role") == "assistant" and self.messages[i - 1].get("role") == "user":
                    self.messages.pop(i)
                    self.messages.pop(i - 1)
                    return self.calc_tokens()
        return cur_tokens


# Add call_with_tools method to LinkAIBot class
def _linkai_call_with_tools(self, messages, tools=None, stream=False, **kwargs):
    """
    Call LinkAI API with tool support for agent integration
    LinkAI is fully compatible with OpenAI's tool calling format
    
    Args:
        messages: List of messages
        tools: List of tool definitions (OpenAI format)
        stream: Whether to use streaming
        **kwargs: Additional parameters (max_tokens, temperature, etc.)
        
    Returns:
        Formatted response in OpenAI format or generator for streaming
    """
    try:
        # Convert messages from Claude format to OpenAI format
        # This is important because Agent uses Claude format internally
        messages = self._convert_messages_to_openai_format(messages)
        
        # Convert tools from Claude format to OpenAI format
        if tools:
            tools = self._convert_tools_to_openai_format(tools)
        
        # Handle system prompt (OpenAI uses system message, Claude uses separate parameter)
        system_prompt = kwargs.get('system')
        if system_prompt:
            # Add system message at the beginning if not already present
            if not messages or messages[0].get('role') != 'system':
                messages = [{"role": "system", "content": system_prompt}] + messages
            else:
                # Replace existing system message
                messages[0] = {"role": "system", "content": system_prompt}
        
        logger.debug(f"[LinkAI] messages: {len(messages)}, tools: {len(tools) if tools else 0}, stream: {stream}")
        
        # Build request parameters (LinkAI uses OpenAI-compatible format)
        raw_ct = conf().get("channel_type", "web")
        if isinstance(raw_ct, list):
            channel_type = raw_ct[0] if raw_ct else "web"
        elif isinstance(raw_ct, str) and "," in raw_ct:
            channel_type = raw_ct.split(",")[0].strip()
        else:
            channel_type = raw_ct

        session_id = kwargs.get("session_id", "")
        body = {
            "messages": messages,
            "model": kwargs.get("model", conf().get("model") or "gpt-3.5-turbo"),
            "temperature": kwargs.get("temperature", conf().get("temperature", 0.9)),
            "top_p": kwargs.get("top_p", conf().get("top_p", 1)),
            "frequency_penalty": kwargs.get("frequency_penalty", conf().get("frequency_penalty", 0.0)),
            "presence_penalty": kwargs.get("presence_penalty", conf().get("presence_penalty", 0.0)),
            "stream": stream,
            "channel_type": kwargs.get("channel_type", channel_type),
            "session_id": session_id,
            "sender_id": session_id,
        }

        try:
            from linkai import LinkAIClient
            client_id = LinkAIClient.fetch_client_id()
            if client_id:
                body["client_id"] = client_id
        except Exception:
            pass

        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")

        thinking = kwargs.get("thinking")
        if thinking:
            body["thinking"] = thinking

        # Prepare headers
        headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}
        base_url = conf().get("linkai_api_base", "https://api.link-ai.tech")
        
        if stream:
            return self._handle_linkai_stream_response(base_url, headers, body)
        else:
            return self._handle_linkai_sync_response(base_url, headers, body)
            
    except Exception as e:
        logger.error(f"[LinkAI] call_with_tools error: {e}")
        if stream:
            def error_generator():
                yield {
                    "error": True,
                    "message": str(e),
                    "status_code": 500
                }
            return error_generator()
        else:
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }

def _handle_linkai_sync_response(self, base_url, headers, body):
    """Handle synchronous LinkAI API response"""
    try:
        res = requests.post(
            url=base_url + "/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=conf().get("request_timeout", 180)
        )
        
        if res.status_code == 200:
            response = res.json()
            logger.debug(f"[LinkAI] reply: model={response.get('model')}, "
                        f"tokens={response.get('usage', {}).get('total_tokens', 0)}")
            
            # LinkAI response is already in OpenAI-compatible format
            return response
        else:
            error_data = res.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            raise Exception(f"LinkAI API error: {res.status_code} - {error_msg}")
            
    except Exception as e:
        logger.error(f"[LinkAI] sync response error: {e}")
        raise

def _handle_linkai_stream_response(self, base_url, headers, body):
    """Handle streaming LinkAI API response"""
    try:
        res = requests.post(
            url=base_url + "/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=conf().get("request_timeout", 180),
            stream=True
        )
        
        if res.status_code != 200:
            error_text = res.text
            try:
                error_data = json.loads(error_text)
                error_msg = error_data.get("error", {}).get("message", error_text)
            except Exception:
                error_msg = error_text or "Unknown error"
            
            yield {
                "error": True,
                "status_code": res.status_code,
                "message": error_msg
            }
            return
        
        # Process streaming response (OpenAI-compatible SSE format)
        for line in res.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    line = line[6:]  # Remove 'data: ' prefix
                    if line == '[DONE]':
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Check for error responses within the stream
                    # Some providers (e.g., MiniMax via LinkAI) return errors as:
                    # {'type': 'error', 'error': {'type': '...', 'message': '...', 'http_code': '400'}}
                    if chunk.get("type") == "error" or (
                        isinstance(chunk.get("error"), dict) and "message" in chunk.get("error", {})
                    ):
                        error_data = chunk.get("error", {})
                        error_msg = error_data.get("message", "Unknown error") if isinstance(error_data, dict) else str(error_data)
                        http_code = error_data.get("http_code", "") if isinstance(error_data, dict) else ""
                        status_code = int(http_code) if http_code and str(http_code).isdigit() else 400
                        logger.error(f"[LinkAI] stream error: {error_msg} (http_code={http_code})")
                        yield {
                            "error": True,
                            "message": error_msg,
                            "status_code": status_code
                        }
                        return

                    # Forward SSE JSON as-is so extensions (e.g. delta._gemini_raw_parts
                    # for Gemini via LinkAI) reach agent_stream and are stored on assistant
                    # messages for the next request. Standard OpenAI fields are unchanged.
                    yield chunk
                        
    except Exception as e:
        logger.error(f"[LinkAI] stream response error: {e}")
        yield {
            "error": True,
            "message": str(e),
            "status_code": 500
        }

def _linkai_convert_messages_to_openai_format(self, messages):
    """
    Override the base OpenAI-compatible conversion to round-trip
    ``reasoning_content`` on assistant messages.

    Internally, the agent layer keeps the model's reasoning trace as a
    Claude-style ``thinking`` content block on the assistant message. The
    base converter drops that block. For thinking-capable models proxied via
    LinkAI (DeepSeek V4, Kimi K2 thinking, …), the upstream API requires
    the trace to be echoed back as a top-level ``reasoning_content`` field
    on every assistant turn that contained tool calls — otherwise the next
    request returns 400. We re-emit it for every assistant turn (it's
    silently ignored on plain text turns).
    """
    openai_messages = OpenAICompatibleBot._convert_messages_to_openai_format(self, messages)
    if not messages:
        return openai_messages

    # DeepSeek (proxied via LinkAI) requires `reasoning_content` on EVERY
    # assistant message once the history contains any tool-call turn — not
    # just the tool-call turn itself. Detect that condition first.
    has_tool_call_history = False
    for src in messages:
        if src.get("role") != "assistant":
            continue
        if src.get("tool_calls"):
            has_tool_call_history = True
            break
        content = src.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content
        ):
            has_tool_call_history = True
            break

    # Walk the original Claude messages to collect each assistant turn's
    # reasoning text, then attach it to the matching converted entry.
    dst_idx = 0
    for src in messages:
        if src.get("role") != "assistant":
            continue
        content = src.get("content")
        reasoning_parts = []
        if isinstance(content, list):
            reasoning_parts = [
                b.get("thinking", "") for b in content
                if isinstance(b, dict) and b.get("type") == "thinking"
            ]
        # Locate the corresponding assistant entry in the converted list.
        while dst_idx < len(openai_messages) and openai_messages[dst_idx].get("role") != "assistant":
            dst_idx += 1
        if dst_idx >= len(openai_messages):
            break
        dst_msg = openai_messages[dst_idx]
        if reasoning_parts:
            dst_msg["reasoning_content"] = "\n".join(reasoning_parts)
        elif has_tool_call_history:
            # Fallback when the trace was lost (proxy stripped it, model
            # switched mid-session, thinking toggled on after tool calls).
            # DeepSeek-style backends validate field presence, not value;
            # non-thinking backends silently ignore the empty string.
            dst_msg["reasoning_content"] = ""
        dst_idx += 1

    return openai_messages


# Attach methods to LinkAIBot class
LinkAIBot.call_with_tools = _linkai_call_with_tools
LinkAIBot._handle_linkai_sync_response = _handle_linkai_sync_response
LinkAIBot._handle_linkai_stream_response = _handle_linkai_stream_response
LinkAIBot._convert_messages_to_openai_format = _linkai_convert_messages_to_openai_format
