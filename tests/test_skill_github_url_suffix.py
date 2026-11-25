"""Copied GitHub links ignore browser query strings and fragments."""

from unittest.mock import patch

import pytest

import cli.commands.skill as skill_cmd


@pytest.mark.parametrize("suffix", ["", "?tab=readme-ov-file", "#readme",
                                  "?tab=readme-ov-file#readme"])
@pytest.mark.parametrize("path,branch,subpath", [
    ("", None, None),
    (".git", None, None),
    ("/tree/main", "main", None),
    ("/tree/main/skills/pdf", "main", "skills/pdf"),
    ("/blob/main/skills/pdf/SKILL.md", "main", "skills/pdf/SKILL.md"),
])
def test_parse_github_url_ignores_suffix(path, branch, subpath, suffix):
    url = "https://github.com/anthropics/skills" + path + suffix

    assert skill_cmd._parse_github_url(url) == ("anthropics", "skills", branch, subpath)


@pytest.mark.parametrize("suffix", ["", "?tab=readme-ov-file#readme"])
@pytest.mark.parametrize("path,direct", [
    ("tree/main/skills/pdf", False),
    ("blob/main/skills/pdf", False),
    ("tree/main/skills/pdf/SKILL.md", True),
    ("blob/main/skills/pdf/SKILL.md", True),
])
def test_install_routes_github_urls_without_suffix(path, direct, suffix):
    with patch.object(skill_cmd, "_install_github") as install:
        result = skill_cmd.install_skill(
            "https://github.com/anthropics/skills/" + path + suffix,
            agent_id="demo",
        )

    assert result.error is None, result.error
    kwargs = {"subpath": "skills/pdf", "branch": "main", "agent_id": "demo"}
    if direct:
        kwargs["skill_name"] = "pdf"
    install.assert_called_once_with("anthropics/skills", result, **kwargs)


def test_install_preserves_non_github_url_query():
    url = "https://example.com/skills.zip?token=example"
    with patch.object(skill_cmd, "_install_archive_url") as install:
        result = skill_cmd.install_skill(url)

    assert result.error is None, result.error
    install.assert_called_once_with(url, result, agent_id=None)
