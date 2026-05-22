"""
Google gemini bot

@author zhayujie
@Date 2023/12/15
"""
# encoding:utf-8

import base64
import json
import mimetypes
import os
import re
import time
from typing import Optional

import requests
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType, Context
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from models.chatgpt.chat_gpt_session import ChatGPTSession
from models.baidu.baidu_wenxin_session import BaiduWenxinSession


# OpenAI对话模型API (可用)
class GoogleGeminiBot(Bot):

    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(ChatGPTSession, model=conf().get("model") or "gpt-3.5-turbo")

    @property
    def api_key(self):
        return conf().get("gemini_api_key")

    @property
    def model(self):
        model_name = conf().get("model") or "gemini-3.1-pro-preview"
        if model_name == "gemini":
            model_name = "gemini-3.1-pro-preview"
        return model_name

    @property
    def api_base(self):
        base = conf().get("gemini_api_base", "").strip()
        if base:
            return base.rstrip('/')
        return "https://generativelanguage.googleapis.com"

    def reply(self, query, context: Context = None) -> Reply:
        session_id = None
        try:
            if context.type != ContextType.TEXT:
                logger.warn(f"[Gemini] Unsupported message type, type={context.type}")
                return Reply(ReplyType.TEXT, None)
            logger.info(f"[Gemini] query={query}")
            session_id = context["session_id"]
            session = self.sessions.session_query(query, session_id)
            filtered_messages = self.filter_messages(session.messages)
            logger.debug(f"[Gemini] messages={filtered_messages}")

            response = self.call_with_tools(
                messages=filtered_messages,
                tools=None,
                stream=False,
                model=self.model
            )

            if isinstance(response, dict) and response.get("error"):
                error_message = response.get("message", "Failed to invoke [Gemini] api!")
                logger.error(f"[Gemini] API error: {error_message}")
                self.sessions.session_reply(error_message, session_id)
                return Reply(ReplyType.ERROR, error_message)

            choices = response.get("choices", []) if isinstance(response, dict) else []
            if choices and choices[0].get("message"):
                reply_text = choices[0]["message"].get("content")
                if reply_text:
                    logger.info(f"[Gemini] reply={reply_text}")
                    self.sessions.session_reply(reply_text, session_id)
                    return Reply(ReplyType.TEXT, reply_text)

            logger.warning("[Gemini] No valid response generated. Checking safety ratings.")
            safety_ratings = response.get("safety_ratings", []) if isinstance(response, dict) else []
            if safety_ratings:
                for rating in safety_ratings:
                    category = rating.get("category", "UNKNOWN")
                    probability = rating.get("probability", "UNKNOWN")
                    logger.warning(f"[Gemini] Safety rating: {category} - {probability}")

            error_message = "No valid response generated due to safety constraints."
            self.sessions.session_reply(error_message, session_id)
            return Reply(ReplyType.ERROR, error_message)
                    
        except Exception as e:
            logger.error(f"[Gemini] Error generating response: {str(e)}", exc_info=True)
            error_message = "Failed to invoke [Gemini] api!"
            if session_id:
                self.sessions.session_reply(error_message, session_id)
            return Reply(ReplyType.ERROR, error_message)
            
    def _convert_to_gemini_messages(self, messages: list):
        res = []
        for msg in messages:
            if msg.get("role") == "user":
                role = "user"
            elif msg.get("role") == "assistant":
                role = "model"
            elif msg.get("role") == "system":
                role = "user"
            else:
                continue
            res.append({
                "role": role,
                "parts": [{"text": msg.get("content")}]
            })
        return res

    @staticmethod
    def filter_messages(messages: list):
        res = []
        turn = "user"
        if not messages:
            return res
        for i in range(len(messages) - 1, -1, -1):
            message = messages[i]
            role = message.get("role")
            if role == "system":
                res.insert(0, message)
                continue
            if role != turn:
                continue
            res.insert(0, message)
            if turn == "user":
                turn = "assistant"
            elif turn == "assistant":
                turn = "user"
        return res

    @staticmethod
    def _extract_image_paths_from_text(content: str):
        if not isinstance(content, str):
            return "", []
        pattern = r"\[图片:\s*([^\]]+)\]"
        image_paths = [m.strip().strip("'\"") for m in re.findall(pattern, content) if m.strip()]
        # Replace markers with path-only hints so the model still knows the
        # original file location (needed when it calls tools like vision).
        def _replace_with_hint(m):
            path = m.group(1).strip().strip("'\"")
            return f"[attached image: {path}]"
        cleaned_text = re.sub(pattern, _replace_with_hint, content)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
        return cleaned_text, image_paths

    @staticmethod
    def _build_image_inline_part(image_path: str):
        if not image_path:
            return None
        try:
            if image_path.startswith("file://"):
                image_path = image_path[7:]

            image_path = os.path.expanduser(image_path)
            if not os.path.exists(image_path):
                logger.warning(f"[Gemini] Image file not found: {image_path}")
                return None

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
            if not mime_type.startswith("image/"):
                mime_type = "image/png"

            return {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(image_bytes).decode("utf-8")
                }
            }
        except Exception as e:
            logger.warning(f"[Gemini] Failed to build inline image part from path={image_path}, err={e}")
            return None

    @staticmethod
    def _build_inline_part_from_image_url(image_url):
        if not image_url:
            return None

        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if not image_url or not isinstance(image_url, str):
            return None

        if image_url.startswith("data:"):
            match = re.match(r"^data:([^;]+);base64,(.+)$", image_url, re.DOTALL)
            if not match:
                logger.warning("[Gemini] Invalid data URL for image block")
                return None
            return {
                "inlineData": {
                    "mimeType": match.group(1),
                    "data": match.group(2).strip()
                }
            }

        if image_url.startswith("file://") or os.path.exists(os.path.expanduser(image_url)):
            return GoogleGeminiBot._build_image_inline_part(image_url)

        if image_url.startswith("http://") or image_url.startswith("https://"):
            try:
                response = requests.get(image_url, timeout=20)
                if response.status_code != 200:
                    logger.warning(f"[Gemini] Failed to fetch remote image: status={response.status_code}, url={image_url}")
                    return None
                mime_type = response.headers.get("Content-Type", "image/png").split(";")[0].strip()
                if not mime_type.startswith("image/"):
                    mime_type = "image/png"
                return {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(response.content).decode("utf-8")
                    }
                }
            except Exception as e:
                logger.warning(f"[Gemini] Failed to download remote image: url={image_url}, err={e}")
                return None

        logger.warning(f"[Gemini] Unsupported image URL format: {image_url[:120]}")
        return None

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using Gemini REST API."""
        try:
            model_name = model or self.model or "gemini-2.0-flash"
            image_part = self._build_inline_part_from_image_url({"url": image_url})
            if not image_part:
                return {"error": True, "message": f"Cannot process image URL: {image_url[:120]}"}

            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [image_part, {"text": question}],
                }],
                "generationConfig": {"maxOutputTokens": max_tokens},
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            }
            endpoint = f"{self.api_base}/v1beta/models/{model_name}:generateContent"
            headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)

            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

            body = resp.json()
            candidates = body.get("candidates", [])
            text_parts = []
            for part in candidates[0].get("content", {}).get("parts", []) if candidates else []:
                if "text" in part:
                    text_parts.append(part["text"])

            usage_meta = body.get("usageMetadata", {})
            return {
                "model": model_name,
                "content": "".join(text_parts),
                "usage": {
                    "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                    "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                    "total_tokens": usage_meta.get("totalTokenCount", 0),
                },
            }
        except Exception as e:
            logger.error(f"[Gemini] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call Gemini API with tool support using REST API (following official docs)
        
        Args:
            messages: List of messages (OpenAI format)
            tools: List of tool definitions (OpenAI/Claude format)
            stream: Whether to use streaming
            **kwargs: Additional parameters (system, max_tokens, temperature, etc.)
            
        Returns:
            Formatted response compatible with OpenAI format or generator for streaming
        """
        try:
            model_name = kwargs.get("model", self.model or "gemini-1.5-flash")
            
            # Build REST API payload
            payload = {"contents": []}
            inline_image_count = 0

            # Keep legacy behavior: disable Gemini safety blocking like old SDK path.
            payload["safetySettings"] = [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
            
            # Extract and set system instruction
            system_prompt = kwargs.get("system", "")
            if not system_prompt:
                for msg in messages:
                    if msg.get("role") == "system":
                        system_prompt = msg["content"]
                        break
            
            if system_prompt:
                payload["system_instruction"] = {
                    "parts": [{"text": system_prompt}]
                }
            
            # Convert messages to Gemini format
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                
                if role == "system":
                    continue
                
                # Convert role
                gemini_role = "user" if role in ["user", "tool"] else "model"
                
                # For model messages that carry original Gemini parts (with
                # thoughtSignature etc.), use them directly instead of
                # reconstructing from Claude-format tool_use blocks.
                if gemini_role == "model" and "_gemini_raw_parts" in msg:
                    raw_parts = msg["_gemini_raw_parts"]
                    if raw_parts:
                        payload["contents"].append({
                            "role": "model",
                            "parts": raw_parts
                        })
                        continue
                
                # Handle different content formats
                parts = []
                
                if isinstance(content, str):
                    # Text with optional [图片: /path/to/file] markers
                    cleaned_text, image_paths = self._extract_image_paths_from_text(content)
                    if cleaned_text:
                        parts.append({"text": cleaned_text})
                    image_added = False
                    for image_path in image_paths:
                        image_part = self._build_image_inline_part(image_path)
                        if image_part:
                            parts.append(image_part)
                            image_added = True
                            inline_image_count += 1
                    if not cleaned_text and not image_added and content:
                        parts.append({"text": content})
                    
                elif isinstance(content, list):
                    # List of content blocks (Claude format)
                    for block in content:
                        if not isinstance(block, dict):
                            if isinstance(block, str):
                                parts.append({"text": block})
                            continue
                        
                        block_type = block.get("type")
                        
                        if block_type == "text":
                            # Text block with optional image markers
                            block_text = block.get("text", "")
                            cleaned_text, image_paths = self._extract_image_paths_from_text(block_text)
                            if cleaned_text:
                                parts.append({"text": cleaned_text})
                            for image_path in image_paths:
                                image_part = self._build_image_inline_part(image_path)
                                if image_part:
                                    parts.append(image_part)

                        elif block_type in ["image", "image_url"]:
                            # OpenAI format: {"type":"image_url","image_url":{"url":"..."}}
                            # Claude format: {"type":"image","source":{"type":"base64","media_type":"...","data":"..."}}
                            image_part = None
                            if block_type == "image":
                                source = block.get("source", {})
                                if isinstance(source, dict) and source.get("type") == "base64" and source.get("data"):
                                    image_part = {
                                        "inlineData": {
                                            "mimeType": source.get("media_type", "image/png"),
                                            "data": source.get("data")
                                        }
                                    }
                                elif block.get("image_url"):
                                    image_part = self._build_inline_part_from_image_url(block.get("image_url"))
                            else:
                                image_part = self._build_inline_part_from_image_url(block.get("image_url"))

                            if image_part:
                                parts.append(image_part)
                                inline_image_count += 1
                            else:
                                logger.warning(f"[Gemini] Skip invalid image block: {str(block)[:200]}")
                            
                        elif block_type == "tool_use":
                            # Convert Claude tool_use to Gemini functionCall
                            fc_name = block.get("name", "unknown")
                            fc_args = block.get("input") or {}
                            parts.append({
                                "functionCall": {
                                    "name": fc_name,
                                    "args": fc_args
                                }
                            })

                        elif block_type == "tool_result":
                            # Convert Claude tool_result to Gemini functionResponse
                            tool_use_id = block.get("tool_use_id")
                            tool_content = block.get("content", "")
                            
                            # Try to parse tool content as JSON
                            try:
                                if isinstance(tool_content, str):
                                    tool_result_data = json.loads(tool_content)
                                else:
                                    tool_result_data = tool_content
                            except Exception:
                                tool_result_data = {"result": tool_content}
                            
                            # Find the tool name from previous messages
                            tool_name = None
                            for prev_msg in reversed(messages):
                                if prev_msg.get("role") == "assistant":
                                    prev_content = prev_msg.get("content", [])
                                    if isinstance(prev_content, list):
                                        for prev_block in prev_content:
                                            if isinstance(prev_block, dict) and prev_block.get("type") == "tool_use":
                                                if prev_block.get("id") == tool_use_id:
                                                    tool_name = prev_block.get("name")
                                                    break
                                    if tool_name:
                                        break
                            
                            # Gemini functionResponse format (Gemini 3 requires `id`)
                            fn_response = {
                                "name": tool_name or "unknown",
                                "response": tool_result_data
                            }
                            if tool_use_id:
                                fn_response["id"] = tool_use_id
                            parts.append({"functionResponse": fn_response})
                            
                        elif "text" in block:
                            # Generic text field
                            parts.append({"text": block["text"]})
                
                if parts:
                    payload["contents"].append({
                        "role": gemini_role,
                        "parts": parts
                    })

            if inline_image_count > 0:
                logger.info(f"[Gemini] Multimodal request includes {inline_image_count} image part(s)")
            
            # Generation config
            gen_config = {}
            if kwargs.get("temperature") is not None:
                gen_config["temperature"] = kwargs["temperature"]

            if gen_config:
                payload["generationConfig"] = gen_config
            
            # Convert tools to Gemini format (REST API style)
            if tools:
                gemini_tools = self._convert_tools_to_gemini_rest_format(tools)
                if gemini_tools:
                    payload["tools"] = gemini_tools
            
            # Make REST API call
            base_url = f"{self.api_base}/v1beta"
            endpoint = f"{base_url}/models/{model_name}:generateContent"
            if stream:
                endpoint = f"{base_url}/models/{model_name}:streamGenerateContent?alt=sse"
            
            headers = {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                stream=stream,
                timeout=60
            )
            
            # Check HTTP status for stream mode (for non-stream, it's checked in handler)
            if stream and response.status_code != 200:
                error_text = response.text
                logger.error(f"[Gemini] API error ({response.status_code}): {error_text}")
                def error_generator():
                    yield {
                        "error": True,
                        "message": f"Gemini API error: {error_text}",
                        "status_code": response.status_code
                    }
                return error_generator()
            
            if stream:
                return self._handle_gemini_rest_stream_response(response, model_name)
            else:
                return self._handle_gemini_rest_sync_response(response, model_name)
                
        except Exception as e:
            logger.error(f"[Gemini] call_with_tools error: {e}", exc_info=True)
            error_msg = str(e)  # Capture error message before creating generator
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
                    "message": str(e),
                    "status_code": 500
                }
    
    def _convert_tools_to_gemini_rest_format(self, tools_list):
        """
        Convert tools to Gemini REST API format
        
        Handles both OpenAI and Claude/Agent formats.
        Returns: [{"functionDeclarations": [...]}]
        """
        function_declarations = []
        
        for tool in tools_list:
            # Extract name, description, and parameters based on format
            if tool.get("type") == "function":
                # OpenAI format: {"type": "function", "function": {...}}
                func = tool.get("function", {})
                name = func.get("name")
                description = func.get("description", "")
                parameters = func.get("parameters", {})
            else:
                # Claude/Agent format: {"name": "...", "description": "...", "input_schema": {...}}
                name = tool.get("name")
                description = tool.get("description", "")
                parameters = tool.get("input_schema", {})
            
            if not name:
                logger.warning(f"[Gemini] Skipping tool without name: {tool}")
                continue
            
            function_declarations.append({
                "name": name,
                "description": description,
                "parameters": parameters
            })
        
        # All functionDeclarations must be in a single tools object (per Gemini REST API spec)
        return [{
            "functionDeclarations": function_declarations
        }] if function_declarations else []
    
    def _handle_gemini_rest_sync_response(self, response, model_name):
        """Handle Gemini REST API sync response and convert to OpenAI format"""
        try:
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"[Gemini] API error ({response.status_code}): {error_text}")
                return {
                    "error": True,
                    "message": f"Gemini API error: {error_text}",
                    "status_code": response.status_code
                }
            
            data = response.json()
            logger.debug(f"[Gemini] Response data: {json.dumps(data, ensure_ascii=False)[:500]}")
            
            # Extract from Gemini response format
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("[Gemini] No candidates in response")
                prompt_feedback = data.get("promptFeedback", {})
                return {
                    "error": True,
                    "message": "No candidates in response",
                    "status_code": 500,
                    "safety_ratings": prompt_feedback.get("safetyRatings", [])
                }
            
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            safety_ratings = candidate.get("safetyRatings", [])
            
            logger.debug(f"[Gemini] Candidate parts count: {len(parts)}")
            
            # Extract text and function calls
            text_content = ""
            tool_calls = []
            
            for part in parts:
                # Check for text
                if "text" in part:
                    text_content += part["text"]
                    logger.debug(f"[Gemini] Text part: {part['text'][:100]}...")
                
                # Check for functionCall (per REST API docs)
                if "functionCall" in part:
                    fc = part["functionCall"]
                    fc_id = fc.get("id") or f"call_{int(time.time() * 1000000)}"
                    logger.info(f"[Gemini] Function call detected: {fc.get('name')} (id={fc_id})")
                    
                    tool_calls.append({
                        "id": fc_id,
                        "type": "function",
                        "function": {
                            "name": fc.get("name"),
                            "arguments": json.dumps(fc.get("args", {}))
                        }
                    })
            
            logger.info(f"[Gemini] Response: text={len(text_content)} chars, tool_calls={len(tool_calls)}")
            
            # Build OpenAI format response
            message_dict = {
                "role": "assistant",
                "content": text_content or None
            }
            if tool_calls:
                message_dict["tool_calls"] = tool_calls
            
            return {
                "id": f"chatcmpl-{time.time()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": message_dict,
                    "finish_reason": "tool_calls" if tool_calls else "stop"
                }],
                "usage": data.get("usageMetadata", {}),
                "safety_ratings": safety_ratings
            }
            
        except Exception as e:
            logger.error(f"[Gemini] sync response error: {e}", exc_info=True)
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _handle_gemini_rest_stream_response(self, response, model_name):
        """Handle Gemini REST API stream response"""
        try:
            all_tool_calls = []
            all_raw_parts = []  # Preserve all Gemini parts (incl. thoughtSignature) for round-trip
            has_sent_tool_calls = False
            has_content = False  # Track if any content was sent
            chunk_count = 0
            last_finish_reason = None
            last_safety_ratings = None
            raw_chunks = []  # Buffer raw chunks for diagnostics on empty response
            non_text_part_keys = []  # Track non-text/functionCall part keys (e.g. thoughtSignature)
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                line = line.decode('utf-8')
                
                # Skip SSE prefixes
                if line.startswith('data: '):
                    line = line[6:]
                
                if not line or line == '[DONE]':
                    continue
                
                try:
                    chunk_data = json.loads(line)
                    chunk_count += 1
                    raw_chunks.append(chunk_data)
                    
                    candidates = chunk_data.get("candidates", [])
                    if not candidates:
                        # Could be a chunk with only usageMetadata / promptFeedback
                        prompt_feedback = chunk_data.get("promptFeedback")
                        if prompt_feedback:
                            logger.warning(f"[Gemini] promptFeedback in chunk: {prompt_feedback}")
                        else:
                            logger.debug(f"[Gemini] No candidates in chunk: {chunk_data}")
                        continue
                    
                    candidate = candidates[0]
                    
                    # 记录 finish_reason 和 safety_ratings
                    if "finishReason" in candidate:
                        last_finish_reason = candidate["finishReason"]
                    if "safetyRatings" in candidate:
                        last_safety_ratings = candidate["safetyRatings"]
                    
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    
                    if not parts:
                        logger.debug(f"[Gemini] No parts in candidate content, candidate={candidate}")
                    
                    # Stream text content
                    for part in parts:
                        # Track unknown part types for diagnostics
                        if "text" not in part and "functionCall" not in part:
                            for k in part.keys():
                                if k not in non_text_part_keys:
                                    non_text_part_keys.append(k)

                        if "text" in part and part["text"]:
                            has_content = True
                            yield {
                                "id": f"chatcmpl-{time.time()}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": part["text"]},
                                    "finish_reason": None
                                }]
                            }
                        
                        # Collect function calls
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            logger.info(f"[Gemini] Function call: {fc.get('name')} (id={fc.get('id')})")
                            # Prefer Gemini's native id; fall back to generated one
                            fc_id = fc.get("id") or f"call_{int(time.time() * 1000000)}_{len(all_tool_calls)}"
                            all_tool_calls.append({
                                "index": len(all_tool_calls),
                                "id": fc_id,
                                "type": "function",
                                "function": {
                                    "name": fc.get("name"),
                                    "arguments": json.dumps(fc.get("args", {}))
                                }
                            })

                    # Preserve all raw parts for round-trip (thoughtSignature, etc.)
                    all_raw_parts.extend(parts)
                    
                except json.JSONDecodeError as je:
                    logger.debug(f"[Gemini] JSON decode error: {je}, line={line[:500]}")
                    continue
            
            # Send tool calls if any were collected
            if all_tool_calls and not has_sent_tool_calls:
                delta = {"tool_calls": all_tool_calls}
                if all_raw_parts:
                    delta["_gemini_raw_parts"] = all_raw_parts
                yield {
                    "id": f"chatcmpl-{time.time()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None
                    }]
                }
                has_sent_tool_calls = True
            elif not has_sent_tool_calls and all_raw_parts:
                # No tool calls but we have raw parts (e.g. text-only response with
                # thoughtSignature) — pass them through for round-trip fidelity.
                yield {
                    "id": f"chatcmpl-{time.time()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"_gemini_raw_parts": all_raw_parts},
                        "finish_reason": None
                    }]
                }
            
            # 如果返回空响应，dump 完整原始 chunks 以便诊断
            if not has_content and not all_tool_calls:
                logger.warning(
                    f"[Gemini] ⚠️  Empty response detected! "
                    f"chunks={chunk_count}, finish_reason={last_finish_reason}, "
                    f"non_text_part_keys={non_text_part_keys}"
                )
                if last_safety_ratings:
                    logger.warning(f"[Gemini] safetyRatings: {last_safety_ratings}")
                # Dump raw chunks (truncate each to avoid huge logs)
                try:
                    for i, ch in enumerate(raw_chunks):
                        ch_str = json.dumps(ch, ensure_ascii=False)
                        if len(ch_str) > 2000:
                            ch_str = ch_str[:2000] + f"...[truncated, total {len(ch_str)} chars]"
                        logger.warning(f"[Gemini] raw chunk[{i}]: {ch_str}")
                except Exception as dump_err:
                    logger.warning(f"[Gemini] Failed to dump raw chunks: {dump_err}")
            
            # Final chunk
            yield {
                "id": f"chatcmpl-{time.time()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "tool_calls" if all_tool_calls else "stop"
                }]
            }
                    
        except Exception as e:
            logger.error(f"[Gemini] stream response error: {e}", exc_info=True)
            error_msg = str(e)
            yield {
                "error": True,
                "message": error_msg,
                "status_code": 500
            }
    
    def _convert_tools_to_gemini_format(self, openai_tools):
        """Convert OpenAI tool format to Gemini function declarations"""
        import google.generativeai as genai
        
        gemini_functions = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                gemini_functions.append(
                    genai.protos.FunctionDeclaration(
                        name=func.get("name"),
                        description=func.get("description", ""),
                        parameters=func.get("parameters", {})
                    )
                )
        
        if gemini_functions:
            return [genai.protos.Tool(function_declarations=gemini_functions)]
        return None
    
    def _handle_gemini_sync_response(self, model, messages, request_params, model_name):
        """Handle synchronous Gemini API response"""
        import json
        
        response = model.generate_content(messages, **request_params)
        
        # Extract text content and function calls
        text_content = ""
        tool_calls = []
        
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    text_content += part.text
                elif hasattr(part, 'function_call') and part.function_call:
                    # Convert Gemini function call to OpenAI format
                    func_call = part.function_call
                    tool_calls.append({
                        "id": f"call_{hash(func_call.name)}",
                        "type": "function",
                        "function": {
                            "name": func_call.name,
                            "arguments": json.dumps(dict(func_call.args))
                        }
                    })
        
        # Build message in OpenAI format
        message = {
            "role": "assistant",
            "content": text_content
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        
        # Format response to match OpenAI structure
        formatted_response = {
            "id": f"gemini_{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "stop" if not tool_calls else "tool_calls"
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # Gemini doesn't provide token counts in the same way
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        
        logger.info(f"[Gemini] call_with_tools reply, model={model_name}")
        return formatted_response
    
    def _handle_gemini_stream_response(self, model, messages, request_params, model_name):
        """Handle streaming Gemini API response"""
        import json
        
        try:
            response_stream = model.generate_content(messages, stream=True, **request_params)
            
            for chunk in response_stream:
                if chunk.candidates and chunk.candidates[0].content:
                    for part in chunk.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            # Text content
                            yield {
                                "id": f"gemini_{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": part.text},
                                    "finish_reason": None
                                }]
                            }
                        elif hasattr(part, 'function_call') and part.function_call:
                            # Function call
                            func_call = part.function_call
                            yield {
                                "id": f"gemini_{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": 0,
                                            "id": f"call_{hash(func_call.name)}",
                                            "type": "function",
                                            "function": {
                                                "name": func_call.name,
                                                "arguments": json.dumps(dict(func_call.args))
                                            }
                                        }]
                                    },
                                    "finish_reason": None
                                }]
                            }
                            
        except Exception as e:
            logger.error(f"[Gemini] stream response error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
