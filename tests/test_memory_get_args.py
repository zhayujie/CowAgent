# encoding:utf-8
"""memory_get must not answer a bad line argument with a Python error.

Both line arguments arrive straight from the model and were used in
comparison/arithmetic with no coercion at all
(agent/tools/memory/memory_get.py:126-133), which broke two ways:

* A string ``start_line`` -- a routine way for a model to send a number --
  raised ``TypeError: '<' not supported between instances of 'str' and 'int'``.
  The blanket ``except Exception`` at line 152 turned it into
  "Error reading memory file: '<' not supported ...", so the model was shown a
  raw Python message instead of anything it could act on.
* A negative ``num_lines`` never raised. ``-1`` made ``end_idx = start_idx - 1``,
  an inverted range whose slice is empty, and the tool answered
  ``status: "success"`` with a "Lines: 2-1" header and no body. That is silent
  data loss wearing a success -- the model reads it as a completed read.

The sibling tools already coerce an integer argument this way before using it
(bash.py:140-145, search_files.py:278-286); memory_get now does too.
"""

import types
from pathlib import Path

from agent.tools.memory.memory_get import MemoryGetTool

BODY = "L1\nL2\nL3\nL4\nL5"


def _tool(workspace):
    """The tool only ever asks the manager for its workspace."""
    config = types.SimpleNamespace(get_workspace=lambda: Path(workspace))
    return MemoryGetTool(types.SimpleNamespace(config=config))


def _memory_file(tmp_path, body=BODY):
    workspace = tmp_path / "agents" / "pm"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "notes.md").write_text(body, encoding="utf-8")
    return _tool(workspace)


def test_a_string_start_line_is_read_as_a_number(tmp_path):
    # The reproduced failure: a model sending "2" got a Python TypeError back.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": "2", "num_lines": 2})

    assert result.status == "success"
    assert "L2" in result.result
    assert "not supported between" not in result.result


def test_a_negative_num_lines_never_reports_an_empty_success(tmp_path):
    # The reproduced failure: -1 read as an empty "Lines: 2-1" success.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": 2, "num_lines": -1})

    assert result.status == "error", "an inverted range must not read as a success"
    assert "num_lines" in result.result
    # And it must not leak a Python message either.
    assert "not supported between" not in result.result
    assert "Lines: 2-1" not in result.result


def test_a_zero_num_lines_is_rejected_rather_than_reading_the_whole_file(tmp_path):
    # Same deliberate rule as max_results/timeout: a count of zero is a
    # mistake worth reporting, not a request for everything.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "num_lines": 0})

    assert result.status == "error"
    assert "num_lines" in result.result


def test_a_non_numeric_argument_names_the_argument_and_the_value(tmp_path):
    # The message has to be something a model can correct, in the shape the
    # other tools use.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": "first"})

    assert result.status == "error"
    assert "start_line" in result.result
    assert "'first'" in result.result
    assert "TypeError" not in result.result


def test_a_non_numeric_num_lines_names_the_argument_and_the_value(tmp_path):
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "num_lines": "all"})

    assert result.status == "error"
    assert "num_lines" in result.result
    assert "'all'" in result.result
    assert "TypeError" not in result.result


def test_an_omitted_num_lines_still_reads_to_the_end(tmp_path):
    # None means "read the rest" and is the documented default -- the coercion
    # must not turn it into an error.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": "4"})

    assert result.status == "success"
    assert "L4" in result.result
    assert "L5" in result.result
    assert "L1" not in result.result


def test_the_existing_line_range_still_behaves(tmp_path):
    # The numbers that already worked must keep working unchanged.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": 2, "num_lines": 3})

    assert result.status == "success"
    assert "L2" in result.result
    assert "L3" in result.result
    assert "L4" in result.result
    assert "L5" not in result.result
    assert "Lines: 2-4" in result.result


def test_a_start_line_below_one_still_clamps_instead_of_failing(tmp_path):
    # Pre-existing behaviour, kept: a low start_line is clamped, not rejected.
    tool = _memory_file(tmp_path)

    result = tool.execute({"path": "memory/notes.md", "start_line": 0, "num_lines": 2})

    assert result.status == "success"
    assert "L1" in result.result
    assert "L2" in result.result
    assert "L3" not in result.result
