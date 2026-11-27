# encoding:utf-8
"""Chat `/skill uninstall image` must not delete `image-generation`.

The uninstall path deletes whatever the resolver returns. Resolving on the folder
name alone (`entry.startswith(name + "-")`) meant one skill's name being a prefix
of another's was enough to delete the other one -- and the reply said `image` had
been uninstalled, while `skills_config.json` kept the `image-generation` entry.
"""
import json
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


def _skill(skills, folder, declared_name=None):
    path = skills / folder
    path.mkdir(parents=True)
    body = "---\nname: {}\ndescription: d\n---\n\nbody\n".format(declared_name or folder)
    (path / "SKILL.md").write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def library(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    skills.mkdir()
    monkeypatch.setattr(cli.utils, "get_skills_dir", lambda agent_id=None: str(skills))
    return skills


def _write_config(skills, names):
    (skills / "skills_config.json").write_text(
        json.dumps({n: {"source": "url"} for n in names}), encoding="utf-8")


def test_a_name_that_only_prefixes_another_skill_deletes_nothing(library):
    _skill(library, "image-generation")
    _write_config(library, ["image-generation"])

    reply = CowCliPlugin()._skill_uninstall("image")

    assert (library / "image-generation" / "SKILL.md").exists(), "an unnamed skill was deleted"
    assert "未安装" in reply or "not installed" in reply


def test_the_prefix_case_is_still_readable_info(library):
    """Same resolver, read-only path: it must not report the other skill either."""
    _skill(library, "image-generation")

    reply = CowCliPlugin()._skill_info("image")

    assert "image-generation" not in reply


def test_a_suffix_name_does_not_delete_another_skill_either(library):
    _skill(library, "demo-weather")

    CowCliPlugin()._skill_uninstall("weather")

    assert (library / "demo-weather" / "SKILL.md").exists()


def test_the_exact_name_is_still_removed(library):
    """Control: the ordinary case."""
    _skill(library, "alpha")
    _write_config(library, ["alpha"])

    CowCliPlugin()._skill_uninstall("alpha")

    assert not (library / "alpha").exists()


def test_a_versioned_folder_is_still_resolved_by_its_declared_name(library):
    """Control: the reason the fallback exists -- folder name carries a suffix."""
    _skill(library, "greeter-1.0", declared_name="greeter")
    _write_config(library, ["greeter"])

    CowCliPlugin()._skill_uninstall("greeter")

    assert not (library / "greeter-1.0").exists()


def test_a_versioned_folder_declaring_another_skill_is_left_alone(library):
    _skill(library, "greeter-1.0", declared_name="other-skill")

    CowCliPlugin()._skill_uninstall("greeter")

    assert (library / "greeter-1.0" / "SKILL.md").exists()
