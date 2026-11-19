"""Two console editors cannot both commit the same expected file version."""

from concurrent.futures import ThreadPoolExecutor
import os
import threading

import pytest

from agent.workspace.service import WorkspaceConflictError, WorkspaceService


@pytest.mark.parametrize("alias", ["same", "symlink", "case", "unicode"])
def test_concurrent_services_reject_second_save_of_same_version(tmp_path, monkeypatch, alias):
    filename = "café.md" if alias == "unicode" else "note.md"
    target = tmp_path / filename
    target.write_text("original", encoding="utf-8")
    os.utime(target, (1000000000, 1000000000))
    second_path = filename
    if alias == "unicode":
        second_path = "cafe\u0301.md"
        if not (tmp_path / second_path).exists() or not target.samefile(tmp_path / second_path):
            pytest.skip("filesystem distinguishes Unicode canonical forms")
    if alias == "case":
        second_path = "NOTE.md"
        if not (tmp_path / second_path).exists():
            pytest.skip("filesystem distinguishes filename case")
    elif alias == "symlink":
        if os.name == "nt":
            pytest.skip("symlink creation may require Windows privileges")
        (tmp_path / "alias.md").symlink_to(target)
        second_path = "alias.md"
    first = WorkspaceService(str(tmp_path))
    second = WorkspaceService(str(tmp_path))
    version = first.read_text(filename)["mtime"]
    publishing = threading.Event()
    release = threading.Event()
    second_resolved = threading.Event()
    second_finished = threading.Event()
    replace = first._replace_atomically
    resolve = second._resolve_file

    def block_first_publish(path, data):
        publishing.set()
        assert release.wait(5), "test did not release the first save"
        replace(path, data)

    def observe_second_resolve(path):
        result = resolve(path)
        second_resolved.set()
        return result

    monkeypatch.setattr(first, "_replace_atomically", block_first_publish)
    monkeypatch.setattr(second, "_resolve_file", observe_second_resolve)

    def second_save():
        try:
            second.write_text(second_path, "second editor", expected_mtime=version)
            return "saved"
        except WorkspaceConflictError:
            return "conflict"
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first.write_text, filename, "first editor", version)
        try:
            assert publishing.wait(5)
            second_result = pool.submit(second_save)
            assert second_resolved.wait(5)
            # The baseline completes this second stale save while first is
            # paused. A serialized implementation waits for the first commit.
            second_finished.wait(0.5)
        finally:
            release.set()
        first_result.result(timeout=5)
        assert second_result.result(timeout=5) == "conflict"
    assert target.read_text(encoding="utf-8") == "first editor"
