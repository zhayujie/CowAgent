"""Every truncated shell result must retain an accessible full output log."""
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agent.tools.bash.bash import Bash
from agent.tools.utils.truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES


@pytest.fixture
def tool(tmp_path, monkeypatch):
    original = tempfile.NamedTemporaryFile

    def owned_temp_file(*args, **kwargs):
        kwargs["dir"] = str(tmp_path)
        return original(*args, **kwargs)

    # Keep generated logs in the owned fixture. No subprocess/stream mocks.
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", owned_temp_file)
    return Bash({"cwd": str(tmp_path)})


def _run(tool, expression, exit_code=0):
    script = f"import sys; sys.stdout.write({expression}); sys.exit({exit_code})"
    command = (subprocess.list2cmdline([sys.executable, "-c", script]) if os.name == "nt"
               else shlex.quote(sys.executable) + " -c " + shlex.quote(script))
    return tool.execute({"command": command, "timeout": 10})


@pytest.mark.parametrize("kind", ["lines", "bytes", "both"])
def test_every_truncation_keeps_the_original_output(tool, kind):
    expressions = {
        "lines": f"'\\n'.join('row-'+str(i) for i in range({DEFAULT_MAX_LINES + 50}))",
        "bytes": f"chr(0x1f389)*({DEFAULT_MAX_BYTES}//4+10)",
        "both": f"'\\n'.join(str(i)+'-'+chr(0x1f389)*10 for i in range({DEFAULT_MAX_LINES + 50}))",
    }
    expression = expressions[kind]
    expected = eval(expression, {"chr": chr, "range": range, "str": str})
    if kind == "lines":
        assert len(expected.encode("utf-8")) < DEFAULT_MAX_BYTES
    result = _run(tool, expression)
    assert result.status == "success", result.result
    details = result.result["details"]
    assert details["truncation"]["truncated"]
    path = Path(details["full_output_path"])
    assert path.parent == Path(tool.cwd)
    assert path.read_text(encoding="utf-8") == expected
    assert str(path) in result.result["output"]
    assert "Full output: None" not in result.result["output"]


def test_untruncated_boundary_does_not_create_a_log(tool):
    expression = f"'\\n'.join('row-'+str(i) for i in range({DEFAULT_MAX_LINES}))"
    result = _run(tool, expression)
    assert result.status == "success", result.result
    assert result.result["details"] is None
    assert not list(Path(tool.cwd).glob("bash-*.log"))


def test_failed_line_truncated_command_keeps_exit_status_and_full_log(tool):
    expression = f"'\\n'.join('row-'+str(i) for i in range({DEFAULT_MAX_LINES + 1}))"
    result = _run(tool, expression, exit_code=2)
    assert result.status == "error", result.result
    assert result.result["exit_code"] == 2
    path = Path(result.result["details"]["full_output_path"])
    assert path.read_text() == eval(expression, {"range": range, "str": str})
    assert "Command exited with code 2" in result.result["output"]
