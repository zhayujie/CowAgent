"""A failed skills_config.json save must not take the other records with it.

``cli/commands/skill.py`` rewrote skills_config.json by truncating it in place,
so a save that dies halfway -- a full disk, the process being killed -- leaves a
half-written document. ``cli.utils.load_skills_config`` cannot parse that and
answers ``{}``, so the next install, enable or uninstall persists its own
baseline over the file and every other skill's entry is gone with it.
"""
import json

import pytest

from cli.commands import skill as cli_skill

EXISTING = {
    "beta": {"name": "beta", "source": "cowhub", "enabled": True, "category": "skill"},
    "gamma": {"name": "gamma", "source": "github", "enabled": False, "category": "skill"},
}


def _fail_halfway(monkeypatch):
    """Let a JSON write start, then fail the way a full disk does.

    The truncation is the point: the first bytes reach the file and the rest
    never arrive.
    """
    def half_dump(obj, fp, **kwargs):
        fp.write('{\n    "half')
        fp.flush()
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", half_dump)


def _skills_dir(tmp_path):
    """A skills dir holding a config plus one custom skill to merge in."""
    skills_dir = tmp_path / "skills"
    (skills_dir / "alpha").mkdir(parents=True)
    (skills_dir / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Demo\n---\n", encoding="utf-8"
    )
    config_path = skills_dir / "skills_config.json"
    config_path.write_text(json.dumps(EXISTING), encoding="utf-8")
    return skills_dir, config_path


def _merge(skills_dir, tmp_path):
    config = json.loads((skills_dir / "skills_config.json").read_text(encoding="utf-8"))
    cli_skill._merge_builtin_into_config(config, str(tmp_path / "none"), str(skills_dir))


def test_a_failed_merge_write_keeps_the_existing_records(tmp_path, monkeypatch):
    skills_dir, config_path = _skills_dir(tmp_path)
    with monkeypatch.context() as patch:
        _fail_halfway(patch)
        _merge(skills_dir, tmp_path)
        assert json.loads(config_path.read_text(encoding="utf-8")) == EXISTING
        # nothing of the aborted replacement is left beside the file
        assert sorted(p.name for p in skills_dir.iterdir()) == [
            "alpha",
            "skills_config.json",
        ]

    _merge(skills_dir, tmp_path)  # control: without a failure the write still happens
    assert json.loads(config_path.read_text(encoding="utf-8"))["alpha"]["source"] == "custom"


def test_a_failed_enable_leaves_the_file_readable(tmp_path, monkeypatch):
    skills_dir, config_path = _skills_dir(tmp_path)
    monkeypatch.setattr(cli_skill, "get_skills_dir", lambda: str(skills_dir))
    _fail_halfway(monkeypatch)

    with pytest.raises(OSError):
        cli_skill._set_enabled("beta", False)

    assert json.loads(config_path.read_text(encoding="utf-8")) == EXISTING
