"""Manual read-aloud persists audio on its requested message, never a newer reply."""

import json
import sqlite3
import threading
import urllib.request
import wave
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

web = pytest.importorskip("web")

from agent.memory import get_conversation_store  # noqa: E402
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry  # noqa: E402
from bridge.bridge import Bridge  # noqa: E402
from bridge.reply import Reply, ReplyType  # noqa: E402
from channel.web.api.files import VoiceTtsHandler  # noqa: E402
from config import conf  # noqa: E402


class QuietRequestHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.mark.parametrize("owner", ["default", "helper"])
@pytest.mark.parametrize(
    "target",
    ["older", "latest", "missing", "new_arrival", "zero", "gone", "edited", "reused"],
)
def test_manual_tts_targets_requested_persisted_message(
    tmp_path, monkeypatch, request, owner, target
):
    root = tmp_path / "default"
    helper = tmp_path / "helper"
    root.mkdir()
    helper.mkdir()
    configuration = conf()
    monkeypatch.setitem(configuration, "agent_workspace", str(root))
    monkeypatch.setitem(configuration, "web_password", "")
    monkeypatch.setitem(configuration, "text_to_voice", "mimo")
    registry = AgentRegistry(
        [
            AgentProfile("default", "Default", str(root)),
            AgentProfile("helper", "Helper", str(helper)),
        ],
        "default",
    )
    # Return to config-following mode before later suites choose a workspace.
    request.addfinalizer(lambda: set_agent_registry(None))
    set_agent_registry(registry)
    stores = {
        key: get_conversation_store(str(path))
        for key, path in [("default", root), ("helper", helper)]
    }
    for store in stores.values():
        if target == "zero":
            store.append_messages(
                "conversation",
                [{"role": "assistant", "content": "zero answer"}],
                channel_type="web",
            )
        store.append_messages(
            "conversation",
            [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "older answer"},
                {"role": "user", "content": "second question"},
                {"role": "assistant", "content": "newer answer"},
            ],
            channel_type="web",
        )
    store = stores[owner]
    with sqlite3.connect(store._db_path) as connection:
        wanted_content = (
            "zero answer"
            if target == "zero"
            else "older answer" if target == "older" else "newer answer"
        )
        expected_seq = connection.execute(
            "SELECT seq FROM messages WHERE agent_id = ? AND session_id = ? AND content = ?",
            (
                "" if owner == "default" else owner,
                "conversation",
                json.dumps(wanted_content),
            ),
        ).fetchone()[0]
    if target == "gone":
        expected_seq = 999999
    body = {"text": wanted_content, "session_id": "conversation"}
    # The console fetch wrapper injects the selected owner into JSON bodies.
    if owner != "default":
        body["agent_id"] = owner
    if target != "missing":
        body["message_seq"] = expected_seq

    def fixed_local_audio(text):
        assert text == body["text"]
        if target in ("edited", "reused"):
            with sqlite3.connect(store._db_path) as connection:
                if target == "edited":
                    connection.execute(
                        "UPDATE messages SET content = ? WHERE agent_id = ? AND session_id = ? AND seq = ?",
                        (
                            json.dumps("edited answer"),
                            "" if owner == "default" else owner,
                            "conversation",
                            expected_seq,
                        ),
                    )
                else:
                    connection.execute(
                        "DELETE FROM messages WHERE agent_id = ? AND session_id = ? AND seq = ?",
                        (
                            "" if owner == "default" else owner,
                            "conversation",
                            expected_seq,
                        ),
                    )
            if target == "reused":
                # Same seq and content, different AUTOINCREMENT id: content
                # comparison alone must not attach to this replacement row.
                store.append_messages(
                    "conversation", [{"role": "assistant", "content": wanted_content}]
                )
        if target in ("new_arrival", "edited", "reused"):
            store.append_messages(
                "conversation",
                [
                    {"role": "user", "content": "arrived during synthesis"},
                    {"role": "assistant", "content": "new arrival"},
                ],
                channel_type="web",
            )
        audio = tmp_path / "fixed.wav"
        with wave.open(str(audio), "wb") as recording:
            recording.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            recording.writeframes(b"\x00\x00" * 80)
        return Reply(ReplyType.VOICE, str(audio))

    # Only synthesis is replaced. Route parsing, auth, publication, registry,
    # message storage and HTTP transport below are the real implementation.
    monkeypatch.setattr(Bridge(), "fetch_text_to_voice", fixed_local_audio)
    app = web.application(("/api/voice/tts", "tts"), {"tts": VoiceTtsHandler})
    server = make_server(
        "127.0.0.1", 0, app.wsgifunc(), handler_class=QuietRequestHandler
    )
    worker = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    worker.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/voice/tts",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.load(response)
        assert result["status"] == "success", result
        with sqlite3.connect(store._db_path) as connection:
            rows = connection.execute(
                "SELECT agent_id, seq, extras FROM messages WHERE session_id = ? AND role = 'assistant'",
                ("conversation",),
            ).fetchall()
        tagged = [
            (agent, seq)
            for agent, seq, extras in rows
            if extras and json.loads(extras).get("audio")
        ]
        expected = (
            []
            if target in ("missing", "gone", "edited", "reused")
            else [("" if owner == "default" else owner, expected_seq)]
        )
        assert tagged == expected
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_clicked_sequence_and_owner_reach_manual_tts_payload():
    """Run the actual trigger and fetch wrapper in Node; no DOM/browser claim."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const render = fs.readFileSync('channel/web/static/js/chat/render.js', 'utf8');
const state = fs.readFileSync('channel/web/static/js/chat/state.js', 'utf8');
const trigger = render.slice(
  render.indexOf('function _triggerManualTts('), render.indexOf('\nfunction addUserMessage('));
const wrapper = state.slice(state.indexOf('const _nativeFetch ='), state.indexOf('\nfunction generateSessionId('));
for (const owner of ['', 'helper']) {
  for (const seq of ['1', '0', undefined, '']) {
    let sent;
    const context = {
      Headers, activeAgentId: owner, sessionId: 'conversation',
      window: {fetch: (url, init) => {
        sent = {url, body: JSON.parse(init.body)};
        return Promise.resolve({json: () => Promise.resolve({})});
      }},
    };
    context.fetch = (...args) => context.window.fetch(...args);
    vm.createContext(context);
    vm.runInContext(wrapper + '\n' + trigger, context);
    context.button = {dataset: {}, querySelector: () => null};
    context.bubble = {dataset: seq === undefined ? {} : {seq}};
    vm.runInContext("_triggerManualTts(button, bubble, 'older answer')", context);
    assert.equal(sent.body.text, 'older answer');
    assert.equal(sent.body.session_id, 'conversation');
    assert.equal(sent.body.agent_id, owner || undefined);
    assert.equal(sent.body.message_seq, seq === '1' ? 1 : seq === '0' ? 0 : undefined);
  }
}
"""
    result = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_latest_assistant_merge_remains_available(tmp_path):
    from agent.memory import ConversationStore

    store = ConversationStore(tmp_path / "messages.db")
    store.append_messages(
        "session",
        [
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "latest", "extras": {"keep": True}},
        ],
    )
    assert store.attach_extras_to_last_assistant("session", {"new": True}) == 1
    with sqlite3.connect(store._db_path) as connection:
        rows = connection.execute(
            "SELECT seq, extras FROM messages ORDER BY seq"
        ).fetchall()
    assert not rows[0][1] or not json.loads(rows[0][1])
    assert json.loads(rows[1][1]) == {"keep": True, "new": True}
