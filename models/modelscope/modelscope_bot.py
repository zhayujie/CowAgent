# encoding:utf-8

import json
import time
import requests

from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from .modelscope_session import ModelScopeSession


class ModelScopeBot(Bot):

    def __init__(self):
        super().__init__()
        model = conf().get("model") or "Qwen/Qwen3.5-27B"
        if model == "modelscope":
            model = "Qwen/Qwen3.5-27B"
        self.sessions = SessionManager(ModelScopeSession, model=model)
        self.args = {
            "model": model,
            "temperature": conf().get("temperature", 0.3),
            "top_p": conf().get("top_p", 1.0),
        }
        self.api_key = conf().get("modelscope_api_key")
        self.base_url = conf().get("modelscope_base_url", "https://api-inference.modelscope.cn/v1")
        if self.base_url.endswith("/chat/completions"):
            self.base_url = self.base_url.rsplit("/chat/completions", 1)[0]
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        
        # Cache context for Agent mode usage
        self._last_context = None
        
        logger.info("[MODELSCOPE] base_url configured as: {}".format(self.base_url))

    def reply(self, query, context=None):
        # Cache context for Agent mode usage
        self._last_context = context
        
        if context.type == ContextType.TEXT:
            logger.info("[MODELSCOPE] query={}".format(query))
            
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
            logger.debug("[MODELSCOPE] session query={}".format(session.messages))

            model = context.get("modelscope_model")
            new_args = self.args.copy()
            if model:
                new_args["model"] = model
            
            model_name = new_args["model"]

            # Unified judgment for thinking model
            if self._is_thinking_model(model_name):
                new_args["enable_thinking"] = True
                reply_content = self.reply_text_stream(session, args=new_args)
            else:
                reply_content = self.reply_text(session, args=new_args)
            
            logger.debug(
                "[MODELSCOPE] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages,
                    session_id,
                    reply_content["content"],
                    reply_content["completion_tokens"],
                )
            )

            if reply_content["completion_tokens"] == 0 and len(reply_content["content"]) > 0:
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            elif reply_content["completion_tokens"] > 0:
                self.sessions.session_reply(
                    reply_content["content"],
                    session_id,
                    reply_content["total_tokens"]
                )
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[MODELSCOPE] reply {} used 0 tokens.".format(reply_content))
            
            return reply
            
        elif context.type == ContextType.IMAGE_CREATE:
            ok, retstring = self.create_img(query, 0)
            return Reply(ReplyType.IMAGE_URL, retstring) if ok else Reply(ReplyType.ERROR, retstring)
        else:
            return Reply(ReplyType.ERROR, "Bot 不支持处理{}类型的消息".format(context.type))

    def reply_text(self, session, args=None, retry_count=0):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key
            }
            
            body = args.copy() if args else {}
            body["messages"] = self._convert_messages_for_modelscope(session.messages)
            body["stream"] = False
            
            res = requests.post(
                "{}/chat/completions".format(self.base_url),
                headers=headers,
                json=body,
                timeout=120
            )
            
            if res.status_code == 200:
                response = res.json()
                return {
                    "total_tokens": response.get("usage", {}).get("total_tokens", 0),
                    "completion_tokens": response.get("usage", {}).get("completion_tokens", 0),
                    "content": response["choices"][0]["message"]["content"] if response.get("choices") else ""
                }
            else:
                response = res.json()
                error = response.get("error", response.get("errors", {}))
                logger.error(
                    "[MODELSCOPE] chat failed, status_code={}, msg={}".format(
                        res.status_code,
                        error.get('message') if isinstance(error, dict) else error
                    )
                )
                
                result = {"completion_tokens": 0, "content": "提问太快啦，请休息一下再问我吧"}
                need_retry = False

                if res.status_code >= 500:
                    logger.warn("[MODELSCOPE] do retry, times={}".format(retry_count))
                    need_retry = retry_count < 2
                elif res.status_code == 401:
                    result["content"] = "授权失败，请检查 API Key 是否正确"
                elif res.status_code == 429:
                    result["content"] = "请求过于频繁，请稍后再试"
                    need_retry = retry_count < 2
                else:
                    need_retry = False
                
                if need_retry:
                    time.sleep(3)
                    return self.reply_text(session, args, retry_count + 1)
                else:
                    return result
                    
        except Exception as e:
            logger.exception(e)
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if need_retry:
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result

    def reply_text_stream(self, session, args=None):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key
            }
            
            body = args.copy() if args else {}
            body["messages"] = self._convert_messages_for_modelscope(session.messages)
            body["stream"] = True

            res = requests.post(
                "{}/chat/completions".format(self.base_url),
                headers=headers,
                json=body,
                stream=True,
                timeout=120
            )
            if res.status_code == 200:
                content = ""
                total_tokens = completion_tokens = 0
                finish_reason = None
                
                for line in res.iter_lines():
                    if not line:
                        continue
                    
                    decoded_line = line.decode('utf-8')
                    if not decoded_line.startswith("data: "):
                        continue
                    
                    data_str = decoded_line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    
                    try:
                        json_data = json.loads(data_str)

                        if "usage" in json_data:
                            total_tokens = json_data["usage"].get("total_tokens", 0)
                            completion_tokens = json_data["usage"].get("completion_tokens", 0)

                        delta = json_data.get("choices", [{}])[0].get("delta", {})
                        if delta and delta.get("content"):
                            content += delta["content"]

                        choice = json_data.get("choices", [{}])[0]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                            
                    except json.JSONDecodeError:
                        continue

                if finish_reason is None and content:
                    finish_reason = "stop"
                
                return {
                    "total_tokens": total_tokens,
                    "completion_tokens": completion_tokens,
                    "content": content
                }
            else:
                return {"completion_tokens": 0, "content": "请求失败"}
                
        except Exception as e:
            logger.exception(e)
            return {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

    def create_img(self, query):
        try:
            logger.info("[ModelScopeImage] image_query={}".format(query))
            
            create_headers = {
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json; charset=utf-8",
                "X-ModelScope-Async-Mode": "true"
            }
            
            payload = {
                "model": conf().get("text_to_image"),
                "prompt": query,
                "n": 1,
            }
            
            logger.debug("[ModelScopeImage] model={}".format(payload["model"]))
            
            res = requests.post(
                "{}/images/generations".format(self.base_url),
                headers=create_headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                timeout=120
            )
            
            logger.debug("[ModelScopeImage] create task status={}".format(res.status_code))
            logger.debug("[ModelScopeImage] create task response={}".format(res.text))
            
            if res.status_code != 200:
                logger.error("[ModelScopeImage] create task failed: {}".format(res.text))
                return False, "创建画图任务失败：{}".format(res.status_code)
            
            task_data = res.json()
            
            task_id = task_data.get("task_id")
            if not task_id:
                logger.error("[ModelScopeImage] No task_id in response: {}".format(task_data))
                return False, "创建画图任务失败：未返回 task_id"
            
            logger.info("[ModelScopeImage] task_id={}".format(task_id))
            
            max_wait_times = 60
            wait_interval = 5
            
            for i in range(max_wait_times):
                time.sleep(wait_interval)
                
                poll_headers = {
                    "Authorization": "Bearer " + self.api_key,
                    "X-ModelScope-Task-Type": "image_generation"
                }
                
                poll_url = "{}/tasks/{}".format(self.base_url, task_id)
                logger.debug("[ModelScopeImage] poll {} URL: {}".format(i+1, poll_url))
                logger.debug("[ModelScopeImage] poll headers: {}".format(poll_headers))
                
                task_res = requests.get(
                    poll_url,
                    headers=poll_headers,
                    timeout=30
                )
                
                logger.debug("[ModelScopeImage] poll {} status={}".format(i+1, task_res.status_code))
                logger.debug("[ModelScopeImage] poll response={}".format(task_res.text))
                
                if task_res.status_code != 200:
                    logger.error("[ModelScopeImage] poll task error: {}".format(task_res.text))
                    continue
                
                data = task_res.json()
                
                task_status = data.get("task_status")
                logger.debug("[ModelScopeImage] task_status={}".format(task_status))
                
                if task_status == "SUCCEED":
                    output_images = data.get("output_images", [])
                    if output_images and len(output_images) > 0:
                        image_url = output_images[0]
                        logger.info("[ModelScopeImage] image generated successfully: {}".format(image_url))
                        return True, image_url
                    else:
                        logger.error("[ModelScopeImage] No output_images in success response: {}".format(data))
                        return False, "画图成功但未返回图片 URL"
                        
                elif task_status == "FAILED":
                    error_msg = "未知错误"
                    if "errors" in data:
                        error_msg = data["errors"].get("message", "未知错误")
                    elif "message" in data:
                        error_msg = data["message"]
                    logger.error("[ModelScopeImage] task failed: {}".format(data))
                    return False, "画图任务失败：{}".format(error_msg)
                    
                elif task_status == "CANCELED":
                    logger.error("[ModelScopeImage] task canceled: {}".format(data))
                    return False, "画图任务已取消"
                    
                logger.debug("[ModelScopeImage] waiting for task to complete...")
            
            logger.error("[ModelScopeImage] task timeout after {} seconds".format(max_wait_times * wait_interval))
            return False, "画图超时，请稍后再试"
            
        except Exception as e:
            logger.error("[ModelScopeImage] error: {}".format(format(e)))
            return False, "画图出现问题，请休息一下再问我吧"

    # ==================== Agent Mode Support ====================

    def _detect_image_intent(self, message):
        """Detect whether the message has drawing intention (keyword detection)"""
        if not message:
            return False
        
        message_lower = message.lower()
        image_keywords = ["画", "图片", "图像", "生成图", "photo", "image", "draw", "paint", "generate"]
        if any(keyword in message_lower for keyword in image_keywords):
            logger.info("[MODELSCOPE] Image intent detected by keyword: {}".format(message[:50]))
            return True
        
        return False

    def _is_thinking_model(self, model_name):
        """
        Determine whether it is a thinking model.
        A thinking model requires: 1) enabling the enable_thinking parameter, and 2) using streaming responses.
        """
        if not model_name:
            return False
        model_name_lower = model_name.lower()
        if "thinking" in model_name_lower or "think" in model_name_lower:
            return True
        if model_name in ["Qwen/QwQ-32B", ]:
            return True
        return False

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call ModelScope API with tool call support.
        Also check ContextType and keywords; if either matches, trigger drawing.
        """
        try:
            # Check the IMAGE_CREATE type from the cached context
            context = getattr(self, '_last_context', None)
            
            # If the context type is IMAGE_CREATE, directly call create_img
            if context and hasattr(context, 'type') and context.type == ContextType.IMAGE_CREATE:
                logger.info("[MODELSCOPE] IMAGE_CREATE context detected, calling create_img directly")
                query = getattr(context, 'content', '')
                if query:
                    ok, result = self.create_img(query)
                    if ok:
                        logger.info("[MODELSCOPE] Image generated: {}".format(result))
                        if stream:
                            return self._create_image_stream_response(result)
                        else:
                            return self._create_image_response(result)
                    else:
                        logger.error("[MODELSCOPE] Image generation failed: {}".format(result))
                        error_content = "画图失败：{}".format(result)
                        if stream:
                            return self._create_error_stream_response(error_content)
                        else:
                            return self._create_error_response(error_content)
            
            # Extract message content
            last_message = ""
            if messages and len(messages) > 0:
                last_msg = messages[-1]
                if isinstance(last_msg, dict):
                    content = last_msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                        last_message = " ".join(text_parts)
                    else:
                        last_message = content
                elif isinstance(last_msg, str):
                    last_message = last_msg
            
            if not isinstance(last_message, str):
                last_message = str(last_message)
            
            logger.debug("[MODELSCOPE] Extracted message: {}".format(last_message[:100]))
            
            # Keyword detection
            has_image_intent = self._detect_image_intent(last_message)
            
            if has_image_intent:
                logger.info("[MODELSCOPE] Image intent detected by keyword, calling create_img directly")
                ok, result = self.create_img(last_message)
                if ok:
                    logger.info("[MODELSCOPE] Image generated: {}".format(result))
                    if stream:
                        return self._create_image_stream_response(result)
                    else:
                        return self._create_image_response(result)
                else:
                    logger.error("[MODELSCOPE] Image generation failed: {}".format(result))
                    error_content = "画图失败：{}".format(result)
                    if stream:
                        return self._create_error_stream_response(error_content)
                    else:
                        return self._create_error_response(error_content)
            
            # No drawing intent, proceed with normal tool call flow
            session_id = kwargs.get('session_id', 'default_session')
            session = self.sessions.session_query("", session_id)
            session.messages = messages
            
            args = self.args.copy()
            args.update(kwargs)
            
            # Unified judgment for thinking model
            model_name = args.get("model", self.args.get("model", ""))
            if self._is_thinking_model(model_name):
                args["enable_thinking"] = True
            
            if tools:
                args["tools"] = self._convert_tools_to_openai_format(tools)
                args["tool_choice"] = "auto"
            
            logger.debug(
                "[MODELSCOPE] call_with_tools: model={}, tools={}, stream={}, enable_thinking={}".format(
                    args.get('model'),
                    len(tools) if tools else 0,
                    stream,
                    args.get('enable_thinking')
                )
            )
            
            if stream:
                return self._handle_stream_response(session, args)
            else:
                return self._handle_sync_response(session, args)
                
        except Exception as e:
            logger.error("[MODELSCOPE] call_with_tools error: {}".format(e))
            error_msg = "{}".format(e)
            def error_generator():
                yield {"error": True, "message": error_msg, "status_code": 500}
            return error_generator()

    def _handle_sync_response(self, session, args):
        result = self.reply_text(session, args)
        
        content = result.get("content", "")
        tool_calls = result.get("tool_calls")
        
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.get("function", {}).get("name", "")
                if tool_name in ["create_image", "generate_image"]:
                    try:
                        tool_args = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
                        prompt = tool_args.get("prompt", "")
                        ok, image_url = self.create_img(prompt)
                        if ok:
                            result["tool_execution_result"] = {"image_url": image_url, "success": True}
                        else:
                            result["tool_execution_result"] = {"error": image_url, "success": False}
                    except Exception as e:
                        logger.error("[MODELSCOPE] Sync tool execution error: {}".format(e))
        
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": result.get("completion_tokens", 0),
                "total_tokens": result.get("total_tokens", 0)
            },
            "model": args.get("model", self.args.get("model"))
        }

    def _handle_stream_response(self, session, args):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key
            }
            
            body = args.copy()
            body["messages"] = self._convert_messages_for_modelscope(session.messages)
            body["stream"] = True
            
            response = requests.post(
                "{}/chat/completions".format(self.base_url),
                headers=headers,
                json=body,
                stream=True,
                timeout=120
            )
            
            if response.status_code != 200:
                yield {"error": True, "message": response.text, "status_code": response.status_code}
                return
            
            current_tool_calls = {}
            finish_reason = None
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                line = line.decode("utf-8")
                if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                    continue
                
                try:
                    chunk = json.loads(line[6:])
                    
                    if chunk.get("error"):
                        yield {"error": True, "message": str(chunk["error"]), "status_code": 500}
                        return
                    
                    choices = chunk.get("choices")
                    if not choices or len(choices) == 0:
                        continue
                    
                    choice = choices[0]
                    if not choice:
                        continue
                    
                    delta = choice.get("delta")
                    if not delta:
                        continue
                    
                    if delta.get("reasoning_content"):
                        yield {
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "reasoning_content": delta["reasoning_content"]
                                }
                            }]
                        }
                        continue
                    
                    tool_call_chunks = delta.get("tool_calls")
                    if tool_call_chunks:
                        cleaned_chunks = []
                        for tool_call_chunk in tool_call_chunks:
                            if not tool_call_chunk:
                                continue
                            
                            index = tool_call_chunk.get("index", 0)
                            func_info = tool_call_chunk.get("function") or {}
                            
                            if index not in current_tool_calls:
                                current_tool_calls[index] = {
                                    "id": tool_call_chunk.get("id") or "",
                                    "name": func_info.get("name") or "",
                                    "arguments": ""
                                }
                                logger.debug("[MODELSCOPE] tool_call start: {}".format(func_info.get('name')))
                            
                            args_str = func_info.get("arguments")
                            if args_str:
                                current_tool_calls[index]["arguments"] += (
                                    args_str if isinstance(args_str, str) else str(args_str)
                                )
                            
                            cleaned_chunk = {
                                "index": index,
                                "id": tool_call_chunk.get("id") or "call_{}".format(index),
                                "type": "function",
                                "function": {
                                    "name": func_info.get("name") or current_tool_calls[index].get("name", ""),
                                    "arguments": func_info.get("arguments") or ""
                                }
                            }
                            cleaned_chunks.append(cleaned_chunk)
                        
                        if cleaned_chunks:
                            yield {
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "tool_calls": cleaned_chunks
                                    }
                                }]
                            }
                        continue
                    
                    content = delta.get("content")
                    if content:
                        logger.debug("[MODELSCOPE] stream content: {}...".format(content[:50]))
                    
                    yield_chunk = {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": delta.get("role"),
                                "content": content
                            }
                        }]
                    }
                    
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                        yield_chunk["choices"][0]["finish_reason"] = finish_reason
                    
                    yield yield_chunk
                    
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error("[MODELSCOPE] chunk process error: {}".format(e))
                    continue
            
            logger.debug(
                "[MODELSCOPE] stream completed: has_tool_calls={}, finish_reason={}".format(
                    len(current_tool_calls) > 0,
                    finish_reason
                )
            )
            
            if current_tool_calls:
                logger.debug("[MODELSCOPE] tool_calls collected: {}".format(list(current_tool_calls.values())))
                
                for idx, tool_call in current_tool_calls.items():
                    tool_name = tool_call.get("name", "")
                    tool_args_str = tool_call.get("arguments", "{}")
                    
                    if tool_name in ["create_image", "generate_image"]:
                        try:
                            tool_args = json.loads(tool_args_str) if tool_args_str else {}
                            prompt = tool_args.get("prompt", "")
                            
                            logger.info("[MODELSCOPE] Executing image tool directly: {}".format(prompt[:50]))
                            
                            ok, result = self.create_img(prompt)
                            
                            if ok:
                                logger.info("[MODELSCOPE] Image generated: {}".format(result))
                                yield {
                                    "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "role": "tool",
                                            "content": json.dumps({"image_url": result, "success": True})
                                        },
                                        "tool_call_id": tool_call.get("id", "")
                                    }]
                                }
                            else:
                                logger.error("[MODELSCOPE] Image generation failed: {}".format(result))
                                yield {
                                    "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "role": "tool",
                                            "content": json.dumps({"error": result, "success": False})
                                        },
                                        "tool_call_id": tool_call.get("id", "")
                                    }]
                                }
                        except Exception as e:
                            logger.error("[MODELSCOPE] Image tool execution error: {}".format(e))
                            yield {
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "tool",
                                        "content": json.dumps({"error": str(e), "success": False})
                                    },
                                    "tool_call_id": tool_call.get("id", "")
                                }]
                            }
            
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason or "stop"
                }]
            }
            
        except Exception as e:
            logger.error("[MODELSCOPE] stream tool call error: {}".format(e))
            error_msg = "{}".format(e)
            def error_generator():
                yield {"error": True, "message": error_msg, "status_code": 500}
            return error_generator()

    # ==================== Format Conversion ====================

    def _convert_messages_for_modelscope(self, messages):
        if not messages:
            return []
        converted = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, str):
                converted.append(msg)
                continue
            if isinstance(content, list):
                new_content = []
                for block in content:
                    if not isinstance(block, dict):
                        new_content.append(block)
                        continue
                    block_type = block.get("type")
                    if block_type == "tool_result":
                        tool_content = block.get("content", "")
                        if not isinstance(tool_content, str):
                            tool_content = json.dumps(tool_content, ensure_ascii=False)
                        new_content.append({
                            "type": "text",
                            "text": "[工具执行结果]: {}".format(tool_content)
                        })
                    elif block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        if not isinstance(tool_input, str):
                            tool_input = json.dumps(tool_input, ensure_ascii=False)
                        new_content.append({
                            "type": "text",
                            "text": "[工具调用]: {}({})".format(tool_name, tool_input)
                        })
                    else:
                        new_content.append(block)
                converted.append({"role": role, "content": new_content})
            else:
                converted.append(msg)
        return converted

    def _convert_tools_to_openai_format(self, tools):
        if not tools:
            return None
        converted = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                converted.append(tool)
            else:
                converted.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        return converted

    def _create_image_response(self, image_url):
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "已为您生成图片：{}".format(image_url),
                    "tool_calls": None
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "model": self.args.get("model")
        }

    def _create_image_stream_response(self, image_url):
        content = "已为您生成图片：{}".format(image_url)
        yield {
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"}
            }]
        }
        chunk_size = 10
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {"content": chunk}
                }]
            }
        yield {
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }

    def _create_error_response(self, error_msg):
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": error_msg,
                    "tool_calls": None
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "model": self.args.get("model")
        }

    def _create_error_stream_response(self, error_msg):
        yield {
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"}
            }]
        }
        chunk_size = 10
        for i in range(0, len(error_msg), chunk_size):
            chunk = error_msg[i:i+chunk_size]
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {"content": chunk}
                }]
            }
        yield {
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
