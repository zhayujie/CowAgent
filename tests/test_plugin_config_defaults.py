"""A plugin whose config.json is empty or only half-filled in must still start.

Both plugins here read required keys straight out of whatever
``Plugin.load_config()`` returned, so a config file that exists but does not
carry them (``{}``, or one key of the two) raised ``KeyError`` in ``__init__``.
``PluginManager.activate_plugins`` answers a plugin that fails to initialise by
disabling it and **persisting** ``enabled=false``, so the plugin then stayed off
across restarts, even after the user put the file right again.

The tests point each plugin at a config under ``tmp_path`` rather than the one
in the repo: ``__file__`` is what the plugin uses for its own directory, and
``Plugin.path`` is what ``load_config`` uses, so both are redirected.
"""
import builtins
import importlib
import json

import pytest

import config
import plugins

PLUGINS = ("banwords", "godcmd")


@pytest.fixture(autouse=True)
def _isolate_global_plugin_config():
    """``Plugin.load_config`` caches into ``config.plugin_config``.

    A leftover entry from another test would be returned instead of the file
    the test just wrote, short-circuiting the case under test.
    """
    for name in PLUGINS:
        config.plugin_config.pop(name, None)
    yield
    for name in PLUGINS:
        config.plugin_config.pop(name, None)


def _load(module_name, plugin_dir, registry_name):
    """Import the plugin module and return it with its registered class.

    ``plugins.register`` binds the decorated name to ``None`` (its wrapper
    returns nothing), so the class has to be read out of the manager.
    """
    plugins.instance.current_plugin_path = plugin_dir
    try:
        module = importlib.import_module(module_name)
    finally:
        plugins.instance.current_plugin_path = None
    return module, plugins.instance.plugins[registry_name]


def _point_at(monkeypatch, module, plugin_cls, tmp_path):
    monkeypatch.setattr(module, "__file__", str(tmp_path / f"{module.__name__}.py"))
    monkeypatch.setattr(plugin_cls, "path", str(tmp_path))
    return tmp_path / "config.json"


def test_banwords_starts_with_an_empty_config_object(tmp_path, monkeypatch):
    module, banwords = _load("plugins.banwords.banwords", "./plugins/banwords", "BANWORDS")
    config_path = _point_at(monkeypatch, module, banwords, tmp_path)
    config_path.write_text("{}", encoding="utf-8")

    plugin = banwords()

    assert plugin.action == "ignore"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"action": "ignore"}


def test_godcmd_starts_with_an_empty_config_object(tmp_path, monkeypatch):
    module, godcmd = _load("plugins.godcmd.godcmd", "./plugins/godcmd", "GODCMD")
    config_path = _point_at(monkeypatch, module, godcmd, tmp_path)
    config_path.write_text("{}", encoding="utf-8")

    plugin = godcmd()

    assert plugin.password == ""
    assert plugin.admin_users == []
    assert plugin.temp_password and len(plugin.temp_password) == 4
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "password": "",
        "admin_users": [],
    }


def test_godcmd_keeps_the_keys_the_config_does_carry(tmp_path, monkeypatch):
    module, godcmd = _load("plugins.godcmd.godcmd", "./plugins/godcmd", "GODCMD")
    config_path = _point_at(monkeypatch, module, godcmd, tmp_path)
    config_path.write_text('{"password": "set-by-the-user"}', encoding="utf-8")

    plugin = godcmd()

    assert plugin.password == "set-by-the-user"
    assert plugin.temp_password is None
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "password": "set-by-the-user",
        "admin_users": [],
    }


def test_banwords_still_writes_the_default_when_the_file_is_missing(tmp_path, monkeypatch):
    module, banwords = _load("plugins.banwords.banwords", "./plugins/banwords", "BANWORDS")
    config_path = _point_at(monkeypatch, module, banwords, tmp_path)

    plugin = banwords()

    assert plugin.action == "ignore"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"action": "ignore"}


def _reject_writes(monkeypatch):
    """Make every write-mode ``open`` fail, the way a read-only dir does.

    Packaged desktop builds can ship the plugin directory read-only, so writing
    the repaired config back is best-effort. Raising there would reach
    ``activate_plugins``, which persists ``enabled=false`` -- the outcome the
    default-config fallback exists to avoid in the first place.
    """
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode or "x" in mode:
            raise PermissionError(13, "Read-only file system", str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)


@pytest.mark.parametrize(
    "module_name, plugin_dir, registry_name",
    [
        ("plugins.banwords.banwords", "./plugins/banwords", "BANWORDS"),
        ("plugins.godcmd.godcmd", "./plugins/godcmd", "GODCMD"),
    ],
)
def test_a_read_only_plugin_dir_does_not_take_the_plugin_down(
    tmp_path, monkeypatch, module_name, plugin_dir, registry_name
):
    module, plugin_cls = _load(module_name, plugin_dir, registry_name)
    config_path = _point_at(monkeypatch, module, plugin_cls, tmp_path)
    config_path.write_text("{}", encoding="utf-8")
    _reject_writes(monkeypatch)

    plugin = plugin_cls()  # must not raise

    # The in-memory defaults are enough to run; only the repair on disk is lost.
    if registry_name == "BANWORDS":
        assert plugin.action == "ignore"
    else:
        assert plugin.password == ""
        assert plugin.admin_users == []
    assert config_path.read_text(encoding="utf-8") == "{}"
