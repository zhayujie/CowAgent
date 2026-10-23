"""Telegram file replies that point at a remote URL.

In a cloud deployment the send tool publishes the file and the bridge hands the
channel its ``https://`` URL instead of a ``file://`` path
(``AgentBridge._create_file_reply``). The FILE/VIDEO branch of
``TelegramChannel._async_send`` opened that URL as a local path, so the upload
failed with FileNotFoundError and the user never got the file.
"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bridge.reply import Reply, ReplyType
from channel.telegram import telegram_channel as mod
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


class _Bot:
    def __init__(self):
        self.documents = []

    async def send_document(self, chat_id, document, filename=None, **kwargs):
        self.documents.append((document.read(), filename))


def _channel(loop, bot, tmp_path, monkeypatch):
    monkeypatch.setattr(state_dir, "tmp_dir", lambda *a, **k: tmp_path)
    cls = mod.TelegramChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._loop = loop
    ch._bot = bot
    return ch


def test_remote_file_reply_is_downloaded_and_uploaded(server, loop, tmp_path, monkeypatch):
    bot = _Bot()
    ch = _channel(loop, bot, tmp_path, monkeypatch)
    reply = Reply(ReplyType.FILE, f"{server}/cow-send/3f9a1c.pdf")
    reply.file_name = "report.pdf"

    ch.send(reply, {"telegram_chat_id": 42})

    assert bot.documents == [(BODY, "report.pdf")]
    assert list(tmp_path.iterdir()) == [], "downloaded temp file was left behind"
    assert reply.content == f"{server}/cow-send/3f9a1c.pdf"


def test_local_file_reply_is_unchanged(loop, tmp_path, monkeypatch):
    bot = _Bot()
    ch = _channel(loop, bot, tmp_path, monkeypatch)
    local = tmp_path / "notes.txt"
    local.write_bytes(b"hello")

    ch.send(Reply(ReplyType.FILE, f"file://{local}"), {"telegram_chat_id": 42})

    assert bot.documents == [(b"hello", None)]
    assert local.exists()


def test_unreachable_remote_file_sends_nothing(loop, tmp_path, monkeypatch):
    bot = _Bot()
    ch = _channel(loop, bot, tmp_path, monkeypatch)

    ch.send(Reply(ReplyType.FILE, "http://127.0.0.1:9/missing.pdf"), {"telegram_chat_id": 42})

    assert bot.documents == []
    assert list(tmp_path.iterdir()) == []
