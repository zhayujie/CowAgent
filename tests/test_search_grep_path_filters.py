"""Exercise directory filters through the native grep-only tool entry point."""

import os
import shutil

import pytest

from agent.tools.search_files.search_files import SearchFiles


@pytest.fixture
def grep_tool(tmp_path, monkeypatch):
    binary = shutil.which("grep")
    if os.name == "nt" or not binary:
        pytest.skip("native POSIX grep required")
    source = tmp_path / "source"
    source.mkdir()
    for path in ["root.py", "src/direct.py", "src/nested/deep.py", "src/note.txt", "other/outside.py"]:
        file = source / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("needle\nneedle again\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "grep").symlink_to(binary)
    monkeypatch.setenv("PATH", str(bin_dir))
    tool = SearchFiles({"cwd": str(source)})
    assert tool._pick_backend().__name__ == "_backend_grep"
    return tool


@pytest.mark.parametrize("file_glob, expected", [
    ("src/*.py", ["src/direct.py"]),
    ("src/**/*.py", ["src/direct.py", "src/nested/deep.py"]),
    ("src/**/*.{py,txt}", ["src/direct.py", "src/nested/deep.py", "src/note.txt"]),
    ("missing/*.py", []),
    ("*.py", ["other/outside.py", "root.py", "src/direct.py", "src/nested/deep.py"]),
])
@pytest.mark.parametrize("mode", ["files", "content", "count"])
def test_grep_only_path_filter(grep_tool, file_glob, expected, mode):
    result = grep_tool.execute({"pattern": "needle", "file_glob": file_glob, "output_mode": mode})
    assert result.status == "success", result.result
    data = result.result
    if mode == "files":
        actual = data["files"]
    elif mode == "count":
        actual = [row["file"] for row in data["counts"]]
        assert all(row["count"] == 2 for row in data["counts"])
    else:
        actual = sorted({row["file"] for row in data["matches"]})
        assert all(row["line"] in (1, 2) for row in data["matches"])
    assert actual == expected
