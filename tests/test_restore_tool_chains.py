"""Restored history keeps the tool calls of its most recent turns.

Reduced to text, a restored conversation is a run of questions each answered
with a finished report and no trace of the work behind it. The model reads
that as how this conversation goes and answers the next request the same
way, reporting work it never started. These cover what a fresh runtime gets
back from the store, and that whatever it gets back is still accepted by a
provider.
"""

import threading
from types import SimpleNamespace

from bridge.agent_initializer import (
    AgentInitializer,
    _RESTORE_TOOL_RESULT_MAX_CHARS,
    _RESTORE_TOOL_TURNS,
)


def _tool_turn(question, call_id, answer, result="print(1)", path="a.py"):
    return [
        {"role": "user", "content": [{"type": "text", "text": question}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": call_id, "name": "read", "input": {"path": path}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id, "content": result}],
        },
        {"role": "assistant", "content": [{"type": "text", "text": answer}]},
    ]


def _blocks(messages, kind):
    return [
        block
        for message in messages
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == kind
    ]


def _history(turns):
    messages = []
    for index in range(turns):
        messages += _tool_turn(f"q{index}", f"call_{index}", f"a{index}")
    return messages


class TestRecentTurnsKeepTheirToolCalls:
    def test_only_the_most_recent_turns_keep_them(self):
        restored = AgentInitializer._restored_history(_history(_RESTORE_TOOL_TURNS + 2))
        kept = [b["id"] for b in _blocks(restored, "tool_use")]
        assert kept == [f"call_{i}" for i in range(2, _RESTORE_TOOL_TURNS + 2)]
        assert [b["tool_use_id"] for b in _blocks(restored, "tool_result")] == kept

    def test_older_turns_are_reduced_to_their_text(self):
        restored = AgentInitializer._restored_history(_history(_RESTORE_TOOL_TURNS + 2))
        assert restored[:4] == [
            {"role": "user", "content": [{"type": "text", "text": "q0"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "a0"}]},
            {"role": "user", "content": [{"type": "text", "text": "q1"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "a1"}]},
        ]

    def test_a_kept_turn_is_replayed_in_order(self):
        restored = AgentInitializer._restored_history(_tool_turn("fix a.py", "c1", "fixed"))
        assert [m["role"] for m in restored] == ["user", "assistant", "user", "assistant"]
        assert restored[-1] == {"role": "assistant", "content": [{"type": "text", "text": "fixed"}]}

    def test_a_turn_without_tools_is_unchanged(self):
        plain = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        ]
        assert AgentInitializer._restored_history(plain) == plain

    def test_nothing_but_role_and_content_reaches_the_model(self):
        for message in AgentInitializer._restored_history(_history(2)):
            assert set(message) == {"role", "content"}


class TestWhatTheyCarryIsClipped:
    def test_a_long_result_is_cut(self):
        restored = AgentInitializer._restored_history(
            _tool_turn("read", "c1", "done", result="x" * 50000)
        )
        result = _blocks(restored, "tool_result")[0]["content"]
        assert result.startswith("x" * _RESTORE_TOOL_RESULT_MAX_CHARS)
        assert len(result) < _RESTORE_TOOL_RESULT_MAX_CHARS + 100
        assert "truncated" in result

    def test_a_block_result_becomes_text(self):
        turn = _tool_turn("shot", "c1", "done")
        turn[2]["content"][0]["content"] = [
            {"type": "text", "text": "saved"},
            {"type": "image", "source": {"type": "base64", "data": "A" * 9000}},
        ]
        result = _blocks(AgentInitializer._restored_history(turn), "tool_result")[0]["content"]
        assert result == "saved\n[image]"

    def test_long_arguments_are_cut_but_still_arguments(self):
        turn = _tool_turn("write", "c1", "done")
        turn[1]["content"][1]["input"] = {"path": "a.py", "content": "y" * 9000, "n": 3}
        call = _blocks(AgentInitializer._restored_history(turn), "tool_use")[0]
        assert call["input"]["path"] == "a.py"
        assert call["input"]["n"] == 3
        assert len(call["input"]["content"]) < 1100

    def test_the_stored_history_is_not_modified(self):
        stored = _tool_turn("read", "c1", "done", result="x" * 50000)
        AgentInitializer._restored_history(stored)
        assert stored[2]["content"][0]["content"] == "x" * 50000


class TestABrokenTurnFallsBackToText:
    def test_a_run_cut_off_mid_call(self):
        turn = _tool_turn("fix", "c1", "done")[:2]
        restored = AgentInitializer._restored_history(turn)
        assert _blocks(restored, "tool_use") == []
        assert restored == [{"role": "user", "content": [{"type": "text", "text": "fix"}]},
                            {"role": "assistant", "content": [{"type": "text", "text": "checking"}]}]

    def test_a_result_for_another_call(self):
        turn = _tool_turn("fix", "c1", "done")
        turn[2]["content"][0]["tool_use_id"] = "c9"
        restored = AgentInitializer._restored_history(turn)
        assert _blocks(restored, "tool_use") == [] and _blocks(restored, "tool_result") == []

    def test_a_turn_ending_on_a_result(self):
        turn = _tool_turn("fix", "c1", "done")[:3]
        assert _blocks(AgentInitializer._restored_history(turn), "tool_use") == []

    def test_a_broken_turn_does_not_take_the_others_with_it(self):
        broken = _tool_turn("q1", "c1", "a1")[:2]
        restored = AgentInitializer._restored_history(
            [*_tool_turn("q0", "c0", "a0"), *broken, *_tool_turn("q2", "c2", "a2")]
        )
        assert [b["id"] for b in _blocks(restored, "tool_use")] == ["c0", "c2"]

    def test_every_replayed_call_has_its_result(self):
        messages = [*_history(4), *_tool_turn("q9", "c9", "a9")[:2]]
        restored = AgentInitializer._restored_history(messages)
        calls = {b["id"] for b in _blocks(restored, "tool_use")}
        results = {b["tool_use_id"] for b in _blocks(restored, "tool_result")}
        assert calls == results


class TestAProviderAcceptsTheReplay:
    def test_openai_format_pairs_every_call_with_its_result(self):
        from models.openai_compatible_bot import OpenAICompatibleBot

        restored = AgentInitializer._restored_history(_history(4))
        converted = OpenAICompatibleBot()._convert_messages_to_openai_format(restored)
        calls = [c["id"] for m in converted if m.get("tool_calls") for c in m["tool_calls"]]
        results = [m["tool_call_id"] for m in converted if m["role"] == "tool"]
        assert calls == results == [f"call_{i}" for i in range(1, 4)]
        for index, message in enumerate(converted):
            if message["role"] == "tool":
                previous = converted[index - 1]
                assert previous["role"] in ("assistant", "tool")

    def test_claude_format_needs_no_repair(self):
        from agent.protocol.message_utils import sanitize_claude_messages

        restored = AgentInitializer._restored_history(_history(4))
        assert sanitize_claude_messages(restored) == 0

    def test_an_id_another_provider_rejects_is_rewritten_on_both_sides(self):
        restored = AgentInitializer._restored_history(_tool_turn("read", "functions.read:0", "done"))
        assert _blocks(restored, "tool_use")[0]["id"] == "functions_read_0"
        assert _blocks(restored, "tool_result")[0]["tool_use_id"] == "functions_read_0"

    def test_ids_that_collide_once_rewritten_fall_back_to_text(self):
        turn = _tool_turn("read", "a.b", "done")
        turn[1]["content"].append({"type": "tool_use", "id": "a:b", "name": "read", "input": {}})
        turn[2]["content"].append({"type": "tool_result", "tool_use_id": "a:b", "content": "ok"})
        assert _blocks(AgentInitializer._restored_history(turn), "tool_use") == []


class TestRestoreEndToEnd:
    def _restore(self, tmp_path, monkeypatch, stored, max_turns=20):
        from agent.memory import clear_conversation_store_cache, conversation_store, get_conversation_store
        from agent.workspace import session_prefs
        from config import conf

        monkeypatch.setattr(
            conversation_store,
            "_resolve_global_binding",
            lambda workspace_root: (tmp_path / "index.db", ""),
        )
        monkeypatch.setitem(conf(), "conversation_persistence", True)
        monkeypatch.setitem(conf(), "agent_max_context_turns", max_turns)
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        clear_conversation_store_cache()
        get_conversation_store(str(tmp_path)).append_messages("chat", stored)

        agent = SimpleNamespace(
            agent_id="primary",
            workspace_dir=str(tmp_path),
            messages=[],
            messages_lock=threading.RLock(),
        )
        AgentInitializer(bridge=None, agent_bridge=None)._restore_conversation_history(
            agent, "chat", str(tmp_path), "primary"
        )
        return agent.messages

    def test_a_restart_brings_the_tool_calls_back(self, tmp_path, monkeypatch):
        restored = self._restore(tmp_path, monkeypatch, _history(2))
        assert [b["id"] for b in _blocks(restored, "tool_use")] == ["call_0", "call_1"]

    def test_the_window_is_a_third_of_the_turn_cap(self, tmp_path, monkeypatch):
        restored = self._restore(tmp_path, monkeypatch, _history(10), max_turns=20)
        questions = [
            m["content"][0]["text"]
            for m in restored
            if m["role"] == "user" and m["content"][0].get("type") == "text"
        ]
        assert questions == [f"q{i}" for i in range(4, 10)]

    def test_a_turn_cut_off_by_a_restart_keeps_its_steps_and_a_note(self, tmp_path, monkeypatch):
        restored = self._restore(tmp_path, monkeypatch, _history(1) + _tool_turn("q1", "call_1", "")[:3])
        assert [b["id"] for b in _blocks(restored, "tool_use")] == ["call_0", "call_1"]
        assert restored[-1]["role"] == "assistant"
        assert restored[-1]["content"][0]["text"].startswith("_(Interrupted")

    def test_a_replay_failure_restores_text(self, tmp_path, monkeypatch):
        def fail(messages, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(AgentInitializer, "_restored_history", staticmethod(fail))
        restored = self._restore(tmp_path, monkeypatch, _history(2))
        assert _blocks(restored, "tool_use") == []
        assert [m["content"][0]["text"] for m in restored] == ["q0", "a0", "q1", "a1"]
