"""Slack file replies that point at a remote URL.

In a cloud deployment the send tool publishes the file and the bridge hands the
channel its ``https://`` URL instead of a ``file://`` path
(``AgentBridge._create_file_reply``). ``SlackChannel._do_send`` passed that URL
to ``files_upload_v2`` as a local path, so the upload failed and the user never
got the file.
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from bridge.reply import Reply, ReplyType
from channel.slack.slack_channel import SlackChannel
from common import state_dir

BODY = b"%PDF-1.4 quarterly numbers"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _channel(uploads, tmp_path, monkeypatch):
    monkeypatch.setattr(state_dir, "tmp_dir", lambda *a, **k: tmp_path)

    def files_upload_v2(file, filename=None, **kwargs):
        # slack_sdk opens a str ``file`` as a local path.
        with open(file, "rb") as f:
            uploads.append((f.read(), filename or os.path.basename(file)))

    ch = SlackChannel.__wrapped__.__new__(SlackChannel.__wrapped__)
    ch._client = SimpleNamespace(files_upload_v2=files_upload_v2)
    return ch


def test_remote_file_reply_is_downloaded_and_uploaded(server, tmp_path, monkeypatch):
    uploads = []
    ch = _channel(uploads, tmp_path, monkeypatch)
    reply = Reply(ReplyType.FILE, f"{server}/cow-send/3f9a1c.pdf")
    reply.file_name = "report.pdf"

    ch.send(reply, {"slack_channel": "C1"})

    assert uploads == [(BODY, "report.pdf")]
    assert list(tmp_path.iterdir()) == [], "downloaded temp file was left behind"


def test_local_file_reply_is_unchanged(tmp_path, monkeypatch):
    uploads = []
    ch = _channel(uploads, tmp_path, monkeypatch)
    local = tmp_path / "notes.txt"
    local.write_bytes(b"hello")

    ch.send(Reply(ReplyType.FILE, f"file://{local}"), {"slack_channel": "C1"})

    assert uploads == [(b"hello", "notes.txt")]
    assert local.exists()
