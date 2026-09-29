# encoding:utf-8

"""
OpenAI Responses API adapter.

Some models (e.g. ``gpt-6-astra``) only support tool calling through the
Responses API: on Chat Completions, tool calling is rejected unless the
reasoning effort is ``none``, and Astra does not support ``none``. To keep the
rest of the agent unchanged we translate at the edges:

- request:  Chat-Completions-shaped ``messages`` / ``tools`` (the shape the
            agent already produces) -> Responses ``input`` items / tools.
- response: Responses output / SSE events -> Chat-Completions-shaped ``dict``
            responses and stream chunks, so ``agent/protocol/agent_stream.py``
            consumes them exactly as it consumes ``/chat/completions`` output:
              chunk["choices"][0]["delta"]["content" | "tool_calls" | ...]
              chunk["choices"][0]["finish_reason"]
              chunk["usage"] = {prompt_tokens, completion_tokens, total_tokens}

This module has no dependency on the ``openai`` SDK — it only shapes plain
dicts consumed/produced by ``OpenAIHTTPClient``.
"""

import json
from typing import Any, Dict, Generator, List, Optional

from common.log import logger


# Models whose tool calling requires the Responses API. Matched by prefix so
# dated snapshots (gpt-6-astra-2026-..) and future gpt-6 variants are covered.
_RESPONSES_ONLY_PREFIXES = ("gpt-6",)

# gpt-6-astra does not support reasoning effort "none"/"minimal"; clamp to the
# lowest it accepts so a config carried over from gpt-5.x does not 400.
_MIN_EFFORT_FALLBACK = "low"
_UNSUPPORTED_EFFORTS = {"none", "minimal"}

# Values of the ``open_ai_api_type`` config key:
#   auto      - Responses only for models that require it (gpt-6*), else Chat Completions
#   chat      - always Chat Completions
#   responses - always Responses (for endpoints that no longer serve /chat/completions)
API_TYPE_AUTO = "auto"
API_TYPE_CHAT = "chat"
API_TYPE_RESPONSES = "responses"
_API_TYPES = {API_TYPE_AUTO, API_TYPE_CHAT, API_TYPE_RESPONSES}


def is_responses_only_model(model_name: str) -> bool:
    """Whether the model must use the Responses API for tool calling."""
    if not model_name or not isinstance(model_name, str):
        return False
    name = model_name.strip().lower()
    return name.startswith(_RESPONSES_ONLY_PREFIXES)


def resolve_api_type(api_type: Optional[str]) -> str:
    """Normalize an ``open_ai_api_type`` value; unknown values fall back to auto."""
    value = str(api_type or "").strip().lower()
    return value if value in _API_TYPES else API_TYPE_AUTO


def use_responses_api(model_name: str, api_type: Optional[str] = None) -> bool:
    """Whether a tool-calling request for ``model_name`` should use Responses."""
    mode = resolve_api_type(api_type)
    if mode == API_TYPE_RESPONSES:
        return True
    if mode == API_TYPE_CHAT:
        return False
    return is_responses_only_model(model_name)


def normalize_effort(effort: Optional[str], model: Optional[str] = None) -> Optional[str]:
    """Map a reasoning effort to one the target model accepts on Responses.

    Only Responses-only models (gpt-6*) lack the "none"/"minimal" tiers; other
    models (e.g. gpt-5.x) receive the value unchanged.
    """
    if not effort:
        return None
    value = str(effort).strip().lower()
    if value in _UNSUPPORTED_EFFORTS and (model is None or is_responses_only_model(model)):
        return _MIN_EFFORT_FALLBACK
    return value


# --------------------------------------------------------------------------- #
# Request translation: Chat Completions -> Responses
# --------------------------------------------------------------------------- #

def _content_to_input_parts(content: Any, role: str) -> Any:
    """Convert a Chat-Completions message content into Responses content.

    Strings pass through. A list of blocks is converted to Responses input
    parts (``input_text`` / ``input_image``); assistant text uses
    ``output_text`` per the Responses schema.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)

    text_type = "output_text" if role == "assistant" else "input_text"
    parts: List[Dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype in ("text", "input_text", "output_text"):
            text = item.get("text") or ""
            if text:
                parts.append({"type": text_type, "text": text})
        elif itype in ("image_url", "input_image") and role == "user":
            image = item.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                parts.append({"type": "input_image", "image_url": url})
    return parts


def messages_to_input(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Chat-Completions messages into Responses ``input`` items.

    Handles the tool-calling round trip:
      - assistant ``tool_calls`` -> ``function_call`` items (internally tagged).
      - ``role: tool`` results   -> ``function_call_output`` items linked by
        ``call_id``.
    Plain system/user/assistant text becomes ``message`` items.
    """
    input_items: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")

        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id") or "",
                "output": _tool_output_text(msg.get("content")),
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            content = msg.get("content")
            if content:
                input_items.append({
                    "role": "assistant",
                    "content": _content_to_input_parts(content, "assistant"),
                })
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                input_items.append({
                    "type": "function_call",
                    "call_id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "arguments": fn.get("arguments") or "{}",
                })
            continue

        role = role if role in ("system", "developer", "user", "assistant") else "user"
        content = _content_to_input_parts(msg.get("content"), role)
        if content == "" or content == []:
            continue
        input_items.append({"role": role, "content": content})
    return input_items


def _tool_output_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(b.get("text", "")) for b in content
            if isinstance(b, dict) and b.get("type") in ("text", "output_text", None)
        )
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def tools_to_responses(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Convert Chat-Completions tools (externally tagged) into Responses tools
    (internally tagged): ``{type:function, function:{name,...}}`` ->
    ``{type:function, name, description, parameters}``."""
    if not tools:
        return None
    converted: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        if isinstance(fn, dict):
            entry = {
                "type": "function",
                "name": fn.get("name"),
                "description": fn.get("description"),
                "parameters": fn.get("parameters") or {},
            }
        else:
            # Already internally tagged / Claude-shaped fallback.
            entry = {
                "type": "function",
                "name": tool.get("name"),
                "description": tool.get("description"),
                "parameters": tool.get("parameters") or tool.get("input_schema") or {},
            }
        converted.append({k: v for k, v in entry.items() if v is not None})
    return converted or None


def build_responses_payload(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    max_output_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
    store: bool = False,
) -> Dict[str, Any]:
    """Assemble a Responses API request body.

    Deliberately omits ``temperature`` / ``top_p`` / penalties: Responses-only
    reasoning models reject them.
    """
    payload: Dict[str, Any] = {
        "model": model,
        "input": messages_to_input(messages),
        "store": store,
    }
    r_tools = tools_to_responses(tools)
    if r_tools:
        payload["tools"] = r_tools
        payload["tool_choice"] = tool_choice or "auto"
    if max_output_tokens:
        payload["max_output_tokens"] = max_output_tokens
    effort = normalize_effort(reasoning_effort, model)
    if effort:
        payload["reasoning"] = {"effort": effort}
    if response_format and response_format.get("type") == "json_object":
        payload["text"] = {"format": {"type": "json_object"}}
    return payload


# --------------------------------------------------------------------------- #
# Response translation: Responses -> Chat Completions
# --------------------------------------------------------------------------- #

def _cc_usage(usage: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(usage, dict):
        return None
    return {
        "prompt_tokens": usage.get("input_tokens") or 0,
        "completion_tokens": usage.get("output_tokens") or 0,
        "total_tokens": usage.get("total_tokens") or 0,
    }


def _status_to_finish_reason(response: Dict[str, Any], has_tool_calls: bool) -> str:
    status = response.get("status")
    if has_tool_calls:
        return "tool_calls"
    if status == "incomplete":
        details = response.get("incomplete_details") or {}
        if details.get("reason") == "max_output_tokens":
            return "length"
    return "stop"


def responses_to_chat_completion(response: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a non-streaming Responses object into a Chat-Completions dict."""
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text_parts.append(str(part.get("text") or ""))
        elif itype == "function_call":
            tool_calls.append({
                "id": item.get("call_id") or item.get("id") or "",
                "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "{}",
                },
            })

    message: Dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": response.get("id"),
        "object": "chat.completion",
        "model": response.get("model"),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _status_to_finish_reason(response, bool(tool_calls)),
        }],
        "usage": _cc_usage(response.get("usage")) or {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        },
    }


def _text_chunk(model: Optional[str], delta: Dict[str, Any],
                finish_reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def responses_stream_to_chat_chunks(
    events: Generator[Dict[str, Any], None, None],
    model: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Translate a Responses SSE event stream into Chat-Completions chunks.

    Emits the shapes ``agent_stream`` already handles:
      - text:       delta.content
      - reasoning:  delta.reasoning_content
      - tool calls: delta.tool_calls = [{index, id, function:{name, arguments}}]
      - final:      finish_reason + top-level usage
      - errors:     {"error": {...}, "message": ..., "status_code": ...}

    Function-call arguments are streamed by Responses as
    ``response.function_call_arguments.delta`` events keyed by ``output_index``;
    we map each output index to a stable ``tool_calls`` index and forward the
    id/name once (on the ``output_item.added`` event) then argument deltas.
    """
    # output_index -> tool_calls stream index
    tool_index_map: Dict[int, int] = {}
    next_tool_index = 0
    saw_tool_call = False
    finished = False

    for event in events:
        if not isinstance(event, dict):
            continue

        # Error chunk forwarded by OpenAIHTTPClient._stream_chat.
        if event.get("error") and "type" not in event:
            yield event
            return

        etype = event.get("type")

        if etype == "response.output_text.delta":
            delta = event.get("delta")
            if delta:
                yield _text_chunk(model, {"content": str(delta)})
            continue

        if etype in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            delta = event.get("delta")
            if delta:
                yield _text_chunk(model, {"reasoning_content": str(delta)})
            continue

        if etype == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                out_idx = event.get("output_index", 0)
                if out_idx not in tool_index_map:
                    tool_index_map[out_idx] = next_tool_index
                    next_tool_index += 1
                saw_tool_call = True
                yield _text_chunk(model, {"tool_calls": [{
                    "index": tool_index_map[out_idx],
                    "id": item.get("call_id") or item.get("id") or "",
                    "type": "function",
                    "function": {"name": item.get("name") or "", "arguments": ""},
                }]})
            continue

        if etype == "response.function_call_arguments.delta":
            out_idx = event.get("output_index", 0)
            if out_idx not in tool_index_map:
                tool_index_map[out_idx] = next_tool_index
                next_tool_index += 1
                saw_tool_call = True
            delta = event.get("delta")
            if delta:
                yield _text_chunk(model, {"tool_calls": [{
                    "index": tool_index_map[out_idx],
                    "function": {"arguments": str(delta)},
                }]})
            continue

        if etype in ("response.completed", "response.incomplete"):
            response = event.get("response") or {}
            finish_reason = _status_to_finish_reason(response, saw_tool_call)
            usage = _cc_usage(response.get("usage"))
            final_chunk = _text_chunk(model or response.get("model"), {}, finish_reason)
            if usage:
                final_chunk["usage"] = usage
            yield final_chunk
            finished = True
            continue

        if etype in ("response.failed", "error"):
            response = event.get("response") or {}
            err = event.get("error") or response.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else ""
            logger.error(f"[Responses] stream error: {message} (code={code})")
            yield {
                "error": {"message": message or "Responses stream error",
                          "code": code or "", "type": err.get("type", "") if isinstance(err, dict) else ""},
                "message": message or "Responses stream error",
                "status_code": 500,
            }
            return

    # Some proxies omit an explicit completed event; make sure the agent sees a
    # terminal finish_reason so it doesn't treat the turn as truncated.
    if not finished:
        yield _text_chunk(model, {}, "tool_calls" if saw_tool_call else "stop")
