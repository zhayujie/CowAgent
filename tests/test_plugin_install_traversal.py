# encoding:utf-8
"""#installp must clone inside ./plugins and only run pip when needed.

The clone directory comes from the repo URL, and the clone is followed by a
pip install of its requirements, so a crafted URL must not choose a directory
outside ./plugins. pip only runs when the repo ships a requirements.txt.
"""
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.package_manager as pkgmgr
from plugins.plugin_manager import PluginManager

# @singleton wraps the class; the bare class rides on __wrapped__.
_PluginManager = PluginManager.__wrapped__


def _fake_dulwich(clone=None, pull=None):
    """Stand-in for dulwich.porcelain; dulwich itself need not be installed."""
    porcelain = types.SimpleNamespace(clone=clone or (lambda *a, **k: None),
                                      pull=pull or (lambda *a, **k: None))
    module = types.ModuleType("dulwich")
    module.porcelain = porcelain
    return patch.dict(sys.modules, {"dulwich": module, "dulwich.porcelain": porcelain})


class TestInstallPluginDirectory(unittest.TestCase):

    def setUp(self):
        self.pm = object.__new__(_PluginManager)
        self.clones = []
        self.pip_calls = []
        for p in (
            _fake_dulwich(clone=lambda repo, dirname, **k: self.clones.append(dirname)),
            patch.object(pkgmgr, "check_dulwich", lambda: None),
            patch.object(pkgmgr, "install_requirements", lambda path: self.pip_calls.append(path) or 0),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _install(self, url):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.makedirs("plugins", exist_ok=True)
                return self.pm.install_plugin(url)
            finally:
                os.chdir(cwd)

    def test_a_traversal_url_clones_inside_plugins(self):
        ok, _ = self._install("https://github.com/a/../../pwn.git")
        self.assertTrue(ok)
        self.assertEqual(self.clones, [os.path.join("./plugins", "pwn")])

    def test_an_absolute_path_url_clones_inside_plugins(self):
        ok, _ = self._install("https://github.com/o//tmp/pwn.git")
        self.assertTrue(ok)
        self.assertEqual(self.clones, [os.path.join("./plugins", "pwn")])

    def test_a_subgroup_url_uses_the_repo_name(self):
        ok, _ = self._install("https://gitlab.com/group/sub/my-plugin.git")
        self.assertTrue(ok)
        self.assertEqual(self.clones, [os.path.join("./plugins", "my-plugin")])

    def test_dot_names_are_rejected(self):
        ok, msg = self._install("https://github.com/a/...git")
        self.assertFalse(ok)
        self.assertIn("不合法", msg)
        self.assertEqual(self.clones, [])

    def test_a_normal_repo_skips_pip_without_requirements(self):
        ok, _ = self._install("https://github.com/someone/nice-plugin.git")
        self.assertTrue(ok)
        self.assertEqual(self.clones, [os.path.join("./plugins", "nice-plugin")])
        self.assertEqual(self.pip_calls, [])


class TestUpdatePluginRequirements(unittest.TestCase):

    def setUp(self):
        self.pm = object.__new__(_PluginManager)
        self.pip_calls = []

    def _update_plugin(self, with_requirements, pip_status=0):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = os.path.join(tmp, "MYPLUGIN")
            os.makedirs(plugin_dir)
            if with_requirements:
                with open(os.path.join(plugin_dir, "requirements.txt"), "w") as f:
                    f.write("click\n")
            self.pm.plugins = {"MYPLUGIN": types.SimpleNamespace(path=plugin_dir)}
            with _fake_dulwich(), \
                    patch.object(pkgmgr, "check_dulwich", lambda: None), \
                    patch.object(pkgmgr, "install_requirements",
                                 lambda path: self.pip_calls.append(path) or pip_status):
                return self.pm.update_plugin("MYPLUGIN")

    def test_update_skips_pip_when_no_requirements(self):
        ok, _ = self._update_plugin(with_requirements=False)
        self.assertTrue(ok)
        self.assertEqual(self.pip_calls, [])

    def test_update_installs_requirements_when_present(self):
        ok, _ = self._update_plugin(with_requirements=True)
        self.assertTrue(ok)
        self.assertEqual(len(self.pip_calls), 1)
        self.assertTrue(self.pip_calls[0].endswith("requirements.txt"))

    def test_a_failed_pip_install_is_reported(self):
        ok, msg = self._update_plugin(with_requirements=True, pip_status=1)
        self.assertFalse(ok)
        self.assertIn("依赖安装失败", msg)


if __name__ == "__main__":
    unittest.main()
