# encoding:utf-8
"""user_datas.pkl must be swapped atomically, never truncated in place.

save_user_datas() runs on SIGTERM, and the one-click update relay SIGKILLs
the process a fixed grace period later (cli/commands/process.py). The old
write opened the pickle with "wb" — truncate first, dump second — so a kill
or a full disk mid-dump left a half pickle behind, and load_user_datas()
then fell back to {} on the next start: every plugin's and session's user
data silently wiped. config.json already goes through common.atomic_write;
this pins the same discipline for the pickle store.
"""
import errno
import os
import pickle
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_mod
from config import Config


class TestUserDatasAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "user_datas.pkl")
        self._patch = patch.object(config_mod, "get_appdata_dir", lambda: self.tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _save(self, data):
        c = Config()
        c.user_datas = data
        c.save_user_datas()

    def _load(self):
        c = Config()
        c.load_user_datas()
        return c.user_datas

    def test_save_then_load_round_trips(self):
        data = {"user_a": {"sessions": ["s1"]}, "user_b": {"score": 3}}
        self._save(data)
        self.assertEqual(self._load(), data)

    def test_an_interrupted_swap_keeps_the_previous_file_intact(self):
        self._save({"old": {"k": "v"}})

        real_replace = os.replace

        def crash_before_swap(src, dst, *args, **kwargs):
            if "user_datas.pkl" in str(dst):
                raise OSError(errno.ENOENT, "simulated kill before the swap")
            return real_replace(src, dst, *args, **kwargs)

        with patch("common.atomic_write.os.replace", side_effect=crash_before_swap):
            self._save({"new": {"k": "v2"}})  # save_user_datas swallows the error

        # The previous pickle is still whole and loadable.
        self.assertEqual(self._load(), {"old": {"k": "v"}})
        # The staging file was cleaned up, not left behind as clutter.
        leftovers = [n for n in os.listdir(self.tmp) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_write_bytes_atomic_is_byte_exact_for_binary_payloads(self):
        # A pickle payload is arbitrary binary (starts \x80\x04…); the atomic
        # path must not decode/re-encode it through any text codec.
        from common.atomic_write import write_bytes_atomic

        payload = pickle.dumps({"bin": b"\x80\x04\xff\x00\xc3\xa9"})
        write_bytes_atomic(self.path, payload)
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), payload)


if __name__ == "__main__":
    unittest.main()
