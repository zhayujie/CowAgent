"""Explicit skill choices must not acknowledge an unsuccessful config save."""

import errno
import json

import pytest
import web

from agent.skills.manager import SkillManager
from agent.skills.service import SkillService
from channel.web.api import skills as skills_api


@pytest.fixture
def library(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    custom = tmp_path / "skills"
    sample = custom / "sample"
    sample.mkdir(parents=True)
    text = "---\nname: sample\ndescription: Stable skill\n---\n# Instructions\n"
    (sample / "SKILL.md").write_text(text, encoding="utf-8")
    manager = SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))
    return manager, SkillService(manager), custom / "skills_config.json", builtin, text


def _fail_save(monkeypatch):
    error = OSError(errno.ENOSPC, "native partial config write")
    attempts = []

    def partial_dump(value, file, **kwargs):
        file.write('{"incomplete":')
        file.flush()
        attempts.append(file.name)
        raise error

    monkeypatch.setattr(json, "dump", partial_dump)
    return error, attempts


def _assert_saved_state(library, saved, enabled):
    manager, _, path, builtin, _ = library
    assert path.read_bytes() == saved
    assert manager.is_skill_enabled("sample") is enabled
    fresh = SkillManager(builtin_dir=str(builtin), custom_dir=str(path.parent))
    assert fresh.is_skill_enabled("sample") is enabled
    assert sorted(p.name for p in path.parent.iterdir()) == ["sample", "skills_config.json"]


@pytest.mark.parametrize("action", ["open", "close"])
def test_console_reports_failed_skill_toggle_without_changing_saved_choice(library, monkeypatch, action):
    manager, service, path, _, _ = library
    previous = action == "close"
    manager.set_skill_enabled("sample", previous)
    saved = path.read_bytes()
    error, attempts = _fail_save(monkeypatch)
    monkeypatch.setattr(skills_api, "_require_auth", lambda: None)
    monkeypatch.setattr(skills_api, "_skill_service", lambda agent_id="": service)
    app = web.application(("/skills", "SkillsHandler"), vars(skills_api), autoreload=False)
    response = json.loads(app.request("/skills", method="POST", data=json.dumps({"action": action, "name": "sample"})).data)
    assert response["status"] == "error"
    assert str(error) in response["message"]
    assert attempts
    _assert_saved_state(library, saved, previous)


def test_failed_explicit_toggle_preserves_exception_and_memory_state(library, monkeypatch):
    manager, _, path, _, _ = library
    saved, entry = path.read_bytes(), manager.skills_config["sample"]
    before = dict(entry)
    error, attempts = _fail_save(monkeypatch)
    with pytest.raises(OSError) as failed:
        manager.set_skill_enabled("sample", False)
    assert failed.value is error
    assert manager.skills_config["sample"] is entry
    assert entry == before
    assert attempts
    _assert_saved_state(library, saved, True)


def test_post_install_metadata_stays_best_effort(library, monkeypatch):
    manager, service, path, _, _ = library
    saved = path.read_bytes()
    _, attempts = _fail_save(monkeypatch)
    service._set_display_name("sample", "Visible title")
    assert attempts
    assert path.read_bytes() == saved


def test_automatic_metadata_sync_remains_best_effort(library, monkeypatch):
    manager, _, path, _, _ = library
    saved = path.read_bytes()
    (path.parent / "sample" / "SKILL.md").write_text("---\nname: sample\ndescription: Refreshed description\n---\n", encoding="utf-8")
    _, attempts = _fail_save(monkeypatch)
    manager.refresh_skills()
    assert attempts
    assert manager.get_skill("sample").skill.description == "Refreshed description"
    assert manager.is_skill_enabled("sample") is True
    assert path.read_bytes() == saved


def test_successful_explicit_choice_survives_a_fresh_manager(library):
    manager, _, path, builtin, _ = library
    manager.set_skill_enabled("sample", False)
    fresh = SkillManager(builtin_dir=str(builtin), custom_dir=str(path.parent))
    assert fresh.is_skill_enabled("sample") is False
