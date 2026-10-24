# encoding:utf-8

import json
import re
import socket
import threading
import time
from typing import Optional

import requests

from models.baidu.baidu_wenxin_session import BaiduWenxinSession
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf

# Optional OpenAI image support
try:
    from models.openai.open_ai_image import OpenAIImage
    _openai_image_available = True
except Exception as e:
    logger.warning(f"OpenAI image support not available: {e}")
    _openai_image_available = False
    OpenAIImage = object  # Fallback to object

user_session = dict()

# Anthropic exposes two mutually exclusive thinking controls. The 4.6
# generation and newer only accept ``adaptive`` (strength then comes from
# ``output_config.effort``) and reject ``enabled``; 4.5 and earlier only accept
# ``enabled`` with an explicit ``budget_tokens`` and reject ``adaptive``.
ADAPTIVE_THINKING_MODELS = (
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-preview",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

# Models that only take the ``enabled`` + ``budget_tokens`` form. Checked after
# ADAPTIVE_THINKING_MODELS, since 4.6-generation names share these prefixes.
BUDGET_THINKING_MODELS = (
    "claude-3-7",
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
)

# Upper bound for the legacy budget so a large max_tokens does not license an
# unbounded thinking pass.
MAX_THINKING_BUDGET = 16000

# Prompt caching uses explicit block-level breakpoints: the top-level
# ``cache_control`` shorthand is not accepted by every Anthropic-compatible
# endpoint. The API rejects a request carrying more than 4 breakpoints.
CACHE_CONTROL = {"type": "ephemeral"}
# A 1h entry must precede every 5m entry in the prompt.
CACHE_TTL_1H = "1h"
MAX_CACHE_BREAKPOINTS = 4
UNCACHEABLE_BLOCK_TYPES = ("thinking", "redacted_thinking")

# Without it the API buffers a tool argument until the whole value is complete,
# so a large `write` streams nothing but a ping every 30s for minutes, and
# networks that drop quiet connections throw the whole generation away.
EAGER_INPUT_STREAMING = "eager_input_streaming"

# With thinking summaries and eager tool input, a healthy stream is never quiet
# for long. Some connections go silent mid-generation yet stay open for half an
# hour, outliving the socket read timeout, so a stream with no event for this
# long is cut and retried.
STREAM_STALL_SECONDS = 90


# While thinking the API may send nothing at all, so a long think looks exactly
# like a dead connection, and some networks cut it at that point. Thinking less
# is what makes the retry finish.
_LOWER_EFFORT = {"max": "medium", "xhigh": "medium", "high": "medium", "medium": "low"}
_MIN_THINKING_BUDGET = 1024


def _lower_thinking(params: dict) -> Optional[dict]:
    """Return params asking for less thinking, or None when it cannot go lower."""
    thinking = params.get("thinking") or {}
    if thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens") or 0
        if budget <= _MIN_THINKING_BUDGET:
            return None
        return dict(params, thinking=dict(thinking, budget_tokens=max(_MIN_THINKING_BUDGET, budget // 2)))
    if not thinking:
        return None
    output_config = params.get("output_config") or {}
    lower = _LOWER_EFFORT.get(output_config.get("effort") or "high")
    if not lower:
        return None
    return dict(params, output_config=dict(output_config, effort=lower))


def _abort_response(response) -> None:
    """Unblock a reader stuck in recv() on this response's socket."""
    raw = getattr(response, "raw", None)
    getters = (
        lambda: raw._fp.fp.raw._sock,
        lambda: raw._connection.sock,
        lambda: raw.connection.sock,
    )
    for get_sock in getters:
        try:
            sock = get_sock()
        except Exception:
            continue
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            break
    try:
        response.close()
    except Exception:
        pass


class _StallWatchdog:
    """Cuts a streaming response that has received no event for ``limit`` seconds."""

    def __init__(self, response, limit: Optional[float] = None):
        self.response = response
        self.limit = STREAM_STALL_SECONDS if limit is None else limit
        self.interval = min(5.0, self.limit / 3)
        self.tripped = False
        self._last = time.monotonic()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def beat(self) -> None:
        self._last = time.monotonic()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if time.monotonic() - self._last > self.limit:
                self.tripped = True
                _abort_response(self.response)
                return


# OpenAI对话模型API (可用)
class ClaudeAPIBot(Bot, OpenAIImage):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(BaiduWenxinSession, model=conf().get("model") or "text-davinci-003")

    @property
    def api_key(self):
        return conf().get("claude_api_key")

    @property
    def api_base(self):
        return conf().get("claude_api_base") or "https://api.anthropic.com/v1"

    @property
    def proxy(self):
        return conf().get("proxy", None)

    def reply(self, query, context=None):
        # acquire reply content
        if context and context.type:
            if context.type == ContextType.TEXT:
                logger.info("[CLAUDE_API] query={}".format(query))
                session_id = context["session_id"]
                reply = None
                if query == "#清除记忆":
                    self.sessions.clear_session(session_id)
                    reply = Reply(ReplyType.INFO, "记忆已清除")
                elif query == "#清除所有":
                    self.sessions.clear_all_session()
                    reply = Reply(ReplyType.INFO, "所有人记忆已清除")
                else:
                    session = self.sessions.session_query(query, session_id)
                    result = self.reply_text(session)
                    logger.info(result)
                    total_tokens, completion_tokens, reply_content = (
                        result["total_tokens"],
                        result["completion_tokens"],
                        result["content"],
                    )
                    logger.debug(
                        "[CLAUDE_API] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(str(session), session_id, reply_content, completion_tokens)
                    )

                    if total_tokens == 0:
                        reply = Reply(ReplyType.ERROR, reply_content)
                    else:
                        self.sessions.session_reply(reply_content, session_id, total_tokens)
                        reply = Reply(ReplyType.TEXT, reply_content)
                return reply
            elif context.type == ContextType.IMAGE_CREATE:
                ok, retstring = self.create_img(query, 0)
                reply = None
                if ok:
                    reply = Reply(ReplyType.IMAGE_URL, retstring)
                else:
                    reply = Reply(ReplyType.ERROR, retstring)
                return reply

    def reply_text(self, session: BaiduWenxinSession, retry_count=0, tools=None):
        try:
            actual_model = self._model_mapping(conf().get("model"))

            # Prepare headers
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            # Extract system prompt if present and prepare Claude-compatible messages
            system_prompt = conf().get("character_desc", "")
            claude_messages = []

            for msg in session.messages:
                if msg.get("role") == "system":
                    system_prompt = msg["content"]
                else:
                    claude_messages.append(msg)

            # Prepare request data
            data = {
                "model": actual_model,
                "messages": claude_messages,
                "max_tokens": self._get_max_tokens(actual_model)
            }

            if system_prompt:
                data["system"] = system_prompt

            if tools:
                data["tools"] = tools

            # Make HTTP request
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=data,
                proxies=proxies,
                timeout=180
            )

            if response.status_code != 200:
                raise Exception(f"API request failed: {response.status_code} - {response.text}")

            claude_response = response.json()
            # Handle response content and tool calls
            res_content = ""
            tool_calls = []

            content_blocks = claude_response.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    res_content += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {})
                    })

            res_content = res_content.strip().replace("<|endoftext|>", "")
            usage = claude_response.get("usage", {})
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            logger.info("[CLAUDE_API] reply={}".format(res_content))
            if tool_calls:
                logger.info("[CLAUDE_API] tool_calls={}".format(tool_calls))

            result = {
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "content": res_content,
            }

            if tool_calls:
                result["tool_calls"] = tool_calls

            return result
        except Exception as e:
            need_retry = retry_count < 2
            result = {"total_tokens": 0, "completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

            # Handle different types of errors
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                logger.warn("[CLAUDE_API] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif "timeout" in error_str:
                logger.warn("[CLAUDE_API] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif "connection" in error_str or "network" in error_str:
                logger.warn("[CLAUDE_API] APIConnectionError: {}".format(e))
                need_retry = False
                result["content"] = "我连接不到你的网络"
            else:
                logger.warn("[CLAUDE_API] Exception: {}".format(e))
                need_retry = False
                self.sessions.clear_session(session.session_id)

            if need_retry:
                logger.warn("[CLAUDE_API] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session, retry_count + 1, tools)
            else:
                return result

    def _model_mapping(self, model) -> str:
        if model == "claude-3-opus":
            return const.CLAUDE_3_OPUS
        elif model == "claude-3-sonnet":
            return const.CLAUDE_3_SONNET
        elif model == "claude-3-haiku":
            return const.CLAUDE_3_HAIKU
        elif model == "claude-3.5-sonnet":
            return const.CLAUDE_35_SONNET
        return model

    def _get_max_tokens(self, model: str) -> int:
        """
        Get the request's max_tokens for the model.

        Only the older Claude 3.x line has a small output cap; everything from
        Claude 4 onward supports 64K. Default to 64K so a newly released model
        (e.g. a future claude-*-6) does not silently regress to a tiny cap —
        no code change needed per new model.
        - Claude 3.5/3.7: 8192
        - Claude 3 Opus: 4096
        - Claude 4+ / default: 64000
        """
        if model and (model.startswith("claude-3-5") or model.startswith("claude-3-7")):
            return 8192
        elif model and model.startswith("claude-3") and "opus" in model:
            return 4096
        return 64000

    @staticmethod
    def _thinking_params(model: str, thinking: object, max_tokens: int) -> Optional[dict]:
        """Translate the generic thinking toggle into this model's native shape.

        ``display`` must be requested explicitly: without it the API returns
        thinking blocks whose ``thinking`` field is empty, carrying only a
        signature. Returns ``None`` whenever a valid config cannot be built —
        including for models with no thinking support at all — so the request
        goes out without the field rather than being rejected.
        """
        if not isinstance(thinking, dict):
            return None

        lowered = (model or "").lower()
        adaptive = lowered.startswith(ADAPTIVE_THINKING_MODELS)
        if not adaptive and not lowered.startswith(BUDGET_THINKING_MODELS):
            return None

        if adaptive:
            # Adaptive-only models reject ``thinking.type: disabled``. When the
            # caller asks to disable thinking, omit the field entirely (the API
            # then defaults to adaptive) rather than sending an unsupported value.
            if thinking.get("type") == "disabled":
                return None
            return {"type": "adaptive", "display": "summarized"}
        if thinking.get("type") == "disabled":
            return {"type": "disabled"}

        # Legacy models need a budget of at least 1024 that stays below
        # max_tokens, since thinking tokens count towards the same limit.
        if not isinstance(max_tokens, int):
            return None
        budget = min(max_tokens // 4, MAX_THINKING_BUDGET, max_tokens - 1)
        if budget < 1024:
            return None
        return {"type": "enabled", "budget_tokens": budget}

    @staticmethod
    def _parse_data_url(data_url: str):
        """Parse a data:<mime>;base64,<data> URL into (media_type, base64_data)."""
        m = re.match(r"^data:([^;]+);base64,(.+)$", data_url, re.DOTALL)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using Claude Messages API (native image blocks)."""
        try:
            actual_model = model or self._model_mapping(conf().get("model"))

            # Build Claude-native image content block
            if image_url.startswith("data:"):
                media_type, b64_data = self._parse_data_url(image_url)
                if not b64_data:
                    return {"error": True, "message": "Invalid base64 data URL"}
                image_block = {
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": media_type or "image/jpeg",
                               "data": b64_data},
                }
            else:
                image_block = {
                    "type": "image",
                    "source": {"type": "url", "url": image_url},
                }

            data = {
                "model": actual_model,
                "max_tokens": max_tokens,
                "messages": [{
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": question},
                    ],
                }],
            }

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            resp = requests.post(f"{self.api_base}/messages",
                                 headers=headers, json=data, proxies=proxies, timeout=180)

            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

            body = resp.json()
            text_parts = [b.get("text", "") for b in body.get("content", [])
                          if b.get("type") == "text"]
            usage = body.get("usage", {})
            return {
                "model": actual_model,
                "content": "".join(text_parts),
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[CLAUDE] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call Claude API with tool support for agent integration

        Args:
            messages: List of messages
            tools: List of tool definitions
            stream: Whether to use streaming
            **kwargs: Additional parameters
            
        Returns:
            Formatted response compatible with OpenAI format or generator for streaming
        """
        # A per-session model override arrives as kwargs["model"] (see
        # AgentLLMModel.call_stream). Prefer it over the global config so
        # switching the model for one chat actually reaches the API; otherwise
        # a session pinned to another provider's model would be sent here with
        # the wrong (global) model name.
        actual_model = self._model_mapping(kwargs.get("model") or conf().get("model"))

        # Extract system prompt from messages if present
        system_prompt = kwargs.get("system", conf().get("character_desc", ""))
        claude_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                claude_messages.append(self._sanitize_message(msg))

        request_params = {
            "model": actual_model,
            "max_tokens": kwargs.get("max_tokens", self._get_max_tokens(actual_model)),
            "messages": claude_messages,
            "stream": stream
        }

        if system_prompt:
            request_params["system"] = system_prompt

        if tools:
            if stream:
                tools = [dict(t, **{EAGER_INPUT_STREAMING: True}) if isinstance(t, dict) and "input_schema" in t else t
                         for t in tools]
            request_params["tools"] = tools
            # Agent turns resend the same long prefix on every step of the tool
            # loop, so cache it; one-off calls without tools are left alone.
            system, request_params["messages"] = self._apply_prompt_cache(
                request_params.get("system"), claude_messages, tools,
                system_ttl=conf().get("claude_cache_ttl", CACHE_TTL_1H))
            if system:
                request_params["system"] = system

        # Claude exposes effort under output_config rather than the generic
        # reasoning_effort field used by OpenAI-compatible providers.
        output_config = dict(kwargs.get("output_config") or {})
        reasoning_effort = kwargs.get("reasoning_effort")
        if reasoning_effort:
            output_config["effort"] = reasoning_effort
        if output_config:
            request_params["output_config"] = output_config

        thinking_params = self._thinking_params(
            actual_model, kwargs.get("thinking"), request_params["max_tokens"]
        )
        if thinking_params:
            request_params["thinking"] = thinking_params
        elif stream and (actual_model or "").lower().startswith(ADAPTIVE_THINKING_MODELS):
            # These models think even when the field is omitted, but then stream
            # nothing until the thinking ends; summaries keep the connection busy
            # so networks that cut idle streams do not drop the request.
            request_params["thinking"] = {"type": "adaptive", "display": "summarized"}

        try:
            if stream:
                return self._handle_stream_response(request_params)
            else:
                return self._handle_sync_response(request_params)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Claude API call error: {e}")
            if stream:
                # Return error generator for stream
                def error_generator():
                    yield {
                        "error": True,
                        "message": error_msg,
                        "status_code": 500
                    }

                return error_generator()
            else:
                # Return error response for sync
                return {
                    "error": True,
                    "message": str(e),
                    "status_code": 500
                }

    @staticmethod
    def _can_mark_cache(block) -> bool:
        if not isinstance(block, dict) or block.get("cache_control"):
            return False
        if block.get("type") in UNCACHEABLE_BLOCK_TYPES:
            return False
        # An empty text block cannot carry cache_control.
        return block.get("type") != "text" or bool(block.get("text"))

    @staticmethod
    def _count_cache_breakpoints(system, messages, tools) -> int:
        blocks = list(tools or [])
        if isinstance(system, list):
            blocks.extend(system)
        for msg in messages or []:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            blocks.extend(content)
            for blk in content:
                if isinstance(blk, dict) and isinstance(blk.get("content"), list):
                    blocks.extend(blk["content"])
        return sum(1 for blk in blocks if isinstance(blk, dict) and blk.get("cache_control"))

    @staticmethod
    def _system_cache_control(system, tools, system_ttl) -> dict:
        """cache_control for the system breakpoint.

        Tools + system are shared by every session and turn of an agent, and users
        often come back after more than 5 minutes, so they get the 1h TTL by default.
        It is skipped when an earlier block already carries a shorter-lived
        breakpoint, since the API rejects a 1h entry placed after a 5m one.
        """
        if system_ttl != CACHE_TTL_1H:
            return CACHE_CONTROL
        earlier = list(tools or []) + (list(system) if isinstance(system, list) else [])
        for blk in earlier:
            cc = blk.get("cache_control") if isinstance(blk, dict) else None
            if cc and cc.get("ttl") != CACHE_TTL_1H:
                return CACHE_CONTROL
        return dict(CACHE_CONTROL, ttl=CACHE_TTL_1H)

    @classmethod
    def _apply_prompt_cache(cls, system, messages: list, tools, system_ttl=None):
        """Place cache breakpoints at the end of the system prompt and of the conversation.

        Tools render before system, so the system breakpoint caches tools + system,
        which stay identical across turns even when the history does not. The
        message breakpoint follows the growing history; the next step of the tool
        loop finds it through the API's 20-block lookback, so it keeps the cheaper
        5m TTL. Breakpoints already present count against the limit of 4. Returns
        new (system, messages) without mutating the inputs, which are shared with
        the agent's history.
        """
        budget = MAX_CACHE_BREAKPOINTS - cls._count_cache_breakpoints(system, messages, tools)
        if budget > 0 and system:
            system_cc = cls._system_cache_control(system, tools, system_ttl)
            blocks = [{"type": "text", "text": system}] if isinstance(system, str) else list(system)
            if cls._can_mark_cache(blocks[-1]):
                blocks[-1] = dict(blocks[-1], cache_control=system_cc)
                system = blocks
                budget -= 1
        if budget > 0 and messages:
            last = messages[-1]
            content = last.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if isinstance(content, list) and content and cls._can_mark_cache(content[-1]):
                content = content[:-1] + [dict(content[-1], cache_control=CACHE_CONTROL)]
                messages = messages[:-1] + [dict(last, content=content)]
        return system, messages

    @staticmethod
    def _build_usage(input_tokens, output_tokens, cache_write, cache_read) -> dict:
        """OpenAI-shaped usage whose prompt_tokens is the whole prompt.

        Anthropic's ``input_tokens`` excludes cached tokens, but the agent reads
        prompt_tokens as everything the model saw this turn (context indicator,
        trimming decisions), so cache writes and reads are added back. The cache
        fields are passed through for the agent's hit-rate logging.
        """
        prompt_tokens = (input_tokens or 0) + (cache_write or 0) + (cache_read or 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens or 0,
            "total_tokens": prompt_tokens + (output_tokens or 0),
            "cache_creation_input_tokens": cache_write or 0,
            "cache_read_input_tokens": cache_read or 0,
        }

    @staticmethod
    def _sanitize_message(msg: dict) -> dict:
        """Strip thinking blocks without a ``signature`` from assistant messages.

        When the session switches from another model (e.g. MiniMax) to Claude,
        the in-memory history may contain thinking blocks that lack the
        ``signature`` field required by the Anthropic API, causing 400 errors.
        We create a shallow copy so the original history is not mutated.
        """
        if msg.get("role") != "assistant":
            return msg
        content = msg.get("content")
        if not isinstance(content, list):
            return msg
        cleaned = [
            block for block in content
            if not (isinstance(block, dict)
                    and block.get("type") == "thinking"
                    and "signature" not in block)
        ]
        if len(cleaned) == len(content):
            return msg
        return {**msg, "content": cleaned}

    def _handle_sync_response(self, request_params):
        """Handle synchronous Claude API response"""
        # Prepare headers
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Make HTTP request
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        response = requests.post(
            f"{self.api_base}/messages",
            headers=headers,
            json=request_params,
            proxies=proxies,
            timeout=180
        )

        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")

        claude_response = response.json()

        # Extract content blocks
        text_content = ""
        reasoning_content = ""
        tool_calls = []

        content_blocks = claude_response.get("content", [])
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "thinking":
                reasoning_content += block.get("thinking", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })

        # Build message in OpenAI format
        message = {
            "role": "assistant",
            "content": text_content
        }
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Format response to match OpenAI structure
        usage = claude_response.get("usage", {})
        formatted_response = {
            "id": claude_response.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": claude_response.get("model", request_params["model"]),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": claude_response.get("stop_reason", "stop")
                }
            ],
            "usage": self._build_usage(
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_creation_input_tokens"), usage.get("cache_read_input_tokens"))
        }

        return formatted_response

    def _handle_stream_response(self, request_params):
        """Stream a response; if it stalls while the model is still thinking, retry with less effort.

        A request that stalls during silent thinking stalls again when resent
        unchanged, so the agent-level retry alone would fail the same way.
        """
        while True:
            visible = False
            stalled_chunk = None
            for chunk in self._stream_once(request_params):
                if chunk.get("error") and chunk.get("stalled") and not visible:
                    stalled_chunk = chunk
                    break
                delta = ((chunk.get("choices") or [{}])[0] or {}).get("delta") or {}
                if delta.get("content") or delta.get("tool_calls"):
                    visible = True
                yield chunk
            if stalled_chunk is None:
                return
            lowered = _lower_thinking(request_params)
            if lowered is None:
                yield stalled_chunk
                return
            logger.warning(f"[Claude] Stream went silent while thinking; retrying with "
                           f"{lowered.get('output_config', {}).get('effort') or lowered.get('thinking')}")
            request_params = lowered

    def _stream_once(self, request_params):
        """Handle streaming Claude API response using HTTP requests"""
        # Prepare headers
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Add stream parameter
        request_params["stream"] = True

        # Track tool use state
        tool_uses_map = {}  # {index: {id, name, input}}
        current_tool_use_index = -1
        stop_reason = None  # Track stop reason from Claude
        # Track token usage across the stream: Anthropic reports input_tokens on
        # the message_start event and (cumulative) output_tokens on message_delta.
        # Surfaced as a final usage chunk so the agent can show a real count.
        usage_input_tokens = 0
        usage_output_tokens = 0
        usage_cache_write = 0
        usage_cache_read = 0
        watchdog = None

        try:
            # Make streaming HTTP request
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=request_params,
                proxies=proxies,
                stream=True,
                timeout=180
            )

            if response.status_code == 400 and EAGER_INPUT_STREAMING in response.text:
                # Some Anthropic-compatible gateways reject the field; drop it and resend.
                logger.warning("[Claude] Endpoint rejected eager_input_streaming, retrying without it")
                request_params["tools"] = [
                    {k: v for k, v in t.items() if k != EAGER_INPUT_STREAMING} if isinstance(t, dict) else t
                    for t in request_params.get("tools") or []
                ]
                response = requests.post(
                    f"{self.api_base}/messages",
                    headers=headers,
                    json=request_params,
                    proxies=proxies,
                    stream=True,
                    timeout=180
                )

            if response.status_code != 200:
                error_text = response.text
                try:
                    error_data = json.loads(error_text)
                    error_msg = error_data.get("error", {}).get("message", error_text)
                except Exception:
                    error_msg = error_text or "Unknown error"

                yield {
                    "error": True,
                    "status_code": response.status_code,
                    "message": error_msg
                }
                return

            # Process streaming response
            watchdog = _StallWatchdog(response)
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        watchdog.beat()
                        line = line[6:]  # Remove 'data: ' prefix
                        if line == '[DONE]':
                            break
                        try:
                            event = json.loads(line)
                            event_type = event.get("type")

                            if event_type == "message_start":
                                # Anthropic reports the prompt token count here.
                                msg_usage = (event.get("message", {}) or {}).get("usage", {}) or {}
                                usage_input_tokens = msg_usage.get("input_tokens", 0) or 0
                                usage_output_tokens = msg_usage.get("output_tokens", 0) or usage_output_tokens
                                usage_cache_write = msg_usage.get("cache_creation_input_tokens", 0) or 0
                                usage_cache_read = msg_usage.get("cache_read_input_tokens", 0) or 0

                            elif event_type == "content_block_start":
                                # New content block
                                block = event.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    current_tool_use_index = event.get("index", 0)
                                    tool_uses_map[current_tool_use_index] = {
                                        "id": block.get("id", ""),
                                        "name": block.get("name", ""),
                                        "input": ""
                                    }

                            elif event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                delta_type = delta.get("type")

                                if delta_type == "thinking_delta":
                                    thinking_text = delta.get("thinking", "")
                                    if thinking_text:
                                        yield {
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "role": "assistant",
                                                    "reasoning_content": thinking_text
                                                },
                                                "finish_reason": None
                                            }]
                                        }

                                elif delta_type == "text_delta":
                                    content = delta.get("text", "")
                                    yield {
                                        "id": event.get("id", ""),
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": request_params["model"],
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": content},
                                            "finish_reason": None
                                        }]
                                    }

                                elif delta_type == "input_json_delta":
                                    # Tool input accumulation
                                    if current_tool_use_index >= 0:
                                        tool_uses_map[current_tool_use_index]["input"] += delta.get("partial_json", "")

                            elif event_type == "message_delta":
                                # Extract stop_reason from delta
                                delta = event.get("delta", {})
                                if "stop_reason" in delta:
                                    stop_reason = delta.get("stop_reason")
                                    logger.info(f"[Claude] Stream stop_reason: {stop_reason}")
                                # Anthropic reports the (cumulative) output token
                                # count on message_delta.
                                md_usage = event.get("usage", {}) or {}
                                if md_usage.get("output_tokens"):
                                    usage_output_tokens = md_usage.get("output_tokens")
                                usage_cache_write = md_usage.get("cache_creation_input_tokens") or usage_cache_write
                                usage_cache_read = md_usage.get("cache_read_input_tokens") or usage_cache_read
                                
                                # Message complete - yield tool calls if any
                                if tool_uses_map:
                                    for idx in sorted(tool_uses_map.keys()):
                                        tool_data = tool_uses_map[idx]
                                        yield {
                                            "id": event.get("id", ""),
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": request_params["model"],
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "tool_calls": [{
                                                        "index": idx,
                                                        "id": tool_data["id"],
                                                        "type": "function",
                                                        "function": {
                                                            "name": tool_data["name"],
                                                            "arguments": tool_data["input"]
                                                        }
                                                    }]
                                                },
                                                "finish_reason": stop_reason
                                            }]
                                        }
                            
                            elif event_type == "error":
                                # Anthropic can fail a stream after the 200
                                # response has started (e.g. overloaded_error).
                                # Surface it so the agent's retry/fallback logic
                                # sees a real error instead of a truncated reply.
                                err = event.get("error") or {}
                                err_type = err.get("type", "")
                                err_msg = err.get("message") or err_type or "Unknown stream error"
                                logger.error(f"[Claude] Stream error event: {err_type}: {err_msg}")
                                yield {
                                    "error": True,
                                    "message": f"{err_type}: {err_msg}" if err_type else err_msg,
                                    "status_code": 529 if err_type == "overloaded_error" else 500,
                                }
                                return

                            elif event_type == "message_stop":
                                # Final event - log completion
                                logger.debug(f"[Claude] Stream completed with stop_reason: {stop_reason}")
                                # Surface token usage as a trailing chunk (OpenAI
                                # streaming shape) so the agent can record a real
                                # prompt_tokens count for the context indicator.
                                if usage_input_tokens or usage_output_tokens:
                                    yield {
                                        "id": event.get("id", ""),
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": request_params["model"],
                                        "choices": [],
                                        "usage": self._build_usage(
                                            usage_input_tokens, usage_output_tokens,
                                            usage_cache_write, usage_cache_read),
                                    }

                        except json.JSONDecodeError:
                            continue

            if watchdog.tripped:
                raise requests.ConnectionError("stream ended after the stall watchdog fired")

        except Exception as e:
            stalled = watchdog is not None and watchdog.tripped
            if stalled:
                message = f"Connection error: stream stalled (no data for {STREAM_STALL_SECONDS}s), aborted for retry"
                logger.error(f"Claude {message}")
                status_code = 0
            elif isinstance(e, requests.RequestException):
                logger.error(f"Claude streaming request error: {e}")
                message = f"Connection error: {str(e)}"
                status_code = 0
            else:
                logger.error(f"Claude streaming error: {e}")
                message = str(e)
                status_code = 500
            yield {
                "error": True,
                "message": message,
                "status_code": status_code,
                "stalled": stalled,
            }
        finally:
            if watchdog is not None:
                watchdog.stop()
