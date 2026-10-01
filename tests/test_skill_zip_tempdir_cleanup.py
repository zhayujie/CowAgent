"""A repo archive that cannot be extracted must not stay in the temp dir.

`_download_repo_zip` creates its scratch directory before opening the archive,
and callers can only clean up a directory they were handed back, so a failure
after mkdtemp leaves the whole downloaded archive behind.
"""

import io
import os
import shutil
import tempfile
import zipfile

import pytest

import cli.commands.skill as skill_cmd


class _Resp:
    def __init__(self, content):
        self.content = content
        self.headers = {}

    def raise_for_status(self):
        return None


def _leftovers(sandbox):
    return sorted(p.name for p in sandbox.glob("cow-skill-*"))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return scratch


def _serve(monkeypatch, payload):
    monkeypatch.setattr(skill_cmd.requests, "get", lambda *a, **k: _Resp(payload))


def test_payload_that_is_not_a_zip_is_cleaned_up(sandbox, monkeypatch):
    _serve(monkeypatch, b"<html>captive proxy page, not a zip</html>")

    with pytest.raises(zipfile.BadZipFile):
        skill_cmd._download_repo_zip("owner/repo")

    assert _leftovers(sandbox) == []


def test_zip_with_a_traversal_entry_is_cleaned_up(sandbox, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", "outside the extraction root")
    _serve(monkeypatch, buf.getvalue())

    with pytest.raises(ValueError, match="path traversal"):
        skill_cmd._download_repo_zip("owner/repo")

    assert _leftovers(sandbox) == []


def test_successful_download_keeps_its_directory(sandbox, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: demo\ndescription: d\n---\n")
    _serve(monkeypatch, buf.getvalue())

    tmp_dir, repo_root = skill_cmd._download_repo_zip("owner/repo")
    try:
        assert os.path.isfile(os.path.join(repo_root, "SKILL.md"))
        assert _leftovers(sandbox) == [os.path.basename(tmp_dir)]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
