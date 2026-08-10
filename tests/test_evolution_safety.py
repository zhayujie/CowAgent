import threading
import unittest
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import agent.evolution.executor as executor


class ToolResult:
    def __init__(self, status, result):
        self.status = status
        self.result = result

    @staticmethod
    def success(result):
        return ToolResult("success", result)

    @staticmethod
    def fail(result):
        return ToolResult("error", result)


# Keep these focused unit tests independent of optional runtime tool packages.
_base_tool_stub = types.ModuleType("agent.tools.base_tool")
_base_tool_stub.ToolResult = ToolResult
sys.modules.setdefault("agent.tools.base_tool", _base_tool_stub)


class _FileTool:
    name = "write"
    description = "test write"
    params = {"type": "object", "properties": {}}

    def __init__(self, cwd):
        self.cwd = str(cwd)

    def _resolve_path(self, path):
        candidate = Path(path)
        return str(candidate if candidate.is_absolute() else Path(self.cwd) / candidate)

    def execute(self, args):
        path = Path(self._resolve_path(args["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.get("content", "changed"), encoding="utf-8")
        return ToolResult.success({"path": str(path)})


class _MemoryConfig:
    def __init__(self, workspace):
        self.workspace = Path(workspace)

    def get_workspace(self):
        return self.workspace

    def get_skills_dir(self):
        return self.workspace / "skills"


class _Agent:
    def __init__(self, workspace, tool):
        self.messages = [
            {"role": "user", "content": "Please remember that I prefer concise replies."},
            {"role": "assistant", "content": "Understood."},
        ]
        self.messages_lock = threading.Lock()
        self.tools = [tool]
        self.model = object()
        self.skill_manager = None
        self.memory_manager = SimpleNamespace(config=_MemoryConfig(workspace))
        self.runtime_info = None
        self._evo_turns = 1


class _ReviewAgent:
    def __init__(self, tools, outcome, write_path):
        self.tools = tools
        self.outcome = outcome
        self.write_path = write_path
        self.model = None

    def run_stream(self, *_args, **_kwargs):
        write = next(t for t in self.tools if t.name == "write")
        result = write.execute({"path": self.write_path, "content": "modified"})
        if result.status != "success":
            raise AssertionError(result.result)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Bridge:
    def __init__(self, agent, outcome, write_path="MEMORY.md"):
        self.agents = {"session": agent}
        self.default_agent = agent
        self.outcome = outcome
        self.write_path = write_path
        self.injected = []

    def create_agent(self, **kwargs):
        return _ReviewAgent(kwargs["tools"], self.outcome, self.write_path)

    def remember_scheduled_output(self, **kwargs):
        self.injected.append(kwargs["content"])


class EvolutionSafetyTest(unittest.TestCase):
    def test_workspace_locks_serialize_only_the_same_workspace(self):
        first = Path.cwd() / ".evolution-lock-test-a"
        second = Path.cwd() / ".evolution-lock-test-b"
        first_lock = executor._get_workspace_lock(first)
        self.assertIs(first_lock, executor._get_workspace_lock(first))
        self.assertIsNot(first_lock, executor._get_workspace_lock(second))

        attempted = threading.Event()
        acquired = threading.Event()

        def acquire_same_workspace():
            attempted.set()
            with executor._get_workspace_lock(first):
                acquired.set()

        first_lock.acquire()
        worker = threading.Thread(target=acquire_same_workspace)
        worker.start()
        try:
            self.assertTrue(attempted.wait(1))
            self.assertFalse(acquired.wait(0.05))
        finally:
            first_lock.release()
        self.assertTrue(acquired.wait(1))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_bash_is_not_selected_for_evolution(self):
        tools = [SimpleNamespace(name="bash"), SimpleNamespace(name="read")]
        self.assertEqual([t.name for t in executor._select_tools(tools)], ["read"])

    def test_write_guard_allows_workspace_task_outputs(self):
        with TemporaryDirectory(dir=Path.cwd()) as tmp:
            ws = Path(tmp)
            tx = executor._EvolutionWriteTransaction(ws)
            guard = executor._WorkspaceWriteGuard(_FileTool(ws), str(ws), set(), tx)
            for rel in (
                "MEMORY.md",
                "AGENT.md",
                "memory/2026-08-06.md",
                "skills/custom/SKILL.md",
                "skills/custom/scripts/helper.py",
                "knowledge/topic.md",
                "output/result.txt",
                "report.html",
                "new-project/src/main.py",
                "config.json",
                "skills_config.json",
                "new-project/skills_config.json",
                "memory/evolution/custom-note.md",
            ):
                result = guard.execute({"path": rel, "content": rel})
                self.assertEqual(result.status, "success", rel)
            tx.rollback()

    def test_write_guard_blocks_only_protected_and_outside_paths(self):
        with (
            TemporaryDirectory(dir=Path.cwd()) as tmp,
            TemporaryDirectory(dir=Path.cwd()) as outside,
        ):
            ws = Path(tmp)
            tx = executor._EvolutionWriteTransaction(ws)
            guard = executor._WorkspaceWriteGuard(
                _FileTool(ws), str(ws), {"builtin"}, tx
            )
            blocked = (
                "memory/.evolution_backups/x.md",
                "skills/builtin/SKILL.md",
                "skills/Builtin/SKILL.md",
                "skills/skills_config.json",
                str(Path(outside) / "escape.txt"),
            )
            for path in blocked:
                result = guard.execute({"path": path, "content": "bad"})
                self.assertEqual(result.status, "error", path)
            tx.rollback()

    def _run_with_outcome(self, outcome, write_path="MEMORY.md"):
        temp = TemporaryDirectory(dir=Path.cwd())
        ws = Path(temp.name)
        (ws / "MEMORY.md").write_text("original", encoding="utf-8")
        (ws / "memory").mkdir()
        agent = _Agent(ws, _FileTool(ws))
        bridge = _Bridge(agent, outcome, write_path)
        cfg = SimpleNamespace(enabled=True, max_steps=3)
        patches = (
            patch.object(executor, "get_evolution_config", return_value=cfg),
            patch.object(executor, "_builtin_skill_names", return_value=set()),
            patch.object(executor, "_running_count", 0),
        )
        return temp, ws, bridge, patches

    def test_silent_after_write_rolls_back(self):
        temp, ws, bridge, patches = self._run_with_outcome("[SILENT]")
        try:
            with patches[0], patches[1], patches[2]:
                self.assertFalse(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual((ws / "MEMORY.md").read_text(encoding="utf-8"), "original")
            self.assertFalse(bridge.injected)
        finally:
            temp.cleanup()

    def test_exception_after_write_rolls_back(self):
        temp, ws, bridge, patches = self._run_with_outcome(RuntimeError("boom"))
        try:
            with patches[0], patches[1], patches[2]:
                self.assertFalse(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual((ws / "MEMORY.md").read_text(encoding="utf-8"), "original")
            self.assertFalse(bridge.injected)
        finally:
            temp.cleanup()

    def test_invalid_summary_after_write_rolls_back(self):
        temp, ws, bridge, patches = self._run_with_outcome("---")
        try:
            with patches[0], patches[1], patches[2]:
                self.assertFalse(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual((ws / "MEMORY.md").read_text(encoding="utf-8"), "original")
        finally:
            temp.cleanup()

    def test_valid_summary_commits_existing_write_flow(self):
        temp, ws, bridge, patches = self._run_with_outcome(
            "Learned a durable preference and updated memory."
        )
        try:
            with patches[0], patches[1], patches[2]:
                self.assertTrue(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual((ws / "MEMORY.md").read_text(encoding="utf-8"), "modified")
            self.assertTrue(bridge.injected)
        finally:
            temp.cleanup()

    def test_long_summary_is_truncated_without_rolling_back(self):
        outcome = "Productive evolution summary. " + ("detail " * 800) + "tail-marker"
        temp, ws, bridge, patches = self._run_with_outcome(outcome)
        try:
            with patches[0], patches[1], patches[2]:
                self.assertTrue(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual((ws / "MEMORY.md").read_text(encoding="utf-8"), "modified")
            self.assertIn("[summary truncated]", bridge.injected[0])
            self.assertNotIn("tail-marker", bridge.injected[0])
        finally:
            temp.cleanup()

    def test_unfinished_task_can_create_a_new_project_subdirectory(self):
        temp, ws, bridge, patches = self._run_with_outcome(
            "Finished the promised generated page.",
            write_path="generated-site/index.html",
        )
        try:
            with patches[0], patches[1], patches[2]:
                self.assertTrue(executor.run_evolution_for_session(bridge, "session"))
            self.assertEqual(
                (ws / "generated-site" / "index.html").read_text(encoding="utf-8"),
                "modified",
            )
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
