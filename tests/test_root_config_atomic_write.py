"""What a config save leaves behind when it cannot finish.

The console routes build root ``config.json`` beside the file and swap it in, so
a save either lands whole or leaves the previous file standing (see
``_write_config_file_for_write``). Two paths outside the console still rewrite
it in place: the cloud client, which writes ``conf()`` back whole whenever a
remote action changes a channel, and the feishu one-click setup, which writes
the app id/secret it just created. Opening the file for writing cuts it short
before the new bytes exist, and ``json.dump`` streams, so anything that goes
wrong partway through -- a full disk, a value it cannot encode, the process
being killed -- leaves a half-written config.json where a complete one stood.

Neither file is a cache that could be rebuilt: what travels through both paths
is what the config file is for. ``load_config`` reads a file it cannot parse as
corruption, and the desktop self-heal path then quarantines it and substitutes
config-template.json, taking every provider key and saved channel credential
with it.

These tests pin the promise those two paths currently keep by accident.
"""

import errno
import importlib
import json
import sys
import types

# The remote client binds an optional runtime SDK at import time; stub it so the
# module can be imported without its parent transport. See
# test_feishu_channel_dispatch.py, which does the same.
if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")

    class _LinkAIClient:  # minimal base so CloudClient can subclass it
        def __init__(self, *a, **k):
            pass

    class _PushMsg:
        pass

    _stub.LinkAIClient = _LinkAIClient
    _stub.PushMsg = _PushMsg
    sys.modules["linkai"] = _stub

cloud_client = importlib.import_module("common.cloud_client")
feishu_channel = importlib.import_module("channel.feishu.feishu_channel")

ORIGINAL = {"agent_workspace": "/srv/cow", "web_password": "hunter2"}


def _an_existing_config(tmp_path):
    """A config.json already on disk, and the exact text it holds."""
    config_path = tmp_path / "config.json"
    text = json.dumps(ORIGINAL, indent=4, ensure_ascii=False)
    config_path.write_text(text, encoding="utf-8")
    return config_path, text


def _leftovers(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if p.name != "config.json")


def _a_disk_that_fills_up_mid_write(obj, fp, **kwargs):
    """Stand-in for ``json.dump`` that gets part of the document out and only
    then reports ENOSPC, the way a real full disk behaves."""
    fp.write('{\n    "agent_workspace": "/srv/cow",\n    "web_password": "hun')
    fp.flush()
    raise OSError(errno.ENOSPC, "No space left on device")


def _a_cloud_client(tmp_path, monkeypatch):
    """A client whose config.json lives in tmp_path.

    ``__new__`` skips ``__init__``, which would open the cloud transport.
    """
    config_path, original = _an_existing_config(tmp_path)
    monkeypatch.setattr(cloud_client, "get_data_root", lambda: str(tmp_path))
    return cloud_client.CloudClient.__new__(cloud_client.CloudClient), config_path, original


def _the_feishu_setup(tmp_path, monkeypatch):
    """Point the one-click setup at a config.json inside tmp_path.

    It derives the path from its own module file three directories up, so
    moving that is what moves the write, without ever touching the config.json
    next to the real source tree.
    """
    config_path, original = _an_existing_config(tmp_path)
    monkeypatch.setattr(feishu_channel, "__file__", str(tmp_path / "a" / "b" / "feishu_channel.py"))
    monkeypatch.setattr(feishu_channel, "conf", lambda: dict(ORIGINAL))
    return config_path, original


# ---------------------------------------------------------------------------
# The cloud client writes conf() back whole.
# ---------------------------------------------------------------------------

def test_a_cloud_save_that_cannot_finish_keeps_the_previous_config(tmp_path, monkeypatch):
    client, config_path, original = _a_cloud_client(tmp_path, monkeypatch)
    monkeypatch.setattr(json, "dump", _a_disk_that_fills_up_mid_write)

    client._save_config_to_file({"model": "gpt-4o"})

    assert config_path.read_text(encoding="utf-8") == original
    assert _leftovers(tmp_path) == []


def test_a_cloud_save_that_succeeds_replaces_the_file(tmp_path, monkeypatch):
    """The guard against a save that "keeps everything" by never writing."""
    client, config_path, _ = _a_cloud_client(tmp_path, monkeypatch)

    client._save_config_to_file({"model": "gpt-4o"})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "gpt-4o"
    assert saved["web_password"] == ORIGINAL["web_password"]
    assert _leftovers(tmp_path) == []


def test_a_cloud_save_lands_in_the_data_root(tmp_path, monkeypatch):
    """The desktop build sets COW_DATA_DIR=~/.cow and the docker image points it
    at /home/agent/.cow, and ``load_config`` reads the data root -- so a
    cloud-pushed config must be written where it will be read back. The save
    used to go to ``get_root()`` (the bundle), which on those deployments is a
    directory nobody reads: it either holds no config.json at all -- the push
    is then dropped with a warning -- or a stale one that is never loaded.
    """
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    data_config = data_root / "config.json"
    data_config.write_text(json.dumps(ORIGINAL, indent=4, ensure_ascii=False), encoding="utf-8")

    # Drive the real resolver: whatever it answers for COW_DATA_DIR is where a
    # save has to land, exactly as on a desktop or docker deployment.
    monkeypatch.setenv("COW_DATA_DIR", str(data_root))
    client = cloud_client.CloudClient.__new__(cloud_client.CloudClient)

    client._save_config_to_file({"model": "gpt-4o"})

    saved = json.loads(data_config.read_text(encoding="utf-8"))
    assert saved.get("model") == "gpt-4o"
    assert saved["web_password"] == ORIGINAL["web_password"]
    assert _leftovers(data_root) == []


# ---------------------------------------------------------------------------
# The feishu one-click setup writes the credentials it just created.
# ---------------------------------------------------------------------------

def test_the_feishu_setup_keeps_the_previous_config_when_the_save_fails(tmp_path, monkeypatch):
    config_path, original = _the_feishu_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(json, "dump", _a_disk_that_fills_up_mid_write)

    assert feishu_channel._persist_feishu_credentials("cli_x", "secret_x") is False

    assert config_path.read_text(encoding="utf-8") == original
    assert _leftovers(tmp_path) == []


def test_the_feishu_setup_still_writes_when_nothing_goes_wrong(tmp_path, monkeypatch):
    config_path, _ = _the_feishu_setup(tmp_path, monkeypatch)

    assert feishu_channel._persist_feishu_credentials("cli_x", "secret_x") is True

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["feishu_app_id"] == "cli_x"
    assert saved["feishu_app_secret"] == "secret_x"
    assert saved["web_password"] == ORIGINAL["web_password"]
    assert _leftovers(tmp_path) == []
