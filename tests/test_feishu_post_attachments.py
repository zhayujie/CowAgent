"""Feishu post messages must keep both the caption and any attached files."""

import json
from pathlib import Path

from channel.feishu import feishu_message


def _event(content):
    return {
        "app_id": "bot",
        "sender": {"sender_id": {"open_id": "user"}},
        "message": {
            "message_id": "message-1",
            "chat_id": "chat-1",
            "message_type": "post",
            "content": json.dumps(content),
        },
    }


def _fake_download(monkeypatch, fail_keys=()):
    calls = []

    def download(message_id, key, resource_type, access_token, path, max_bytes, domain=None):
        calls.append((key, resource_type, path))
        if key in fail_keys:
            return False
        Path(path).write_bytes(b"data")
        return True

    monkeypatch.setattr(feishu_message, "_download_resource", download)
    return calls


def test_caption_with_top_level_file_keeps_text_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    calls = _fake_download(monkeypatch)

    post = {
        "title": "",
        "content": [[{"tag": "text", "text": "interview brief"}]],
        "files": [{"file_key": "file_v3_abc", "file_name": "brief.md", "is_folder": False}],
    }
    message = feishu_message.FeishuMessage(_event(post), access_token="token")

    file_path = str(tmp_path / "file_v3_abc.md")
    assert message.content == f"interview brief\n[文件: {file_path}]"
    assert message.post_text == "interview brief"
    assert message.attachments == [(file_path, "file")]
    assert calls == [("file_v3_abc", "file", file_path)]


def test_locale_wrapped_post_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    _fake_download(monkeypatch)

    post = {
        "zh_cn": {
            "title": "",
            "content": [[{"tag": "text", "text": "hello"}, {"tag": "a", "text": "doc", "href": "https://x.y"}]],
        },
        "files": [{"file_key": "file-1", "file_name": "a.pdf"}],
    }
    message = feishu_message.FeishuMessage(_event(post), access_token="token")

    assert message.content.startswith("hello\ndoc (https://x.y)\n[文件: ")
    assert message.attachments == [(str(tmp_path / "file-1.pdf"), "file")]


def test_files_without_caption_have_no_post_text(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    _fake_download(monkeypatch, fail_keys={"file-2"})

    post = {
        "title": "",
        "content": [],
        "files": [
            {"file_key": "file-1", "file_name": "a.txt"},
            {"file_key": "file-2", "file_name": "b.txt"},
            {"file_key": "folder-1", "file_name": "dir", "is_folder": True},
        ],
    }
    message = feishu_message.FeishuMessage(_event(post), access_token="token")

    assert message.post_text == ""
    assert message.has_file_attachments
    assert message.attachments == [(str(tmp_path / "file-1.txt"), "file")]
    assert message.failed_files == ["b.txt"]
    assert "[文件夹: dir]" in message.content


def test_media_element_is_downloaded_as_video(tmp_path, monkeypatch):
    monkeypatch.setattr(feishu_message.state_dir, "tmp_dir", lambda: tmp_path)
    _fake_download(monkeypatch)

    post = {"content": [[{"tag": "text", "text": "look"}], [{"tag": "media", "file_key": "vid-1", "image_key": "cover"}]]}
    message = feishu_message.FeishuMessage(_event(post), access_token="token")

    video_path = str(tmp_path / "vid-1.mp4")
    assert message.content == f"look\n[视频: {video_path}]"
    assert message.attachments == [(video_path, "video")]
