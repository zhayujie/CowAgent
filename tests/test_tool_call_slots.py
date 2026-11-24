"""Streamed tool-call deltas land in one buffer slot per call, with or without `index`."""

import json

from agent.protocol.agent_stream import _parse_tool_args, _tool_call_slot


def _collect(deltas):
    buffer = {}
    for tc_delta in deltas:
        slot = _tool_call_slot(buffer, tc_delta)
        call = buffer.setdefault(slot, {"id": "", "name": "", "arguments": ""})
        if tc_delta.get("id"):
            call["id"] = tc_delta["id"]
        func = tc_delta.get("function") or {}
        if func.get("name"):
            call["name"] = func["name"]
        if func.get("arguments"):
            call["arguments"] += func["arguments"]
    return [buffer[k] for k in sorted(buffer)]


def _complete(call_id, path):
    args = json.dumps({"path": path, "content": "x"})
    return {"id": call_id, "type": "function", "function": {"name": "write", "arguments": args}}


def test_parallel_calls_sent_without_index_stay_apart():
    calls = _collect([_complete("call_a", "AGENT.md"), _complete("call_b", "USER.md")])
    assert [c["id"] for c in calls] == ["call_a", "call_b"]
    assert [_parse_tool_args(c["arguments"], "tool_calls")[0]["path"] for c in calls] == ["AGENT.md", "USER.md"]


def test_unindexed_fragments_of_one_call_are_joined():
    calls = _collect([
        {"id": "call_a", "function": {"name": "write", "arguments": '{"path": "AG'}},
        {"function": {"arguments": 'ENT.md"}'}},
        {"id": "call_a", "function": {"arguments": ""}},
    ])
    assert len(calls) == 1
    assert _parse_tool_args(calls[0]["arguments"], "tool_calls")[0] == {"path": "AGENT.md"}


def test_indexed_streams_follow_the_index():
    calls = _collect([
        {"index": 0, "id": "call_a", "function": {"name": "read", "arguments": ""}},
        {"index": 1, "id": "call_b", "function": {"name": "read", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path": "a"}'}},
        {"index": 1, "function": {"arguments": '{"path": "b"}'}},
    ])
    assert [c["arguments"] for c in calls] == ['{"path": "a"}', '{"path": "b"}']


def test_unparseable_args_tell_the_model_nothing_ran():
    _, error = _parse_tool_args('{"a": 1}{"b": 2}', "tool_calls", "write")
    assert "did not run" in error
