# encoding:utf-8
"""Godcmd #auth must not be brute-forceable at IM speed.

Admin unlocks #installp (repo clone + pip install), so the temp password is
drawn with secrets from an unambiguous alphabet and wrong guesses lock the
sender out for a while. The lock is per sender only, so other senders
cannot lock the real admin out.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plugins

_old_plugin_path = plugins.instance.current_plugin_path
plugins.instance.current_plugin_path = os.path.join(os.getcwd(), "plugins", "godcmd")
try:
    import plugins.godcmd.godcmd as godcmd
finally:
    plugins.instance.current_plugin_path = _old_plugin_path

Godcmd = plugins.instance.plugins["GODCMD"]

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


class _Base(unittest.TestCase):

    def _plugin(self):
        plugin = object.__new__(Godcmd)
        from agent.guest.access import LoginLimiter

        plugin.password = "real-password"
        plugin.temp_password = "TPWD23"
        plugin.admin_users = []
        plugin._auth_limiter = LoginLimiter(per_profile=False)
        # authenticate() appends into global_config; keep tests hermetic.
        patcher = patch.dict(godcmd.global_config, {"admin_users": []}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return plugin


class TestTempPasswordEntropy(unittest.TestCase):

    def test_temp_password_is_six_unambiguous_symbols(self):
        for _ in range(20):
            pw = godcmd._generate_temp_password()
            self.assertEqual(len(pw), 6)
            self.assertTrue(all(c in ALPHABET for c in pw), pw)
        # The confusable characters must not be in the alphabet at all.
        for c in "0O1I":
            self.assertNotIn(c, ALPHABET)

    def test_draws_differ(self):
        # Two draws sharing all six symbols would suggest a fixed seed.
        draws = {godcmd._generate_temp_password() for _ in range(10)}
        self.assertGreater(len(draws), 1)


class TestAuthenticateLockout(_Base):

    def test_wrong_passwords_lock_the_sender_out(self):
        plugin = self._plugin()
        for _ in range(5):
            ok, msg = plugin.authenticate("attacker", ["wrong"], False, False)
            self.assertFalse(ok)
        ok, msg = plugin.authenticate("attacker", ["real-password"], False, False)
        self.assertFalse(ok, "the correct password must not bypass the lock")
        self.assertIn("尝试次数过多", msg)

    def test_the_lock_is_per_client(self):
        plugin = self._plugin()
        for _ in range(5):
            plugin.authenticate("attacker", ["wrong"], False, False)
        ok, msg = plugin.authenticate("someone-else", ["real-password"], False, False)
        self.assertTrue(ok)

    def test_many_senders_failing_do_not_lock_out_the_admin(self):
        plugin = self._plugin()
        for i in range(40):
            for _ in range(4):
                plugin.authenticate(f"attacker-{i}", ["wrong"], False, False)
        ok, _ = plugin.authenticate("admin", ["real-password"], False, False)
        self.assertTrue(ok)

    def test_a_success_clears_earlier_failures(self):
        plugin = self._plugin()
        for _ in range(4):
            plugin.authenticate("admin", ["wrong"], False, False)
        ok, _ = plugin.authenticate("admin", ["real-password"], False, False)
        self.assertTrue(ok)
        plugin.admin_users.clear()
        for _ in range(4):
            plugin.authenticate("admin", ["wrong"], False, False)
        ok, _ = plugin.authenticate("admin", ["real-password"], False, False)
        self.assertTrue(ok, "failures from before the success still counted")

    def test_the_temp_password_is_case_insensitive(self):
        plugin = self._plugin()
        ok, msg = plugin.authenticate("admin", ["tpwd23"], False, False)
        self.assertTrue(ok)
        self.assertIn("请尽快设置口令", msg)

    def test_a_correct_password_success_without_prior_failures(self):
        plugin = self._plugin()
        ok, msg = plugin.authenticate("admin", ["real-password"], False, False)
        self.assertTrue(ok)
        self.assertIn("认证成功", msg)


if __name__ == "__main__":
    unittest.main()
