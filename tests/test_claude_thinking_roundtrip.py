# encoding:utf-8
"""Signed thinking must survive the agent's tool loop unmodified.

Within a tool-use turn the API needs every thinking block back exactly as it
was produced, signature included. Without it the next request of the loop runs
without the model's earlier reasoning, and the model starts writing internal
control tags such as <thinking_mode> into its visible text.
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor, MAX_STORED_REASONING_CHARS


class _FakeStreamResponse:
    status_code = 200
    text = ""

    def __init__(self, events):
        self._lines = [f"data: {json.dumps(e)}".encode() for e in events]

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


def _bot(monkeypatch, events):
    from config import conf
    from models.claudeapi import claude_api_bot
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    monkeypatch.setitem(conf(), "claude_api_key", "test")
    monkeypatch.setitem(conf(), "proxy", "")
    monkeypatch.setattr(claude_api_bot.requests, "post",
                        lambda *a, **kw: _FakeStreamResponse(events))
    return ClaudeAPIBot.__new__(ClaudeAPIBot)


def _stream(monkeypatch, events):
    bot = _bot(monkeypatch, events)
    return list(bot._handle_stream_response({"model": "claude-opus-5-5", "messages": []}))


def _deltas(chunks):
    return [((c.get("choices") or [{}])[0] or {}).get("delta") or {} for c in chunks]


def _text(chunks):
    return "".join(d.get("content") or "" for d in _deltas(chunks))


def _layout(chunks):
    layouts = [d["_claude_content_blocks"] for d in _deltas(chunks) if d.get("_claude_content_blocks")]
    assert len(layouts) <= 1
    return layouts[0] if layouts else None


def _text_events(*pieces, index=0):
    events = [{"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}]
    events += [{"type": "content_block_delta", "index": index,
                "delta": {"type": "text_delta", "text": p}} for p in pieces]
    events.append({"type": "content_block_stop", "index": index})
    return events


def _thinking_events(index, text, signature):
    return [
        {"type": "content_block_start", "index": index,
         "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": text}},
        {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": signature}},
        {"type": "content_block_stop", "index": index},
    ]


def _tool_events(index, tool_id="toolu_1"):
    return [
        {"type": "content_block_start", "index": index,
         "content_block": {"type": "tool_use", "id": tool_id, "name": "bash", "input": {}}},
        {"type": "content_block_delta", "index": index,
         "delta": {"type": "input_json_delta", "partial_json": "{\"command\": \"ls\"}"}},
        {"type": "content_block_stop", "index": index},
    ]


def _end(stop_reason="tool_use"):
    return [
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 9}},
        {"type": "message_stop"},
    ]


def _interleaved_turn(thinking_text="plan the listing"):
    return (
        [{"type": "message_start", "message": {"usage": {"input_tokens": 5}}}]
        + _thinking_events(0, thinking_text, "sig-A")
        + _text_events("Let me look.", index=1)
        + _thinking_events(2, "now run it", "sig-B")
        + _tool_events(3)
        + _end()
    )


# -- the stream reports the block layout -------------------------------------

def test_signed_thinking_is_reported_in_response_order(monkeypatch):
    chunks = _stream(monkeypatch, _interleaved_turn())

    assert _layout(chunks) == [
        {"type": "thinking", "thinking": "plan the listing", "signature": "sig-A"},
        {"type": "text"},
        {"type": "thinking", "thinking": "now run it", "signature": "sig-B"},
        {"type": "tool_use"},
    ]


def test_redacted_thinking_is_kept_as_received(monkeypatch):
    redacted = {"type": "redacted_thinking", "data": "opaque"}
    chunks = _stream(monkeypatch, [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": redacted},
        {"type": "content_block_stop", "index": 0},
        *_text_events("done", index=1),
        *_end("end_turn"),
    ])

    assert _layout(chunks) == [redacted, {"type": "text"}]


def test_no_layout_without_a_signature(monkeypatch):
    # Some gateways strip signatures; such thinking cannot be sent back anyway.
    chunks = _stream(monkeypatch, [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}},
        {"type": "content_block_stop", "index": 0},
        *_text_events("hi", index=1),
        *_end("end_turn"),
    ])

    assert _layout(chunks) is None
    assert _text(chunks) == "hi"


# -- control tags never reach the visible text -------------------------------

def test_control_tag_in_one_delta_is_removed(monkeypatch):
    chunks = _stream(monkeypatch, _text_events("补一个 UA 头：\n<thinking_mode>interactive</thinking_mode>") + _end())

    assert _text(chunks) == "补一个 UA 头：\n"


def test_control_tag_split_across_deltas_is_removed(monkeypatch):
    pieces = ["输出了：\n<", "thinking", "_mode>inter", "active</think", "ing_mode>\n", "下一步"]
    chunks = _stream(monkeypatch, _text_events(*pieces) + _end("end_turn"))

    assert _text(chunks) == "输出了：\n下一步"


def test_reasoning_effort_tag_is_removed(monkeypatch):
    chunks = _stream(monkeypatch, _text_events("ok<reasoning_effort>85</reasoning_effort>", " go") + _end())

    assert _text(chunks) == "ok go"


def test_ordinary_angle_brackets_are_kept(monkeypatch):
    text = "a < b, <div>x</div>, <thinking_mode is a word, <think"
    pieces = [text[i:i + 3] for i in range(0, len(text), 3)]
    chunks = _stream(monkeypatch, _text_events(*pieces) + _end("end_turn"))

    assert _text(chunks) == text


def test_unclosed_control_tag_is_released_as_text(monkeypatch):
    chunks = _stream(monkeypatch, _text_events("see <thinking_mode>interactive") + _end("end_turn"))

    assert _text(chunks) == "see <thinking_mode>interactive"


def test_sync_response_strips_control_tags(monkeypatch):
    from config import conf
    from models.claudeapi import claude_api_bot
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    body = {"content": [{"type": "text", "text": "done\n<thinking_mode>interactive</thinking_mode>"}],
            "stop_reason": "end_turn", "usage": {}}
    response = SimpleNamespace(status_code=200, text="", json=lambda: body)
    monkeypatch.setitem(conf(), "claude_api_key", "test")
    monkeypatch.setitem(conf(), "proxy", "")
    monkeypatch.setattr(claude_api_bot.requests, "post", lambda *a, **kw: response)
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)

    result = bot._handle_sync_response({"model": "claude-opus-5-5", "messages": []})

    assert result["choices"][0]["message"]["content"] == "done\n"


# -- the agent stores the blocks and sends them back -------------------------

def _executor(chunks):
    class _Model:
        model = "claude-opus-5-5"

        def call_stream(self, request):
            yield from chunks

    class _Exec(AgentStreamExecutor):
        def _is_thinking_enabled(self):
            return False

        def _trim_messages(self):
            return None

        def _validate_and_fix_messages(self):
            return None

        def _catalog_max_output_tokens(self):
            return 16

    return _Exec(agent=SimpleNamespace(), model=_Model(), system_prompt="", tools=[],
                 max_turns=2, messages=[], on_event=lambda e: None)


def test_agent_keeps_signed_thinking_in_place_and_whole(monkeypatch):
    long_thinking = "x" * (MAX_STORED_REASONING_CHARS * 2)
    chunks = _stream(monkeypatch, _interleaved_turn(long_thinking))
    executor = _executor(chunks)

    text, tool_calls, _ = executor._call_llm_stream(retry_on_empty=False)

    assert text == "Let me look."
    assert [tc["name"] for tc in tool_calls] == ["bash"]
    content = executor.messages[-1]["content"]
    assert [b["type"] for b in content] == ["thinking", "text", "thinking", "tool_use"]
    assert content[0] == {"type": "thinking", "thinking": long_thinking, "signature": "sig-A"}
    assert content[2]["signature"] == "sig-B"
    assert content[3]["id"] == "toolu_1" and content[3]["input"] == {"command": "ls"}


def test_signed_thinking_reaches_the_next_request():
    from models.claudeapi.claude_api_bot import ClaudeAPIBot

    message = {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "plan", "signature": "sig-A"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}},
    ]}

    assert ClaudeAPIBot._sanitize_message(message) == message


def test_other_providers_keep_the_old_layout():
    executor = _executor([
        {"choices": [{"delta": {"reasoning_content": "think"}}]},
        {"choices": [{"delta": {"content": "answer"}}]},
    ])

    executor._call_llm_stream(retry_on_empty=False)

    assert executor.messages[-1]["content"] == [
        {"type": "thinking", "thinking": "think"},
        {"type": "text", "text": "answer"},
    ]


# -- storage ------------------------------------------------------------------

def _stored_turn(thinking_text):
    return [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": thinking_text, "signature": "sig-A"},
            {"type": "redacted_thinking", "data": "opaque"},
            {"type": "thinking", "thinking": "", "signature": "sig-empty"},
            {"type": "text", "text": "Let me look."},
            {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}},
        ]},
    ]


def test_stored_thinking_is_truncated_and_unsigned():
    from bridge.agent_bridge import AgentBridge

    messages = _stored_turn("y" * (MAX_STORED_REASONING_CHARS * 2))
    stored = AgentBridge._unsign_thinking_blocks(messages)

    blocks = stored[1]["content"]
    assert [b["type"] for b in blocks] == ["thinking", "text", "tool_use"]
    assert "signature" not in blocks[0]
    assert len(blocks[0]["thinking"]) < MAX_STORED_REASONING_CHARS * 2
    # The in-memory history keeps the signed blocks for the rest of the run.
    assert messages[1]["content"][0]["signature"] == "sig-A"
    assert len(messages[1]["content"]) == 5


def test_unsigned_history_is_stored_unchanged():
    from bridge.agent_bridge import AgentBridge

    messages = [{"role": "assistant", "content": [{"type": "thinking", "thinking": "t"},
                                                  {"type": "text", "text": "a"}]}]

    assert AgentBridge._unsign_thinking_blocks(messages)[0] is messages[0]


def test_stripping_thinking_also_drops_redacted_blocks():
    from bridge.agent_bridge import AgentBridge

    stored = AgentBridge._strip_thinking_blocks(_stored_turn("plan"))

    assert [b["type"] for b in stored[1]["content"]] == ["text", "tool_use"]
