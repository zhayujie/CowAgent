"""Attachment uploads keep the media kind, so the console can play them.

Audio used to be lumped in with generic files and video could not be picked
at all, while the two upload routes spelled their classification out twice.
These tests drive the real routes and pin the extension -> kind mapping.
"""

import json
import threading
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from channel.web.core._common import classify_attachment_type


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def console(tmp_path):
    workspace = tmp_path / "default"
    workspace.mkdir()
    registry = SimpleNamespace(get=lambda agent_id=None: SimpleNamespace(workspace=str(workspace)))

    from channel.web import web_channel

    with patch("channel.web.api.files._require_auth"), patch(
        "agent.registry.get_agent_registry", return_value=registry
    ):
        app = web_channel.build_app()
        server = make_server("127.0.0.1", 0, app.wsgifunc(), handler_class=_QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield SimpleNamespace(base=f"http://127.0.0.1:{server.server_address[1]}", workspace=workspace)
        finally:
            server.shutdown()
            server.server_close()


def _upload(console, filename, blob=b"media"):
    boundary = "----cowmedia"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{console.base}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


@pytest.mark.parametrize("filename,expected", [
    ("voice.mp3", "audio"),
    ("meeting.m4a", "audio"),
    ("clip.mp4", "video"),
    ("clip.mkv", "video"),
    ("photo.png", "image"),
    ("notes.txt", "file"),
])
def test_upload_reports_the_media_kind(console, filename, expected):
    result = _upload(console, filename)

    assert result["status"] == "success", result
    assert result["file_type"] == expected, result


def test_import_by_path_reports_audio(console, tmp_path):
    source = tmp_path / "recording.wav"
    source.write_bytes(b"RIFF")

    request = urllib.request.Request(
        f"{console.base}/upload",
        data=json.dumps({"local_path": str(source)}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with patch("channel.web.core.channel._is_loopback_request", return_value=True), patch(
        "channel.web.core.channel._desktop_token_matches", return_value=True
    ):
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())

    assert result["status"] == "success", result
    assert result["file_type"] == "audio", result


@pytest.mark.parametrize("ext,expected", [
    (".mp3", "audio"), (".wav", "audio"), (".flac", "audio"), (".opus", "audio"),
    (".MP4", "video"), (".mov", "video"),
    (".PNG", "image"),
    (".pdf", "file"), ("", "file"),
])
def test_extension_classification_is_case_insensitive(ext, expected):
    assert classify_attachment_type(ext) == expected


def test_audio_attachment_is_named_in_the_agent_prompt(monkeypatch):
    """The agent needs the kind, not just the path, to reach for the right tool."""
    from channel.web import web_channel
    from common import i18n

    previous_lang = i18n.get_language()
    i18n.set_language("en")
    bridge = SimpleNamespace(agent_router=SimpleNamespace(resolve=lambda **kwargs: "default"))
    monkeypatch.setattr(
        "bridge.bridge.Bridge", lambda: SimpleNamespace(get_agent_bridge=lambda: bridge)
    )
    monkeypatch.setattr("channel.web.core.channel.conf", lambda: {"single_chat_prefix": [""]})
    monkeypatch.setattr(web_channel.web, "data", lambda: json.dumps({
        "session_id": "s1",
        "message": "listen to this",
        "stream": False,
        "attachments": [{"file_type": "audio", "file_path": "/tmp/voice.mp3"}],
    }).encode())

    raw_class = web_channel.WebChannel.__closure__[0].cell_contents
    instance = object.__new__(raw_class)
    instance.request_to_session = {}
    instance.request_to_agent = {}
    instance.session_queues = {}
    instance.msg_id_counter = 0
    instance._sse_streams_lock = threading.Lock()
    instance._compose_context = lambda ctype, prompt, **kwargs: {"prompt": prompt}
    captured = {}
    handed_over = threading.Event()

    def _capture(context):
        captured["prompt"] = context["prompt"]
        handed_over.set()

    instance.produce = _capture

    try:
        response = json.loads(raw_class.post_message(instance))
        assert response["status"] == "success", response
        assert handed_over.wait(5), "post_message never handed the turn to produce()"
    finally:
        i18n.set_language(previous_lang)

    assert "[Audio: /tmp/voice.mp3]" in captured["prompt"]
