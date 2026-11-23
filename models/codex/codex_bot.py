"""Run Codex as a CowAgent chat provider over the official App Server."""

import hashlib
import json
import re
from threading import BoundedSemaphore
from uuid import uuid4

from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from config import conf
from models.bot import Bot
from models.chatgpt.chat_gpt_session import ChatGPTSession
from models.codex.app_server import AppServer, CodexError, LOGIN_REQUIRED, TOOL_NAMESPACE
from models.openai.responses_adapter import messages_to_input
from models.openai_compatible_bot import OpenAICompatibleBot
from models.session_manager import SessionManager

# Each model call runs its own App Server child; cap how many run at once.
# Codex reloads auth.json when another child has refreshed the token.
_MODEL_CALLS = BoundedSemaphore(4)
# Silence allowed between two App Server messages during a turn.
_IDLE_TIMEOUT = 300
# Parallel calls of one response arrive back to back; wait this long for more.
_TOOL_CALL_GRACE = 0.2
_BASE_INSTRUCTIONS = "You are the model powering CowAgent. Answer in the user's language."
_TOOL_EXECUTION_INSTRUCTIONS = (
    "CowAgent is the host for this conversation. It executes the supplied cowagent tools and "
    "controls their permissions. Use these tools for requested actions, including file edits "
    "and commands, when the appropriate tool is available. CowAgent will return the result "
    "or any permission denial. Report what the tools actually did. The App Server's local "
    "execution settings apply only to its own built-in tools and do not determine what "
    "CowAgent tools can do. Use CowAgent's current instructions and tool results to determine "
    "access instead of relying on previous assistant statements about permissions."
)


def _tool_alias(name):
    prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:40]
    suffix = hashlib.sha256(name.encode()).hexdigest()[:12]
    return f"cow_{prefix}_{suffix}"


def _response_history(messages):
    history = messages_to_input(messages)
    for item in history:
        if item.get("type") == "function_call":
            item["name"] = _tool_alias(item["name"])
            item["namespace"] = TOOL_NAMESPACE
        elif "role" in item:
            item["type"] = "message"
            if isinstance(item["content"], str):
                kind = "output_text" if item["role"] == "assistant" else "input_text"
                item["content"] = [{"type": kind, "text": item["content"]}]
    return history


def _turn_input(history):
    if history and history[-1].get("role") == "user":
        parts = history.pop()["content"]
        return [
            {"type": "image", "url": part["image_url"]} if part["type"] == "input_image"
            else {"type": "text", "text": part["text"]}
            for part in parts
        ]
    return [{"type": "text", "text": "Continue using the conversation and any tool results above."}]


def _usage(params):
    tokens = params["tokenUsage"]["total"]
    return {
        "prompt_tokens": tokens["inputTokens"], "completion_tokens": tokens["outputTokens"],
        "total_tokens": tokens["totalTokens"],
        "prompt_tokens_details": {"cached_tokens": tokens.get("cachedInputTokens", 0)},
    }


def _chunk(model, delta=None, finish=None, usage=None):
    chunk = {"model": model, "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        chunk["usage"] = usage
    return chunk


class CodexBot(Bot, OpenAICompatibleBot):
    def __init__(self):
        self.sessions = SessionManager(ChatGPTSession, model=conf().get("model") or "")

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        chunks = self._stream(messages, tools, kwargs)
        if stream:
            return chunks
        content, tool_calls, usage = [], [], {}
        model = finish = None
        for chunk in chunks:
            if chunk.get("error"):
                return chunk
            model = chunk["model"]
            choice = chunk["choices"][0]
            delta = choice["delta"]
            content.append(delta.get("content", ""))
            tool_calls.extend({k: v for k, v in call.items() if k != "index"}
                              for call in delta.get("tool_calls", []))
            usage = chunk.get("usage", usage)
            finish = choice.get("finish_reason") or finish
        message = {"role": "assistant", "content": "".join(content)}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"model": model, "choices": [
            {"index": 0, "message": message, "finish_reason": finish},
        ], "usage": usage}

    def _stream(self, messages, tools, options):
        model = options.get("model") or conf().get("model") or None
        system = options.get("system")
        converted = self._convert_messages_to_openai_format(messages)
        if system and converted and converted[0].get("role") == "system":
            converted = converted[1:]
        history = _response_history(converted)
        inputs = _turn_input(history)

        dynamic_tools = []
        names = {}
        for tool in self._convert_tools_to_openai_format(tools) or []:
            function = tool["function"]
            name = function["name"]
            alias = _tool_alias(name)
            names[alias] = name
            dynamic_tools.append({
                "type": "function", "name": alias, "description": function.get("description") or "",
                "inputSchema": function.get("parameters") or {"type": "object", "properties": {}},
                "deferLoading": False,
            })
        instructions = f"{_BASE_INSTRUCTIONS}\n\n{system}" if system else _BASE_INSTRUCTIONS
        try:
            idle = max(conf().get("request_timeout") or 0, _IDLE_TIMEOUT)
            with _MODEL_CALLS, AppServer(timeout=idle, idle=True) as server:
                server.require_chatgpt()
                result = server.request("thread/start", {
                    "model": model, "modelProvider": "openai", "ephemeral": True,
                    "approvalPolicy": "never", "sandbox": "read-only", "environments": [],
                    "baseInstructions": instructions,
                    "developerInstructions": _TOOL_EXECUTION_INSTRUCTIONS,
                    # CowAgent supplies the workspace and permission context for its tools.
                    "config": {
                        "include_permissions_instructions": False,
                        "include_environment_context": False,
                    },
                    "dynamicTools": [{
                        "type": "namespace", "name": TOOL_NAMESPACE,
                        "description": "Tools executed by CowAgent.", "tools": dynamic_tools,
                    }] if dynamic_tools else [],
                })
                thread_id = result["thread"]["id"]
                actual_model = result.get("model") or model
                if history:
                    server.request("thread/inject_items", {"threadId": thread_id, "items": history})
                turn = {"threadId": thread_id, "input": inputs}
                if options.get("reasoning_effort"):
                    turn["effort"] = options["reasoning_effort"]
                turn_id = server.request("turn/start", turn, preserve_events=True)["turn"]["id"]
                yield from self._turn_events(server, actual_model, thread_id, turn_id, names)
        except (CodexError, OSError) as exc:
            yield {"error": True, "message": str(exc), "status_code": getattr(exc, "status_code", 503)}

    @staticmethod
    def _tool_call(event, names):
        """A CowAgent function call from an ``item/tool/call`` request, else None."""
        if event.get("method") != "item/tool/call" or "id" not in event:
            return None
        params = event.get("params") or {}
        name = names.get(params.get("tool")) if params.get("namespace") == TOOL_NAMESPACE else None
        arguments = params.get("arguments")
        if not name or not isinstance(arguments, dict):
            return None
        return {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}

    @staticmethod
    def _turn_events(server, model, thread_id, turn_id, names):
        usage = None
        streamed_items = set()
        while True:
            event = server.receive()
            method, params = event.get("method"), event.get("params") or {}
            if params.get("threadId") != thread_id or (
                "turnId" in params and params["turnId"] != turn_id
            ):
                if method and "id" in event:
                    server.reject(event)
                continue

            if method == "item/tool/call" and "id" in event:
                call = CodexBot._tool_call(event, names)
                if call:
                    # CowAgent owns tool execution. End this isolated App Server
                    # call and replay the real results from CowAgent on the next call.
                    calls = [call]
                    while True:
                        more = server.receive(wait=_TOOL_CALL_GRACE)
                        if not more:
                            break
                        same_thread = (more.get("params") or {}).get("threadId") == thread_id
                        extra = CodexBot._tool_call(more, names) if same_thread else None
                        if extra:
                            calls.append(extra)
                        elif more.get("method") == "thread/tokenUsage/updated":
                            usage = _usage(more["params"])
                        elif more.get("method") and "id" in more:
                            server.reject(more)
                    yield _chunk(model, {"tool_calls": [
                        {"index": i, "type": "function", "id": "call_cow_" + uuid4().hex, "function": fn}
                        for i, fn in enumerate(calls)
                    ]})
                    yield _chunk(model, finish="tool_calls", usage=usage)
                    return
            if method and "id" in event:
                server.reject(event)
            elif method == "item/agentMessage/delta":
                streamed_items.add(params.get("itemId"))
                yield _chunk(model, {"content": params["delta"]})
            elif method == "item/completed":
                item = params["item"]
                if item["type"] == "agentMessage" and item["id"] not in streamed_items and item.get("text"):
                    yield _chunk(model, {"content": item["text"]})
            elif method == "thread/tokenUsage/updated":
                usage = _usage(params)
            elif method == "turn/completed" and params["turn"]["id"] == turn_id:
                turn = params["turn"]
                if turn["status"] != "completed":
                    error = turn.get("error") or {}
                    message = error.get("message") or f"Codex turn {turn['status']}."
                    info = error.get("codexErrorInfo")
                    if info == "unauthorized":
                        raise CodexError(f"{message} {LOGIN_REQUIRED}", 401)
                    if info in ("rateLimitExceeded", "usageLimitExceeded"):
                        raise CodexError(message, 429)
                    if info == "contextWindowExceeded":
                        raise CodexError(f"Context window exceeded. {message}", 400)
                    raise CodexError(message)
                yield _chunk(model, finish="stop", usage=usage)
                return

    def reply(self, query, context=None):
        if context is None or context.type != ContextType.TEXT:
            return Reply(ReplyType.ERROR, "The Codex provider supports text chat.")
        session_id = context["session_id"]
        if query in conf().get("clear_memory_commands", ["#清除记忆"]):
            self.sessions.clear_session(session_id)
            return Reply(ReplyType.INFO, "Memory cleared")
        session = self.sessions.session_query(query, session_id)
        result = self.call_with_tools(session.messages, model=context.get("gpt_model"))
        if result.get("error"):
            session.messages.pop()
            return Reply(ReplyType.ERROR, result["message"])
        content = result["choices"][0]["message"]["content"]
        self.sessions.session_reply(content, session_id, result["usage"].get("total_tokens"))
        return Reply(ReplyType.TEXT, content)
