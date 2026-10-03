"""Reloading a plugin must not discard the configuration it already has.

``PluginManager.reload_plugin`` used to call ``remove_plugin_config(name)`` on
the way in, to force the fresh instance to re-read its settings. That only ever
worked for a plugin carrying its own ``config.json`` in its bundle: the loader
falls back to that file and never looks at ``plugins/config.json``, which is
where a plugin configured at runtime actually lives.

So the entry was dropped and nothing put it back. A plugin with no bundle file
came up on its documented defaults, and the reload reported success. Measured
through the real ``PluginManager`` and the real ``Godcmd``:

    before reload : {'password': 's3cret', 'admin_users': ['alice']}
    reload_plugin returned: True
      live instance : password='' admin_users=[] temp='9623'

The admin password and the admin list are gone, and a random four-digit
temporary password is logged in their place -- the admin has locked themselves
out until the process restarts. The removal also ran before the membership
check, so ``#reloadp <a name that is not loaded>`` erased that plugin's settings
before discovering there was nothing to reload.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from plugins.plugin_manager import PluginManager


class ReloadPluginKeepsConfigTest(unittest.TestCase):
    """A reload re-instantiates the plugin; it must not reconfigure it."""

    def setUp(self):
        # PluginManager is a @singleton, so every test in the process gets this
        # one object: everything touched here has to be handed back, or the next
        # test finds a registry with a single plugin in it.
        self.manager = PluginManager()
        self._saved = {
            attr: getattr(self.manager, attr)
            for attr in ("plugins", "instances", "listening_plugins",
                         "current_plugin_path", "save_config", "disable_plugin")
        }
        self._saved_plugin_config = config.plugin_config
        self.addCleanup(self._restore)

        # A scratch plugin path, so registering a plugin here touches no real
        # installation. It has to be in place before the plugin module is
        # imported, because @register refuses to register without one.
        self.manager.current_plugin_path = os.path.join(
            tempfile.mkdtemp(prefix="reloadp-"), "godcmd")
        os.makedirs(self.manager.current_plugin_path, exist_ok=True)
        self.manager.save_config = lambda: None
        self.manager.disable_plugin = lambda name: None

        import plugins.godcmd.godcmd as godcmd_mod

        self.godcmd_mod = godcmd_mod
        self._saved_global_config = dict(godcmd_mod.global_config)

        # Narrow the registry to Godcmd so activate_plugins cannot wander into
        # other plugins. @register does not return the class, so the module
        # attribute is None and the registry is where the class lives.
        self.godcmd_cls = self.manager.plugins["GODCMD"]
        self.manager.plugins = {"GODCMD": self.godcmd_cls}

    def _restore(self):
        for attr, value in self._saved.items():
            setattr(self.manager, attr, value)
        config.plugin_config = self._saved_plugin_config
        self.godcmd_mod.global_config.clear()
        self.godcmd_mod.global_config.update(self._saved_global_config)
        # Godcmd repairs a missing config.json in its own bundle directory; drop
        # whatever this run produced.
        path = os.path.join(os.path.dirname(self.godcmd_mod.__file__), "config.json")
        if os.path.exists(path):
            os.remove(path)

    def _configure(self, password="s3cret", admins=("alice",)):
        config.plugin_config = {
            "godcmd": {"password": password, "admin_users": list(admins)}
        }
        self.manager.activate_plugins()
        return self.manager.instances["GODCMD"]

    def test_a_reload_keeps_the_configured_password_and_admins(self):
        before = self._configure()
        self.assertEqual(before.password, "s3cret")
        self.assertEqual(before.admin_users, ["alice"])

        self.assertTrue(self.manager.reload_plugin("GODCMD"))

        after = self.manager.instances["GODCMD"]
        self.assertEqual(after.password, "s3cret",
                         "#reloadp cleared the admin password")
        self.assertEqual(after.admin_users, ["alice"],
                         "#reloadp cleared the admin list")

    def test_a_reload_does_not_invent_a_temporary_password(self):
        self._configure()
        self.manager.reload_plugin("GODCMD")

        after = self.manager.instances["GODCMD"]
        self.assertIsNone(
            after.temp_password,
            "a fresh temporary password means the configured one was thrown away",
        )

    def test_the_config_entry_survives_the_reload(self):
        self._configure()
        self.manager.reload_plugin("GODCMD")

        self.assertEqual(
            config.pconf("Godcmd"),
            {"password": "s3cret", "admin_users": ["alice"]},
            "the in-memory plugin config lost its entry",
        )

    def test_reloading_a_name_that_is_not_loaded_changes_nothing(self):
        # Settings for a plugin that is configured but not currently loaded --
        # disabled, or filtered out of this workspace. There is nothing to
        # reload, so the config must be left alone.
        config.plugin_config = {
            "godcmd": {"password": "s3cret", "admin_users": ["alice"]},
            "banwords": {"password": "other", "admin_users": ["bob"]},
        }

        self.assertNotIn("BANWORDS", self.manager.instances)
        self.assertFalse(self.manager.reload_plugin("Banwords"))

        self.assertEqual(
            config.pconf("Banwords"), {"password": "other", "admin_users": ["bob"]},
            "a reload that found nothing to do still erased the config",
        )

    def test_a_reload_still_replaces_the_instance(self):
        # The point of reload_plugin: the old instance goes, a new one is built.
        first = self._configure()
        self.manager.reload_plugin("GODCMD")
        second = self.manager.instances["GODCMD"]

        self.assertIsNot(first, second, "reload did not re-instantiate the plugin")
        self.assertEqual(self.manager.instances["GODCMD"].password, "s3cret")


if __name__ == "__main__":
    unittest.main()