# encoding:utf-8
"""
Regression test for QQ attachment filenames.

A sender-supplied filename longer than the filesystem's path-component limit
made _download_attachment's download_to_file() call raise
OSError(ENAMETOOLONG) and the attachment was silently replaced with a
"[... download failed]" placeholder. QQ now uses the shared
channel/chat_message.py::safe_filename, which caps the name at 180 chars.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.qq import qq_message


class TestQqSafeFilename(unittest.TestCase):
    def test_overlong_name_is_capped_at_180(self):
        result = qq_message.safe_filename("a" * 500)
        self.assertLessEqual(len(result), 180)

    def test_overlong_attachment_path_stays_within_limit(self):
        captured = {}
        def fake_download_to_file(url, path, *a, **k):
            captured["path"] = path
            return None
        att = {"url": "https://example.test/file", "filename": "b" * 500}
        with patch.object(qq_message, "download_to_file", fake_download_to_file), \
             patch.object(qq_message, "_get_tmp_dir", return_value="/tmp/qqtmp"):
            path = qq_message._download_attachment(att, "m1", 0)
        self.assertTrue(path)
        basename = os.path.basename(path)
        # basename == "qq_m1_0_" + safe_filename(filename); the safe part must
        # be capped at 180 so the full path component stays under the FS limit.
        self.assertTrue(basename.startswith("qq_m1_0_"))
        fname = basename[len("qq_m1_0_"):]
        self.assertLessEqual(len(fname), 180)

    def test_normal_name_passthrough(self):
        self.assertEqual(qq_message.safe_filename("report-2026.pdf"), "report-2026.pdf")

    def test_dot_names_are_rejected(self):
        self.assertEqual(qq_message.safe_filename(".."), "")
        self.assertEqual(qq_message.safe_filename("."), "")
