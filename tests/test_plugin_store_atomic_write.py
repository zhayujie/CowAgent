"""plugins.json has to survive a bad write, and a bad file must not stop the load.

``PluginManager.save_config`` wrote straight into plugins.json, so anything that
failed partway through -- a full disk, an update interrupted mid-copy -- left a
truncated document where the plugin states used to be. ``load_config`` then read
it with a bare ``json.load`` and no guard, so the next start raised
``JSONDecodeError`` out of ``load_plugins``. ``app.py:252`` calls that on first
start, and the desktop client calls it on a daemon thread, so the same raise
became either a failed start or a plugin system that never comes up and logs
nothing at all.

The store is the only place ``enabled`` and ``priority`` live, and six call
sites write it (enable, disable, set priority, install, uninstall, first scan),
so losing it takes every plugin back to defaults.

``_plugins_data_dir`` and ``_plugins_resource_dir`` are redirected at the module
so both copies land under tmp_path; the real ones are the CWD-relative
``./plugins`` in a source checkout.
"""
import json

import pytest

from common.sorted_dict import SortedDict
from plugins import plugin_manager


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect both plugin dirs at tmp_path and return (writable, shipped)."""
    data_dir = tmp_path / "data"
    res_dir = tmp_path / "res"
    data_dir.mkdir()
    res_dir.mkdir()
    monkeypatch.setattr(plugin_manager, "_plugins_data_dir", lambda: str(data_dir))
    monkeypatch.setattr(plugin_manager, "_plugins_resource_dir", lambda: str(res_dir))
    return data_dir / "plugins.json", res_dir / "plugins.json"


def _pconf(godcmd_enabled=True):
    return {
        "plugins": {
            "GODCMD": {"enabled": godcmd_enabled, "priority": 9999},
        }
    }


def _load():
    return plugin_manager.PluginManager.new_instance().load_config()


def _sorted_pconf(entries):
    return {"plugins": SortedDict(lambda k, v: v["priority"], entries, reverse=True)}


def test_a_truncated_store_does_not_raise_out_of_load_config(store):
    """The headline case: this used to raise JSONDecodeError and abort startup."""
    data_cfg, _ = store
    data_cfg.write_text(
        '{\n    "plugins": {\n        "GODCMD": {\n            "enabl', encoding="utf-8"
    )

    pconf = _load()

    assert list(pconf["plugins"]) == []


def test_a_truncated_store_is_repaired_on_disk(store):
    """Recovering in memory is not enough -- the next start reads it again."""
    data_cfg, _ = store
    data_cfg.write_text('{"plugins": {"GODCMD": {"enabled": tru', encoding="utf-8")

    _load()

    assert json.loads(data_cfg.read_text(encoding="utf-8")) == {"plugins": {}}


def test_a_damaged_writable_copy_falls_back_to_the_shipped_one(store):
    """The fallback load_config documents, now reachable.

    It was already written as "prefer the data dir, fall back to the resource
    dir", but it picked between them with os.path.exists, and a damaged file
    passes that check.
    """
    data_cfg, res_cfg = store
    data_cfg.write_text('{"plugins": {"GODCMD": {"enabled": tru', encoding="utf-8")
    res_cfg.write_text(json.dumps(_pconf()), encoding="utf-8")

    pconf = _load()

    assert list(pconf["plugins"]) == ["GODCMD"]
    assert pconf["plugins"]["GODCMD"]["enabled"] is True
    # And the writable copy is put back in a usable state.
    assert json.loads(data_cfg.read_text(encoding="utf-8"))["plugins"]["GODCMD"]["enabled"] is True


def test_a_store_that_parsed_but_lost_its_plugins_mapping_is_ignored(store):
    """Valid JSON is not the same as a valid store: the old code then hit
    KeyError one line later."""
    data_cfg, _ = store
    data_cfg.write_text('{"plugins_typo": {}}', encoding="utf-8")

    pconf = _load()

    assert list(pconf["plugins"]) == []


def test_a_healthy_store_is_loaded_without_being_rewritten(store):
    """The control: the guard must not pass by rewriting the file every time."""
    data_cfg, _ = store
    original = json.dumps({"plugins": {"GODCMD": {"enabled": True, "priority": 9999}}}, indent=4)
    data_cfg.write_text(original, encoding="utf-8")

    pconf = _load()

    assert list(pconf["plugins"]) == ["GODCMD"]
    assert pconf["plugins"]["GODCMD"]["priority"] == 9999
    assert data_cfg.read_text(encoding="utf-8") == original


def test_a_save_that_fails_keeps_the_previous_store(store, monkeypatch):
    """A save that dies partway must not take the old file with it."""
    data_cfg, _ = store
    good = json.dumps(_pconf(), indent=4)
    data_cfg.write_text(good, encoding="utf-8")

    def failing_dump(obj, fp, **kwargs):
        # json.dump streams, so the destination already holds a prefix when it
        # gives up -- that is the whole problem.
        fp.write('{\n    "plugins": {\n        "GODCMD": {\n            "enabl')
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", failing_dump)

    manager = plugin_manager.PluginManager.new_instance()
    manager.pconf = _sorted_pconf({"HELLO": {"enabled": False, "priority": 1}})

    with pytest.raises(OSError):
        manager.save_config()

    assert data_cfg.read_text(encoding="utf-8") == good


def test_a_failed_save_leaves_no_temp_file_behind(store, monkeypatch):
    data_cfg, _ = store

    def failing_dump(obj, fp, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", failing_dump)

    manager = plugin_manager.PluginManager.new_instance()
    manager.pconf = _sorted_pconf({"HELLO": {"enabled": False, "priority": 1}})

    with pytest.raises(OSError):
        manager.save_config()

    assert not (data_cfg.parent / "plugins.json.tmp").exists()
