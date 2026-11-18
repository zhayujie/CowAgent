# encoding:utf-8
"""Chat `/skill info` rejects names that would read outside the skills dirs.

`/skill uninstall` validates the name with _check_skill_name before touching
the filesystem (see test_cow_cli_skill_uninstall_traversal.py), but /skill
info joined the raw chat string into a path and echoed the SKILL.md it found
there — so "/skill info ../../.." (or an absolute path) published any
SKILL.md on disk into the chat. Same check, same fence.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cli.utils
import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    from plugins.cow_cli.cow_cli import KNOWN_COMMANDS  # noqa: F401
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]

SECRET = "secret-skill-body"


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "SKILL.md").write_text(SECRET)
    monkeypatch.setattr(cli.utils, "get_skills_dir", lambda agent_id=None: str(skills))
    monkeypatch.setattr(
        cli.utils, "get_builtin_skills_dir", lambda: str(tmp_path / "builtin")
    )
    return victim


@pytest.mark.parametrize("absolute", [False, True])
def test_traversal_name_is_refused(dirs, absolute):
    result = CowCliPlugin()._skill_info(str(dirs) if absolute else "../victim")
    assert SECRET not in result
    assert "无法查看" in result or "Cannot view" in result


def test_normal_skill_info_still_works(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\nAlpha body")
    monkeypatch.setattr(cli.utils, "get_skills_dir", lambda agent_id=None: str(skills))
    monkeypatch.setattr(
        cli.utils, "get_builtin_skills_dir", lambda: str(tmp_path / "builtin")
    )
    result = CowCliPlugin()._skill_info("alpha")
    assert "Alpha body" in result
