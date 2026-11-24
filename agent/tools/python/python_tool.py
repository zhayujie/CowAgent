"""
Python tool - run Python code in the agent's own interpreter.

For the mobile app, which has an interpreter but no shell to start a process
with. See guard.py for what bounds the code.
"""

import ast
import builtins
import os
import sys
import threading
import time
import traceback
from typing import Any, Dict, Optional

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.python import guard
from agent.tools.utils.truncate import truncate_tail
from common.log import logger


class _Timeout(BaseException):
    pass


class _Cancelled(BaseException):
    pass


class _TooMuchMemory(BaseException):
    pass


# One run at a time: sys.argv and sys.path are process-wide, and the memory
# watch reads the whole process.
_running = threading.Lock()


def _no_input(*_args, **_kwargs):
    raise EOFError("input() has no one to answer it here; put the values in the code or pass them as args.")


def _peak_mb() -> Optional[float]:
    """The process's peak memory so far; it only grows, which is enough to see a run's growth."""
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return None
    return peak / (1024 * 1024) if sys.platform in ("darwin", "ios") else peak / 1024


def _compile(source: str, filename: str):
    """The code, and its last line apart when it is an expression, so its value can be shown."""
    tree = ast.parse(source, filename)
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    return compile(tree, filename, "exec"), compile(last, filename, "eval") if last else None


def _format_error(exc: BaseException) -> str:
    """The traceback from the code's own frames down, without the tool's."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename == __file__:
        tb = tb.tb_next
    return "".join(traceback.format_exception(type(exc), exc, tb)).rstrip()


class Python(BaseTool):
    """Run Python code in-process, bounded by the session's permission mode."""

    DEFAULT_TIMEOUT = 60
    MAX_TIMEOUT = 300
    # Growth past this risks the system closing the whole app.
    MEMORY_LIMIT_MB = 512
    # Deep recursion needs more than the small default stack of a secondary thread.
    STACK_BYTES = 16 * 1024 * 1024

    name: str = "python"
    description: str = (
        f"Run Python {sys.version_info.major}.{sys.version_info.minor} code in the agent's own interpreter. "
        "This device has no shell, so this is the way to compute, process data, parse and convert files "
        "(CSV, JSON, Excel via openpyxl, PDF text via pypdf, zip, sqlite3) and make HTTP requests "
        "(requests or urllib). Printed output is returned, plus the value of a final expression.\n\n"
        "AVAILABLE: the standard library plus requests, PyYAML, openpyxl, pypdf, regex and chardet. "
        "Nothing can be installed and no programs can be started (subprocess, os.system).\n"
        "PATHS: the variable WORKSPACE holds the workspace path. The current directory is not the "
        "workspace, so build paths from WORKSPACE or use absolute paths. Writes are confined by the "
        "session's permission mode.\n"
        "Each call starts with fresh variables; nothing carries over between calls. Keep data small: "
        "a run that takes too much memory is stopped."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to run. Pass this or path.",
            },
            "path": {
                "type": "string",
                "description": "A .py file to run instead of code, e.g. a skill's script; relative to the workspace.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command-line arguments, read by the code from sys.argv[1:].",
            },
            "timeout": {
                "type": "integer",
                "description": f"Seconds to allow, default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT}.",
            },
        },
        "required": [],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())

    def _workspace(self) -> str:
        agent = getattr(self, "context", None)
        effective = getattr(agent, "effective_cwd", None)
        if callable(effective):
            try:
                return effective()
            except Exception:
                pass
        return self.cwd

    def _write_check(self, cwd: str):
        """How each write of this run is judged: the session's permission mode, read now."""
        from agent.permission import WORKSPACE_WRITE, check_write_path, global_mode

        agent = getattr(self, "context", None)
        mode, roots, protected = WORKSPACE_WRITE, [cwd], []
        try:
            if callable(getattr(agent, "effective_permission_mode", None)):
                mode, roots, protected = agent.effective_permission_mode(), agent.write_roots(), agent.protected_paths()
            else:
                mode = global_mode()
        except Exception as e:
            logger.warning(f"[python] Permission mode unavailable, confining to the workspace: {e}")

        def check(path: str) -> Optional[str]:
            decision = check_write_path(mode, path, cwd, roots, protected)
            return None if decision.allowed else decision.reason

        return check

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        code = params.get("code")
        path = params.get("path")
        if bool(code) == bool(path):
            return ToolResult.fail("Error: pass either code or path.")
        args = [str(a) for a in (params.get("args") or [])]
        timeout = params.get("timeout") or self.DEFAULT_TIMEOUT
        if not 0 < timeout <= self.MAX_TIMEOUT:
            return ToolResult.fail(f"Error: timeout must be between 1 and {self.MAX_TIMEOUT} seconds.")

        cwd = self._workspace()
        filename = "<python>"
        if path:
            filename = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
            try:
                with open(filename, encoding="utf-8") as f:
                    code = f.read()
            except OSError as e:
                return ToolResult.fail(f"Error: cannot read {path}: {e}")
        try:
            body, last = _compile(code, filename)
        except SyntaxError as e:
            return ToolResult.fail(_format_error(e))

        if not _running.acquire(timeout=timeout):
            return ToolResult.fail("Error: another Python run is still going; try again once it has finished.")
        try:
            return self._run(body, last, filename, args, timeout, cwd)
        finally:
            _running.release()

    def _run(self, body, last, filename: str, args: list, timeout: int, cwd: str) -> ToolResult:
        guard.install()
        run = guard.Run(self._write_check(cwd))
        namespace = {
            "__name__": "__main__",
            "__file__": filename,
            "__builtins__": {**builtins.__dict__, "input": _no_input},
            "WORKSPACE": cwd,
        }
        outcome: Dict[str, Any] = {}

        def target():
            guard.enter(run)
            try:
                exec(body, namespace)
                if last is not None:
                    value = eval(last, namespace)
                    if value is not None:
                        print(repr(value))
            except SystemExit as e:
                outcome["exit"] = e.code
            except (_Timeout, _Cancelled, _TooMuchMemory) as e:
                outcome["stopped"] = type(e)
            except BaseException as e:
                outcome["error"] = _format_error(e)
            finally:
                guard.leave(run)

        script_dir = os.path.dirname(filename) if filename != "<python>" else None
        saved_argv, saved_path, saved_modules = sys.argv, list(sys.path), set(sys.modules)
        sys.argv = [filename if script_dir else "-c"] + args
        if script_dir:
            sys.path.insert(0, script_dir)

        thread = self._start(target)
        baseline = _peak_mb()
        deadline = time.monotonic() + timeout
        stop = None
        while thread.is_alive():
            thread.join(0.2)
            if not thread.is_alive():
                break
            peak = _peak_mb()
            if self.is_cancelled():
                stop = _Cancelled
            elif time.monotonic() > deadline:
                stop = _Timeout
            elif baseline is not None and peak is not None and peak - baseline > self.MEMORY_LIMIT_MB:
                stop = _TooMuchMemory
            if stop:
                guard.interrupt(run, stop)
                thread.join(2.0)
                break

        stuck = thread.is_alive()
        sys.argv, sys.path[:] = saved_argv, saved_path
        if script_dir and not stuck:
            self._forget_modules(saved_modules, script_dir)
        return self._result(run, outcome, stop, stuck, timeout)

    def _start(self, target) -> threading.Thread:
        previous = threading.stack_size()
        try:
            threading.stack_size(self.STACK_BYTES)
        except (ValueError, RuntimeError):
            previous = None
        try:
            thread = threading.Thread(target=target, name="python-tool", daemon=True)
            thread.start()
        finally:
            if previous is not None:
                threading.stack_size(previous)
        return thread

    @staticmethod
    def _forget_modules(before: set, script_dir: str) -> None:
        """Modules a script imported from its own folder, so the next one with the same names gets its own."""
        for name in set(sys.modules) - before:
            file = getattr(sys.modules.get(name), "__file__", None) or ""
            if file and os.path.realpath(file).startswith(os.path.realpath(script_dir) + os.sep):
                sys.modules.pop(name, None)

    def _result(self, run, outcome: dict, stop, stuck: bool, timeout: int) -> ToolResult:
        stop = outcome.get("stopped") or stop
        note, failed = "", True
        if stuck:
            note = (f"Stopped waiting after {timeout}s: the code is blocked in a call that cannot be "
                    "interrupted and may still finish in the background.")
        elif stop is _Timeout:
            note = f"Stopped after {timeout}s. Pass a larger timeout (max {self.MAX_TIMEOUT}) if the work needs it."
        elif stop is _Cancelled:
            note = "Cancelled."
        elif stop is _TooMuchMemory:
            note = (f"Stopped: the code took more than {self.MEMORY_LIMIT_MB} MB of memory, which risks the "
                    "system closing the app. Work through the data in smaller pieces.")
        elif "error" in outcome:
            note = outcome["error"]
        elif outcome.get("exit") not in (None, 0):
            note = f"Exited with code {outcome['exit']}"
        else:
            failed = False

        output = run.output.text()
        if run.output.dropped:
            output = f"[{run.output.dropped} earlier characters of output dropped]\n{output}"
        text = "\n".join(part for part in (output.rstrip(), note) if part) or "(no output)"
        cut = truncate_tail(text)
        if cut.truncated:
            text = f"[Showing the last {cut.output_lines} of {cut.total_lines} lines]\n{cut.content}"
        return ToolResult.fail(text) if failed else ToolResult.success(text)
