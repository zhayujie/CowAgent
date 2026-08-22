"""Tests for GitHub Skill installation branch selection."""

import io
import shutil
import zipfile

from cli.commands import skill as skill_command


class _Response:
    def __init__(self, content=b"", payload=None):
        self.content = content
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_github_url_preserves_unpinned_default_branch():
    assert skill_command._parse_github_url(
        "https://github.com/owner/repo"
    ) == ("owner", "repo", None, None)
    assert skill_command._parse_github_url(
        "https://github.com/owner/repo/tree/master/skills/example"
    ) == ("owner", "repo", "master", "skills/example")


def test_download_repo_zip_uses_head_for_default_branch(monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("repo-default/SKILL.md", "example")
    requested = []

    def fake_get(url, **kwargs):
        requested.append((url, kwargs))
        return _Response(content=archive.getvalue())

    monkeypatch.setattr(skill_command.requests, "get", fake_get)

    tmp_dir, repo_root = skill_command._download_repo_zip("owner/repo")
    try:
        assert requested[0][0] == "https://github.com/owner/repo/archive/HEAD.zip"
        assert repo_root.endswith("repo-default")
    finally:
        shutil.rmtree(tmp_dir)


def test_contents_api_omits_ref_for_default_branch(tmp_path, monkeypatch):
    requested = []

    def fake_get(url, **kwargs):
        requested.append((url, kwargs))
        return _Response(payload=[])

    monkeypatch.setattr(skill_command.requests, "get", fake_get)

    skill_command._download_github_dir(
        "owner", "repo", None, "skills/example", str(tmp_path)
    )

    assert requested[0][0] == (
        "https://api.github.com/repos/owner/repo/contents/skills/example"
    )


def test_xquik_shorthand_installs_from_repository_default_branch(
    tmp_path, monkeypatch
):
    download_dir = tmp_path / "download"
    repo_root = download_dir / "repo"
    for name in ("x-twitter-scraper", "xquik-social-research"):
        skill_dir = repo_root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test fixture\n---\n",
            encoding="utf-8",
        )
    installed_dir = tmp_path / "installed"
    requested = []

    def fake_download(spec, branch=None, host="github", timeout=30):
        requested.append((spec, branch, host, timeout))
        return str(download_dir), str(repo_root)

    monkeypatch.setattr(skill_command, "get_skills_dir", lambda: str(installed_dir))
    monkeypatch.setattr(skill_command, "_download_repo_zip", fake_download)

    result = skill_command.install_skill("Xquik-dev/x-twitter-scraper")

    assert result.error is None
    assert result.installed == ["x-twitter-scraper", "xquik-social-research"]
    assert requested == [("Xquik-dev/x-twitter-scraper", None, "github", 30)]
    assert (installed_dir / "x-twitter-scraper" / "SKILL.md").is_file()
    assert (installed_dir / "xquik-social-research" / "SKILL.md").is_file()
