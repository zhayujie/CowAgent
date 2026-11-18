# encoding:utf-8
"""Tools must not crash on an explicit null string argument.

Models do send ``{"path": null}`` — the key exists, so ``args.get("path",
".")`` returns None (the default only covers a *missing* key) and the
following ``.strip()`` raised ``AttributeError: 'NoneType' object has no
attribute 'strip'``, an error the model can do nothing with. read/bash
already use the ``or``-form; ls, web_fetch and vision were the gaps.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.ls.ls import Ls
from agent.tools.vision.vision import Vision
from agent.tools.web_fetch.web_fetch import WebFetch


class TestNullStringArgs(unittest.TestCase):

    def test_ls_null_path_falls_back_to_the_workspace_root(self):
        tool = Ls({"cwd": os.getcwd()})
        result = tool.execute({"path": None})
        # Must not raise; empty dir or a listing both count as "handled".
        self.assertNotIn("AttributeError", str(result.result))

    def test_web_fetch_null_url_reports_a_clear_error(self):
        tool = WebFetch({})
        result = tool.execute({"url": None})
        self.assertNotIn("AttributeError", str(result.result))

    def test_vision_null_image_reports_the_missing_parameter(self):
        tool = Vision({"cwd": os.getcwd()})
        result = tool.execute({"image": None, "question": "?"})
        self.assertIn("'image' parameter is required", str(result.result))

    def test_vision_null_question_reports_the_missing_parameter(self):
        tool = Vision({"cwd": os.getcwd()})
        result = tool.execute({"image": "x.png", "question": None})
        self.assertIn("'question' parameter is required", str(result.result))


if __name__ == "__main__":
    unittest.main()
