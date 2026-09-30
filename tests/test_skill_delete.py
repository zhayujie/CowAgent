"""Deleting a skill removes the directory it was loaded from."""

import pytest

SKILL_MD = "---\nname: {name}\ndescription: does a thing\n---\n\n# {name}\n"


def _write_skill(root, folder, name):
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_MD.format(name=name), encoding="utf-8")
    return path.parent


def _service(tmp_path):
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService

    builtin = tmp_path / "builtin"
    custom = tmp_path / "custom"
    builtin.mkdir()
    custom.mkdir()
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))), builtin, custom


def test_delete_removes_a_folder_named_differently_from_the_skill(tmp_path):
    svc, _, custom = _service(tmp_path)
    folder = _write_skill(custom, "wecom-cli", "wecom-unified")
    svc.manager.refresh_skills()

    svc.delete({"name": "wecom-unified"})

    assert not folder.exists()
    assert svc.manager.get_skill("wecom-unified") is None


def test_delete_still_removes_a_folder_named_after_the_skill(tmp_path):
    svc, _, custom = _service(tmp_path)
    folder = _write_skill(custom, "plain", "plain")
    svc.manager.refresh_skills()

    svc.delete({"name": "plain"})

    assert not folder.exists()


def test_delete_refuses_a_skill_loaded_from_outside_the_workspace(tmp_path):
    svc, builtin, _ = _service(tmp_path)
    folder = _write_skill(builtin, "shipped", "shipped")
    svc.manager.refresh_skills()

    with pytest.raises(ValueError):
        svc.delete({"name": "shipped"})

    assert folder.exists()


def test_delete_of_an_unknown_skill_is_a_no_op(tmp_path):
    svc, _, custom = _service(tmp_path)
    _write_skill(custom, "keep", "keep")
    svc.manager.refresh_skills()

    svc.delete({"name": "missing"})

    assert (custom / "keep").exists()
