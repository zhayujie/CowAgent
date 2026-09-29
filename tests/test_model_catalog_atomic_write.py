"""The catalog store and the legacy cleanup must not be truncated in place.

``_write_store`` wrote straight into the overlay file and
``_strip_legacy_config_key`` straight into config.json, so a failure partway
through -- a full disk, an update interrupted mid-copy -- leaves a document that
no longer parses. The two are worse in opposite directions:

- The overlay store fails *silently*. ``_read_store`` swallows the decode error
  on purpose ("Never raises: a corrupt file yields an empty store rather than
  taking the whole models view down"), so the user's overrides read back as
  "none at all", and the next ``save_catalog`` -- which reads the store fresh
  before rewriting it -- writes that empty baseline back. A recoverable file
  becomes a permanent loss.
- config.json fails *loudly*. ``load_config`` treats an unparseable user config
  as corruption, and the desktop client then quarantines it and drops in
  config-template.json, so every API key and channel credential goes with it.

Both now go through one helper that builds the result beside the file and
os.replace()s it in, the shape the rest of the tree already uses.
"""
import json

import pytest

from models import model_catalog


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "system" / "models.json"
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    return path


@pytest.fixture(autouse=True)
def _clear_cache():
    """_load caches the store in a module global; a leftover would hide the file
    each test just wrote."""
    model_catalog._invalidate()
    yield
    model_catalog._invalidate()


def _fail_after(monkeypatch, prefix):
    """Make json.dump emit ``prefix`` and then fail, the way a full disk does."""

    def failing_dump(obj, fp, **kwargs):
        fp.write(prefix)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", failing_dump)


def test_a_failed_store_write_keeps_the_previous_store(store_path, monkeypatch):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps({"providers": {"p1": {"overrides": [], "hidden": []}}}, indent=4)
    store_path.write_text(good, encoding="utf-8")
    _fail_after(monkeypatch, '{\n    "providers": {\n        "p1": ')

    with pytest.raises(OSError):
        model_catalog._write_store({"providers": {}})

    assert store_path.read_text(encoding="utf-8") == good


def test_a_failed_store_write_leaves_no_temp_file(store_path, monkeypatch):
    _fail_after(monkeypatch, "{")

    with pytest.raises(OSError):
        model_catalog._write_store({"providers": {}})

    assert not (store_path.parent / "models.json.tmp").exists()


def test_a_store_write_lands_in_one_piece(store_path):
    doc = {"providers": {"p1": {"overrides": [{"name": "m"}], "hidden": ["old"]}}}

    model_catalog._write_store(doc)

    assert json.loads(store_path.read_text(encoding="utf-8")) == doc
    assert not (store_path.parent / "models.json.tmp").exists()


def test_a_failed_legacy_cleanup_keeps_config_json(tmp_path, monkeypatch):
    """_strip_legacy_config_key rewrites the user's whole config.json."""
    cfg = tmp_path / "config.json"
    good = json.dumps(
        {"web_password": "hunter2", "provider_model_catalog": {"p1": []}}, indent=4
    )
    cfg.write_text(good, encoding="utf-8")

    import config

    monkeypatch.setattr(config, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(config, "conf", lambda: {"provider_model_catalog": {"p1": []}})
    _fail_after(monkeypatch, '{\n    "web_password": "hunter2",\n    "prov')

    with pytest.raises(OSError):
        model_catalog._strip_legacy_config_key()

    assert cfg.read_text(encoding="utf-8") == good


def test_saving_a_catalog_keeps_the_providers_already_stored(store_path):
    """The control for the silent-loss path: save_catalog reads the store back
    before rewriting it, so anything it cannot see is gone for good."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps({"providers": {"keep": {"overrides": [{"name": "m"}], "hidden": []}}}),
        encoding="utf-8",
    )

    model_catalog.save_catalog("added", [{"name": "n"}])

    saved = json.loads(store_path.read_text(encoding="utf-8"))["providers"]
    assert "keep" in saved
    assert "added" in saved
