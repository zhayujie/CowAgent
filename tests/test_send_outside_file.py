# encoding:utf-8
"""Send copies files outside the home dir and workspace (e.g. /tmp) into
<workspace>/tmp/ so path-based clients can still serve them."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.send.send import Send


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "cow"
    outside = tmp_path / "outside"
    for d in (workspace, outside):
        d.mkdir(parents=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setattr(Send, "_workspace_root", lambda self: str(workspace))
    return home, workspace, outside


def test_outside_file_is_copied_into_workspace_tmp(env):
    _, workspace, outside = env
    src = outside / "page-0.png"
    src.write_bytes(b"\x89PNG data")
    result = Send({"cwd": str(workspace)}).execute({"path": str(src)})
    assert result.status == "success"
    sent = result.result["path"]
    assert os.path.dirname(sent) == os.path.realpath(str(workspace / "tmp"))
    assert open(sent, "rb").read() == b"\x89PNG data"
    assert result.result["file_name"] == "page-0.png"
    assert result.result["file_type"] == "image"
    assert src.exists()


def test_same_name_sent_twice_gets_distinct_copies(env):
    _, workspace, outside = env
    src = outside / "page.png"
    src.write_bytes(b"one")
    tool = Send({"cwd": str(workspace)})
    first = tool.execute({"path": str(src)}).result["path"]
    second = tool.execute({"path": str(src)}).result["path"]
    assert first != second


@pytest.mark.parametrize("where", ["workspace", "home"])
def test_file_inside_home_or_workspace_is_sent_in_place(env, where):
    home, workspace, _ = env
    base = workspace if where == "workspace" else home
    src = base / "note.txt"
    src.write_text("hello")
    result = Send({"cwd": str(workspace)}).execute({"path": str(src)})
    assert result.result["path"] == str(src)
    assert not (workspace / "tmp").exists()


def test_copy_failure_falls_back_to_original_path(env, monkeypatch):
    _, workspace, outside = env
    src = outside / "page.png"
    src.write_bytes(b"x")
    monkeypatch.setattr("agent.tools.send.send.shutil.copy2",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    result = Send({"cwd": str(workspace)}).execute({"path": str(src)})
    assert result.status == "success"
    assert result.result["path"] == str(src)
