"""Transient weixin media must live in the agent's managed tmp dir.

Regression test for the ``/tmp/wx_media_*`` path this channel used to write
when a reply referenced an ``http(s)://`` URL. On Windows a bare ``/tmp``
resolves against the *current drive*, so the same process writes to a different
disk depending on where it was launched -- and it sits outside the workspace
the app manages and cleans.
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from channel.weixin import weixin_channel as wxc
from common import state_dir

CHANNEL_CLS = wxc.WeixinChannel.__wrapped__


@pytest.fixture
def agent_workspace(tmp_path):
    set_agent_registry(AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1"))
    yield tmp_path
    # None, not the previous instance: an instance argument re-pins the
    # registry and would leak this workspace into the later tests.
    set_agent_registry(None)


def _fake_response(content=b"payload", content_type="image/png"):
    resp = Mock()
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = lambda: None
    return resp


def test_a_downloaded_url_is_cached_in_the_agent_tmp_dir(agent_workspace):
    with patch.object(wxc.requests, "get", return_value=_fake_response()):
        local_path = CHANNEL_CLS._resolve_media_path("https://files.example.com/pic.png")

    assert local_path, "the download must succeed"
    assert str(Path(local_path).parent) == str(state_dir.tmp_dir())


def test_a_sent_video_is_uploaded_from_the_agent_tmp_dir(agent_workspace):
    uploaded = []
    ch = CHANNEL_CLS.__new__(CHANNEL_CLS)
    ch.api = Mock()
    ch._check_send_response = lambda resp, receiver: None
    ch._send_text = lambda text, receiver, token: None
    with patch.object(wxc.requests, "get", return_value=_fake_response(content_type="video/mp4")), \
            patch.object(wxc, "upload_media_to_cdn",
                         side_effect=lambda api, path, receiver, media_type=2: uploaded.append(path) or {
                             "encrypt_query_param": "q", "aes_key_b64": "k", "ciphertext_size": 1,
                         }):
        ch._send_video("https://files.example.com/clip.mp4", "recv-1", "tok-1")

    assert len(uploaded) == 1, "the video must reach the upload step"
    assert str(Path(uploaded[0]).parent) == str(state_dir.tmp_dir())


def test_the_channel_source_keeps_no_hardcoded_tmp_path():
    """Guards against a new ``/tmp/...`` literal drifting back into the file."""
    source = Path(inspect.getsourcefile(wxc)).read_text(encoding="utf-8")
    assert [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/tmp/")
    ] == []
