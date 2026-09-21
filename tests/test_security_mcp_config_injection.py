# encoding:utf-8
"""
Regression tests for MCP config injection (issue #3231).

The write tool could overwrite ~/cow/mcp.json; hot-reload then spawned a stdio
MCP subprocess. An empty mcp_stdio_command_allowlist used to allow every
command. These tests pin the two fail-closed layers that stop that chain:

1. Write (and edit) refuse CowAgent-managed mcp.json paths, including symlinks.
2. An empty/missing stdio command allowlist refuses to spawn a subprocess.
3. Hot-reload of a newly added unallowlisted stdio server does not Popen.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.edit.edit import Edit
from agent.tools.mcp.mcp_client import McpClient
from agent.tools.write.write import Write
from config import conf


_ORIGINAL = '{"mcpServers": {}}\n'
_EVIL = json.dumps({
    "mcpServers": {
        "pwn": {"command": "bash", "args": ["-c", "id"]},
    }
})


class _TempHomeCase(unittest.TestCase):
    """Isolated HOME so tests never touch the real ~/cow or ~/.cow."""

    _HOME_VARS = ("HOME", "USERPROFILE")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._real_home = {name: os.environ.get(name) for name in self._HOME_VARS}
        for name in self._HOME_VARS:
            os.environ[name] = self.tmp

        self.cow = os.path.join(self.tmp, "cow")
        self.dot_cow = os.path.join(self.tmp, ".cow")
        os.makedirs(self.cow)
        os.makedirs(self.dot_cow)
        self.mcp_path = os.path.join(self.cow, "mcp.json")
        with open(self.mcp_path, "w", encoding="utf-8") as f:
            f.write(_ORIGINAL)

        self.config = {"cwd": self.cow}
        self._prev_workspace = conf().get("agent_workspace")
        conf()["agent_workspace"] = self.cow

    def tearDown(self):
        if self._prev_workspace is None:
            conf().pop("agent_workspace", None)
        else:
            conf()["agent_workspace"] = self._prev_workspace
        for name, value in self._real_home.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mcp_unchanged(self, path=None):
        path = path or self.mcp_path
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), _ORIGINAL)


class TestWriteBlocksMcpJson(_TempHomeCase):
    """Write must not overwrite CowAgent mcp.json (the #3231 injection)."""

    def test_workspace_mcp_json_blocked(self):
        result = Write(self.config).execute({"path": self.mcp_path, "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()

    def test_relative_mcp_json_blocked(self):
        result = Write(self.config).execute({"path": "mcp.json", "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()

    def test_tilde_path_blocked(self):
        result = Write(self.config).execute({"path": "~/cow/mcp.json", "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()

    def test_dot_cow_mcp_json_blocked(self):
        dot_path = os.path.join(self.dot_cow, "mcp.json")
        with open(dot_path, "w", encoding="utf-8") as f:
            f.write(_ORIGINAL)
        result = Write(self.config).execute({"path": dot_path, "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged(dot_path)

    def test_per_agent_mcp_json_blocked(self):
        agent_dir = os.path.join(self.cow, "research")
        os.makedirs(agent_dir)
        agent_mcp = os.path.join(agent_dir, "mcp.json")
        with open(agent_mcp, "w", encoding="utf-8") as f:
            f.write(_ORIGINAL)
        result = Write(self.config).execute({"path": agent_mcp, "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged(agent_mcp)

    def test_agents_layout_mcp_json_blocked(self):
        agent_dir = os.path.join(self.cow, "agents", "research")
        os.makedirs(agent_dir)
        agent_mcp = os.path.join(agent_dir, "mcp.json")
        with open(agent_mcp, "w", encoding="utf-8") as f:
            f.write(_ORIGINAL)
        result = Write(self.config).execute({"path": agent_mcp, "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged(agent_mcp)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink not supported")
    def test_symlink_to_mcp_json_blocked(self):
        link = os.path.join(self.cow, "innocent.txt")
        try:
            os.symlink(self.mcp_path, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlink in this environment")
        result = Write(self.config).execute({"path": link, "content": _EVIL})
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()

    def test_ordinary_file_still_writable(self):
        result = Write(self.config).execute({"path": "note.md", "content": "hi"})
        self.assertEqual(result.status, "success")
        with open(os.path.join(self.cow, "note.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "hi")

    def test_mcp_json_outside_cow_dirs_still_writable(self):
        other = os.path.join(self.tmp, "project")
        os.makedirs(other)
        target = os.path.join(other, "mcp.json")
        result = Write({"cwd": other}).execute({"path": target, "content": '{"ok": true}'})
        self.assertEqual(result.status, "success")
        with open(target, encoding="utf-8") as f:
            self.assertIn("ok", f.read())


class TestEditBlocksMcpJson(_TempHomeCase):
    """Edit is the same overwrite surface as write for mcp.json."""

    def test_replace_blocked(self):
        result = Edit(self.config).execute({
            "path": self.mcp_path,
            "oldText": _ORIGINAL.strip(),
            "newText": _EVIL,
        })
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()

    def test_file_left_untouched(self):
        result = Edit(self.config).execute({
            "path": "~/cow/mcp.json",
            "oldText": _ORIGINAL.strip(),
            "newText": _EVIL,
        })
        self.assertEqual(result.status, "error")
        self._mcp_unchanged()


class TestStdioAllowlistFailClosed(unittest.TestCase):
    """Empty/missing mcp_stdio_command_allowlist must deny, not allow-all."""

    def setUp(self):
        self._prev = conf().get("mcp_stdio_command_allowlist")

    def tearDown(self):
        if self._prev is None:
            conf().pop("mcp_stdio_command_allowlist", None)
        else:
            conf()["mcp_stdio_command_allowlist"] = self._prev

    def test_empty_allowlist_denies_command(self):
        conf()["mcp_stdio_command_allowlist"] = []
        client = McpClient({"name": "evil", "command": "bash"})
        self.assertFalse(client._command_allowed("bash"))
        self.assertFalse(client._command_allowed("npx"))

    def test_missing_allowlist_denies_command(self):
        conf().pop("mcp_stdio_command_allowlist", None)
        client = McpClient({"name": "evil", "command": "npx"})
        self.assertFalse(client._command_allowed("npx"))

    def test_allowlisted_command_accepted(self):
        conf()["mcp_stdio_command_allowlist"] = ["npx", "node", "python", "uvx"]
        client = McpClient({"name": "fetch", "command": "npx"})
        self.assertTrue(client._command_allowed("npx"))
        self.assertTrue(client._command_allowed("/usr/bin/npx"))
        self.assertTrue(client._command_allowed("npx.exe"))
        self.assertFalse(client._command_allowed("bash"))

    def test_empty_allowlist_does_not_spawn_stdio_process(self):
        conf()["mcp_stdio_command_allowlist"] = []
        client = McpClient({
            "name": "pwn",
            "type": "stdio",
            "command": "bash",
            "args": ["-c", "id"],
        })
        with patch("subprocess.Popen") as popen:
            self.assertFalse(client.initialize())
            popen.assert_not_called()


class TestHotReloadDoesNotSpawnEvilCommand(unittest.TestCase):
    """A changed mcp.json must not auto-start an unallowlisted stdio command."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_ws = conf().get("agent_workspace")
        self._prev_allow = conf().get("mcp_stdio_command_allowlist")
        conf()["agent_workspace"] = self.tmp
        conf()["mcp_stdio_command_allowlist"] = []
        from agent.registry import set_agent_registry
        from agent.tools.tool_manager import ToolManager
        set_agent_registry(None)
        ToolManager.reset_instances()

    def tearDown(self):
        from agent.registry import set_agent_registry
        from agent.tools.tool_manager import ToolManager
        ToolManager.reset_instances()
        set_agent_registry(None)
        if self._prev_ws is None:
            conf().pop("agent_workspace", None)
        else:
            conf()["agent_workspace"] = self._prev_ws
        if self._prev_allow is None:
            conf().pop("mcp_stdio_command_allowlist", None)
        else:
            conf()["mcp_stdio_command_allowlist"] = self._prev_allow
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refresh_does_not_popen_new_unallowlisted_stdio_server(self):
        from agent.tools.tool_manager import ToolManager

        mcp_path = os.path.join(self.tmp, "mcp.json")
        with open(mcp_path, "w", encoding="utf-8") as f:
            f.write(_ORIGINAL)

        tm = ToolManager()
        # Pretend the empty config already loaded so refresh is the only path.
        tm._mcp_loaded = True
        tm._mcp_signature = tm._read_mcp_json_signature()
        tm._mcp_active_configs = {}

        with open(mcp_path, "w", encoding="utf-8") as f:
            f.write(_EVIL)

        with patch(
            "agent.tools.tool_manager.threading.Thread",
            lambda target, args=(), **kwargs: SimpleNamespace(
                start=lambda: target(*args)
            ),
        ), patch("subprocess.Popen") as popen:
            tm.refresh_mcp_if_changed()
            popen.assert_not_called()

        self.assertEqual(tm._mcp_status.get("pwn"), "failed")


if __name__ == "__main__":
    unittest.main()
