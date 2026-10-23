"""Discord file replies that point at a remote URL.

In a cloud deployment the send tool publishes the file and the bridge hands the
channel its ``https://`` URL instead of a ``file://`` path
(``AgentBridge._create_file_reply``). ``DiscordChannel._async_send`` passed that
URL to ``discord.File`` as a local path, so the upload failed and the user never
got the file.
"""
import asyncio
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bridge.reply import Reply, ReplyType
from channel.discord import discord_channel as mod
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


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


class _File:
    """Reads the file up front, as ``discord.File`` opens a str path on construction."""

    def __init__(self, fp, filename=None):
        with open(fp, "rb") as f:
            self.body = f.read()
        self.filename = filename


def _channel(loop, sends, tmp_path, monkeypatch):
    monkeypatch.setattr(state_dir, "tmp_dir", lambda *a, **k: tmp_path)
    discord = types.ModuleType("discord")
    discord.File = _File
    monkeypatch.setitem(sys.modules, "discord", discord)

    async def send(content=None, file=None):
        sends.append((content, file.body, file.filename))

    cls = mod.DiscordChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._loop = loop
    ch._client = types.SimpleNamespace(get_channel=lambda _id: types.SimpleNamespace(send=send))
    return ch


def test_remote_file_reply_is_downloaded_and_uploaded(server, loop, tmp_path, monkeypatch):
    sends = []
    ch = _channel(loop, sends, tmp_path, monkeypatch)
    reply = Reply(ReplyType.FILE, f"{server}/cow-send/3f9a1c.pdf")
    reply.file_name = "report.pdf"

    ch.send(reply, {"discord_channel_id": 7})

    assert sends == [(None, BODY, "report.pdf")]
    assert list(tmp_path.iterdir()) == [], "downloaded temp file was left behind"
    assert reply.content == f"{server}/cow-send/3f9a1c.pdf"


def test_local_file_reply_is_unchanged(loop, tmp_path, monkeypatch):
    sends = []
    ch = _channel(loop, sends, tmp_path, monkeypatch)
    local = tmp_path / "notes.txt"
    local.write_bytes(b"hello")

    ch.send(Reply(ReplyType.FILE, f"file://{local}"), {"discord_channel_id": 7})

    assert sends == [(None, b"hello", None)]
    assert local.exists()
