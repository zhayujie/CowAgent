# encoding:utf-8

import time
import json
from typing import Optional

from models.bot import Bot
from models.zhipuai.zhipu_ai_session import ZhipuAISession
from models.zhipuai.zhipu_ai_image import ZhipuAIImage
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from zai import ZhipuAiClient


# ZhipuAI对话模型API
class ZHIPUAIBot(Bot, ZhipuAIImage):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(ZhipuAISession, model=conf().get("model") or "ZHIPU_AI")
        self.args = {
            "model": conf().get("model") or "glm-4",  # 对话模型的名称
            "temperature": conf().get("temperature", 0.9),  # 值在(0,1)之间(智谱AI 的温度不能取 0 或者 1)
            "top_p": conf().get("top_p", 0.7),  # 值在(0,1)之间(智谱AI 的 top_p 不能取 0 或者 1)
        }
        # 初始化客户端，支持自定义 API base URL（例如智谱国际版 z.ai）
        api_key = conf().get("zhipu_ai_api_key")
        api_base = conf().get("zhipu_ai_api_base")
        
        if api_base:
            self.client = ZhipuAiClient(api_key=api_key, base_url=api_base)
        else:
            self.client = ZhipuAiClient(api_key=api_key)

    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[ZHIPU_AI] query={}".format(query))

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
            logger.debug("[ZHIPU_AI] session query={}".format(session.messages))

            model = context.get("gpt_model")
            new_args = None
            if model:
                new_args = self.args.copy()
                new_args["model"] = model

            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[ZHIPU_AI] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[ZHIPU_AI] reply {} used 0 tokens.".format(reply_content))
            return reply
        elif context.type == ContextType.IMAGE_CREATE:
            ok, retstring = self.create_img(query, 0)
            reply = None
            if ok:
                reply = Reply(ReplyType.IMAGE_URL, retstring)
            else:
                reply = Reply(ReplyType.ERROR, retstring)
            return reply

        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: ZhipuAISession, args=None, retry_count=0) -> dict:
        """
        Call ZhipuAI API to get the answer
        :param session: a conversation session
        :param args: request arguments
        :param retry_count: retry count
        :return: {}
        """
        try:
            if args is None:
                args = self.args
            response = self.client.chat.completions.create(messages=session.messages, **args)
            # logger.debug("[ZHIPU_AI] response={}".format(response))
            # logger.info("[ZHIPU_AI] reply={}, total_tokens={}".format(response.choices[0]['message']['content'], response["usage"]["total_tokens"]))

            return {
                "total_tokens": response.usage.total_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "content": response.choices[0].message.content,
            }
        except Exception as e:
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            error_str = str(e).lower()
            
            # Check error type by error message content
            if "rate" in error_str and "limit" in error_str:
                logger.warn("[ZHIPU_AI] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif "timeout" in error_str or "timed out" in error_str:
                logger.warn("[ZHIPU_AI] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif "api" in error_str and ("error" in error_str or "gateway" in error_str):
                logger.warn("[ZHIPU_AI] APIError: {}".format(e))
                result["content"] = "请再问我一次"
                if need_retry:
                    time.sleep(10)
            elif "connection" in error_str or "network" in error_str:
                logger.warn("[ZHIPU_AI] ConnectionError: {}".format(e))
                result["content"] = "我连接不到你的网络"
                if need_retry:
                    time.sleep(5)
            else:
                logger.exception("[ZHIPU_AI] Exception: {}".format(e), e)
                need_retry = False
                self.sessions.clear_session(session.session_id)

            if need_retry:
                logger.warn("[ZHIPU_AI] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using ZhipuAI OpenAI-compatible SDK.
        Always uses glm-5v-turbo — the text models (glm-5-turbo etc.) do not support vision.
        """
        try:
            vision_model = "glm-5v-turbo"
            response = self.client.chat.completions.create(
                model=vision_model,
                max_tokens=max_tokens,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            )
            content = response.choices[0].message.content or ""
            usage = response.usage
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[ZHIPU_AI] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call ZhipuAI API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → ZhipuAI format)
        2. System prompt injection
        3. API calling with ZhipuAI SDK
        4. Tool stream support (tool_stream=True for GLM-4.7)
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response or generator for streaming
        """
        try:
            # Convert messages from Claude format to ZhipuAI format
            messages = self._convert_messages_to_zhipu_format(messages)
            
            # Convert tools from Claude format to ZhipuAI format
            if tools:
                tools = self._convert_tools_to_zhipu_format(tools)
            
            # Handle system prompt
            system_prompt = kwargs.get('system')
            if system_prompt:
                # Add system message at the beginning if not already present
                if not messages or messages[0].get('role') != 'system':
                    messages = [{"role": "system", "content": system_prompt}] + messages
                else:
                    # Replace existing system message
                    messages[0] = {"role": "system", "content": system_prompt}
            
            # Build request parameters
            request_params = {
                "model": kwargs.get("model", self.args.get("model", "glm-4")),
                "messages": messages,
                "temperature": kwargs.get("temperature", self.args.get("temperature", 0.9)),
                "top_p": kwargs.get("top_p", self.args.get("top_p", 0.7)),
                "stream": stream
            }
            
            # Add max_tokens if specified
            if kwargs.get("max_tokens"):
                request_params["max_tokens"] = kwargs["max_tokens"]
            
            # Add tools if provided
            if tools:
                request_params["tools"] = tools
                # GLM-4.7 with zai-sdk supports tool_stream for streaming tool calls
                if stream:
                    request_params["tool_stream"] = kwargs.get("tool_stream", True)
            
            # Add thinking parameter for deep thinking mode (GLM-4.7)
            thinking = kwargs.get("thinking")
            if thinking:
                request_params["thinking"] = thinking
            elif "glm-4.7" in request_params["model"]:
                # Enable thinking by default for GLM-4.7
                request_params["thinking"] = {"type": "disabled"}
            
            # Make API call with ZhipuAI SDK
            if stream:
                return self._handle_stream_response(request_params)
            else:
                return self._handle_sync_response(request_params)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[ZHIPU_AI] call_with_tools error: {error_msg}")
            if stream:
                def error_generator():
                    yield {
                        "error": True,
                        "message": error_msg,
                        "status_code": 500
                    }
                return error_generator()
            else:
                return {
                    "error": True,
                    "message": error_msg,
                    "status_code": 500
                }
    
    def _handle_sync_response(self, request_params):
        """Handle synchronous ZhipuAI API response"""
        try:
            response = self.client.chat.completions.create(**request_params)
            
            # Convert ZhipuAI response to OpenAI-compatible format
            return {
                "id": response.id,
                "object": "chat.completion",
                "created": response.created,
                "model": response.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": response.choices[0].message.role,
                        "content": response.choices[0].message.content,
                        "tool_calls": self._convert_tool_calls_to_openai_format(
                            getattr(response.choices[0].message, 'tool_calls', None)
                        )
                    },
                    "finish_reason": response.choices[0].finish_reason
                }],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
        except Exception as e:
            logger.error(f"[ZHIPU_AI] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _handle_stream_response(self, request_params):
        """Handle streaming ZhipuAI API response"""
        try:
            stream = self.client.chat.completions.create(**request_params)
            
            # Stream chunks to caller, converting to OpenAI format
            for chunk in stream:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # Convert to OpenAI-compatible format
                openai_chunk = {
                    "id": chunk.id,
                    "object": "chat.completion.chunk",
                    "created": chunk.created,
                    "model": chunk.model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": chunk.choices[0].finish_reason
                    }]
                }
                
                # Add role if present
                if hasattr(delta, 'role') and delta.role:
                    openai_chunk["choices"][0]["delta"]["role"] = delta.role
                
                # Add content if present
                if hasattr(delta, 'content') and delta.content:
                    openai_chunk["choices"][0]["delta"]["content"] = delta.content
                
                # Add reasoning_content as separate field if present (GLM-5/GLM-4.7 thinking)
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    openai_chunk["choices"][0]["delta"]["reasoning_content"] = delta.reasoning_content
                
                # Add tool_calls if present
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    # For streaming, tool_calls need special handling
                    openai_tool_calls = []
                    for tc in delta.tool_calls:
                        tool_call_dict = {
                            "index": getattr(tc, 'index', 0),
                            "id": getattr(tc, 'id', None),
                            "type": "function",
                            "function": {}
                        }
                        
                        # Add function name if present
                        if hasattr(tc, 'function') and hasattr(tc.function, 'name') and tc.function.name:
                            tool_call_dict["function"]["name"] = tc.function.name
                        
                        # Add function arguments if present
                        if hasattr(tc, 'function') and hasattr(tc.function, 'arguments') and tc.function.arguments:
                            tool_call_dict["function"]["arguments"] = tc.function.arguments
                        
                        openai_tool_calls.append(tool_call_dict)
                    
                    openai_chunk["choices"][0]["delta"]["tool_calls"] = openai_tool_calls
                
                yield openai_chunk
                
        except Exception as e:
            logger.error(f"[ZHIPU_AI] stream response error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _convert_tools_to_zhipu_format(self, tools):
        """
        Convert tools from Claude format to ZhipuAI format
        
        Claude format: {name, description, input_schema}
        ZhipuAI format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        zhipu_tools = []
        for tool in tools:
            # Check if already in ZhipuAI/OpenAI format
            if 'type' in tool and tool['type'] == 'function':
                zhipu_tools.append(tool)
            else:
                # Convert from Claude format
                zhipu_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return zhipu_tools
    
    def _convert_messages_to_zhipu_format(self, messages):
        """
        Convert messages from Claude format to ZhipuAI format
        
        Claude uses content blocks with types like 'tool_use', 'tool_result'
        ZhipuAI uses 'tool_calls' in assistant messages and 'tool' role for results
        """
        if not messages:
            return []
        
        zhipu_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # Handle string content (already in correct format)
            if isinstance(content, str):
                zhipu_messages.append(msg)
                continue
            
            # Handle list content (Claude format with content blocks)
            if isinstance(content, list):
                # Check if this is a tool result message (user role with tool_result blocks)
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # Convert each tool_result block to a separate tool message
                    for block in content:
                        if block.get("type") == "tool_result":
                            zhipu_messages.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id"),
                                "content": block.get("content", "")
                            })
                
                # Check if this is an assistant message with tool_use blocks
                elif role == "assistant":
                    # Separate text content and tool_use blocks
                    text_parts = []
                    tool_calls = []
                    
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })
                    
                    # Build ZhipuAI format assistant message
                    zhipu_msg = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None
                    }
                    
                    if tool_calls:
                        zhipu_msg["tool_calls"] = tool_calls
                    
                    zhipu_messages.append(zhipu_msg)
                else:
                    # Other list content, keep as is
                    zhipu_messages.append(msg)
            else:
                # Other formats, keep as is
                zhipu_messages.append(msg)
        
        return zhipu_messages
    
    def _convert_tool_calls_to_openai_format(self, tool_calls):
        """Convert ZhipuAI tool_calls to OpenAI format"""
        if not tool_calls:
            return None
        
        openai_tool_calls = []
        for tool_call in tool_calls:
            openai_tool_calls.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            })
        
        return openai_tool_calls
