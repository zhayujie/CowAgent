"""The multipart routes have to read the Agent from where the clients put it.

Both clients scope a request by putting ``agent_id`` in the **query string** and
deliberately keep it out of a multipart body: web.py merges query and form
fields, and a duplicate collapses into a list that reaches handlers expecting a
string. The console's fetch wrapper does it for every same-origin request
(``chat/state.js``), and the desktop client's ``postFormData`` does the same
(``api/client.ts``).

``/upload`` learned this when its preview URLs started naming the Agent. The two
multipart routes that were not touched still parse the body alone through
``_raw_web_input()`` — ``rawinput(method="post")`` — so they never see the Agent
and fall back to the default one: a recording is written into the default
Agent's workspace, and an imported document builds the default Agent's knowledge
service. Both land in a workspace the user did not select.

These tests drive a real server because the bug is in the contract between the
client's URL and the handler's parser, not in either one alone.
"""

import json
import threading
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

DESKTOP_TOKEN = "desktop-token-for-tests"
OTHER_AGENT = "helper"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def console(tmp_path, monkeypatch):
    """A running console whose Agents own separate workspaces under tmp_path."""
    monkeypatch.setenv("COW_DESKTOP_TOKEN", DESKTOP_TOKEN)

    workspaces = {
        None: tmp_path / "default",
        "default": tmp_path / "default",
        OTHER_AGENT: tmp_path / "agents" / OTHER_AGENT,
    }
    for path in workspaces.values():
        path.mkdir(parents=True, exist_ok=True)

    registry = SimpleNamespace(
        get=lambda agent_id=None: SimpleNamespace(workspace=str(workspaces[agent_id]))
    )

    from channel.web import web_channel

    # A console password set by an earlier test would 401 these requests, and
    # the login flow is not what is under test here.
    with patch("channel.web.api.files._require_auth"), patch(
        "channel.web.api.knowledge._require_auth"
    ), patch("agent.registry.get_agent_registry", return_value=registry):
        app = web_channel.build_app()
        server = make_server("127.0.0.1", 0, app.wsgifunc(), handler_class=_QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield SimpleNamespace(
                base=f"http://127.0.0.1:{server.server_address[1]}",
                workspaces=workspaces,
            )
        finally:
            server.shutdown()
            server.server_close()


def _post_multipart(console, path, agent_id, filename, field, content_type, blob):
    """What the browser sends: the Agent rides in the query string only."""
    boundary = "----cowtest"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()

    query = f"?agent_id={agent_id}" if agent_id else ""
    request = urllib.request.Request(
        f"{console.base}{path}{query}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def _uploaded_names(workspace):
    uploads = workspace / "tmp"
    return sorted(p.name for p in uploads.glob("voice_input_*")) if uploads.is_dir() else []


def _fake_asr(text):
    """Stub the transcription. ``Bridge`` is an ``@singleton``, so it is the
    instance's class that carries the method, not the name in ``bridge.bridge``."""
    from bridge.reply import Reply, ReplyType
    from bridge.bridge import Bridge

    return patch.object(
        type(Bridge()), "fetch_voice_to_text", return_value=Reply(ReplyType.TEXT, text)
    )


@pytest.mark.parametrize("agent_id", [None, OTHER_AGENT], ids=["default", "named"])
def test_a_recording_lands_in_the_workspace_of_the_agent_it_was_sent_to(console, agent_id):
    with _fake_asr("recognised text"):
        result = _post_multipart(
            console,
            "/api/voice/asr",
            agent_id,
            "recording.webm",
            "file",
            "audio/webm",
            b"\x1aE\xdf\xa3fake-webm",
        )

    assert result["status"] == "success", result
    selected = console.workspaces[agent_id]
    other = console.workspaces[None if agent_id else OTHER_AGENT]

    assert len(_uploaded_names(selected)) == 1, (
        f"the recording sent to agent {agent_id!r} is not in its own workspace "
        f"({selected}/tmp holds {_uploaded_names(selected)})"
    )
    assert _uploaded_names(other) == [], (
        f"the recording sent to agent {agent_id!r} was written into another "
        f"Agent's workspace ({other}/tmp)"
    )


def test_the_recording_url_names_the_agent_so_the_bubble_can_fetch_it_back(console):
    """An <audio src> doesn't pass through the fetch wrapper, so the URL the
    handler hands back is fetched verbatim — it has to carry the Agent itself,
    exactly like /upload's preview_url now does."""
    with _fake_asr("recognised text"):
        result = _post_multipart(
            console,
            "/api/voice/asr",
            OTHER_AGENT,
            "recording.webm",
            "file",
            "audio/webm",
            b"\x1aE\xdf\xa3fake-webm",
        )

    assert f"agent_id={OTHER_AGENT}" in result["audio_url"], (
        f"the recording URL {result['audio_url']!r} names no Agent, so it "
        f"resolves against the default Agent's uploads"
    )


@pytest.mark.parametrize("agent_id", [None, OTHER_AGENT], ids=["default", "named"])
def test_an_imported_document_targets_the_selected_agents_knowledge(console, agent_id):
    built = []

    from agent.knowledge.service import KnowledgeService as _Real

    class _Recorder:
        MAX_IMPORT_TOTAL_SIZE = _Real.MAX_IMPORT_TOTAL_SIZE
        MAX_IMPORT_FILE_SIZE = _Real.MAX_IMPORT_FILE_SIZE
        MAX_IMPORT_FILES = _Real.MAX_IMPORT_FILES

        def __init__(self, workspace, **_options):
            built.append(workspace)

        def dispatch(self, action, payload):
            return {"code": 200, "imported": len(payload["files"]), "skipped": 0, "failed": 0}

    with patch("agent.knowledge.service.KnowledgeService", _Recorder):
        result = _post_multipart(
            console,
            "/api/knowledge/import",
            agent_id,
            "notes.md",
            "files",
            "text/markdown",
            b"# notes\n",
        )

    assert result["status"] == "success", result
    assert built == [str(console.workspaces[agent_id])], (
        f"an import sent to agent {agent_id!r} built the knowledge service for "
        f"{built}, which is another Agent's workspace"
    )
