"""Regression tests for URL replies from the keyword plugin."""

from types import SimpleNamespace
from unittest.mock import patch

from bridge.context import Context, ContextType
from bridge.reply import ReplyType
import plugins
from plugins import Event, EventContext

plugins.instance.current_plugin_path = "./plugins/keyword"
import plugins.keyword.keyword  # noqa: F401
plugins.instance.current_plugin_path = None

Keyword = plugins.instance.plugins["KEYWORD"]


def _handle(reply_text):
    plugin = Keyword.__new__(Keyword)
    plugin.keyword = {"download": reply_text}
    event = EventContext(
        Event.ON_HANDLE_CONTEXT,
        {"context": Context(ContextType.TEXT, "download"), "reply": None},
    )
    plugin.on_handle_context(event)
    return event["reply"]


def test_image_url_with_query_string_is_detected():
    reply = _handle("https://cdn.example.com/banner.PNG?version=2")

    assert reply.type is ReplyType.IMAGE_URL
    assert reply.content == "https://cdn.example.com/banner.PNG?version=2"


def test_video_url_with_query_string_is_detected():
    reply = _handle("https://cdn.example.com/demo.MP4?download=1")

    assert reply.type is ReplyType.VIDEO_URL


def test_http_scheme_without_host_remains_text():
    reply = _handle("https:report.xlsx")

    assert reply.type is ReplyType.TEXT


def test_xlsx_url_uses_path_filename_without_query_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = SimpleNamespace(content=b"spreadsheet")

    with patch("plugins.keyword.keyword.requests.get", return_value=response):
        reply = _handle("https://cdn.example.com/report.XLSX?token=secret")

    assert reply.type is ReplyType.FILE
    assert reply.content == "tmp/report.XLSX"
    assert (tmp_path / reply.content).read_bytes() == b"spreadsheet"
