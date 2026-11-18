# encoding:utf-8
"""The vision tool must apply the shared credential-path guard.

read/edit/write/send/memory_get all refuse ~/.cow/.env and symlinks to it.
Vision sends the file bytes to an external API, so it needs the same guard.

HOME is redirected to a temp dir so the real credential file is never read.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.vision.vision import Vision

_DENIED = "Access denied"
_SECRET = "sk-SECRET-canary-value"
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _TempHomeCase(unittest.TestCase):
    """Each test gets an isolated HOME holding a credential file."""

    # USERPROFILE matters for the same Windows reason as in
    # test_security_edit_env_bypass.py: ntpath.expanduser ignores HOME.
    _HOME_VARS = ("HOME", "USERPROFILE")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._real_home = {name: os.environ.get(name) for name in self._HOME_VARS}
        for name in self._HOME_VARS:
            os.environ[name] = self.tmp

        os.makedirs(os.path.join(self.tmp, ".cow"))
        with open(os.path.join(self.tmp, ".cow", ".env"), "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={_SECRET}\n")

        self.workspace = os.path.join(self.tmp, "cow")
        os.makedirs(self.workspace)

    def tearDown(self):
        for name, value in self._real_home.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, image):
        vision = Vision({"cwd": self.workspace})
        with patch.object(Vision, "_resolve_providers", return_value=[]):
            return vision.execute({"image": image, "question": "what is this?"})


class TestVisionCredentialGuard(_TempHomeCase):

    def test_direct_credential_path_is_denied(self):
        result = self._run(os.path.join(self.tmp, ".cow", ".env"))
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))

    def test_workspace_symlink_to_credentials_is_denied(self):
        link = os.path.join(self.workspace, "shot.png")
        os.symlink(os.path.join(self.tmp, ".cow", ".env"), link)
        result = self._run("shot.png")
        self.assertEqual(result.status, "error")
        self.assertIn(_DENIED, str(result.result))

    def test_an_ordinary_image_is_not_caught_by_the_guard(self):
        # A plain workspace image must pass the guard; with providers patched
        # to none, the run stops at provider resolution — not at denial.
        path = os.path.join(self.workspace, "shot.png")
        with open(path, "wb") as f:
            f.write(_PNG)
        result = self._run("shot.png")
        self.assertNotIn(_DENIED, str(result))


if __name__ == "__main__":
    unittest.main()
