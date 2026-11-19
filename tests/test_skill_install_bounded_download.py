"""`cow skill install` must cap every download it makes.

Each network entry point of the skill installer buffered a bare requests.get
whole, so an oversized URL was read into memory before anything could object.
They now go through the shared bounded helper, imported lazily so an installed
CLI (which ships only the ``cli`` package) still starts.
"""

import os
import shutil
import subprocess
import sys

import pytest

import cli.commands.skill as skill_cmd
import common.media_download as media_download
from cli.commands.skill import SkillInstallError


class _Stream:
    """A minimal streamed response: chunks, headers, close."""

    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = headers or {}
        # The pre-fix code paths read the whole body instead of streaming.
        self.content = b"".join(self._chunks)
        self.text = self.content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        return None


class _Listing(_Stream):
    """The Contents API listing response."""

    def __init__(self, items):
        super().__init__([b"[]"])
        self._items = items

    def json(self):
        return self._items


def _cap(monkeypatch, size=1024):
    """Shrink the shared cap so an oversized body is a few chunks, not 100 MB."""
    monkeypatch.setattr(media_download, "MAX_FILE_BYTES", size)


def _oversized(chunks=8, size=512):
    return [b"x" * size] * chunks


def test_repo_zip_download_refuses_an_oversized_archive(monkeypatch, tmp_path):
    sandbox = tmp_path / "tmp"
    sandbox.mkdir()
    monkeypatch.setattr(skill_cmd.tempfile, "tempdir", str(sandbox))
    _cap(monkeypatch)
    monkeypatch.setattr(skill_cmd.requests, "get",
                        lambda *a, **k: _Stream(_oversized()))

    with pytest.raises(ValueError, match="too large"):
        skill_cmd._download_repo_zip("owner/repo")

    # The failure path cleans its scratch directory either way.
    assert list(sandbox.iterdir()) == []


def test_skill_md_download_refuses_an_oversized_page(monkeypatch):
    _cap(monkeypatch)
    monkeypatch.setattr(skill_cmd.requests, "get",
                        lambda *a, **k: _Stream(_oversized()))

    with pytest.raises(SkillInstallError, match="too large"):
        skill_cmd._install_url("https://example.test/SKILL.md", skill_cmd.InstallResult())


def test_archive_download_refuses_an_oversized_package(monkeypatch):
    _cap(monkeypatch)
    monkeypatch.setattr(skill_cmd.requests, "get",
                        lambda *a, **k: _Stream(_oversized(),
                                                headers={"Content-Type": "application/zip"}))

    with pytest.raises(SkillInstallError, match="too large"):
        skill_cmd._install_archive_url("https://example.test/pkg.zip",
                                       skill_cmd.InstallResult())


_LISTING = [{
    "type": "file",
    "path": "skills/demo/SKILL.md",
    "download_url": "https://raw.example.com/skills/demo/SKILL.md",
}]


def _contents_api(monkeypatch, file_response):
    def _get(url, **kwargs):
        if url.startswith("https://api.github.com/"):
            return _Listing(_LISTING)
        return file_response

    monkeypatch.setattr(skill_cmd.requests, "get", _get)


def test_contents_api_file_download_refuses_an_oversized_file(monkeypatch, tmp_path):
    _cap(monkeypatch)
    _contents_api(monkeypatch, _Stream(_oversized()))

    with pytest.raises(ValueError, match="too large"):
        skill_cmd._download_github_dir("owner", "repo", "main", "skills/demo",
                                       str(tmp_path / "dest"))

    assert not (tmp_path / "dest" / "SKILL.md").exists()


def test_contents_api_still_writes_ordinary_files(monkeypatch, tmp_path):
    payload = b"---\nname: demo\ndescription: d\n---\n"
    _contents_api(monkeypatch, _Stream([payload]))

    skill_cmd._download_github_dir("owner", "repo", "main", "skills/demo",
                                   str(tmp_path / "dest"))

    assert (tmp_path / "dest" / "SKILL.md").read_bytes() == payload


def test_the_cli_imports_without_the_project_on_the_path(tmp_path):
    """An installed CLI ships only the ``cli`` package: no ``common`` at import time."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shutil.copytree(os.path.join(root, "cli"), tmp_path / "cli")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, "-c", "import cli.cli, cli.commands.skill"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
