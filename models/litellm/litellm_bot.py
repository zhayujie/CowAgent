# encoding:utf-8

"""
LiteLLM Bot — one provider that reaches 100+ LLMs through the LiteLLM SDK.

Unlike the generic ``custom`` OpenAI-compatible bot (which only talks to a single
OpenAI-shaped HTTP endpoint), this bot calls ``litellm.completion`` directly, so a
provider-prefixed model string routes natively to the right backend and LiteLLM
handles that provider's own auth:

    anthropic/claude-3-5-sonnet, gemini/gemini-1.5-pro, groq/llama-3.1-70b,
    bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0, azure/<deployment>, ...

Config (config.json):
    "bot_type": "litellm",
    "model": "anthropic/claude-3-5-sonnet",   # provider-prefixed
    "litellm_api_key": "",                      # optional; falls back to the
                                                 # provider's own env var
    "litellm_base_url": ""                       # optional; e.g. a LiteLLM proxy
"""

import time
from typing import Optional

from models.bot import Bot
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from .litellm_session import LiteLLMSession


class LiteLLMBot(Bot, OpenAICompatibleBot):
    """LiteLLM gateway bot (chat + agent tools + vision) via the litellm SDK."""

    def __init__(self):
        super().__init__()
        model = conf().get("model") or "gpt-4o-mini"
        self.sessions = SessionManager(LiteLLMSession, model=model)
        self.args = {
            "model": model,
            "temperature": conf().get("temperature", 0.7),
            "top_p": conf().get("top_p", 1.0),
        }

    # ---- config plumbing (used by the inherited agent tool/vision methods) ----

    @property
    def api_key(self):
        return conf().get("litellm_api_key")

    @property
    def base_url(self):
        # Optional. When unset LiteLLM uses the provider's default endpoint.
        return conf().get("litellm_base_url") or None

    def get_api_config(self):
        return {
            "api_key": self.api_key,
            "api_base": self.base_url,
            "model": conf().get("model") or "gpt-4o-mini",
            "default_temperature": conf().get("temperature", 0.7),
            "default_top_p": conf().get("top_p", 1.0),
        }

    def _completion_kwargs(self):
        """Common kwargs for every litellm call: credentials + cross-provider safety."""
        kwargs = {"drop_params": True}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        return kwargs

    # ---- classic chat path ----

    def reply(self, query, context=None):
        if context.type != ContextType.TEXT:
            return Reply(ReplyType.ERROR, "Bot cannot process message of type {}".format(context.type))

        logger.info("[LITELLM] query={}".format(query))
        session_id = context["session_id"]

        clear_memory_commands = conf().get("clear_memory_commands", [])
        if query in clear_memory_commands:
            self.sessions.clear_session(session_id)
            return Reply(ReplyType.INFO, "Memory cleared.")

        session = self.sessions.session_query(query, session_id)
        model = context.get("litellm_model")
        new_args = self.args.copy()
        if model:
            new_args["model"] = model

        reply_content = self.reply_text(session, args=new_args)
        logger.debug(
            "[LITELLM] session_id={}, reply_cont={}, completion_tokens={}".format(
                session_id, reply_content["content"], reply_content["completion_tokens"]
            )
        )
        if reply_content["completion_tokens"] > 0:
            self.sessions.session_reply(reply_content["content"], session_id, reply_content["total_tokens"])
            return Reply(ReplyType.TEXT, reply_content["content"])
        return Reply(ReplyType.ERROR, reply_content["content"])

    def reply_text(self, session: LiteLLMSession, args=None, retry_count: int = 0) -> dict:
        """Call litellm.completion and return {total_tokens, completion_tokens, content}."""
        try:
            import litellm

            body = dict(args) if args else dict(self.args)
            response = litellm.completion(
                messages=session.messages,
                **body,
                **self._completion_kwargs(),
            )
            usage = getattr(response, "usage", None)
            return {
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "content": response.choices[0].message.content or "",
            }
        except ImportError:
            logger.error("[LITELLM] litellm is not installed. Install it with `pip install litellm`.")
            return {"completion_tokens": 0, "content": "litellm is not installed on the server."}
        except Exception as e:
            need_retry = retry_count < 2
            cls_name = type(e).__name__
            # Retry only on transient errors; surface auth/bad-request immediately.
            transient = cls_name in (
                "Timeout", "APIConnectionError", "InternalServerError",
                "ServiceUnavailableError", "RateLimitError",
            )
            logger.warning("[LITELLM] completion failed (attempt {}): {}: {}".format(retry_count + 1, cls_name, e))
            if transient and need_retry:
                time.sleep(3)
                return self.reply_text(session, args, retry_count + 1)
            return {"completion_tokens": 0, "content": "[LiteLLM error] {}".format(e)}

    # ---- agent tool-calling transport: reuse the base's format conversion /
    #      request building, but dispatch through the litellm SDK ----

    def _handle_sync_response(self, request_params, api_key, api_base):
        try:
            import litellm

            params = dict(request_params)
            params.pop("stream", None)
            response = litellm.completion(
                api_key=api_key or None,
                api_base=api_base or None,
                drop_params=True,
                **params,
            )
            return response.model_dump() if hasattr(response, "model_dump") else response
        except Exception as e:
            logger.error("[LITELLM] sync response error: {}".format(e))
            return {"error": True, "message": str(e), "status_code": 500}

    def _handle_stream_response(self, request_params, api_key, api_base):
        try:
            import litellm

            params = dict(request_params)
            params.pop("stream", None)
            stream = litellm.completion(
                api_key=api_key or None,
                api_base=api_base or None,
                drop_params=True,
                stream=True,
                **params,
            )
            for chunk in stream:
                yield chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
        except Exception as e:
            logger.error("[LITELLM] stream response error: {}".format(e))
            yield {"error": True, "message": str(e), "status_code": 500}

    # ---- vision via the litellm SDK (OpenAI-style image_url content) ----

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        try:
            import litellm

            vision_model = model or self.args.get("model")
            response = litellm.completion(
                model=vision_model,
                max_tokens=max_tokens,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
                **self._completion_kwargs(),
            )
            usage = getattr(response, "usage", None)
            return {
                "model": vision_model,
                "content": response.choices[0].message.content or "",
                "usage": {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                },
            }
        except Exception as e:
            logger.error("[LITELLM] call_vision error: {}".format(e))
            return {"error": True, "message": str(e)}
