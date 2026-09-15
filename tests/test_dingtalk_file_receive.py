"""DingTalk inbound file receive: type mapping, download, single/group cache.

Covers item 1 of https://github.com/zhayujie/CowAgent/issues/3156.
dingtalk_stream is stubbed so the suite does not need the optional SDK.
"""
import os
import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


if "dingtalk_stream" not in sys.modules:
    _ds = types.ModuleType("dingtalk_stream")

    class _ChatbotMessage:
        pass

    class _AckMessage:
        STATUS_OK = 0
        STATUS_SYSTEM_EXCEPTION = 1

    class _ChatbotHandler:
        pass

    _ds.ChatbotMessage = _ChatbotMessage
    _ds.AckMessage = _AckMessage
    _ds.ChatbotHandler = _ChatbotHandler
    _ds.CallbackMessage = object
    sys.modules["dingtalk_stream"] = _ds

    _card = types.ModuleType("dingtalk_stream.card_replier")

    class _CardReplier:
        def __init__(self, *args, **kwargs):
            pass

    class _AICardReplier(_CardReplier):
        pass

    class _AICardStatus:
        PROCESSING = "PROCESSING"

    _card.CardReplier = _CardReplier
    _card.AICardReplier = _AICardReplier
    _card.AICardStatus = _AICardStatus
    sys.modules["dingtalk_stream.card_replier"] = _card


from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.dingtalk.dingtalk_message import DingTalkMessage, _safe_filename
from channel.file_cache import get_file_cache


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"data", text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.text = text

    def json(self):
        return self._json


class FakeHandler:
    def __init__(self, robot_code="robot-1"):
        self.robot_code = robot_code

    def get_image_download_url(self, download_code):
        return f"dingtalk://download/{self.robot_code}:{download_code}"


class FakeEvent:
    def __init__(self, message_type="file", conversation_type="1", **kwargs):
        self.message_id = kwargs.get("message_id", "mid-1")
        self.message_type = message_type
        self.conversation_id = kwargs.get("conversation_id", "cid-1")
        self.conversation_type = conversation_type
        self.sender_id = kwargs.get("sender_id", "sender-1")
        self.sender_staff_id = kwargs.get("sender_staff_id", "staff-1")
        self.chatbot_user_id = kwargs.get("chatbot_user_id", "bot-1")
        self.conversation_title = kwargs.get("conversation_title", "title")
        self.robot_code = kwargs.get("robot_code", "robot-1")
        self.create_at = kwargs.get("create_at", 1_700_000_000_000)
        self.image_content = kwargs.get("image_content")
        self.rich_text_content = kwargs.get("rich_text_content")
        self.text = kwargs.get("text", SimpleNamespace(content=""))
        self.extensions = kwargs.get("extensions", {})
        self._image_list = kwargs.get("image_list")
        self._text_list = kwargs.get("text_list", [])

    def get_image_list(self):
        if self._image_list is not None:
            return self._image_list
        if self.message_type == "picture" and self.image_content is not None:
            return [self.image_content.download_code]
        return []

    def get_text_list(self):
        return list(self._text_list)


def _stub_dingtalk_download(monkeypatch, tmp_path, body=b"%PDF-1.4 fake"):
    monkeypatch.setattr(
        "channel.dingtalk.dingtalk_message.state_dir.tmp_dir",
        lambda *a, **k: tmp_path,
    )
    monkeypatch.setattr(
        "config.conf",
        lambda: {"dingtalk_client_id": "id", "dingtalk_client_secret": "secret"},
    )

    def fake_post(url, **kwargs):
        if "oauth2/accessToken" in url:
            return FakeResponse(json_data={"accessToken": "tok"})
        if "messageFiles/download" in url:
            payload = kwargs.get("json") or {}
            assert payload.get("downloadCode") == "dl-code"
            assert payload.get("robotCode") == "robot-1"
            return FakeResponse(json_data={"downloadUrl": "https://cdn.example/file.bin"})
        raise AssertionError(url)

    def fake_get(url, **kwargs):
        assert url == "https://cdn.example/file.bin"
        return FakeResponse(content=body)

    monkeypatch.setattr("channel.dingtalk.dingtalk_message.requests.post", fake_post)
    monkeypatch.setattr("channel.dingtalk.dingtalk_message.requests.get", fake_get)


def test_text_and_audio_still_map_to_text():
    text_msg = DingTalkMessage(
        FakeEvent(message_type="text", text=SimpleNamespace(content=" hello ")),
        FakeHandler(),
    )
    assert text_msg.ctype == ContextType.TEXT
    assert text_msg.content == "hello"

    audio_msg = DingTalkMessage(
        FakeEvent(
            message_type="audio",
            extensions={"content": {"recognition": " spoken "}},
        ),
        FakeHandler(),
    )
    assert audio_msg.ctype == ContextType.TEXT
    assert audio_msg.content == "spoken"


def test_file_message_downloads_and_keeps_filename(monkeypatch, tmp_path):
    _stub_dingtalk_download(monkeypatch, tmp_path)
    event = FakeEvent(
        message_type="file",
        extensions={"content": {"downloadCode": "dl-code", "fileName": "report.pdf"}},
    )
    msg = DingTalkMessage(event, FakeHandler())
    assert msg.ctype == ContextType.FILE
    assert msg.content == msg.file_path
    assert msg.file_path.endswith("report.pdf")
    assert os.path.isfile(msg.file_path)
    with open(msg.file_path, "rb") as fh:
        assert fh.read() == b"%PDF-1.4 fake"


def test_file_payload_accepts_file_key_and_traversal_name(monkeypatch, tmp_path):
    _stub_dingtalk_download(monkeypatch, tmp_path)
    event = FakeEvent(
        message_type="file",
        extensions={"file": {"downloadCode": "dl-code", "fileName": r"..\..\evil.pdf"}},
    )
    msg = DingTalkMessage(event, FakeHandler())
    assert msg.ctype == ContextType.FILE
    assert os.path.dirname(msg.file_path) == str(tmp_path)
    assert os.path.basename(msg.file_path).endswith("evil.pdf")
    assert ".." not in os.path.basename(msg.file_path)


def test_file_message_missing_download_code_does_not_hit_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "channel.dingtalk.dingtalk_message.state_dir.tmp_dir",
        lambda *a, **k: tmp_path,
    )

    def boom(*a, **k):
        raise AssertionError("network should not be called")

    monkeypatch.setattr("channel.dingtalk.dingtalk_message.requests.post", boom)
    monkeypatch.setattr("channel.dingtalk.dingtalk_message.requests.get", boom)

    msg = DingTalkMessage(
        FakeEvent(message_type="file", extensions={"content": {"fileName": "a.pdf"}}),
        FakeHandler(),
    )
    assert msg.ctype == ContextType.FILE
    assert msg.file_path is None
    assert msg.content == "[文件下载失败]"


def test_picture_still_maps_to_image_png(monkeypatch, tmp_path):
    _stub_dingtalk_download(monkeypatch, tmp_path, body=b"\x89PNG")
    event = FakeEvent(
        message_type="picture",
        image_content=SimpleNamespace(download_code="dl-code"),
        image_list=["dl-code"],
    )
    msg = DingTalkMessage(event, FakeHandler())
    assert msg.ctype == ContextType.IMAGE
    assert msg.image_path.endswith(".png")
    assert os.path.isfile(msg.image_path)


def test_unknown_type_logs_instead_of_missing_image(caplog):
    with caplog.at_level("WARNING"):
        msg = DingTalkMessage(FakeEvent(message_type="video"), FakeHandler())
    assert msg.ctype is None
    assert msg.content is None
    assert any("unsupported message type: video" in rec.message for rec in caplog.records)
    assert "[未找到图片]" not in (msg.content or "")


def test_safe_filename_keeps_basename_only():
    assert _safe_filename(r"..\..\a b.pdf") == "a b.pdf"
    assert _safe_filename("") == ""


_MSG_SEQ = 0


def _make_cmsg(**kwargs):
    global _MSG_SEQ
    _MSG_SEQ += 1
    msg = ChatMessage({})
    msg.msg_id = kwargs.get("msg_id", "m-%s" % _MSG_SEQ)
    msg.create_time = kwargs.get("create_time", int(time.time() * 1000))
    msg.ctype = kwargs["ctype"]
    msg.content = kwargs.get("content", "")
    msg.from_user_id = kwargs.get("from_user_id", "sender-1")
    msg.other_user_id = kwargs.get("other_user_id", "cid-1")
    msg.is_group = kwargs.get("is_group", False)
    msg.my_msg = False
    msg.image_path = kwargs.get("image_path")
    msg.file_path = kwargs.get("file_path")
    return msg


@pytest.fixture
def dingtalk_channel(monkeypatch):
    monkeypatch.setattr(
        "agent.team_addressing.stamp_speaker_from_channel",
        lambda *a, **k: None,
        raising=False,
    )
    from channel.dingtalk.dingtalk_channel import DingTalkChanel

    get_file_cache().cache.clear()
    cls = DingTalkChanel.__wrapped__
    ch = cls.__new__(cls)
    ch.receivedMsgs = {}
    composed = []

    def compose(ctype, content, **kwargs):
        composed.append((ctype, content, kwargs.get("isgroup")))
        return {"receiver": "x"}

    ch._compose_context = compose
    ch.produce = MagicMock()
    ch._composed = composed
    yield ch
    get_file_cache().cache.clear()


def test_single_chat_caches_file_until_following_text(dingtalk_channel, tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")
    ch = dingtalk_channel

    ch.handle_single(
        _make_cmsg(
            ctype=ContextType.FILE,
            content=str(file_path),
            file_path=str(file_path),
            from_user_id="sender-1",
        )
    )
    assert ch._composed == []
    ch.produce.assert_not_called()

    ch.handle_single(
        _make_cmsg(
            ctype=ContextType.TEXT,
            content="summarize this",
            from_user_id="sender-1",
        )
    )
    assert len(ch._composed) == 1
    ctype, content, isgroup = ch._composed[0]
    assert ctype == ContextType.TEXT
    assert isgroup is False
    assert content.startswith("summarize this")
    assert "[文件: %s]" % file_path in content.replace("\\", "/") or str(file_path) in content


def test_group_chat_caches_file_until_following_text(dingtalk_channel, tmp_path):
    file_path = tmp_path / "deck.pptx"
    file_path.write_bytes(b"pptx")
    ch = dingtalk_channel

    ch.handle_group(
        _make_cmsg(
            ctype=ContextType.FILE,
            content=str(file_path),
            file_path=str(file_path),
            is_group=True,
            from_user_id="cid-9",
            other_user_id="cid-9",
        )
    )
    assert ch._composed == []

    ch.handle_group(
        _make_cmsg(
            ctype=ContextType.TEXT,
            content="what is in the deck?",
            is_group=True,
            from_user_id="cid-9",
            other_user_id="cid-9",
        )
    )
    assert len(ch._composed) == 1
    ctype, content, isgroup = ch._composed[0]
    assert ctype == ContextType.TEXT
    assert isgroup is True
    assert "what is in the deck?" in content
    assert str(file_path) in content


def test_failed_file_download_is_not_cached(dingtalk_channel):
    ch = dingtalk_channel
    ch.handle_single(
        _make_cmsg(
            ctype=ContextType.FILE,
            content="[文件下载失败]",
            file_path=None,
            from_user_id="sender-1",
        )
    )
    ch.handle_single(
        _make_cmsg(
            ctype=ContextType.TEXT,
            content="hello",
            from_user_id="sender-1",
        )
    )
    ctype, content, _ = ch._composed[0]
    assert content == "hello"


def test_unsupported_type_does_not_produce(dingtalk_channel):
    ch = dingtalk_channel
    ch.handle_single(_make_cmsg(ctype=None, content=None, from_user_id="sender-1"))
    assert ch._composed == []
    ch.produce.assert_not_called()
