"""The update status file is replaced, never rewritten in place.

``read_update_status`` reports an unparseable file as ``{"state": "idle"}``, and
``_web_console_update`` uses that state to refuse a second update while one is
running. A status file rewritten in place is empty for the duration of the
write, so a crash — or a reader arriving mid-write — turns a running update into
an idle one and the guard lets a second update start on top of the first.
This does not serialize concurrent read-modify-write operations.
"""

import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cli.update_service import read_update_status, status_path, write_update_status


def test_the_status_file_is_replaced_rather_than_rewritten_in_place(tmp_path):
    write_update_status({"state": "running", "worker_pid": 4321}, str(tmp_path))
    path = status_path(str(tmp_path))
    first_inode = os.stat(path).st_ino

    write_update_status({"step": "pull"}, str(tmp_path))

    # A fresh inode means the previous file was swapped out whole, so no reader
    # can observe the target truncated or half-written.
    assert os.stat(path).st_ino != first_inode
    # The read-modify-write still merges rather than overwriting.
    merged = read_update_status(str(tmp_path))
    merged.pop("updated_at")
    assert merged == {"state": "running", "worker_pid": 4321, "step": "pull"}
    # No temporary sibling is left behind.
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_a_failed_write_leaves_the_running_status_intact(tmp_path, monkeypatch):
    write_update_status({"state": "running", "worker_pid": 4321}, str(tmp_path))
    path = status_path(str(tmp_path))
    before = path.read_text(encoding="utf-8")

    def fail(src, dst):
        raise OSError(errno.EIO, "injected I/O error", dst)

    monkeypatch.setattr("common.atomic_write.os.replace", fail)

    # The caller is told the write failed instead of silently losing the state.
    with pytest.raises(OSError):
        write_update_status({"state": "restarting"}, str(tmp_path))

    # The previous status survives whole, so the in-progress guard still holds.
    assert path.read_text(encoding="utf-8") == before
    assert read_update_status(str(tmp_path))["state"] == "running"


def test_the_on_disk_format_is_unchanged(tmp_path):
    write_update_status({"state": "running", "message": "拉取更新"}, str(tmp_path))

    text = status_path(str(tmp_path)).read_text(encoding="utf-8")

    # Two-space indent, non-ASCII kept verbatim, one trailing newline.
    assert text.endswith("}\n")
    assert '\n  "state": "running"' in text
    assert "拉取更新" in text
    assert json.loads(text)["message"] == "拉取更新"


@pytest.mark.parametrize("write_status", [False, True])
def test_installed_cli_imports_without_project_root(tmp_path, write_status):
    project_root = Path(__file__).resolve().parents[1]
    installed = tmp_path / "installed"
    shutil.copytree(project_root / "cli", installed / "cli")
    script = """
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
assert importlib.util.find_spec("common") is None
from cli import update_service, utils
assert "common" not in sys.modules
if sys.argv[3] == "write":
    utils.get_project_root = lambda: sys.argv[2]
    root = Path(sys.argv[1]).parent / "status"
    update_service.write_update_status({"state": "running"}, str(root))
    assert json.loads(update_service.status_path(str(root)).read_text())["state"] == "running"
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(installed), str(project_root),
         "write" if write_status else "import"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
