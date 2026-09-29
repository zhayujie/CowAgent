"""Regression tests for URL replies from the keyword plugin."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

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


def test_xlsx_url_uses_path_filename_without_query_string(tmp_path):
    # The attachment goes to the agent's managed tmp dir, not a `tmp/` resolved
    # against the process CWD: the packaged desktop app does not control its CWD
    # and may not be able to write there. Pin an agent so the dir is knowable.
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
    from common import state_dir

    set_agent_registry(
        AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1")
    )
    try:
        expected_dir = state_dir.tmp_dir()
        response = SimpleNamespace(status_code=200, content=b"spreadsheet")

        with patch("plugins.keyword.keyword.requests.get", return_value=response):
            reply = _handle("https://cdn.example.com/report.XLSX?token=secret")

        assert reply.type is ReplyType.FILE
        # The query string must not leak into the saved name.
        assert Path(reply.content).name == "report.XLSX"
        assert Path(reply.content).parent == expected_dir
        assert Path(reply.content).read_bytes() == b"spreadsheet"
    finally:
        set_agent_registry(None)


def test_failed_download_is_reported_instead_of_saved(tmp_path):
    # A 404 is the host's error page, not the document the keyword points at.
    # Saving it as `report.XLSX` and replying FILE hands the user a corrupt file
    # under a confident name; the failure has to surface instead.
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
    from common import state_dir

    set_agent_registry(
        AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1")
    )
    try:
        expected_dir = state_dir.tmp_dir()
        response = SimpleNamespace(status_code=404, content=b"<html>404</html>")

        with patch("plugins.keyword.keyword.requests.get", return_value=response):
            reply = _handle("https://cdn.example.com/report.XLSX")

        assert reply.type is ReplyType.ERROR
        # Nothing was written: the error page must not become the user's file.
        assert list(expected_dir.glob("report*")) == []
    finally:
        set_agent_registry(None)


def test_unreachable_host_is_reported_instead_of_raising(tmp_path):
    # A refused or timed-out connection raises out of requests. That reaches only
    # the worker's log, so the user gets no reply at all; the keyword has to
    # answer with the failure.
    from agent.registry import AgentProfile, AgentRegistry, set_agent_registry

    set_agent_registry(
        AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1")
    )
    try:
        with patch(
            "plugins.keyword.keyword.requests.get",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            reply = _handle("https://cdn.example.com/report.XLSX")

        assert reply.type is ReplyType.ERROR
        assert "ConnectionError" in reply.content
        # The URL may carry a token; the error must not echo it back.
        assert "cdn.example.com" not in reply.content
    finally:
        set_agent_registry(None)
