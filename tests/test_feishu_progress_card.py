from channel.feishu.feishu_progress_card import FeishuProgressState
from common import i18n

# Card text is localized via i18n.t; lock English so assertions are stable
# regardless of the host machine locale.
i18n.set_language("en")


def _panels(card):
    return [
        element
        for element in card["body"]["elements"]
        if element.get("tag") == "collapsible_panel"
    ]


def test_running_card_has_status_header_and_stream_target():
    state = FeishuProgressState(started_at=100.0)

    card = state.build_card(streaming=True, now=102.0)

    assert card["header"]["template"] == "blue"
    assert card["header"]["title"]["content"] == "Working"
    assert card["config"]["streaming_mode"] is True
    # No reasoning yet: the Reasoning panel must not be rendered.
    assert _panels(card) == []
    stream = next(
        element
        for element in card["body"]["elements"]
        if element.get("element_id") == "stream_md"
    )
    assert stream["content"] == "..."


def test_tool_turn_populates_reasoning_and_tools_lanes():
    state = FeishuProgressState(started_at=100.0)
    state.consume({"type": "turn_start", "data": {"turn": 1}})
    state.consume({"type": "reasoning_update", "data": {"delta": "Need the latest files."}})
    state.consume({"type": "message_update", "data": {"delta": "Checking now."}})
    state.consume({"type": "message_end", "data": {"tool_calls": [{"name": "read_file"}]}})
    state.consume(
        {
            "type": "tool_execution_start",
            "data": {"tool_call_id": "t1", "tool_name": "read_file"},
        }
    )

    card = state.build_card(streaming=True, now=103.0)
    panels = _panels(card)
    assert panels[0]["header"]["title"]["content"] == "🤔 Thinking"
    assert panels[1]["header"]["title"]["content"] == "🔧 Tools (1)"
    assert panels[0]["elements"][0]["text"]["content"] == "Need the latest files."
    assert "read_file" in panels[1]["elements"][0]["text"]["content"]
    assert "running" in panels[1]["elements"][0]["text"]["content"]

    # Tool end marks the step done and shows its own elapsed time.
    state.consume(
        {
            "type": "tool_execution_end",
            "data": {"tool_call_id": "t1", "status": "success", "execution_time": 1.2},
        }
    )
    done_card = state.build_card(streaming=True, now=104.0)
    tool_row = _panels(done_card)[1]["elements"][0]["text"]["content"]
    assert "done" in tool_row
    assert "1.2s" in tool_row


def test_agent_end_finalizes_status_body_and_footer():
    state = FeishuProgressState(started_at=100.0)
    state.consume({"type": "turn_start", "data": {"turn": 1}})
    state.consume(
        {
            "type": "agent_end",
            "data": {"final_response": "**Finished**", "cancelled": False},
        }
    )

    card = state.build_card(streaming=False, now=105.2)

    # Successful completion hides the status header entirely.
    assert "header" not in card
    assert card["config"]["streaming_mode"] is False
    assert next(
        element["content"]
        for element in card["body"]["elements"]
        if element.get("element_id") == "stream_md"
    ) == "**Finished**"
    footer = card["body"]["elements"][-1]
    assert footer["text_size"] == "notation"
    assert footer["content"] == "5.2s · 1 turn"


def test_cancelled_agent_uses_partial_output_and_stopped_status():
    state = FeishuProgressState(started_at=100.0)
    state.consume({"type": "message_update", "data": {"delta": "partial"}})
    state.consume({"type": "agent_cancelled", "data": {}})
    state.consume(
        {
            "type": "agent_end",
            "data": {"final_response": "stale response", "cancelled": True},
        }
    )

    card = state.build_card(streaming=False, now=101.0)

    assert card["header"]["title"]["content"] == "Stopped"
    assert next(
        element["content"]
        for element in card["body"]["elements"]
        if element.get("element_id") == "stream_md"
    ) == "partial"


def test_card_text_is_always_english():
    """Chinese locales were removed; even an explicit zh config renders English."""
    try:
        i18n.set_language("zh")  # resolves to "en" in the English-only build
        state = FeishuProgressState(started_at=100.0)
        state.consume({"type": "turn_start", "data": {"turn": 1}})
        state.consume({"type": "reasoning_update", "data": {"delta": "thinking"}})
        state.consume({"type": "message_end", "data": {"tool_calls": [{"name": "read_file"}]}})
        state.consume(
            {
                "type": "tool_execution_start",
                "data": {"tool_call_id": "t1", "tool_name": "read_file"},
            }
        )

        card = state.build_card(streaming=True, now=102.0)

        assert card["header"]["title"]["content"] == "Working"
        panels = _panels(card)
        assert panels[0]["header"]["title"]["content"] == "🤔 Thinking"
        assert panels[1]["header"]["title"]["content"] == "🔧 Tools (1)"
        assert "running" in panels[1]["elements"][0]["text"]["content"]
        footer = card["body"]["elements"][-1]
        assert footer["content"] == "2.0s · 1 turn"
    finally:
        i18n.set_language("en")
