import pytest
from agent.protocol.message_utils import sanitize_claude_messages

@pytest.mark.parametrize("extra", [[], [{"type": "text", "text": "Keep this note"}], [{"type": "image", "source": {"type": "base64", "data": "x"}}]])
def test_orphan_removal_preserves_actual_matched_tool_output(extra):
    valid = {"type": "tool_result", "tool_use_id": "t1", "content": "real tool output"}
    messages = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}]},
                {"role": "user", "content": [valid, {"type": "tool_result", "tool_use_id": "orphan", "content": "drop"}] + extra}]
    sanitize_claude_messages(messages)
    assert messages[1]["content"] == [valid] + extra
    assert not valid.get("is_error")
    assert sanitize_claude_messages(messages) == 0

def test_all_orphan_message_is_removed():
    messages = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "orphan", "content": "drop"}]}]
    sanitize_claude_messages(messages)
    assert messages == []


@pytest.mark.parametrize("block", [
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "x"}},
    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "x"}},
])
@pytest.mark.parametrize("identifier", ["orphan", None])
def test_leading_orphan_preserves_multimodal_content(block, identifier):
    messages = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": identifier, "content": "drop"},
        block,
    ]}]

    assert sanitize_claude_messages(messages) == 1
    assert messages == [{"role": "user", "content": [block]}]
    assert sanitize_claude_messages(messages) == 0


def test_leading_orphan_is_not_matched_to_a_later_tool_call():
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "stale"},
            {"type": "text", "text": "Read this"},
        ]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "fresh"}]},
    ]

    assert sanitize_claude_messages(messages) == 1
    assert messages[0]["content"] == [{"type": "text", "text": "Read this"}]
    assert messages[-1]["content"][0]["content"] == "fresh"
    assert sanitize_claude_messages(messages) == 0
