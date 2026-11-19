# encoding:utf-8
"""File replies are shown under ``reply.file_name`` when the bridge sets it.

A file served from a URL is often stored under a random name; using the URL's
last segment would rename the user's document.
"""
import types
from unittest.mock import MagicMock, patch

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

URL = "https://files.example.com/send/3f2a9c.docx"


def _file_reply(name="季度报告.docx"):
    reply = Reply(ReplyType.FILE, URL)
    reply.file_name = name
    return reply


def test_feishu_uploads_under_the_reply_name():
    from channel.feishu import feishu_channel as mod

    posts = []

    def post(url, files=None, data=None, headers=None, timeout=None):
        posts.append({"files": files, "data": data})
        return types.SimpleNamespace(content=b"{}", json=lambda: {"code": 0, "data": {"file_key": "fk"}})

    ch = mod.FeiShuChanel.__wrapped__.__new__(mod.FeiShuChanel.__wrapped__)
    with patch.object(mod, "download_bytes", return_value=b"doc"), \
            patch.object(mod.requests, "post", side_effect=post):
        assert ch._upload_file_url(URL, "token", "季度报告.docx") == "fk"
        assert ch._upload_file_url(URL, "token") == "fk"

    assert posts[0]["data"] == {"file_type": "doc", "file_name": "季度报告.docx"}
    assert posts[0]["files"]["file"][0] == "季度报告.docx"
    assert posts[1]["data"]["file_name"] == "3f2a9c.docx"


def test_dingtalk_file_message_uses_the_reply_name():
    from channel.dingtalk import dingtalk_channel as mod

    ch = mod.DingTalkChanel.__wrapped__.__new__(mod.DingTalkChanel.__wrapped__)
    ch._robot_code = "rb-1"
    ch.get_access_token = lambda: "token"
    ch.reply_text = lambda *a, **k: None
    ch.upload_media = lambda path, media_type="image": "media-1"
    sent = []
    ch._send_file_message = lambda token, msg, key, param, is_group: sent.append(param) or True
    context = Context(ContextType.TEXT, "", {
        "receiver": "u-1",
        "msg": types.SimpleNamespace(is_group=False, incoming_message=object(), robot_code="rb-1"),
    })

    ch.send(_file_reply(), context)

    assert sent[0]["fileName"] == "季度报告.docx"
    assert sent[0]["fileType"] == "docx"


def test_wecom_bot_uploads_under_the_reply_name():
    from channel.wecom_bot import wecom_bot_channel as mod

    ch = mod.WecomBotChannel.__wrapped__.__new__(mod.WecomBotChannel.__wrapped__)
    ch._ws_send = lambda data: None
    ch._gen_req_id = lambda: "req-1"
    names = []
    ch._upload_media = lambda path, media_type="file", file_name="": names.append(file_name) or "media-id"

    def download(url, prefix, ext, max_bytes, read_timeout, max_seconds=None):
        path = mod.state_dir.tmp_file(prefix, ext)
        with open(path, "wb") as f:
            f.write(b"doc")
        return path, 3, ""

    with patch.object(mod, "_download_remote_media", side_effect=download):
        ch._send_file(URL, "chat-1", False, file_name="季度报告.docx")

    assert names == ["季度报告.docx"]


def test_wecom_bot_upload_init_carries_the_name(tmp_path):
    from channel.wecom_bot import wecom_bot_channel as mod

    ch = mod.WecomBotChannel.__wrapped__.__new__(mod.WecomBotChannel.__wrapped__)
    ch._gen_req_id = lambda: "req-1"
    sent = []
    ch._send_and_wait = lambda payload, timeout=None: sent.append(payload) or {"errcode": 1}
    path = tmp_path / "wecom_file_1a2b.docx"
    path.write_bytes(b"document")

    ch._upload_media(str(path), "file", "季度报告.docx")

    assert sent[0]["body"]["filename"] == "季度报告.docx"


def _kf_channel():
    from channel.wechat_kf.wechat_kf_channel import WechatKfChannel

    ch = WechatKfChannel.__wrapped__.__new__(WechatKfChannel.__wrapped__)
    ch.client = MagicMock()
    ch.client.media.upload.return_value = {"media_id": "media-1"}
    ch._send_file = lambda *a, **k: None
    return ch


class _KfCtx(dict):
    kwargs = {}


def test_wechat_kf_sends_a_remote_file_under_the_reply_name():
    from channel.wechat_kf import wechat_kf_channel as mod

    ch = _kf_channel()
    ctx = _KfCtx({"receiver": "user-1", "external_userid": "ext-1", "open_kfid": "kf-1"})
    with patch.object(mod, "download_bytes", return_value=b"doc") as download:
        ch.send(_file_reply(), ctx)

    assert download.call_args.args[0] == URL
    assert ch.client.media.upload.call_args.args == ("file", ("季度报告.docx", b"doc"))
