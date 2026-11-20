# encoding:utf-8
"""The catalog editor's backend contract, for the OVERLAY model.

A provider's catalog is an overlay on its presets, not a replacement:
- ``seed`` is the preset base (typed with real capabilities),
- ``catalog`` is the user's overrides, ``hidden`` the removed presets,
- ``effective`` is the merged list the editor loads.

These tests pin that contract, the overlay storage roundtrip, and the merge
that layers overrides onto the presets while dropping tombstoned models.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub


def _providers_with(config, catalog_map=None, hidden_map=None):
    """Provider overview rows, as the models API returns them."""
    from channel.web.api import models as models_api

    with patch.object(models_api, "conf", return_value=config), \
            patch("models.custom_provider.conf", return_value=config), \
            patch("channel.web.api.models.model_catalog.get_catalog_map",
                  return_value=catalog_map or {}), \
            patch("channel.web.api.models.model_catalog.get_hidden_map",
                  return_value=hidden_map or {}):
        return models_api.ModelsHandler._provider_overview()


def _provider(config, pid, catalog_map=None, hidden_map=None):
    for p in _providers_with(config, catalog_map, hidden_map):
        if p["id"] == pid:
            return p
    return None


class TestSeedRows(unittest.TestCase):
    """`seed` gives the editor the preset base typed with real capabilities."""

    def test_a_builtin_vendor_seeds_its_preset_models(self):
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu")
        self.assertIsNotNone(p)
        self.assertTrue(p["seed"], "a built-in vendor must offer seed rows")
        names = [e["name"] for e in p["seed"]]
        self.assertIn("glm-5.2", names)

    def test_every_seed_row_carries_at_least_one_tag(self):
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu")
        for entry in p["seed"]:
            self.assertTrue(
                entry.get("capabilities"),
                f"seed row {entry.get('name')!r} has no capabilities",
            )

    def test_only_conversational_presets_are_tagged_text(self):
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu")
        asr_only = [e for e in p["seed"] if e["capabilities"] == ["asr"]]
        self.assertTrue(asr_only, "expected at least one ASR-only preset")
        for entry in asr_only:
            self.assertNotIn("text", entry["capabilities"])

    def test_a_model_listed_for_two_roles_carries_both_tags(self):
        p = _provider({"open_ai_api_key": "sk-x"}, "openai")
        by_name = {e["name"]: e for e in p["seed"]}
        vl = next((e for n, e in by_name.items()
                   if set(["text", "vision"]).issubset(e["capabilities"])), None)
        self.assertIsNotNone(vl, "no OpenAI preset carries both text+vision")

    def test_the_legacy_custom_card_has_no_seed(self):
        p = _provider({"custom_api_key": "sk-x"}, "custom")
        if p:  # hidden in multi-provider mode; only assert when present
            self.assertEqual(p["seed"], [])


class TestEffectiveAndOverlayFields(unittest.TestCase):
    """The editor loads `effective` and diffs against `seed`/`catalog`."""

    def test_without_an_overlay_effective_equals_the_presets(self):
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu")
        self.assertFalse(p["catalog"])
        self.assertFalse(p["hidden"])
        self.assertEqual(
            [e["name"] for e in p["effective"]],
            [e["name"] for e in p["seed"]],
        )

    def test_an_override_replaces_only_that_models_metadata(self):
        """The other presets stay on the effective list — an overlay adds to
        the presets, it does not wipe them."""
        override = [{"name": "glm-5.2", "capabilities": ["text"], "context_window": 200000}]
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu",
                      catalog_map={"zhipu": override})
        names = [e["name"] for e in p["effective"]]
        # Every preset is still present...
        for s in p["seed"]:
            self.assertIn(s["name"], names)
        # ...but glm-5.2 now carries the user's window.
        g52 = next(e for e in p["effective"] if e["name"] == "glm-5.2")
        self.assertEqual(g52["context_window"], 200000)

    def test_builtin_alias_is_exposed_separately_from_raw_model_names(self):
        override = [{"name": "glm-5.2", "alias": "GLM-5.2", "capabilities": ["text"]}]
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu",
                      catalog_map={"zhipu": override})
        self.assertIn("glm-5.2", p["models"])
        self.assertEqual(p["model_labels"], {"glm-5.2": "GLM-5.2"})

    def test_a_hidden_preset_drops_out_of_the_effective_list(self):
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu",
                      hidden_map={"zhipu": ["glm-5.2"]})
        names = [e["name"] for e in p["effective"]]
        self.assertNotIn("glm-5.2", names)

    def test_a_new_override_is_appended_to_the_presets(self):
        override = [{"name": "brand-new-model", "capabilities": ["text"]}]
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu",
                      catalog_map={"zhipu": override})
        names = [e["name"] for e in p["effective"]]
        self.assertIn("brand-new-model", names)
        self.assertGreater(len(names), 1, "presets must still be present")

    def test_models_field_follows_the_effective_list(self):
        override = [{"name": "brand-new-model", "capabilities": ["text"]}]
        p = _provider({"zhipu_ai_api_key": "sk-x"}, "zhipu",
                      catalog_map={"zhipu": override})
        self.assertIn("brand-new-model", p["models"])


class TestApplyCatalogFiltersByCapability(unittest.TestCase):
    """The chat dropdown only offers text-tagged models from the overlay."""

    def test_no_overlay_keeps_the_preset_dropdown(self):
        from channel.web.api import models as models_api

        presets = {"zhipu": [{"value": "glm-5.2"}]}
        with patch("channel.web.api.models.model_catalog.get_catalog_map", return_value={}), \
                patch("channel.web.api.models.model_catalog.get_hidden_map", return_value={}):
            out = models_api.ModelsHandler._apply_catalog(presets, "text")
        self.assertEqual(out["zhipu"], [{"value": "glm-5.2"}])

    def test_overlay_narrows_to_text_tagged_effective_models(self):
        from channel.web.api import models as models_api

        override = [{"name": "chat-only", "capabilities": ["text"]},
                    {"name": "vec", "capabilities": ["embedding"]}]
        with patch("channel.web.api.models.model_catalog.get_catalog_map",
                   return_value={"zhipu": override}), \
                patch("channel.web.api.models.model_catalog.get_hidden_map", return_value={}):
            out = models_api.ModelsHandler._apply_catalog({}, "text")
        names = [m["value"] for m in out["zhipu"]]
        self.assertIn("chat-only", names)
        self.assertNotIn("vec", names, "embedding-only model must not reach the chat dropdown")

    def test_overlay_alias_is_picker_label_and_raw_id_hint(self):
        from channel.web.api import models as models_api

        override = [{"name": "raw/model-id", "alias": "Friendly", "capabilities": ["text"]}]
        with patch("channel.web.api.models.model_catalog.get_catalog_map",
                   return_value={"zhipu": override}), \
                patch("channel.web.api.models.model_catalog.get_hidden_map", return_value={}):
            out = models_api.ModelsHandler._apply_catalog({}, "text")
        self.assertIn({
            "value": "raw/model-id", "label": "Friendly", "hint": "raw/model-id",
        }, out["zhipu"])


class TestSaveCatalogHandler(unittest.TestCase):
    """POST action=save_catalog -- what the editor's Save button calls."""

    def _post(self, payload):
        import json

        from channel.web.api import models as models_api

        handler = models_api.ModelsHandler()
        with patch.object(models_api, "conf", return_value={}), \
                patch("channel.web.api.models.model_catalog.save_catalog",
                      return_value=payload.get("models") or []) as save:
            raw = handler._handle_save_catalog(payload)
        data = json.loads(raw)
        return data, save

    def test_a_valid_overlay_saves(self):
        data, save = self._post({
            "provider_id": "zhipu",
            "models": [{"name": "glm-5.2", "capabilities": ["text"]}],
            "hidden": ["glm-4.7"],
        })
        self.assertEqual(data["status"], "success")
        save.assert_called_once()
        # hidden is forwarded to the storage layer.
        self.assertEqual(save.call_args[0][2], ["glm-4.7"])

    def test_an_empty_overlay_clears_back_to_presets(self):
        data, _ = self._post({"provider_id": "zhipu", "models": [], "hidden": []})
        self.assertEqual(data["status"], "success")

    def test_a_missing_provider_id_is_rejected(self):
        data, save = self._post({"models": []})
        self.assertEqual(data["status"], "error")
        save.assert_not_called()

    def test_an_unknown_provider_is_rejected(self):
        data, _ = self._post({"provider_id": "not-a-vendor", "models": []})
        self.assertEqual(data["status"], "error")

    def test_a_custom_provider_id_is_accepted(self):
        data, _ = self._post({"provider_id": "custom:3f2a9c1b", "models": []})
        self.assertEqual(data["status"], "success")


class TestOverlayStorage(unittest.TestCase):
    """The storage layer roundtrips overrides + hidden to system/models.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cow_catalog_")
        # The store lives at <shared workspace>/system/models.json; point that
        # workspace at a temp dir so the test never touches a real one.
        from common import state_dir
        self._store = os.path.join(self.tmp, "system", "models.json")
        self.patcher = patch.object(
            state_dir, "models_catalog_file", return_value=state_dir.Path(self._store))
        self.patcher.start()
        from models import model_catalog
        self.mc = model_catalog
        self.mc._invalidate()

    def tearDown(self):
        self.patcher.stop()
        self.mc._invalidate()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_writes_under_system_models_json(self):
        self.mc.save_catalog("zhipu", [{"name": "m", "capabilities": ["text"]}], [])
        self.assertTrue(os.path.exists(self._store))
        self.assertTrue(self._store.endswith(os.path.join("system", "models.json")))

    def test_it_does_not_touch_config_json(self):
        self.mc.save_catalog("zhipu", [{"name": "m", "capabilities": ["text"]}], ["x"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "config.json")))

    def test_overrides_and_hidden_roundtrip(self):
        self.mc.save_catalog(
            "zhipu",
            [{"name": "glm-5.3", "capabilities": ["text"], "context_window": 2000000}],
            ["glm-4.7"],
        )
        self.assertEqual(self.mc.get_catalog_map()["zhipu"][0]["context_window"], 2000000)
        self.assertEqual(self.mc.get_hidden_map()["zhipu"], ["glm-4.7"])

    def test_an_empty_overlay_drops_the_provider(self):
        self.mc.save_catalog("zhipu", [{"name": "m", "capabilities": ["text"]}], [])
        self.mc.save_catalog("zhipu", [], [])
        self.assertNotIn("zhipu", self.mc.get_catalog_map())
        self.assertNotIn("zhipu", self.mc.get_hidden_map())

    def test_a_name_cannot_be_both_overridden_and_hidden(self):
        """The override wins; the redundant tombstone is dropped."""
        self.mc.save_catalog(
            "zhipu", [{"name": "glm-5.2", "capabilities": ["text"]}], ["glm-5.2"])
        self.assertEqual(self.mc.get_hidden_map().get("zhipu"), None)

    def test_resolve_returns_override_but_not_untouched_presets(self):
        """An untouched preset resolves to {} so the budget resolver falls back
        to the code-side constants — a later constant bump still reaches it."""
        self.mc.save_catalog(
            "zhipu",
            [{"name": "glm-5.3", "capabilities": ["text"], "context_window": 2000000}],
            [],
        )
        self.assertEqual(
            self.mc.resolve_model_meta("zhipu", "glm-5.3").get("context_window"), 2000000)
        self.assertEqual(self.mc.resolve_model_meta("zhipu", "glm-5.2"), {})

    def test_a_legacy_bare_list_doc_is_read_as_overrides(self):
        """A hand-written models.json using the old bare-list shape still loads."""
        import json

        os.makedirs(os.path.dirname(self._store), exist_ok=True)
        with open(self._store, "w") as f:
            json.dump({"providers": {"zhipu": [{"name": "m", "capabilities": ["text"]}]}}, f)
        self.mc._invalidate()
        self.assertEqual(self.mc.get_catalog_map()["zhipu"][0]["name"], "m")


class TestLegacyConfigMigration(unittest.TestCase):
    """A pre-overlay config.json catalog is imported once, then removed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cow_catalog_")
        self._store = os.path.join(self.tmp, "system", "models.json")
        self._config = os.path.join(self.tmp, "config.json")
        from common import state_dir
        self.state_dir = state_dir
        self.store_patcher = patch.object(
            state_dir, "models_catalog_file", return_value=state_dir.Path(self._store))
        self.store_patcher.start()
        from models import model_catalog
        self.mc = model_catalog
        self.mc._invalidate()

    def tearDown(self):
        self.store_patcher.stop()
        self.mc._invalidate()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_config(self, data):
        import json
        with open(self._config, "w") as f:
            json.dump(data, f)

    def test_legacy_catalog_migrates_to_overlay_and_is_stripped(self):
        self._write_config({
            "provider_model_catalog": {
                "zhipu": [{"name": "glm-legacy", "capabilities": ["text"],
                           "context_window": 999}]
            }
        })
        live = {"provider_model_catalog": {
            "zhipu": [{"name": "glm-legacy", "capabilities": ["text"],
                       "context_window": 999}]}}
        with patch("config.conf", return_value=live), \
                patch("config.get_data_root", return_value=self.tmp):
            got = self.mc.get_catalog_map()
        # Migrated into the overlay store as an override...
        self.assertEqual(got["zhipu"][0]["name"], "glm-legacy")
        self.assertEqual(got["zhipu"][0]["context_window"], 999)
        self.assertTrue(os.path.exists(self._store))
        # ...and the legacy key removed from both the file and the live config.
        import json
        with open(self._config) as f:
            self.assertNotIn("provider_model_catalog", json.load(f))
        self.assertNotIn("provider_model_catalog", live)

    def test_migration_does_not_run_when_overlay_already_exists(self):
        import json
        os.makedirs(os.path.dirname(self._store), exist_ok=True)
        with open(self._store, "w") as f:
            json.dump({"providers": {"zhipu": {
                "overrides": [{"name": "keep", "capabilities": ["text"]}],
                "hidden": []}}}, f)
        self._write_config({"provider_model_catalog": {
            "zhipu": [{"name": "should-not-win", "capabilities": ["text"]}]}})
        with patch("config.conf", return_value={"provider_model_catalog": {
                "zhipu": [{"name": "should-not-win", "capabilities": ["text"]}]}}), \
                patch("config.get_data_root", return_value=self.tmp):
            got = self.mc.get_catalog_map()
        self.assertEqual(got["zhipu"][0]["name"], "keep")


class TestCatalogNormalization(unittest.TestCase):
    """Rules the editor relies on when building its payload."""

    def test_a_row_without_a_name_is_rejected(self):
        from models import model_catalog

        with self.assertRaises(ValueError):
            model_catalog.normalize_entry({"capabilities": ["text"]})

    def test_capabilities_default_to_text(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry({"name": "m"})
        self.assertEqual(entry["capabilities"], ["text"])

    def test_an_unknown_capability_is_dropped_not_rejected(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry({"name": "m", "capabilities": ["text", "telepathy"]})
        self.assertEqual(entry["capabilities"], ["text"])

    def test_a_capitalised_capability_is_kept_lowercased(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry({"name": "m", "capabilities": [" Vision ", "TEXT"]})
        self.assertEqual(entry["capabilities"], ["vision", "text"])

    def test_a_row_of_only_unknown_capabilities_falls_back_to_text(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry({"name": "m", "capabilities": ["telepathy"]})
        self.assertEqual(entry["capabilities"], ["text"])

    def test_a_non_positive_context_window_is_rejected(self):
        from models import model_catalog

        with self.assertRaises(ValueError):
            model_catalog.normalize_entry({"name": "m", "context_window": 0})

    def test_an_unbudgeted_model_can_be_saved_without_numbers(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry(
            {"name": "text-embed-3", "capabilities": ["embedding"]})
        self.assertEqual(entry["capabilities"], ["embedding"])
        self.assertNotIn("context_window", entry)
        self.assertNotIn("max_output_tokens", entry)

    def test_a_model_can_carry_both_text_and_an_extra_role(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry(
            {"name": "vl", "capabilities": ["text", "vision"], "context_window": 128000})
        self.assertEqual(sorted(entry["capabilities"]), ["text", "vision"])
        self.assertEqual(entry["context_window"], 128000)

    def test_set_but_valid_numbers_are_kept(self):
        from models import model_catalog

        entry = model_catalog.normalize_entry(
            {"name": "m", "context_window": 200000, "max_output_tokens": 16000})
        self.assertEqual(entry["context_window"], 200000)
        self.assertEqual(entry["max_output_tokens"], 16000)


if __name__ == "__main__":
    unittest.main()
