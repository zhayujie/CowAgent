"""Images attached to a query go straight to a vision-capable main model, for the current run only."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.protocol.agent_stream import _IMAGE_NOT_ATTACHED, AgentStreamExecutor
from agent.tools.vision.vision import Vision
from config import conf
from models.claudeapi.claude_api_bot import ClaudeAPIBot

PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Model:
    def __init__(self, name="vision-main", bot=None, fail_with_images=None):
        self.model = name
        self.bot = bot or SimpleNamespace(supports_vision=True)
        self.fail_with_images = fail_with_images
        self.requests = []

    def catalog_model_meta(self):
        return {}

    def call_stream(self, request):
        self.requests.append(request.messages)
        has_image = any(
            isinstance(b, dict) and b.get("type") == "image_url"
            for m in request.messages for b in (m.get("content") or []) if isinstance(m.get("content"), list)
        )
        if has_image and self.fail_with_images:
            yield {"error": {"message": self.fail_with_images}, "status_code": 400}
            return
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "photo.png").write_bytes(PIXEL_PNG)
    monkeypatch.setitem(conf(), "tools", {})
    monkeypatch.setitem(conf(), "use_linkai", False)
    return tmp_path


def _executor(workspace, model, history=None):
    agent = SimpleNamespace(name="t", messages=[], tools=[], workspace_dir=None, memory_manager=None,
                            _current_session_id="s", _current_agent_id="default")
    vision = Vision({"cwd": str(workspace)})
    return AgentStreamExecutor(agent=agent, model=model, system_prompt="", tools=[vision], max_turns=3,
                               messages=list(history or []))


def _start_run(ex, text):
    ex.run_user_message = {"role": "user", "content": [{"type": "text", "text": text}]}
    ex.messages.append(ex.run_user_message)
    ex._run_images = None
    ex._run_images_disabled = False


def _images(messages):
    return [b for m in messages if isinstance(m.get("content"), list)
            for b in m["content"] if isinstance(b, dict) and b.get("type") == "image_url"]


def _has_note(message):
    content = message.get("content")
    if isinstance(content, str):
        return _IMAGE_NOT_ATTACHED in content
    return any(isinstance(b, dict) and b.get("text") == _IMAGE_NOT_ATTACHED for b in content)


def test_image_rides_only_on_the_current_query(workspace):
    old_query = {"role": "user", "content": [{"type": "text", "text": "earlier\n[图片: tmp/photo.png]"}]}
    ex = _executor(workspace, _Model(), history=[old_query, {"role": "assistant", "content": "seen"}])
    _start_run(ex, "read this\n[Image: tmp/photo.png]")

    sent = ex._prepare_messages()

    assert len(_images(sent)) == 1
    assert _images(sent)[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert sent[-1]["content"][0]["text"].endswith("[Image: tmp/photo.png]")
    assert not _has_note(sent[-1])
    assert _has_note(sent[0])
    assert _images(ex.messages) == [] and not any(_has_note(m) for m in ex.messages)


def test_history_images_given_as_plain_strings_get_the_note_too(workspace):
    ex = _executor(workspace, _Model(), history=[
        {"role": "user", "content": "earlier\n[图片: tmp/photo.png]"},
        {"role": "assistant", "content": "seen"},
    ])
    _start_run(ex, "and now?")

    sent = ex._prepare_messages()

    assert sent[0]["content"].endswith(_IMAGE_NOT_ATTACHED)
    assert not _has_note(sent[-1])


def _text_only_main(model, mp):
    model.bot.supports_vision = False


def _other_vision_model(model, mp):
    mp.setitem(conf(), "tools", {"vision": {"model": "some-other-vision-model"}})


def _provider_default_auto(model, mp):
    mp.setitem(conf(), "use_linkai", True)
    mp.setitem(conf(), "linkai_api_key", "k")


@pytest.mark.parametrize("setup", [_text_only_main, _other_vision_model, _provider_default_auto])
def test_images_stay_with_the_vision_tool_when_the_main_model_is_not_its_target(workspace, monkeypatch, setup):
    model = _Model()
    setup(model, monkeypatch)
    ex = _executor(workspace, model)
    _start_run(ex, "[图片: tmp/photo.png]")

    sent = ex._prepare_messages()

    assert _images(sent) == []
    assert _has_note(sent[-1])


def test_vision_model_set_to_the_main_model_counts_as_main(workspace, monkeypatch):
    monkeypatch.setitem(conf(), "tools", {"vision": {"model": "Vision-Main"}})
    ex = _executor(workspace, _Model())
    _start_run(ex, "[图片: tmp/photo.png]")

    assert len(_images(ex._prepare_messages())) == 1


def test_rejected_image_request_retries_without_images(workspace):
    model = _Model(fail_with_images="image input is not supported for this model")
    ex = _executor(workspace, model)
    _start_run(ex, "what is this\n[图片: tmp/photo.png]")

    with patch.object(ex, "_identify_complete_turns", return_value=[]):
        text, tool_calls, _ = ex._call_llm_stream()

    assert text == "ok" and tool_calls == []
    assert len(model.requests) == 2
    assert len(_images(model.requests[0])) == 1
    assert _images(model.requests[1]) == []
    assert _has_note(model.requests[1][-1])
    assert ex.run_user_message in ex.messages


def _gemini_parts(monkeypatch, messages):
    from models.gemini import google_gemini_bot
    from models.gemini.google_gemini_bot import GoogleGeminiBot

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setitem(conf(), "gemini_api_key", "test")
    monkeypatch.setattr(google_gemini_bot.requests, "post", fake_post)
    GoogleGeminiBot.__new__(GoogleGeminiBot).call_with_tools(messages, tools=[], stream=False, model="gemini-x")
    return [content["parts"] for content in captured["payload"]["contents"]]


def test_gemini_text_markers_inline_only_the_latest_query(workspace, monkeypatch):
    photo = str(workspace / "tmp" / "photo.png")
    parts = _gemini_parts(monkeypatch, [
        {"role": "user", "content": f"earlier\n[图片: {photo}]"},
        {"role": "assistant", "content": "seen"},
        {"role": "user", "content": f"now\n[图片: {photo}]"},
    ])

    assert [sum("inlineData" in p for p in turn) for turn in parts] == [0, 0, 1]
    assert parts[0] == [{"text": f"earlier\n[图片: {photo}]"}]


def test_gemini_agent_messages_take_images_from_blocks_not_markers(workspace, monkeypatch):
    photo = str(workspace / "tmp" / "photo.png")
    parts = _gemini_parts(monkeypatch, [
        {"role": "user", "content": [{"type": "text", "text": f"earlier\n[图片: {photo}]"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "seen"}]},
        {"role": "user", "content": [
            {"type": "text", "text": f"now\n[图片: {photo}]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        ]},
    ])

    assert [sum("inlineData" in p for p in turn) for turn in parts] == [0, 0, 1]
    assert parts[2][1] == {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}


def test_dashscope_converts_image_url_blocks_and_gates_vision_by_api():
    from models.dashscope.dashscope_bot import DashscopeBot

    bot = DashscopeBot.__new__(DashscopeBot)
    out = bot._convert_messages_to_dashscope_format([{"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]}])

    assert out[0]["content"] == [{"type": "text", "text": "hi"}, {"image": "data:image/png;base64,QUJD"}]
    assert DashscopeBot.model_supports_vision("qwen3.8-flash")
    assert not DashscopeBot.model_supports_vision("qwen-plus")


def test_claude_bot_converts_image_url_blocks():
    msg = {"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]}

    out = ClaudeAPIBot._sanitize_message(msg)

    assert out["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
    }
    assert msg["content"][1]["type"] == "image_url"
