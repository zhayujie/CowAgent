"""WeCom bot media replies remove every file they download or derive, but never a local file."""

import base64
import inspect
import os

import pytest

from channel.wecom_bot import wecom_bot_channel as mod

# A real 1x1 PNG: _ensure_image_format identifies the format by its bytes.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(mod.state_dir, "tmp_dir", lambda: root)
    return root


@pytest.fixture
def channel(workspace, monkeypatch):
    cls = mod.WecomBotChannel.__wrapped__
    handle = cls.__new__(cls)
    handle.uploads = []

    def _upload(local_path, media_type, file_name=""):
        with open(local_path, "rb") as fh:
            handle.uploads.append((os.path.basename(local_path), len(fh.read())))
        return f"media-{len(handle.uploads)}"

    def _download(url, prefix, ext, max_bytes, read_timeout, max_seconds=None):
        path = mod.state_dir.tmp_file(prefix, ext or ".bin")
        with open(path, "wb") as fh:
            fh.write(_PNG)
        return path, len(_PNG), "image/png"

    handle._upload_media = _upload
    handle._ws_send = lambda payload: None
    handle._send_text = lambda text, *a, **k: None
    handle._gen_req_id = lambda: "req-1"
    monkeypatch.setattr(mod, "_download_remote_media", _download)
    return handle


def _leftovers(workspace):
    return sorted(p.name for p in workspace.iterdir())


@pytest.mark.parametrize("sender,url", [("_send_image", "https://example.com/a.png"),
                                        ("_send_file", "https://example.com/a.pdf")])
def test_a_remote_reply_leaves_nothing_behind(channel, workspace, sender, url):
    getattr(channel, sender)(url, "chat-1", False)

    assert channel.uploads
    assert _leftovers(workspace) == []


def test_a_failed_voice_conversion_still_removes_the_download(channel, workspace, monkeypatch):
    import voice.audio_convert as audio

    def _boom(src, dst):
        raise RuntimeError("ffmpeg unavailable")

    monkeypatch.setattr(audio, "any_to_amr", _boom)
    channel._send_voice("https://example.com/a.mp3", "chat-1", False)

    assert _leftovers(workspace) == []


def test_the_image_pipeline_removes_every_derived_file(channel, workspace):
    def _derived(name):
        path = workspace / name
        path.write_bytes(b"derived")
        return str(path)

    channel._ensure_image_format = lambda p: _derived("wecom_fmt_conv.png")
    channel._compress_image = lambda p, limit: _derived("wecom_compressed.jpg")

    channel._send_image("https://example.com/a.png", "chat-1", False)

    assert len(channel.uploads) == 1
    assert _leftovers(workspace) == []


def test_upload_or_download_failure_still_cleans_up(channel, workspace, monkeypatch):
    def _upload_fails(local_path, media_type):
        raise RuntimeError("upload failed")

    channel._upload_media = _upload_fails
    with pytest.raises(RuntimeError):
        channel._send_image("https://example.com/a.png", "chat-1", False)
    assert _leftovers(workspace) == []

    def _download_fails(*args, **kwargs):
        raise ValueError("remote media is empty")

    monkeypatch.setattr(mod, "_download_remote_media", _download_fails)
    channel._send_image("https://example.com/a.png", "chat-1", False)
    assert _leftovers(workspace) == []


@pytest.mark.parametrize("scheme", ["file://", ""])
def test_a_local_file_is_never_deleted(channel, workspace, scheme):
    local = workspace / "produced-by-agent.png"
    local.write_bytes(_PNG)

    channel._send_image(f"{scheme}{local}", "chat-1", False)

    assert local.exists()
    assert channel.uploads


def test_the_download_has_a_total_time_budget():
    default = inspect.signature(mod._download_remote_media).parameters["max_seconds"].default
    assert default == mod._MAX_REMOTE_MEDIA_SECONDS > 0
