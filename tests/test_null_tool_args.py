# encoding:utf-8
"""Tools must not crash on an explicit null string argument.

Models do send ``{"path": null}`` — the key exists, so ``args.get("path",
".")`` returns None (the default only covers a *missing* key) and the
following ``.strip()`` raised ``AttributeError: 'NoneType' object has no
attribute 'strip'``, an error the model can do nothing with. Every built-in
tool now uses the ``or``-form; MCP tools keep their arguments untouched
(the fix is per-tool on purpose — dropping nulls centrally would change what
remote MCP servers receive).

The tests go through ``BaseTool.execute_tool`` — the path the agent actually
calls — so they also pin the "failed ToolResult, not a crash" contract.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.browser.browser_tool import BrowserTool
from agent.tools.edit.edit import Edit
from agent.tools.ls.ls import Ls
from agent.tools.send.send import Send
from agent.tools.vision.vision import Vision
from agent.tools.web_fetch.web_fetch import WebFetch
from agent.tools.write.write import Write


def _run(tool, args):
    return tool.execute_tool(args)


class TestNullStringArgs(unittest.TestCase):

    def test_null_path_falls_back_or_fails_cleanly(self):
        cases = [
            (Ls({"cwd": os.getcwd()}), {"path": None}),
            (Edit({"cwd": os.getcwd()}), {"path": None}),
            (Write({"cwd": os.getcwd()}), {"path": None, "content": "x"}),
            (Send({"cwd": os.getcwd()}), {"path": None}),
        ]
        for tool, args in cases:
            with self.subTest(tool=type(tool).__name__):
                result = _run(tool, args)
                self.assertNotIn("AttributeError", str(result.result))

    def test_null_url_and_action_report_clear_errors(self):
        self.assertNotIn("AttributeError", str(_run(WebFetch({}), {"url": None}).result))
        self.assertNotIn("AttributeError", str(_run(BrowserTool({}), {"action": None}).result))
        self.assertNotIn(
            "AttributeError",
            str(_run(BrowserTool({}), {"action": "click", "selector": None}).result),
        )

    def test_vision_null_parameters_report_the_missing_parameter(self):
        tool = Vision({"cwd": os.getcwd()})
        self.assertIn("'image' parameter is required",
                      str(_run(tool, {"image": None, "question": "?"}).result))
        self.assertIn("'question' parameter is required",
                      str(_run(tool, {"image": "x.png", "question": None}).result))


if __name__ == "__main__":
    unittest.main()
