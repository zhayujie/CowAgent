"""The off-hours allowlist has to cover the aliases godcmd actually answers to.

`common/time_check.py` lets a couple of configuration commands through when the
service hours say no, so an admin can still change the window and reload. That
allowlist is a hand-written pattern, and it had drifted from the command table
it is supposed to mirror:

    godcmd ADMIN_COMMANDS["reconf"]["alias"]  ->  ['reconf', '重载配置']
    time_check allowlist                     ->  #reconf, #更新配置

So the one Chinese spelling of the command was dropped, while `#更新配置` --
which is not a godcmd command at all but a reload handled by ten
`models/*_bot.py` implementations -- was let through. Measured through the
decorator:

    send '#reconf'        -> reached handler: True
    send '#重载配置'       -> reached handler: False
    send '#更新配置'       -> reached handler: True

The check below is written against godcmd's own table so the two cannot drift
apart again, whatever spelling is added next.
"""

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from common.time_check import time_checker  # noqa: E402

GODCMD = os.path.join(ROOT, "plugins", "godcmd", "godcmd.py")


def _admin_command_aliases() -> dict:
    """Read ADMIN_COMMANDS straight out of the source.

    Importing the plugin module runs ``@register``, which refuses to register
    until a plugin path is set -- a side effect a unit test should not need.
    """
    tree = ast.parse(Path(GODCMD).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "ADMIN_COMMANDS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("ADMIN_COMMANDS not found in godcmd.py")


class _Msg:
    def __init__(self, content):
        self.content = content


class _Channel:
    """The decorator only ever touches ``args[0].content``."""

    def __init__(self):
        self.reached = False

    @time_checker
    def handle_single(self, msg):
        self.reached = True


class OffHoursAllowlistTest(unittest.TestCase):

    def _send(self, text):
        """Run one message through the decorator with the time module on and a
        window we are almost never inside, so the off-hours branch is taken."""
        channel = _Channel()
        conf = {
            "chat_time_module": True,
            "chat_start_time": "00:00",
            "chat_stop_time": "00:01",
        }
        with patch("common.time_check.config.conf", return_value=conf):
            channel.handle_single(_Msg(text))
        return channel.reached

    def test_every_godcmd_reconf_alias_gets_through_off_hours(self):
        aliases = _admin_command_aliases()["reconf"]["alias"]
        self.assertTrue(aliases, "godcmd declares no reconf alias")
        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertTrue(
                    self._send("#" + alias),
                    f"#{alias} is an admin command godcmd answers to, but the "
                    "off-hours allowlist drops it",
                )

    def test_the_bot_reload_command_still_gets_through(self):
        # #更新配置 predates this allowlist and is implemented by the model bots
        # (load_config()); it reloads the same thing, so it stays.
        self.assertTrue(self._send("#更新配置"))

    def test_an_ordinary_command_is_still_refused_off_hours(self):
        for text in ("#resetall", "你好", "#starta"):
            with self.subTest(text=text):
                self.assertFalse(
                    self._send(text),
                    "the off-hours allowlist should not have grown",
                )

    def test_the_allowlist_covers_exactly_the_reload_commands(self):
        # Pins the shape rather than a spelling: anything the allowlist accepts
        # has to be a reload command somewhere, and vice versa.
        allowed_by_godcmd = {
            "#" + a for a in _admin_command_aliases()["reconf"]["alias"]
        }
        for command in sorted(allowed_by_godcmd):
            with self.subTest(command=command):
                self.assertTrue(self._send(command))


if __name__ == "__main__":
    unittest.main()