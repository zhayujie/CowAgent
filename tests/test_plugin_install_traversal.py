# encoding:utf-8
"""The #installp repo URL must not escape the plugins directory.

The repo-name regex group flows straight into os.path.join("./plugins", ...).
A crafted URL can carry a slash in that segment: an absolute form
(https://github.com/o//tmp/pwn.git — join then drops the ./plugins prefix)
or a traversal form (https://github.com/a/../../pwn.git) cloned anywhere on
disk the process can write. The clone is followed by a pip install of the
cloned requirements, so a bad directory also means running attacker-chosen
code. These tests pin the plain-name requirement and that pip only runs for
repos that actually ship a requirements.txt.
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


class _FakePorcelain(types.SimpleNamespace):
    """Stand-in for dulwich.porcelain; dulwich itself need not be installed."""

    def __init__(self, clone=None, pull=None):
        super().__init__(clone=clone or (lambda *a, **k: None),
                         pull=pull or (lambda *a, **k: None))


class TestInstallPluginTraversal(unittest.TestCase):

    def setUp(self):
        self.pm = object.__new__(_PluginManager)
        self.calls = []
        fake = _FakePorcelain(clone=lambda repo, dirname, **k: self.calls.append(dirname))
        pkg_calls = []
        self.pkg_calls = pkg_calls
        module = types.ModuleType("dulwich")
        module.porcelain = fake
        import builtins
        real_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name == "dulwich":
                return module
            if name == "dulwich.porcelain":
                return fake
            return real_import(name, *args, **kwargs)

        enter = patch("builtins.__import__", side_effect=_import)
        enter_pip = patch.object(pkgmgr, "check_dulwich", lambda: None)
        enter_req = patch.object(pkgmgr, "install_requirements",
                                 lambda path: pkg_calls.append(path) or 0)
        enter.start()
        enter_pip.start()
        enter_req.start()
        self.addCleanup(lambda: (enter.stop(), enter_pip.stop(), enter_req.stop()))

    def test_traversal_url_is_rejected_without_cloning(self):
        ok, msg = self.pm.install_plugin("https://github.com/a/../../pwn.git")
        self.assertFalse(ok)
        self.assertIn("不合法", msg)
        self.assertEqual(self.calls, [], "clone ran for a traversal URL")

    def test_absolute_path_url_is_rejected_without_cloning(self):
        ok, msg = self.pm.install_plugin("https://github.com/o//tmp/pwn.git")
        self.assertFalse(ok)
        self.assertEqual(self.calls, [], "clone ran for an absolute-path URL")

    def test_dot_names_are_rejected(self):
        ok, _ = self.pm.install_plugin("https://github.com/a/...git"
                                       .replace("...git", "..git"))
        self.assertFalse(ok)

    def test_a_normal_repo_clones_inside_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.makedirs("plugins", exist_ok=True)
                ok, _ = self.pm.install_plugin("https://github.com/someone/nice-plugin.git")
            finally:
                os.chdir(cwd)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [os.path.join("./plugins", "nice-plugin")])
        # No requirements.txt was shipped: pip must not have run at all.
        self.assertEqual(self.pkg_calls, [])


class TestInstallRequirementsOnlyWhenPresent(unittest.TestCase):

    def setUp(self):
        self.pm = object.__new__(_PluginManager)
        self.pkg_calls = []
        self.pull_calls = []

    def _update_plugin(self, with_requirements):
        fake = _FakePorcelain(pull=lambda dirname, *a, **k: self.pull_calls.append(dirname))
        module = types.ModuleType("dulwich")
        module.porcelain = fake
        import builtins
        real_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name.startswith("dulwich"):
                return module
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = os.path.join(tmp, "MYPLUGIN")
            os.makedirs(plugin_dir)
            if with_requirements:
                with open(os.path.join(plugin_dir, "requirements.txt"), "w") as f:
                    f.write("click\n")
            self.pm.plugins = {"MYPLUGIN": types.SimpleNamespace(path=plugin_dir)}
            with patch("builtins.__import__", side_effect=_import), \
                    patch.object(pkgmgr, "check_dulwich", lambda: None), \
                    patch.object(pkgmgr, "install_requirements",
                                 lambda path: self.pkg_calls.append(path) or 0):
                return self.pm.update_plugin("MYPLUGIN")

    def test_update_skips_pip_when_no_requirements(self):
        ok, _ = self._update_plugin(with_requirements=False)
        self.assertTrue(ok)
        self.assertEqual(self.pkg_calls, [])

    def test_update_installs_requirements_when_present(self):
        ok, _ = self._update_plugin(with_requirements=True)
        self.assertTrue(ok)
        self.assertEqual(len(self.pkg_calls), 1)
        self.assertTrue(self.pkg_calls[0].endswith("requirements.txt"))


if __name__ == "__main__":
    unittest.main()
