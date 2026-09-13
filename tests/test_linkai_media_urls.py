# encoding:utf-8
"""Regression tests for LinkAI media URL classification."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Channel:
    def __init__(self):
        self.sent = []

    def send(self, reply, context):
        self.sent.append(reply)


def _send(monkeypatch, url):
    from config import conf
    from models.linkai import link_ai_bot
    from models.linkai.link_ai_bot import LinkAIBot

    monkeypatch.setitem(conf(), "max_media_send_count", 10)
    monkeypatch.setitem(conf(), "media_send_interval", 0)
    monkeypatch.setattr(link_ai_bot, "_download_file", lambda u: u)

    channel = _Channel()
    LinkAIBot._send_image(LinkAIBot.__new__(LinkAIBot), channel, None, [url])
    return [r.type.name for r in channel.sent]


def test_plain_image_url_is_sent_as_image(monkeypatch):
    assert _send(monkeypatch, "https://cdn.example.com/pic.png") == ["IMAGE_URL"]


def test_video_url_with_query_is_sent_as_video(monkeypatch):
    assert _send(monkeypatch, "https://cdn.example.com/clip.mp4?token=abc") == ["VIDEO_URL"]


def test_uppercase_extension_is_recognized(monkeypatch):
    assert _send(monkeypatch, "https://cdn.example.com/clip.MP4") == ["VIDEO_URL"]


def test_file_url_with_query_is_sent_as_file(monkeypatch):
    assert _send(monkeypatch, "https://cdn.example.com/report.pdf?sig=xyz") == ["FILE"]


def test_downloaded_file_name_excludes_query(monkeypatch, tmp_path):
    from models.linkai import link_ai_bot

    monkeypatch.setattr(
        link_ai_bot.requests, "get", lambda url, **kw: type("R", (), {"content": b"x"})()
    )
    monkeypatch.chdir(tmp_path)
    path = link_ai_bot._download_file("https://cdn.example.com/report.pdf?sig=1")
    assert os.path.basename(path) == "report.pdf"
