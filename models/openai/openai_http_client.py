# encoding:utf-8

"""
Lightweight HTTP client for OpenAI-compatible APIs.

This client is a drop-in replacement for the parts of the `openai` SDK that this
project actually uses (chat completions, completions, image generation), so we
can drop the hard dependency on `openai==0.27.x`.

Design goals:
- Pure `requests` based (no httpx / pydantic / openai SDK dependency).
- Returns plain `dict` responses with the same shape OpenAI's HTTP API returns,
  so existing code that does `response["choices"][0]["message"]["content"]` /
  `response["usage"]["total_tokens"]` keeps working.
- Streaming yields plain `dict` chunks (parsed SSE `data:` JSON), matching the
  shape that `agent/protocol/agent_stream.py` consumes:
    chunk["choices"][0]["delta"]["content" | "tool_calls" | "reasoning_content"]
    chunk["choices"][0]["finish_reason"]
  Plus dict-style error chunks: {"error": True, "message": ..., "status_code": ...}
- Compatible with arbitrary OpenAI-compatible endpoints (LinkAI, Azure-style
  proxies, DeepSeek, Moonshot, etc.) by allowing per-call api_key / api_base
  override and trusting whatever path/payload shape the caller passes.
"""

import hashlib
import json
import re
import time
import uuid
from typing import Any, Dict, Generator, Optional
from urllib.parse import urlparse

import requests

from common.log import logger
from common.deployment import is_desktop


DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 600  # seconds; matches old openai SDK default
# Longest a stream may send only SSE comments (e.g. ": keep-alive") before we
# give up. Each comment resets the per-read socket timeout, so without this an
# overloaded endpoint can hold a turn open forever. Same cap as the other
# providers (deepseek / moonshot / mimo / doubao / minimax / linkai / modelscope).
STREAM_KEEPALIVE_MAX_SECONDS = 180


class _KeepAliveOnlyStream(Exception):
    """Raised when a stream has sent only comments for too long."""


_APP_TITLE = "CowAgent"
_APP_REFERER = "https://github.com/zhayujie/CowAgent"


# Optional client-source tag. Only sent to the source-tagged hosts below, so no
# client identity leaks to a user's own proxy.
_SOURCE_HEADER = "X-Client-Source"

# Per-gateway app attribution headers, only sent when the request host
# matches a documented gateway. Sending these to user-configured custom
# proxies would leak app identity, so we dispatch by host suffix.
_ATTRIBUTION_HEADERS_BY_HOST: Dict[str, Dict[str, str]] = {
    "openrouter.ai": {
        "HTTP-Referer": _APP_REFERER,
        "X-Title": _APP_TITLE,
    },
    "orcarouter.ai": {
        "HTTP-Referer": _APP_REFERER,
        "X-Title": _APP_TITLE,
    },
    "ai-gateway.vercel.sh": {
        "HTTP-Referer": _APP_REFERER,
        "X-Title": _APP_TITLE,
    },
    "link-ai.tech": {
        "X-Title": _APP_TITLE,
    },
}

# Hosts that also receive the client-source tag. Resolved per request rather
# than baked into the table above, so COW_DESKTOP set after import is honored.
_SOURCE_TAGGED_HOSTS = ("link-ai.tech",)


def _resolve_attribution_headers(url: str) -> Dict[str, str]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return {}
    if not host:
        return {}
    for suffix, headers in _ATTRIBUTION_HEADERS_BY_HOST.items():
        if host == suffix or host.endswith("." + suffix):
            resolved = dict(headers)
            if any(host == h or host.endswith("." + h) for h in _SOURCE_TAGGED_HOSTS):
                try:
                    from common.utils import apply_client_source
                    apply_client_source(resolved)
                except Exception:
                    resolved[_SOURCE_HEADER] = (
                        "desktop" if is_desktop() else "open-source"
                    )
            return resolved
    return {}


# Gateways that require a stable per-conversation session id for routing and
# prompt caching, and reject requests without it. The value is a hash of the
# ambient session, so raw chat / user ids never leave the process.
_SESSION_HEADER_BY_HOST: Dict[str, str] = {
    "opencode.ai": "x-opencode-session",
}

# Used when a request runs outside any conversation (e.g. a background job).
_PROCESS_SESSION_ID = uuid.uuid4().hex


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def _session_token() -> str:
    try:
        from common.runtime_identity import current_identity
        identity = current_identity()
    except Exception:
        return _PROCESS_SESSION_ID
    if not identity.session_id:
        return _PROCESS_SESSION_ID
    scope = f"{identity.agent_id or ''}:{identity.session_id}"
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


def _user_agent() -> str:
    try:
        from cli import __version__
    except Exception:
        return _APP_TITLE
    return f"{_APP_TITLE}/{__version__}"


def _resolve_session_headers(url: str) -> Dict[str, str]:
    host = _host_of(url)
    if not host:
        return {}
    for suffix, header in _SESSION_HEADER_BY_HOST.items():
        if _host_matches(host, suffix):
            # These gateways also ask clients to identify themselves instead
            # of sending a generic HTTP-library user agent.
            return {header: _session_token(), "User-Agent": _user_agent()}
    return {}


def resolve_host_headers(url: str) -> Dict[str, str]:
    """Headers a known gateway expects for ``url``; {} for any other host."""
    headers = _resolve_attribution_headers(url)
    headers.update(_resolve_session_headers(url))
    return headers


class OpenAIHTTPError(Exception):
    """Raised for non-2xx responses. Carries status code + parsed body."""

    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        # Try to extract human-readable message from OpenAI-style error envelope
        if not message and isinstance(body, dict):
            err = body.get("error") or {}
            if isinstance(err, dict):
                message = err.get("message") or ""
            elif isinstance(err, str):
                message = err
        if not message:
            message = str(body)[:500]
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class OpenAIHTTPClient:
    """Minimal HTTP client for OpenAI-compatible endpoints.

    Per-instance defaults (api_key / api_base / proxy / timeout) can be
    overridden on every call. Callers can also pass ``extra_headers`` for
    Azure-style ``api-key`` headers or custom routing headers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: Optional[float] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_key = api_key
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.proxies = (
            {"http": proxy, "https": proxy} if proxy else None
        )
        self.extra_headers = dict(extra_headers) if extra_headers else {}

    # ------------------------------------------------------------------ #
    # Public API surface (mirrors what the old openai SDK provided)
    # ------------------------------------------------------------------ #

    def chat_completions(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        extra_query: Optional[Dict[str, str]] = None,
        path: str = "/chat/completions",
        stream: bool = False,
        **payload,
    ):
        """POST /chat/completions.

        When ``stream=True`` returns a generator yielding parsed SSE chunks
        (plain ``dict``). On error during streaming, yields a single dict with
        ``{"error": True, ...}`` and stops, matching the contract expected by
        ``agent/protocol/agent_stream.py``.
        """
        payload["stream"] = stream
        return self._request(
            path=path,
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            proxy=proxy,
            extra_headers=extra_headers,
            extra_query=extra_query,
            stream=stream,
        )

    def responses(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        extra_query: Optional[Dict[str, str]] = None,
        path: str = "/responses",
        stream: bool = False,
        **payload,
    ):
        """POST /responses (OpenAI Responses API).

        Required for models like gpt-6-astra whose tool calling is only
        supported on Responses (Chat Completions cannot do tool calling with a
        non-``none`` reasoning effort, and Astra does not support ``none``).

        Non-streaming returns the raw Responses ``dict``. Streaming returns a
        generator yielding parsed SSE event ``dict`` objects (each carries a
        ``type`` such as ``response.output_text.delta``); the caller is
        responsible for translating them into whatever shape it needs. On
        error during streaming a single ``{"error": ..., "status_code": ...}``
        chunk is yielded, matching :meth:`chat_completions`.
        """
        payload["stream"] = stream
        return self._request(
            path=path,
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            proxy=proxy,
            extra_headers=extra_headers,
            extra_query=extra_query,
            stream=stream,
        )

    def completions(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        **payload,
    ) -> Dict[str, Any]:
        """POST /completions (legacy text completion). Non-streaming only."""
        payload.pop("stream", None)
        return self._request(
            path="/completions",
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            stream=False,
        )

    def images_generate(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        **payload,
    ) -> Dict[str, Any]:
        """POST /images/generations."""
        return self._request(
            path="/images/generations",
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            stream=False,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_headers(
        self,
        api_key: Optional[str],
        extra_headers: Optional[Dict[str, str]],
        url: Optional[str] = None,
    ) -> Dict[str, str]:
        key = api_key if api_key is not None else self.api_key
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if url:
            headers.update(resolve_host_headers(url))
        if self.extra_headers:
            headers.update(self.extra_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _request(
        self,
        *,
        path: str,
        payload: Dict[str, Any],
        api_key: Optional[str],
        api_base: Optional[str],
        timeout: Optional[float],
        stream: bool,
        proxy: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        extra_query: Optional[Dict[str, str]] = None,
    ):
        base = (api_base or self.api_base).rstrip("/") if api_base else self.api_base
        url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
        headers = self._build_headers(api_key, extra_headers, url=url)
        req_timeout = timeout if timeout is not None else self.timeout
        proxies = (
            {"http": proxy, "https": proxy} if proxy else self.proxies
        )

        # Drop None-valued keys; some providers reject explicit nulls.
        clean_payload = {k: v for k, v in payload.items() if v is not None}

        if stream:
            # Return a generator. Errors during stream are yielded as a single
            # error chunk so callers (agent_stream) can map them to their
            # existing error-handling path without try/except around the loop.
            return self._stream_chat(
                url=url,
                headers=headers,
                payload=clean_payload,
                proxies=proxies,
                timeout=req_timeout,
                params=extra_query,
            )

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=clean_payload,
                timeout=req_timeout,
                proxies=proxies,
                params=extra_query,
            )
        except requests.exceptions.Timeout as e:
            raise OpenAIHTTPError(408, {}, f"Request timed out: {e}")
        except requests.exceptions.ConnectionError as e:
            raise OpenAIHTTPError(0, {}, f"Connection error: {e}")
        except requests.exceptions.RequestException as e:
            raise OpenAIHTTPError(0, {}, f"Request failed: {e}")

        return self._parse_response(resp)

    @staticmethod
    def _parse_response(resp: requests.Response) -> Dict[str, Any]:
        # Try JSON, fall back to text
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}

        if resp.status_code >= 400:
            raise OpenAIHTTPError(resp.status_code, data)

        return data

    def _stream_chat(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        proxies: Optional[Dict[str, str]],
        timeout: float,
        params: Optional[Dict[str, str]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Stream SSE response and yield parsed JSON chunks.

        Yields:
            - Normal chunks: dict with ``choices[0].delta`` etc.
            - Error chunks: ``{"error": True, "message": str, "status_code": int}``
              followed by termination of the generator.
        """
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxies,
                stream=True,
                params=params,
            )
        except requests.exceptions.Timeout as e:
            yield self._make_error_chunk(408, f"Request timed out: {e}")
            return
        except requests.exceptions.ConnectionError as e:
            yield self._make_error_chunk(0, f"Connection error: {e}")
            return
        except requests.exceptions.RequestException as e:
            yield self._make_error_chunk(0, f"Request failed: {e}")
            return

        if resp.status_code >= 400:
            try:
                # Read full body once for error reporting
                try:
                    body = resp.json()
                except ValueError:
                    body = {"raw": resp.text[:1000]}
                err_msg = ""
                err_code = ""
                err_type = ""
                if isinstance(body, dict):
                    err = body.get("error") or {}
                    if isinstance(err, dict):
                        err_msg = err.get("message") or ""
                        err_code = err.get("code") or ""
                        err_type = err.get("type") or ""
                    elif isinstance(err, str):
                        err_msg = err
                if not err_msg:
                    err_msg = str(body)[:500]
                yield {
                    "error": {
                        "message": err_msg,
                        "code": err_code,
                        "type": err_type,
                    },
                    # Top-level fields kept for backward compatibility with the
                    # error-shape that `_handle_stream_response` previously emitted.
                    "message": err_msg,
                    "status_code": resp.status_code,
                }
                return
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

        # IMPORTANT: do NOT use `iter_lines(decode_unicode=True)`.
        #
        # `requests` decodes per-network-chunk using the response's declared
        # encoding (often Latin-1 / ISO-8859-1 for SSE), which mangles UTF-8
        # codepoints that straddle a chunk boundary. Some upstreams (Azure
        # OpenAI proxies, Cloudflare-fronted gateways, ...) split TCP chunks
        # aggressively in the middle of multibyte characters, producing
        # garbled text and "skip malformed SSE chunk" errors.
        #
        # The fix is to read raw bytes, accumulate them until we have a
        # complete SSE event (terminated by a blank line per the SSE spec:
        # https://html.spec.whatwg.org/multipage/server-sent-events.html),
        # and only THEN decode as UTF-8. This mirrors what the official
        # openai SDK 1.x does in `openai/_streaming.py::SSEDecoder` (which
        # itself is copied from httpx-sse).
        try:
            for sse_event in self._iter_sse_events(resp):
                # `sse_event` is the joined `data:` payload as a str.
                if sse_event == "[DONE]":
                    return
                if not sse_event:
                    continue
                try:
                    chunk = json.loads(sse_event)
                except ValueError:
                    logger.debug(
                        f"[OpenAIHTTP] skip malformed SSE chunk: {sse_event[:200]}"
                    )
                    continue
                yield chunk
        except _KeepAliveOnlyStream:
            logger.error(
                f"[OpenAIHTTP] Stream timeout: only keep-alive received for "
                f"{STREAM_KEEPALIVE_MAX_SECONDS}s"
            )
            yield self._make_error_chunk(
                504,
                f"Stream timeout: only keep-alive received for {STREAM_KEEPALIVE_MAX_SECONDS}s",
            )
        except requests.exceptions.ChunkedEncodingError as e:
            yield self._make_error_chunk(0, f"Stream interrupted: {e}")
        except requests.exceptions.RequestException as e:
            yield self._make_error_chunk(0, f"Stream error: {e}")
        finally:
            try:
                resp.close()
            except Exception:
                pass

    @staticmethod
    def _iter_sse_events(resp: requests.Response) -> Generator[str, None, None]:
        """Decode an SSE byte stream into joined `data:` payloads.

        Implements the subset of the SSE spec that OpenAI / OpenAI-compatible
        endpoints actually use:
          - Events are separated by blank lines (\\r\\r, \\n\\n, or \\r\\n\\r\\n).
          - Within an event, multiple ``data:`` lines are concatenated with
            "\\n" (per spec).
          - ``event:``, ``id:``, ``retry:`` and comment lines (``:``) are
            tolerated but not yielded — for chat-completion we only care
            about the JSON payload in ``data:``.
          - Bytes are buffered until a complete event boundary is seen so
            UTF-8 codepoints split across TCP chunks decode correctly.

        Yields each event's joined ``data`` string. The terminal sentinel
        ``[DONE]`` is yielded as a literal string so the caller can break.

        Raises ``_KeepAliveOnlyStream`` once comment lines are all that has
        arrived for longer than ``STREAM_KEEPALIVE_MAX_SECONDS``.
        """
        buf = b""
        last_data_at = time.time()
        data_lines = []
        first_line = True
        skip_lf = False
        newline = re.compile(rb"\r\n|\r|\n")

        def consume_line(raw_line):
            nonlocal first_line, last_data_at
            # Only the stream's initial BOM is framing. Other Unicode line
            # separators are payload and must survive inside JSON strings.
            encoding = "utf-8-sig" if first_line else "utf-8"
            first_line = False
            line = raw_line.decode(encoding, errors="replace")
            if not line:
                if data_lines:
                    event = "\n".join(data_lines)
                    data_lines.clear()
                    return event
            elif line.startswith(":"):
                if time.time() - last_data_at > STREAM_KEEPALIVE_MAX_SECONDS:
                    raise _KeepAliveOnlyStream()
            else:
                last_data_at = time.time()
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "data":
                    data_lines.append(value)
            return None

        # Read in fixed-size slices, never `chunk_size=None`: urllib3 only
        # streams with `None` when the response is chunk-encoded. A proxy that
        # delimits SSE by closing the connection (no Transfer-Encoding, no
        # Content-Length) makes `read(None)` block until EOF, so the whole
        # reply arrives in one burst at the end.
        for raw in resp.iter_content(chunk_size=1024, decode_unicode=False):
            if not raw:
                continue
            # A CR at a network-chunk boundary already ended its line. The
            # optional following LF belongs to that same delimiter.
            if skip_lf:
                if raw.startswith(b"\n"):
                    raw = raw[1:]
                skip_lf = False
            buf += raw
            while (match := newline.search(buf)) is not None:
                raw_line = buf[:match.start()]
                skip_lf = match.group() == b"\r" and match.end() == len(buf)
                buf = buf[match.end():]
                event = consume_line(raw_line)
                if event is not None:
                    yield event

        # Preserve compatibility with proxies that omit the final blank line.
        if buf:
            consume_line(buf)
        if data_lines:
            yield "\n".join(data_lines)

    @staticmethod
    def _make_error_chunk(status_code: int, message: str) -> Dict[str, Any]:
        return {
            "error": {"message": message, "code": "", "type": ""},
            "message": message,
            "status_code": status_code,
        }


# A tiny helper for callers that just need a one-shot client without storing
# state. Keeps call sites cleaner than instantiating the class every time.
def get_default_client(
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    proxy: Optional[str] = None,
    timeout: Optional[float] = None,
) -> OpenAIHTTPClient:
    return OpenAIHTTPClient(
        api_key=api_key, api_base=api_base, proxy=proxy, timeout=timeout
    )
