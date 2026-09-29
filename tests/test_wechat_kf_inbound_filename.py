"""wechat_kf inbound file: the server-supplied name stays one path component.

``channel/chat_message.py::safe_filename`` states the contract -- every inbound
attachment is written to ``tmp_dir()/<file_name>``, so a name holding a path
separator has to be reduced before it reaches ``os.path.join``. weixin gets
that guard from a371f371; slack, discord, qq and dingtalk sanitize their own
inbound names. The WeCom customer-service channel parses its name out of the
``Content-Disposition`` header of the media download and used it as-is.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from bridge.context import ContextType
from channel.wechat_kf import wechat_kf_message as mod
from channel.wechat_kf.wechat_kf_message import WechatKfMessage

MEDIA_ID = "3rDPHxBQtdWeQLzxwpT-HNYw2eXba7ma9lQc"

HOSTILE = [
    ('attachment; filename="../../outside.txt"', "outside.txt"),
    ("attachment; filename*=UTF-8''..%2F..%2Fevil.pdf", "evil.pdf"),
    ('attachment; filename="sub/dir/quarterly.pdf"', "quarterly.pdf"),
    (r'attachment; filename="..\..\windows\temp\x.txt"', "x.txt"),
]


class _FakeMedia:
    def __init__(self, disposition):
        self._disposition = disposition

    def download(self, media_id):
        headers = {} if self._disposition is None else {"Content-Disposition": self._disposition}
        return SimpleNamespace(status_code=200, headers=headers, content=b"payload")


class _FakeClient:
    def __init__(self, disposition):
        self.media = _FakeMedia(disposition)


def _message(tmp_path, monkeypatch, disposition, msgtype="file"):
    monkeypatch.setattr(mod, "_get_tmp_dir", lambda: str(tmp_path))
    raw = {
        "msgid": "kfmsg001",
        "send_time": 1700000000,
        "origin": 3,
        "msgtype": msgtype,
        "open_kfid": "wk_open_kfid",
        "external_userid": "wm_external_userid",
        msgtype: {"media_id": MEDIA_ID},
    }
    return WechatKfMessage(msg=raw, client=_FakeClient(disposition))


@pytest.mark.parametrize("disposition,expected", HOSTILE)
def test_a_name_with_a_separator_stays_inside_the_tmp_dir(tmp_path, monkeypatch, disposition, expected):
    msg = _message(tmp_path, monkeypatch, disposition)
    msg.prepare()

    assert msg.ctype == ContextType.FILE
    path = Path(msg.content)
    assert path.parent == tmp_path, f"{msg.content} left the tmp dir"
    assert path.name == expected
    assert path.read_bytes() == b"payload", "the download itself must still happen"
    assert not (tmp_path.parent / expected).exists(), "nothing may land above the tmp dir"


def test_an_ordinary_name_is_still_the_one_the_server_handed_back(tmp_path, monkeypatch):
    msg = _message(tmp_path, monkeypatch, 'attachment; filename="report 2024.pdf"')
    msg.prepare()

    assert Path(msg.content).name == "report 2024.pdf"
    assert Path(msg.content).read_bytes() == b"payload"


@pytest.mark.parametrize(
    "disposition",
    [None, "", 'attachment; filename=""', "inline; size=12"],
)
def test_a_response_without_a_usable_name_falls_back_to_the_media_id(tmp_path, monkeypatch, disposition):
    msg = _message(tmp_path, monkeypatch, disposition)
    msg.prepare()

    assert Path(msg.content) == tmp_path / MEDIA_ID
    assert Path(msg.content).read_bytes() == b"payload"


def test_the_image_branch_is_unchanged(tmp_path, monkeypatch):
    msg = _message(tmp_path, monkeypatch, None, msgtype="image")
    msg.prepare()

    assert msg.ctype == ContextType.IMAGE
    assert Path(msg.content) == tmp_path / (MEDIA_ID + ".jpg")
    assert Path(msg.content).read_bytes() == b"payload"
