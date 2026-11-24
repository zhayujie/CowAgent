"""The python tool: runs code in-process for the mobile app, bounded by the session's permission mode."""

import os

import pytest

from agent.permission import READ_ONLY, WORKSPACE_WRITE, check_write_path
from agent.permission import policy
from agent.tools import tool_manager
from agent.tools.python.python_tool import Python


class _Agent:
    def __init__(self, workspace, mode=WORKSPACE_WRITE, protected=()):
        self.workspace = str(workspace)
        self.mode = mode
        self.protected = list(protected)

    def effective_cwd(self):
        return self.workspace

    def effective_permission_mode(self):
        return self.mode

    def write_roots(self):
        return [self.workspace]

    def protected_paths(self):
        return self.protected


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    workspace, outside, temp = tmp_path / "ws", tmp_path / "outside", tmp_path / "tmp"
    for d in (workspace, outside, temp):
        d.mkdir()
    # The system temp dir is always writable; keep it apart from "outside".
    monkeypatch.setattr(policy.tempfile, "gettempdir", lambda: str(temp))
    return workspace, outside


def _tool(workspace, **agent):
    tool = Python({"cwd": str(workspace)})
    tool.context = _Agent(workspace, **agent)
    return tool


def test_prints_and_shows_the_last_expression(dirs):
    result = _tool(dirs[0]).execute({"code": "print('hi')\nsum(range(4))"})
    assert result.status == "success"
    assert result.result == "hi\n6"


def test_errors_come_back_as_the_code_s_own_traceback(dirs):
    result = _tool(dirs[0]).execute({"code": "x = 1\n1 / 0"})
    assert result.status == "error"
    assert "ZeroDivisionError" in result.result
    assert "python_tool.py" not in result.result


def test_a_run_past_its_timeout_is_stopped(dirs):
    result = _tool(dirs[0]).execute({"code": "while True:\n    pass", "timeout": 1})
    assert result.status == "error"
    assert "Stopped after 1s" in result.result


def test_a_run_eating_memory_is_stopped(dirs):
    tool = _tool(dirs[0])
    tool.MEMORY_LIMIT_MB = 64
    code = (
        "import time\n"
        "hold = []\n"
        "for _ in range(400):\n"
        "    hold.append(bytearray(1 << 20)); time.sleep(0.002)\n"
        "print('finished')\n"
    )
    result = tool.execute({"code": code, "timeout": 30})
    assert result.status == "error"
    assert "MB of memory" in result.result and "finished" not in result.result


def test_memory_is_watched_below_an_earlier_peak(dirs):
    spike = bytearray(400 << 20)
    spike[::4096] = b"x" * len(spike[::4096])
    del spike
    test_a_run_eating_memory_is_stopped(dirs)


def test_cancelling_the_turn_stops_the_run(dirs):
    import threading
    tool = _tool(dirs[0])
    tool.cancel_event = threading.Event()
    threading.Timer(0.5, tool.cancel_event.set).start()
    result = tool.execute({"code": "while True:\n    pass", "timeout": 30})
    assert result.result == "Cancelled."


def test_writes_stay_inside_the_workspace(dirs):
    workspace, outside = dirs
    code = (
        "import os\n"
        "open(os.path.join(WORKSPACE, 'ok.txt'), 'w').write('fine')\n"
        f"open({str(outside / 'no.txt')!r}, 'w')\n"
    )
    result = _tool(workspace).execute({"code": code})
    assert result.status == "error"
    assert "PermissionError" in result.result and "outside the writable area" in result.result
    assert (workspace / "ok.txt").read_text() == "fine"
    assert not (outside / "no.txt").exists()


def test_read_only_reads_but_writes_nothing(dirs):
    workspace, _ = dirs
    (workspace / "data.txt").write_text("42")
    tool = _tool(workspace, mode=READ_ONLY)
    assert tool.execute({"code": "open(WORKSPACE + '/data.txt').read()"}).result == "'42'"
    result = tool.execute({"code": "open(WORKSPACE + '/new.txt', 'w')"})
    assert "read-only" in result.result
    assert not (workspace / "new.txt").exists()


def test_protected_files_stay_untouched(dirs):
    workspace, _ = dirs
    config = workspace / "config.json"
    config.write_text("{}")
    result = _tool(workspace, protected=[str(config)]).execute({"code": f"open({str(config)!r}, 'a')"})
    assert result.status == "error"
    assert config.read_text() == "{}"


def test_threads_it_starts_are_held_to_the_same_bounds(dirs):
    workspace, outside = dirs
    code = (
        "import threading\n"
        "def write():\n"
        "    try:\n"
        f"        open({str(outside / 'no.txt')!r}, 'w')\n"
        "    except PermissionError:\n"
        "        print('refused in thread')\n"
        "t = threading.Thread(target=write); t.start(); t.join()\n"
    )
    result = _tool(workspace).execute({"code": code})
    assert result.result == "refused in thread"
    assert not (outside / "no.txt").exists()


@pytest.mark.parametrize("code", [
    "import subprocess; subprocess.run(['true'])",
    "import os; os.system('true')",
    "import os; os._exit(0)",
    "import os; os.chdir('/')",
    "import os; os.environ['COW_TEST'] = '1'",
])
def test_what_the_whole_app_shares_is_off_limits(dirs, code):
    cwd = os.getcwd()
    result = _tool(dirs[0]).execute({"code": code})
    assert result.status == "error"
    assert "Not possible here" in result.result
    assert os.getcwd() == cwd and "COW_TEST" not in os.environ


def test_runs_a_script_with_args_and_forgets_its_modules(dirs):
    workspace, _ = dirs
    scripts = workspace / "scripts"
    scripts.mkdir()
    (scripts / "helper_mod_for_test.py").write_text("NAME = 'helper'\n")
    (scripts / "main.py").write_text("import sys, helper_mod_for_test\nprint(helper_mod_for_test.NAME, sys.argv[1:])\n")
    result = _tool(workspace).execute({"path": "scripts/main.py", "args": ["a", "b"]})
    assert result.result == "helper ['a', 'b']"
    import sys
    assert "helper_mod_for_test" not in sys.modules


def test_a_script_sees_the_workspace_as_it_would_under_a_shell(dirs, monkeypatch):
    monkeypatch.delenv("AGENT_WORKSPACE", raising=False)
    workspace = dirs[0]
    result = _tool(workspace).execute({"code": "import os\nos.environ['AGENT_WORKSPACE']"})
    assert result.result == repr(str(workspace))
    assert "AGENT_WORKSPACE" not in os.environ


def test_input_has_no_one_to_answer(dirs):
    result = _tool(dirs[0]).execute({"code": "input('name? ')"})
    assert "EOFError" in result.result


def test_offered_on_the_phone_only(monkeypatch):
    monkeypatch.setattr(tool_manager, "is_mobile", lambda: False)
    assert not tool_manager._available_here("python", Python)
    monkeypatch.setattr(tool_manager, "is_mobile", lambda: True)
    assert tool_manager._available_here("python", Python)
    assert not tool_manager._available_here("bash", object)


def test_check_write_path_follows_the_mode(dirs):
    workspace, outside = dirs
    inside = str(workspace / "a.txt")
    assert check_write_path(WORKSPACE_WRITE, inside, str(workspace), [str(workspace)]).allowed
    assert not check_write_path(WORKSPACE_WRITE, str(outside / "a.txt"), str(workspace), [str(workspace)]).allowed
    assert not check_write_path(READ_ONLY, inside, str(workspace), [str(workspace)]).allowed
