import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from channel.feishu.feishu_message import FeishuMessage


def _event(parent_id="om_parent", text="What does this mean?"):
    return {
        "app_id": "cli_bot",
        "sender": {"sender_id": {"open_id": "ou_user"}},
        "message": {
            "message_id": "om_child",
            "parent_id": parent_id,
            "chat_id": "oc_chat",
            "message_type": "text",
            "content": json.dumps({"text": text}),
        },
    }


def _response(body, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: body)


def test_text_reply_fetches_parent_without_replacing_user_message(monkeypatch):
    response = _response(
        {
            "code": 0,
            "data": {
                "items": [
                    {
                        "msg_type": "text",
                        "body": {"content": json.dumps({"text": "Original answer"})},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(
        "channel.feishu.feishu_message.requests.get", lambda **kwargs: response
    )

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert message.content == "What does this mean?"
    assert message.quoted_content == "Original answer"
    assert message.content_with_quote() == (
        "[Quoted message]\nOriginal answer\n[/Quoted message]\n\n"
        "What does this mean?"
    )


def test_post_reply_extracts_title_and_text(monkeypatch):
    post = {
        "title": "Release note",
        "content": [
            [
                {"tag": "text", "text": "Fixed the scheduler."},
                {"tag": "a", "text": "Details", "href": "https://example.com"},
            ]
        ],
    }
    response = _response(
        {
            "code": 0,
            "data": {
                "items": [
                    {"msg_type": "post", "body": {"content": json.dumps(post)}}
                ]
            },
        }
    )
    monkeypatch.setattr(
        "channel.feishu.feishu_message.requests.get", lambda **kwargs: response
    )

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert message.quoted_content == (
        "Release note\nFixed the scheduler.\nDetails (https://example.com)"
    )


def test_quoted_image_is_downloaded_and_added_as_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    post = {
        "msg_type": "image",
        "body": {"content": json.dumps({"image_key": "quoted-image"})},
    }
    response = _response({"code": 0, "data": {"items": [post]}})
    monkeypatch.setattr(
        "channel.feishu.feishu_message.requests.get", lambda **kwargs: response
    )
    monkeypatch.setattr(
        "channel.feishu.feishu_message.download_to_file",
        lambda url, path, *args, **kwargs: open(path, "wb").write(b"image-bytes"),
    )

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert len(message.attachments) == 1
    image_path, image_type = message.attachments[0]
    assert image_type == "image"
    assert open(image_path, "rb").read() == b"image-bytes"
    marker = "[图片: " + image_path + "]"
    assert marker in message.quoted_content
    assert marker in message.content_with_quote()
    assert "[Image]" not in message.quoted_content


def test_quoted_post_downloads_all_images(tmp_path, monkeypatch):
    monkeypatch.setattr("channel.feishu.feishu_message.state_dir.tmp_dir", lambda: tmp_path)
    post = {
        "msg_type": "post",
        "body": {"content": json.dumps({
            "content": [[
                {"tag": "text", "text": "caption"},
                {"tag": "img", "image_key": "image-1"},
                {"tag": "img", "image_key": "image-2"},
            ]]
        })},
    }
    response = _response({"code": 0, "data": {"items": [post]}})
    monkeypatch.setattr(
        "channel.feishu.feishu_message.requests.get", lambda **kwargs: response
    )
    monkeypatch.setattr(
        "channel.feishu.feishu_message.download_to_file",
        lambda url, path, *args, **kwargs: open(path, "wb").write(b"image-bytes"),
    )

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert [kind for _, kind in message.attachments] == ["image", "image"]
    assert "caption" in message.quoted_content
    assert message.quoted_content.count("[图片: ") == 2


def test_quote_fetch_failure_keeps_current_message_usable(monkeypatch):
    def fail(**kwargs):
        raise TimeoutError("network timeout")

    monkeypatch.setattr("channel.feishu.feishu_message.requests.get", fail)

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert message.quoted_content == ""
    assert message.content_with_quote() == "What does this mean?"


def test_message_without_parent_does_not_fetch(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("quote API should not be called")

    monkeypatch.setattr("channel.feishu.feishu_message.requests.get", unexpected)

    message = FeishuMessage(_event(parent_id=""), access_token="tenant-token")

    assert message.quoted_content == ""
    assert message.content_with_quote() == "What does this mean?"


def test_quoted_post_keeps_code_blocks(monkeypatch):
    post = {
        "title": "",
        "content": [
            [{"tag": "text", "text": "The job fails with:"}],
            [{"tag": "code_block", "language": "PYTHON", "text": "KeyError: 'user_id'"}],
        ],
    }
    response = _response(
        {
            "code": 0,
            "data": {
                "items": [
                    {"msg_type": "post", "body": {"content": json.dumps(post)}}
                ]
            },
        }
    )
    monkeypatch.setattr(
        "channel.feishu.feishu_message.requests.get", lambda **kwargs: response
    )

    message = FeishuMessage(_event(), access_token="tenant-token")

    assert message.quoted_content == "The job fails with:\nKeyError: 'user_id'"


@pytest.mark.parametrize("cached_quote", ["absent", "present", "missing_file"])
def test_quote_reuses_only_its_conversations_pending_images(tmp_path, monkeypatch, cached_quote):
    from agent.protocol.agent_stream import _IMAGE_MARKER_RE
    from channel.feishu.feishu_channel import FeiShuChanel
    from channel.file_cache import FileCache
    from common import state_dir

    monkeypatch.setattr(state_dir, "tmp_dir", lambda: tmp_path)
    cache = FileCache()
    monkeypatch.setattr("channel.file_cache.get_file_cache", lambda: cache)
    monkeypatch.setattr("channel.feishu.feishu_channel._ensure_lark_imported", lambda: None)
    downloads = []
    downloaded_paths = {}

    def download(message_id, key, kind, token, path, limit, **kwargs):
        downloads.append((message_id, key))
        downloaded_paths[message_id] = Path(path)
        downloaded_paths[message_id].write_bytes(key.encode())
        return True

    monkeypatch.setattr("channel.feishu.feishu_message._download_resource", download)
    quote = {"msg_type": "image", "body": {"content": json.dumps({"image_key": "quoted"})}}
    monkeypatch.setattr("channel.feishu.feishu_message.requests.get", lambda **kwargs:
                        _response({"code": 0, "data": {"items": [quote]}}))

    def make_channel(instance_id):
        channel = FeiShuChanel.new_instance()
        channel.apply_instance(instance_id, "team", {"feishu_app_id": "cli_bot"})
        monkeypatch.setattr(channel, "fetch_access_token", lambda: "tenant-token")
        monkeypatch.setattr(channel, "_make_feishu_stream_callback", lambda *_: None)
        monkeypatch.setattr(channel, "produce", contexts.append)
        return channel

    def event(message_id, sender="ou_user", parent_id=None, image_key=None):
        payload = _event(parent_id)
        payload["sender"] = {"sender_id": {"open_id": sender}, "sender_type": "user"}
        payload["message"].update(message_id=message_id, chat_type="p2p")
        if image_key:
            payload["message"].update(message_type="image", content=json.dumps({"image_key": image_key}))
        return payload

    contexts = []
    channel = make_channel("feishu-one")
    other_bot = make_channel("feishu-two")
    channel._handle_message_event(event("om_image", image_key="ordinary"))
    if cached_quote != "absent":
        channel._handle_message_event(event("om_parent", image_key="quoted"))
        if cached_quote == "missing_file":
            downloaded_paths["om_parent"].unlink()
    other_bot._handle_message_event(event("om_other_bot"))
    channel._handle_message_event(event("om_other_user", sender="ou_other"))
    channel._handle_message_event(event("om_query", parent_id="om_parent"))
    assert len(contexts) == 3
    assert all(not _IMAGE_MARKER_RE.search(ctx.content) for ctx in contexts[:2])
    query = contexts[-1]
    assert query["bound_agent_id"] == "team"
    images = _IMAGE_MARKER_RE.findall(query.content)
    assert [Path(path).read_bytes() for path in images] == [b"quoted", b"ordinary"]
    quote_downloads = 2 if cached_quote == "missing_file" else 1
    assert downloads == [("om_image", "ordinary")] + [("om_parent", "quoted")] * quote_downloads
    channel._handle_message_event(event("om_next_query"))
    assert not _IMAGE_MARKER_RE.search(contexts[-1].content)
