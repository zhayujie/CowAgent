"""Fuzzy edits with outer blank lines retain the containing Python block."""

import pytest

from agent.tools.edit.edit import Edit


@pytest.mark.parametrize("outer_newlines", ["", "\n", "\n\n"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_fuzzy_edit_keeps_conditional_scope(tmp_path, outer_newlines, ending):
    path = tmp_path / "conditional.py"
    source = (
        "def choose(enabled):\n"
        "    if enabled:\n"
        "        marker = True\n"
        "        value = 'old'\n"
        "        return value\n"
        "    return 'disabled'\n"
    )
    path.write_bytes(source.replace("\n", ending).encode())
    old = outer_newlines + "    value = 'old'\n    return value" + outer_newlines
    new = outer_newlines + "    value = 'new'\n    return value" + outer_newlines
    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": path.name, "oldText": old, "newText": new,
    })
    assert result.status == "success", result.result
    namespace = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    assert namespace["choose"](False) == "disabled"
    assert namespace["choose"](True) == "new"
    if ending == "\r\n":
        assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


@pytest.mark.parametrize("replacement_indent,disabled", [("        ", "disabled"), ("    ", "new")])
def test_exact_edit_keeps_requested_replacement_indentation(tmp_path, replacement_indent, disabled):
    path = tmp_path / "exact.py"
    path.write_text(
        "def choose(enabled):\n"
        "    if enabled:\n"
        "        marker = True\n"
        "        value = 'old'\n"
        "        return value\n"
        "    return 'disabled'\n"
    )
    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": path.name,
        "oldText": "\n        value = 'old'\n        return value\n",
        "newText": f"\n{replacement_indent}value = 'new'\n{replacement_indent}return value\n",
    })
    assert result.status == "success", result.result
    namespace = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    assert namespace["choose"](False) == disabled
    assert namespace["choose"](True) == "new"
