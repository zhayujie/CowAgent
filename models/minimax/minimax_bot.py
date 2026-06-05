# encoding:utf-8

import time
import json
from typing import Optional

import requests

from models.bot import Bot
from models.minimax.minimax_session import MinimaxSession
from models.session_manager import SessionManager
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from common import const
from agent.protocol.message_utils import drop_orphaned_tool_results_openai


# MiniMax对话模型API
class MinimaxBot(Bot):
    def __init__(self):
        super().__init__()
        self.args = {
            "model": conf().get("model") or "MiniMax-M2.7",
            "temperature": conf().get("temperature", 0.3),
            "top_p": conf().get("top_p", 0.95),
        }
        self.sessions = SessionManager(MinimaxSession, model=const.MiniMax)

    @property
    def api_key(self):
        key = conf().get("minimax_api_key")
        if not key:
            key = conf().get("Minimax_api_key")
        return key

    @property
    def api_base(self):
        return conf().get("minimax_api_base", "https://api.minimaxi.com/v1")

    def reply(self, query, context: Context = None) -> Reply:
        # acquire reply content
        logger.info("[MINIMAX] query={}".format(query))
        if context.type == ContextType.TEXT:
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
            logger.debug("[MINIMAX] session query={}".format(session))

            model = context.get("Minimax_model")
            new_args = self.args.copy()
            if model:
                new_args["model"] = model

            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[MINIMAX] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[MINIMAX] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: MinimaxSession, args=None, retry_count=0) -> dict:
        """
        Call MiniMax API to get the answer using REST API
        :param session: a conversation session
        :param args: request arguments
        :param retry_count: retry count
        :return: {}
        """
        try:
            if args is None:
                args = self.args

            # Build request
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            request_body = {
                "model": args.get("model", self.args["model"]),
                "messages": session.messages,
                "temperature": args.get("temperature", self.args["temperature"]),
                "top_p": args.get("top_p", self.args["top_p"]),
            }

            url = f"{self.api_base}/chat/completions"
            logger.debug(f"[MINIMAX] Calling {url} with model={request_body['model']}")

            response = requests.post(url, headers=headers, json=request_body, timeout=60)

            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                total_tokens = result["usage"]["total_tokens"]
                completion_tokens = result["usage"]["completion_tokens"]

                logger.debug(f"[MINIMAX] reply_text: content_length={len(content)}, tokens={total_tokens}")

                return {
                    "total_tokens": total_tokens,
                    "completion_tokens": completion_tokens,
                    "content": content,
                }
            else:
                error_msg = response.text
                logger.error(f"[MINIMAX] API error: status={response.status_code}, msg={error_msg}")

                # Parse error for better messages
                result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
                need_retry = False

                if response.status_code >= 500:
                    logger.warning(f"[MINIMAX] Server error, retry={retry_count}")
                    need_retry = retry_count < 2
                elif response.status_code == 401:
                    result["content"] = "授权失败，请检查API Key是否正确"
                    need_retry = False
                elif response.status_code == 429:
                    result["content"] = "请求过于频繁，请稍后再试"
                    need_retry = retry_count < 2
                else:
                    need_retry = False

                if need_retry:
                    time.sleep(3)
                    return self.reply_text(session, args, retry_count + 1)
                else:
                    return result

        except requests.exceptions.Timeout:
            logger.error("[MINIMAX] Request timeout")
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "请求超时，请稍后再试"}
            if need_retry:
                time.sleep(3)
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result
        except Exception as e:
            logger.error(f"[MINIMAX] reply_text error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if need_retry:
                time.sleep(3)
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using MiniMax OpenAI-compatible API.
        Always uses MiniMax-Text-01 — other MiniMax models do not support vision.
        """
        try:
            vision_model = "MiniMax-Text-01"
            payload = {
                "model": vision_model,
                "max_tokens": max_tokens,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(f"{self.api_base}/chat/completions",
                                 headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            if "error" in data:
                return {"error": True, "message": data["error"].get("message", str(data["error"]))}
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[MINIMAX] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call MiniMax API with tool support for agent integration

        This method handles:
        1. Format conversion (Claude format → OpenAI format)
        2. System prompt injection
        3. API calling with REST API
        4. Interleaved Thinking support (reasoning_split=True)

        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)

        Returns:
            Formatted response or generator for streaming
        """
        try:
            # Convert messages from Claude format to OpenAI format
            converted_messages = self._convert_messages_to_openai_format(messages)

            # Extract and inject system prompt if provided
            system_prompt = kwargs.pop("system", None)
            if system_prompt:
                # Add system message at the beginning
                converted_messages.insert(0, {"role": "system", "content": system_prompt})

            # Convert tools from Claude format to OpenAI format
            converted_tools = None
            if tools:
                converted_tools = self._convert_tools_to_openai_format(tools)

            # Prepare API parameters
            model = kwargs.pop("model", None) or self.args["model"]
            max_tokens = kwargs.pop("max_tokens", 100000)
            temperature = kwargs.pop("temperature", self.args["temperature"])

            # Build request body
            request_body = {
                "model": model,
                "messages": converted_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": stream,
            }

            # Add tools if provided
            if converted_tools:
                request_body["tools"] = converted_tools

            # Add reasoning_split=True for better thinking control (M2.1 feature)
            # This separates thinking content into reasoning_details field
            request_body["reasoning_split"] = True

            logger.debug(f"[MINIMAX] API call: model={model}, tools={len(converted_tools) if converted_tools else 0}, stream={stream}")

            if stream:
                return self._handle_stream_response(request_body)
            else:
                return self._handle_sync_response(request_body)

        except Exception as e:
            logger.error(f"[MINIMAX] call_with_tools error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            def error_generator():
                yield {"error": True, "message": str(e), "status_code": 500}
            return error_generator()

    def _convert_messages_to_openai_format(self, messages):
        """
        Convert messages from Claude format to OpenAI format

        Claude format:
        - role: "user" | "assistant"
        - content: string | list of content blocks

        OpenAI format:
        - role: "user" | "assistant" | "tool"
        - content: string
        - tool_calls: list (for assistant)
        - tool_call_id: string (for tool results)
        """
        converted = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "user":
                # Handle user message
                if isinstance(content, list):
                    has_tool_result = any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                    )
                    if has_tool_result:
                        text_parts = []
                        tool_results = []

                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                                elif block.get("type") == "tool_result":
                                    tool_call_id = block.get("tool_use_id") or ""
                                    if not tool_call_id:
                                        logger.warning(f"[MINIMAX] tool_result missing tool_use_id")
                                    result_content = block.get("content", "")
                                    if not isinstance(result_content, str):
                                        result_content = json.dumps(result_content, ensure_ascii=False)
                                    tool_results.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "content": result_content
                                    })

                        if text_parts:
                            converted.append({
                                "role": "user",
                                "content": "\n".join(text_parts)
                            })

                        for tool_result in tool_results:
                            converted.append(tool_result)
                    else:
                        # Keep as-is for multimodal content (e.g. image_url blocks)
                        converted.append(msg)
                else:
                    # Simple text content
                    converted.append({
                        "role": "user",
                        "content": str(content)
                    })

            elif role == "assistant":
                # Handle assistant message
                openai_msg = {"role": "assistant"}

                if isinstance(content, list):
                    # Parse content blocks
                    text_parts = []
                    tool_calls = []

                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                # Convert to OpenAI tool_calls format
                                tool_calls.append({
                                    "id": block.get("id"),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name"),
                                        "arguments": json.dumps(block.get("input", {}))
                                    }
                                })

                    # Set content (can be empty if only tool calls)
                    if text_parts:
                        openai_msg["content"] = "\n".join(text_parts)
                    elif not tool_calls:
                        openai_msg["content"] = ""

                    # Set tool_calls
                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls
                        # When tool_calls exist and content is empty, set to None
                        if not text_parts:
                            openai_msg["content"] = None

                else:
                    # Simple text content
                    openai_msg["content"] = str(content) if content else ""

                converted.append(openai_msg)

        return drop_orphaned_tool_results_openai(converted)

    def _convert_tools_to_openai_format(self, tools):
        """
        Convert tools from Claude format to OpenAI format

        Claude format:
        {
            "name": "tool_name",
            "description": "description",
            "input_schema": {...}
        }

        OpenAI format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "description",
                "parameters": {...}
            }
        }
        """
        converted = []

        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "parameters": tool.get("input_schema", {})
                }
            })

        return converted

    def _handle_sync_response(self, request_body):
        """Handle synchronous API response"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            # Remove stream from body for sync request
            request_body.pop("stream", None)

            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, timeout=60)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MINIMAX] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            result = response.json()
            message = result["choices"][0]["message"]
            finish_reason = result["choices"][0]["finish_reason"]

            # Build response in Claude-like format
            response_data = {
                "role": "assistant",
                "content": []
            }

            # Add reasoning_details (thinking) if present
            if "reasoning_details" in message:
                for reasoning in message["reasoning_details"]:
                    if "text" in reasoning:
                        response_data["content"].append({
                            "type": "thinking",
                            "thinking": reasoning["text"]
                        })

            # Add text content if present
            if message.get("content"):
                response_data["content"].append({
                    "type": "text",
                    "text": message["content"]
                })

            # Add tool calls if present
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    response_data["content"].append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": json.loads(tool_call["function"]["arguments"])
                    })

            # Set stop_reason
            if finish_reason == "tool_calls":
                response_data["stop_reason"] = "tool_use"
            elif finish_reason == "stop":
                response_data["stop_reason"] = "end_turn"
            else:
                response_data["stop_reason"] = finish_reason

            yield response_data

        except requests.exceptions.Timeout:
            logger.error("[MINIMAX] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MINIMAX] sync response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}

    def _handle_stream_response(self, request_body):
        """Handle streaming API response

        Args:
            request_body: API request parameters
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            url = f"{self.api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=request_body, stream=True, timeout=60)

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[MINIMAX] API error: status={response.status_code}, msg={error_msg}")
                yield {"error": True, "message": error_msg, "status_code": response.status_code}
                return

            current_content = []
            current_tool_calls = {}
            current_reasoning = []
            finish_reason = None
            chunk_count = 0

            # Process SSE stream
            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode('utf-8')
                if not line.startswith('data: '):
                    continue

                data_str = line[6:]  # Remove 'data: ' prefix
                if data_str.strip() == '[DONE]':
                    break

                try:
                    chunk = json.loads(data_str)
                    chunk_count += 1
                except json.JSONDecodeError as e:
                    logger.warning(f"[MINIMAX] JSON decode error: {e}, data: {data_str[:100]}")
                    continue

                # Check for error response (MiniMax format)
                if chunk.get("type") == "error" or "error" in chunk:
                    error_data = chunk.get("error", {})
                    error_msg = error_data.get("message", "Unknown error")
                    error_type = error_data.get("type", "")
                    http_code = error_data.get("http_code", "")
                    
                    logger.error(f"[MINIMAX] API error: {error_msg} (type: {error_type}, code: {http_code})")
                    
                    yield {
                        "error": True,
                        "message": error_msg,
                        "status_code": int(http_code) if http_code.isdigit() else 500
                    }
                    return

                if not chunk.get("choices"):
                    continue

                choice = chunk["choices"][0]
                delta = choice.get("delta", {})

                # Handle reasoning_details (thinking)
                if "reasoning_details" in delta:
                    for reasoning in delta["reasoning_details"]:
                        if "text" in reasoning:
                            reasoning_id = reasoning.get("id", "reasoning-text-1")
                            reasoning_index = reasoning.get("index", 0)
                            reasoning_text = reasoning["text"]

                            # Accumulate reasoning text
                            if reasoning_index >= len(current_reasoning):
                                current_reasoning.append({"id": reasoning_id, "text": ""})

                            current_reasoning[reasoning_index]["text"] += reasoning_text

                            yield {
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "reasoning_content": reasoning_text
                                    }
                                }]
                            }

                # Handle text content
                if "content" in delta and delta["content"]:
                    # Start new content block if needed
                    if not any(block.get("type") == "text" for block in current_content):
                        current_content.append({"type": "text", "text": ""})

                    # Accumulate text
                    for block in current_content:
                        if block.get("type") == "text":
                            block["text"] += delta["content"]
                            break

                    # Yield OpenAI-format delta (for agent_stream.py compatibility)
                    yield {
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": delta["content"]
                            }
                        }]
                    }

                # Handle tool calls
                if "tool_calls" in delta:
                    for tool_call_chunk in delta["tool_calls"]:
                        index = tool_call_chunk.get("index", 0)
                        if index not in current_tool_calls:
                            # Start new tool call
                            current_tool_calls[index] = {
                                "id": tool_call_chunk.get("id", ""),
                                "type": "tool_use",
                                "name": tool_call_chunk.get("function", {}).get("name", ""),
                                "input": ""
                            }
                        
                        # Accumulate tool call arguments
                        if "function" in tool_call_chunk and "arguments" in tool_call_chunk["function"]:
                            current_tool_calls[index]["input"] += tool_call_chunk["function"]["arguments"]

                        # Yield OpenAI-format tool call delta
                        yield {
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "tool_calls": [tool_call_chunk]
                                }
                            }]
                        }

                # Handle finish_reason
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

            # Log complete reasoning_details for debugging
            if current_reasoning:
                logger.debug(f"[MINIMAX] ===== Complete Reasoning Details =====")
                for i, reasoning in enumerate(current_reasoning):
                    reasoning_text = reasoning.get("text", "")
                    logger.debug(f"[MINIMAX] Reasoning {i+1} (length={len(reasoning_text)}):")
                    logger.debug(f"[MINIMAX] {reasoning_text}")
                logger.debug(f"[MINIMAX] ===== End Reasoning Details =====")

            # Yield final chunk with finish_reason (OpenAI format)
            yield {
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason
                }]
            }

        except requests.exceptions.Timeout:
            logger.error("[MINIMAX] Request timeout")
            yield {"error": True, "message": "Request timeout", "status_code": 500}
        except Exception as e:
            logger.error(f"[MINIMAX] stream response error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"error": True, "message": str(e), "status_code": 500}
