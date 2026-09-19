"""Transient wecom_bot media must live in the agent's managed tmp dir.

Regression test for the eight ``/tmp/...`` literals this channel used to
write. On Windows a bare ``/tmp`` resolves against the *current drive*, so the
same process writes to a different disk depending on where it was launched.
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from channel.wecom_bot import wecom_bot_channel as wbc
from common import state_dir

CHANNEL_CLS = wbc.WecomBotChannel.__wrapped__


@pytest.fixture
def agent_workspace(tmp_path):
    set_agent_registry(AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1"))
    yield tmp_path
    # None, not the previous instance: an instance argument re-pins the
    # registry and would leak this workspace into the later tests.
    set_agent_registry(None)


def _channel(uploads):
    # __init__ touches the global conf; these methods only need the two hooks.
    ch = CHANNEL_CLS.__new__(CHANNEL_CLS)
    ch._ws_send = lambda data: None
    ch._upload_media = lambda path, media_type="file": (uploads.append(path), "media-id")[1]
    return ch


def _fake_response():
    resp = Mock()
    resp.content = b"payload"
    resp.raise_for_status = lambda: None
    return resp


def test_downloaded_replies_are_uploaded_from_the_agent_tmp_dir(agent_workspace):
    uploads = []
    ch = _channel(uploads)
    with patch.object(wbc.requests, "get", return_value=_fake_response()):
        ch._send_file("https://files.example.com/report.pdf", "recv-1", is_group=False)
        ch._send_voice("https://files.example.com/note.amr", "recv-1", is_group=False)

    assert len(uploads) == 2, "both replies must reach the upload step"
    assert [str(Path(path).parent) for path in uploads] == [str(state_dir.tmp_dir())] * 2


def test_the_callback_image_cache_is_written_to_the_agent_tmp_dir(agent_workspace):
    ch = _channel([])
    with patch.object(wbc.requests, "get", return_value=_fake_response()):
        # The cache unlinks itself from a finally block. That cleanup is not
        # what this test asserts on, so the leftover file is the evidence.
        with patch.object(wbc.os, "remove"):
            ch._load_image_base64("https://files.example.com/pic.png")

    cache_files = list(state_dir.tmp_dir().glob("wecom_cb_img_*"))
    assert cache_files, "the cache file must land in the agent tmp dir"


def test_the_channel_source_keeps_no_hardcoded_tmp_path():
    """Guards against a new ``/tmp/...`` literal drifting back into the file."""
    source = Path(inspect.getsourcefile(wbc)).read_text(encoding="utf-8")
    assert [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/tmp/")
    ] == []
