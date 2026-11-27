"""Lazily downloaded voice/video lands on the path the context already carries.

The message is parsed on the poll thread before an Agent is bound, while the
download runs on the worker thread after binding, so tmp_dir() resolves to two
different directories. The download must reuse the announced path.
"""

from pathlib import Path

import pytest

from channel.weixin import weixin_message as messages


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    receive_dir, worker_dir = tmp_path / "shared", tmp_path / "agent"
    receive_dir.mkdir()
    worker_dir.mkdir()
    current = {"dir": receive_dir}
    monkeypatch.setattr(messages, "_get_tmp_dir", lambda: str(current["dir"]))

    def fake_download(_base, _param, _key, save_path):
        Path(save_path).write_bytes(b"media")

    monkeypatch.setattr(messages, "download_media_from_cdn", fake_download)
    return current, receive_dir, worker_dir


def _media_msg(item_type, key):
    raw = {"message_id": "m1", "from_user_id": "u", "to_user_id": "bot",
           "item_list": [{"type": item_type, key: {
               "media": {"encrypt_query_param": "q", "aes_key": "00" * 16}}}]}
    return messages.WeixinMessage(raw, cdn_base_url="http://cdn.invalid")


@pytest.mark.parametrize("item_type,key", [
    (messages.ITEM_VOICE, "voice_item"),
    (messages.ITEM_VIDEO, "video_item"),
])
def test_download_reuses_the_announced_path(dirs, item_type, key):
    current, receive_dir, worker_dir = dirs
    msg = _media_msg(item_type, key)
    announced = msg.content
    assert Path(announced).parent == receive_dir

    current["dir"] = worker_dir
    msg.prepare()

    assert msg.content == announced
    assert Path(announced).read_bytes() == b"media"
    assert not any(worker_dir.iterdir())
