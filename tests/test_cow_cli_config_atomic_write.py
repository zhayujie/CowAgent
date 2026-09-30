"""A failed write must not destroy the config files ``cow_cli`` owns.

``cli/commands/skill.py`` is not the only writer of the skill registry: the
inline ``cow_cli`` console keeps its own read-modify-write dance and wrote the
file with ``open(path, "w")``. That truncates before it writes, so a crash, a
``kill``, or a full disk between the truncate and the final flush leaves a
half-written file behind and every record in it is gone. ``uninstall`` was
worse than that: it swallowed the exception and still reported success.

The same shape holds for ``config.json``, which ``cow_cli`` rewrites for
``/config`` and ``/knowledge``. ``config.load_config`` deliberately re-raises on
a parse error unless the packaged desktop build is running, so a truncated
``config.json`` means the next start fails outright in a source deployment.

Both files now go through ``_write_json_atomically``: serialise into a sibling
``<path>.tmp`` and ``os.replace`` it into place, so the real path only ever
holds the old or the new content.
"""
import json
import os

import pytest

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "cow_cli")
try:
    from plugins.cow_cli.cow_cli import KNOWN_COMMANDS
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

CowCliPlugin = plugins.instance.plugins["COW_CLI"]

EXISTING = {
    "alpha": {"source": "custom", "enabled": True},
    "beta": {"source": "github", "enabled": False},
}


def test_the_writes_under_test_are_reachable_from_chat():
    """These are user-facing chat commands, not dead code."""
    assert {"skill", "config"} <= KNOWN_COMMANDS


def _skills_dir(tmp_path, monkeypatch):
    """Point ``cow_cli`` at a private skills directory holding two records."""
    skills_dir = tmp_path / "skills"
    (skills_dir / "alpha").mkdir(parents=True)
    (skills_dir / "alpha" / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    config_path = skills_dir / "skills_config.json"
    config_path.write_text(json.dumps(EXISTING, indent=4), encoding="utf-8")
    monkeypatch.setattr("cli.utils.get_skills_dir", lambda: str(skills_dir))
    return config_path


def _fail_halfway(monkeypatch):
    """Make the next ``json.dump`` die after writing a partial object."""
    def _dump(obj, fp, **kwargs):
        fp.write('{\n    "half')
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", _dump)


def _read(config_path):
    return json.loads(config_path.read_text(encoding="utf-8"))


def _leftover(config_path):
    return sorted(p.name for p in config_path.parent.iterdir())


def test_a_failed_enable_keeps_the_existing_records(tmp_path, monkeypatch):
    config_path = _skills_dir(tmp_path, monkeypatch)
    _fail_halfway(monkeypatch)

    with pytest.raises(OSError):
        CowCliPlugin()._skill_set_enabled("alpha", False)

    assert _read(config_path) == EXISTING
    assert _leftover(config_path) == ["alpha", "skills_config.json"]


def test_a_failed_uninstall_keeps_the_existing_records(tmp_path, monkeypatch):
    config_path = _skills_dir(tmp_path, monkeypatch)
    _fail_halfway(monkeypatch)

    CowCliPlugin()._skill_uninstall("alpha")

    assert _read(config_path) == EXISTING
    # nothing of the aborted replacement is left beside the file
    assert _leftover(config_path) == ["skills_config.json"]
