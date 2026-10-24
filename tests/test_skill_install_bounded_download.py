# encoding:utf-8
"""`cow skill install` must cap every download it makes.

Each network entry point of the skill installer used a bare requests.get plus
resp.content / resp.text, so an oversized or endless URL was buffered whole
before anything could object -- ``media_download``'s docstring spells out why
a socket timeout alone never fires on a server that keeps trickling bytes. The
skill service (``agent/skills/service.py``) already routes through the shared
helper; the CLI installer was the one that did not.
"""

import pytest

import cli.commands.skill as skill_cmd
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


def _cap(monkeypatch, module, size=1024):
    """Shrink the shared cap so an oversized body is a few chunks, not 100 MB.

    ``raising=False`` keeps this working on the unfixed code, where the
    module does not import the constant yet: there the real 100 MB cap
    applies and the small body sails through -- which is the bug.
    """
    monkeypatch.setattr(module, "MAX_FILE_BYTES", size, raising=False)


def _oversized(chunks=8, size=512):
    return [b"x" * size] * chunks


def test_repo_zip_download_refuses_an_oversized_archive(monkeypatch, tmp_path):
    sandbox = tmp_path / "tmp"
    sandbox.mkdir()
    monkeypatch.setattr(skill_cmd.tempfile, "tempdir", str(sandbox))
    _cap(monkeypatch, skill_cmd)
    monkeypatch.setattr(skill_cmd.requests, "get",
                        lambda *a, **k: _Stream(_oversized()))

    with pytest.raises(ValueError, match="too large"):
        skill_cmd._download_repo_zip("owner/repo")

    # The failure path cleans its scratch directory either way.
    assert list(sandbox.iterdir()) == []


def test_skill_md_download_refuses_an_oversized_page(monkeypatch):
    _cap(monkeypatch, skill_cmd)
    monkeypatch.setattr(skill_cmd.requests, "get",
                        lambda *a, **k: _Stream(_oversized()))

    with pytest.raises(SkillInstallError, match="too large"):
        skill_cmd._install_url("https://example.test/SKILL.md", skill_cmd.InstallResult())


def test_archive_download_refuses_an_oversized_package(monkeypatch):
    _cap(monkeypatch, skill_cmd)
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
    _cap(monkeypatch, skill_cmd)
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
