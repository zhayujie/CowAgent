"""A multipart request that repeats a field has to keep every value.

A folder upload repeats ``files`` and ``relative_paths`` once per file, and a
knowledge import repeats ``files`` once per document. web.py 0.76 parses forms
with the ``multipart`` package and keeps only the last value of a repeated
field, so both routes silently kept one file while reporting success: the
counts of files and paths still matched (1 == 1). These tests drive a real
server because the bug is in how the form body is parsed, not in the handler.
"""

import json
import threading
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def console(tmp_path):
    workspace = tmp_path / "default"
    workspace.mkdir()
    registry = SimpleNamespace(get=lambda agent_id=None: SimpleNamespace(workspace=str(workspace)))

    from channel.web import web_channel

    with patch("channel.web.api.files._require_auth"), patch(
        "channel.web.api.knowledge._require_auth"
    ), patch("agent.registry.get_agent_registry", return_value=registry):
        app = web_channel.build_app()
        server = make_server("127.0.0.1", 0, app.wsgifunc(), handler_class=_QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield SimpleNamespace(base=f"http://127.0.0.1:{server.server_address[1]}", workspace=workspace)
        finally:
            server.shutdown()
            server.server_close()


def _post_form(console, path, fields):
    """``fields`` is a list of (name, value) or (name, (filename, bytes))."""
    boundary = "----cowmulti"
    chunks = []
    for name, value in fields:
        if isinstance(value, tuple):
            filename, blob = value
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    "Content-Type: text/plain\r\n\r\n"
                ).encode() + blob + b"\r\n"
            )
        else:
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )
    body = b"".join(chunks) + f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{console.base}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def test_a_folder_upload_keeps_every_file(console):
    fields = [("upload_id", "abc123")]
    for i in range(3):
        fields.append(("files", (f"f{i}.txt", f"content{i}".encode())))
        fields.append(("relative_paths", f"docs/f{i}.txt"))

    result = _post_form(console, "/upload", fields)

    assert result["status"] == "success", result
    assert result["file_count"] == 3, result
    saved = sorted(p.name for p in (console.workspace / "tmp" / "webdir_abc123" / "docs").iterdir())
    assert saved == ["f0.txt", "f1.txt", "f2.txt"]


def test_a_folder_upload_beyond_the_default_part_cap_is_accepted(console):
    fields = [("upload_id", "big")]
    for i in range(80):
        fields.append(("files", (f"f{i}.txt", b"x")))
        fields.append(("relative_paths", f"many/f{i}.txt"))

    result = _post_form(console, "/upload", fields)

    assert result["status"] == "success", result
    assert result["file_count"] == 80


def test_a_knowledge_import_keeps_every_document(console):
    received = []

    from agent.knowledge.service import KnowledgeService as _Real

    class _Recorder:
        MAX_IMPORT_TOTAL_SIZE = _Real.MAX_IMPORT_TOTAL_SIZE
        MAX_IMPORT_FILE_SIZE = _Real.MAX_IMPORT_FILE_SIZE
        MAX_IMPORT_FILES = _Real.MAX_IMPORT_FILES

        def __init__(self, workspace, **_options):
            pass

        def dispatch(self, action, payload):
            received.extend(f["filename"] for f in payload["files"])
            received.append(("category", payload["target_category"]))
            return {"code": 200, "imported": len(payload["files"]), "skipped": 0, "failed": 0}

    fields = [("target_category", "notes"), ("conflict_strategy", "rename")]
    fields += [("files", (f"doc{i}.md", b"# doc")) for i in range(3)]

    with patch("agent.knowledge.service.KnowledgeService", _Recorder):
        result = _post_form(console, "/api/knowledge/import", fields)

    assert result["status"] == "success", result
    assert received == ["doc0.md", "doc1.md", "doc2.md", ("category", "notes")]
