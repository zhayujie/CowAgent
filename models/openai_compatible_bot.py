# encoding:utf-8

"""
OpenAI-Compatible Bot Base Class

Provides a common implementation for bots that are compatible with OpenAI's API format.
This includes: OpenAI, LinkAI, Azure OpenAI, and many third-party providers.
"""

import json
import requests
from typing import Optional
from common.log import logger
from agent.protocol.message_utils import drop_orphaned_tool_results_openai
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError


class OpenAICompatibleBot:
    """
    Base class for OpenAI-compatible bots.
    
    Provides common tool calling implementation that can be inherited by:
    - ChatGPTBot
    - LinkAIBot  
    - OpenAIBot
    - AzureChatGPTBot
    - Other OpenAI-compatible providers
    
    Subclasses only need to override get_api_config() to provide their specific API settings.
    """
    
    def get_api_config(self):
        """
        Get API configuration for this bot.
        
        Subclasses should override this to provide their specific config.
        
        Returns:
            dict: {
                'api_key': str,
                'api_base': str (optional),
                'model': str,
                'default_temperature': float,
                'default_top_p': float,
                'default_frequency_penalty': float,
                'default_presence_penalty': float,
            }
        """
        raise NotImplementedError("Subclasses must implement get_api_config()")
    
    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call OpenAI-compatible API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → OpenAI format)
        2. System prompt injection
        3. API calling with proper configuration
        4. Error handling
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response in OpenAI format or generator for streaming
        """
        try:
            # Get API configuration from subclass
            api_config = self.get_api_config()
            
            # Convert messages from Claude format to OpenAI format
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
            
            # Build request parameters
            request_params = {
                "model": kwargs.get("model", api_config.get('model', 'gpt-3.5-turbo')),
                "messages": messages,
                "temperature": kwargs.get("temperature", api_config.get('default_temperature', 0.9)),
                "top_p": kwargs.get("top_p", api_config.get('default_top_p', 1.0)),
                "frequency_penalty": kwargs.get("frequency_penalty", api_config.get('default_frequency_penalty', 0.0)),
                "presence_penalty": kwargs.get("presence_penalty", api_config.get('default_presence_penalty', 0.0)),
                "stream": stream
            }
            
            # Add max_tokens if specified
            if kwargs.get("max_tokens"):
                request_params["max_tokens"] = kwargs["max_tokens"]
            
            # Add tools if provided
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = kwargs.get("tool_choice", "auto")
            
            # Make API call with proper configuration
            api_key = api_config.get('api_key')
            api_base = api_config.get('api_base')
            
            if stream:
                return self._handle_stream_response(request_params, api_key, api_base)
            else:
                return self._handle_sync_response(request_params, api_key, api_base)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{self.__class__.__name__}] call_with_tools error: {error_msg}")
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
    
    def _get_http_client(self) -> OpenAIHTTPClient:
        """Build an HTTP client honoring the global proxy config.

        Subclasses can override this for custom auth headers (e.g. Azure's
        ``api-key`` header) by returning a pre-configured client.
        """
        from config import conf
        proxy = conf().get("proxy") or None
        return OpenAIHTTPClient(proxy=proxy)

    def _handle_sync_response(self, request_params, api_key, api_base):
        """Handle synchronous chat-completion via HTTP."""
        params = dict(request_params)
        params.pop("stream", None)
        # Translate legacy SDK timeout kwarg to our HTTP client kwarg.
        timeout = params.pop("request_timeout", None) or params.pop("timeout", None)
        try:
            client = self._get_http_client()
            return client.chat_completions(
                api_key=api_key,
                api_base=api_base,
                timeout=timeout,
                stream=False,
                **params,
            )
        except OpenAIHTTPError as e:
            logger.error(
                f"[{self.__class__.__name__}] sync response error: "
                f"HTTP {e.status_code}: {e.message}"
            )
            return {
                "error": True,
                "message": e.message,
                "status_code": e.status_code or 500,
            }
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500,
            }

    def _handle_stream_response(self, request_params, api_key, api_base):
        """Handle streaming chat-completion via HTTP (SSE).

        Yields dict chunks in OpenAI's standard streaming shape:
          {"choices": [{"delta": {...}, "finish_reason": ...}], ...}
        On error, yields a single ``{"error": ..., "status_code": ...}`` chunk
        — the same contract :mod:`agent.protocol.agent_stream` already handles.
        """
        params = dict(request_params)
        params.pop("stream", None)
        timeout = params.pop("request_timeout", None) or params.pop("timeout", None)
        try:
            client = self._get_http_client()
            stream = client.chat_completions(
                api_key=api_key,
                api_base=api_base,
                timeout=timeout,
                stream=True,
                **params,
            )
            for chunk in stream:
                yield chunk
        except OpenAIHTTPError as e:
            logger.error(
                f"[{self.__class__.__name__}] stream response error: "
                f"HTTP {e.status_code}: {e.message}"
            )
            yield {
                "error": True,
                "message": e.message,
                "status_code": e.status_code or 500,
            }
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] stream response error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500,
            }
    
    def _convert_tools_to_openai_format(self, tools):
        """
        Convert tools from Claude format to OpenAI format
        
        Claude format: {name, description, input_schema}
        OpenAI format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        openai_tools = []
        for tool in tools:
            # Check if already in OpenAI format
            if 'type' in tool and tool['type'] == 'function':
                openai_tools.append(tool)
            else:
                # Convert from Claude format
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return openai_tools
    
    def _convert_messages_to_openai_format(self, messages):
        """
        Convert messages from Claude format to OpenAI format
        
        Claude uses content blocks with types like 'tool_use', 'tool_result'
        OpenAI uses 'tool_calls' in assistant messages and 'tool' role for results
        """
        if not messages:
            return []
        
        openai_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # Handle string content (already in correct format)
            if isinstance(content, str):
                openai_messages.append(msg)
                continue
            
            # Handle list content (Claude format with content blocks)
            if isinstance(content, list):
                # Check if this is a tool result message (user role with tool_result blocks)
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # Separate text content and tool_result blocks
                    text_parts = []
                    tool_results = []

                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            tool_results.append(block)

                    # First, add tool result messages (must come immediately after assistant with tool_calls)
                    for block in tool_results:
                        tool_call_id = block.get("tool_use_id") or ""
                        if not tool_call_id:
                            logger.warning(f"[OpenAICompatible] tool_result missing tool_use_id, using empty string")
                        # Ensure content is a string (some providers require string content)
                        result_content = block.get("content", "")
                        if not isinstance(result_content, str):
                            result_content = json.dumps(result_content, ensure_ascii=False)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_content
                        })

                    # Then, add text content as a separate user message if present
                    if text_parts:
                        openai_messages.append({
                            "role": "user",
                            "content": " ".join(text_parts)
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
                            tool_id = block.get("id") or ""
                            if not tool_id:
                                logger.warning(f"[OpenAICompatible] tool_use missing id for '{block.get('name')}'")
                            tool_calls.append({
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })

                    # Build OpenAI format assistant message
                    openai_msg = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None
                    }

                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls

                    if msg.get("_gemini_raw_parts"):
                        openai_msg["_gemini_raw_parts"] = msg["_gemini_raw_parts"]

                    openai_messages.append(openai_msg)
                else:
                    # Other list content, keep as is
                    openai_messages.append(msg)
            else:
                # Other formats, keep as is
                openai_messages.append(msg)

        return drop_orphaned_tool_results_openai(openai_messages)

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using the OpenAI-compatible /chat/completions endpoint."""
        try:
            api_config = self.get_api_config()
            vision_model = model or api_config.get("model", "gpt-4o")
            api_key = api_config.get("api_key", "")
            api_base = (api_config.get("api_base") or "https://api.openai.com/v1").rstrip("/")

            payload = {
                "model": vision_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                f"{api_base}/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            if resp.status_code != 200:
                body = resp.text[:500]
                logger.error(f"[{self.__class__.__name__}] call_vision HTTP {resp.status_code}: {body}")
                return {"error": True, "message": f"HTTP {resp.status_code}: {body}"}
            data = resp.json()
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
            logger.error(f"[{self.__class__.__name__}] call_vision error: {e}")
            return {"error": True, "message": str(e)}
