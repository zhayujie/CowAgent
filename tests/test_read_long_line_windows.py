"""On Windows, read suggests a command for a long line that cmd.exe can run.

The bash tool runs commands through cmd.exe there, which has no tail or head,
so the tail/head command read suggested failed with "'tail' is not recognized".
"""
import re
import shlex
import sys

import pytest

from agent.tools.bash.bash import Bash
from agent.tools.read import read as read_module
from agent.tools.read.read import Read
from agent.tools.utils.truncate import DEFAULT_MAX_BYTES


def _suggested_command(tmp_path, path, offset):
    result = Read({"cwd": str(tmp_path)}).execute({"path": str(path), "offset": offset})
    assert result.status == "success", result.result
    return re.search(r"Use bash tool to read: (.*)\]$", result.result["content"]).group(1)


def _write_long_second_line(path):
    path.write_text("header\n" + "B" * (DEFAULT_MAX_BYTES + 20) + "\n", encoding="utf-8")
    return path


def test_windows_suggests_powershell_with_the_path_as_a_literal(monkeypatch, tmp_path):
    monkeypatch.setattr(read_module, "_IS_WIN", True)
    path = _write_long_second_line(tmp_path / "notes draft's.txt")

    command = _suggested_command(tmp_path, path, 2)

    assert command.startswith('powershell -NoProfile -Command "')
    # A PowerShell single-quoted string escapes a quote by doubling it.
    assert "-LiteralPath '" + str(path).replace("'", "''") + "'" in command
    assert "-Skip 1 -First 1" in command
    assert str(DEFAULT_MAX_BYTES) in command
    assert "tail -n" not in command and "head -c" not in command


def test_windows_doubles_typographic_apostrophes_in_the_path(monkeypatch, tmp_path):
    # PowerShell also ends a single-quoted string at the typographic single
    # quotes (U+2018 to U+201B), so doubling only the ASCII one leaves a path
    # with a curly apostrophe failing with "The string is missing the terminator".
    monkeypatch.setattr(read_module, "_IS_WIN", True)
    path = _write_long_second_line(tmp_path / "John\u2019s notes.txt")

    command = _suggested_command(tmp_path, path, 2)

    assert "-LiteralPath '" + str(path).replace("\u2019", "\u2019\u2019") + "'" in command


def test_windows_keeps_percent_signs_away_from_cmd(monkeypatch, tmp_path):
    # cmd.exe expands %NAME% even inside double quotes, so a folder literally
    # named %APPDATA% would reach PowerShell as the real AppData path.
    monkeypatch.setattr(read_module, "_IS_WIN", True)
    (tmp_path / "%APPDATA%").mkdir()
    path = _write_long_second_line(tmp_path / "%APPDATA%" / "main.log")

    command = _suggested_command(tmp_path, path, 2)

    assert "%" not in command
    spelled = str(path).replace("'", "''").replace("%", "'+[char]37+'")
    assert f"-LiteralPath ('{spelled}')" in command


def test_other_platforms_keep_tail_and_head(monkeypatch, tmp_path):
    monkeypatch.setattr(read_module, "_IS_WIN", False)
    path = _write_long_second_line(tmp_path / "notes draft's.txt")

    assert _suggested_command(tmp_path, path, 2) == (
        f"tail -n +2 -- {shlex.quote(str(path))} | head -c {DEFAULT_MAX_BYTES}"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="runs the command through cmd.exe")
def test_windows_command_returns_the_line_through_the_bash_tool(monkeypatch, tmp_path):
    # Three-byte characters, so the byte cap falls inside one. Cut there, the
    # output is no longer valid UTF-8 and the bash tool garbles it.
    line = "数" * (DEFAULT_MAX_BYTES // 3 + 10)
    monkeypatch.setenv("COW_READ_TEST", "expanded")
    path = tmp_path / "数据 John\u2019s %COW_READ_TEST% export's.json"
    path.write_bytes(b"[\r\n" + line.encode("utf-8") + b"\r\n]\r\n")

    command = _suggested_command(tmp_path, path, 2)
    result = Bash({"cwd": str(tmp_path)}).execute({"command": command})

    assert result.status == "success", result.result
    whole_characters = DEFAULT_MAX_BYTES - DEFAULT_MAX_BYTES % 3
    assert result.result["output"] == line.encode("utf-8")[:whole_characters].decode("utf-8")
