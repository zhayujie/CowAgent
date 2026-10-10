"""The native ripgrep backend retains bounded previews for long source lines."""

import shutil

import pytest

from agent.tools.search_files.search_files import SearchFiles
from agent.tools.utils.truncate import GREP_MAX_LINE_LENGTH


@pytest.mark.skipif(not shutil.which("rg"), reason="native ripgrep is not installed")
@pytest.mark.parametrize("length", [80, 2400])
@pytest.mark.parametrize("mode", ["content", "files", "count"])
def test_long_matching_line_retains_source_preview(tmp_path, monkeypatch, length, mode):
    line = "const invoiceTotal = " + "x" * length
    path = tmp_path / "bundle.js"
    path.write_text(line + "\nconst other = 1;\n", encoding="utf-8")
    tool = SearchFiles({"cwd": str(tmp_path)})
    monkeypatch.setattr(tool, "_pick_backend", lambda: tool._backend_rg)
    result = tool.execute({"pattern": "invoiceTotal", "output_mode": mode})
    assert result.status == "success", result.result
    assert result.result["match_count"] == 1
    if mode == "content":
        match = result.result["matches"][0]
        assert match["file"] == "bundle.js"
        assert match["line"] == 1
        assert match["match"].startswith("const invoiceTotal = ")
        assert "Omitted long matching line" not in match["match"]
        assert len(match["match"]) <= GREP_MAX_LINE_LENGTH + 20
    elif mode == "files":
        assert result.result["files"] == ["bundle.js"]
    else:
        assert result.result["counts"] == [{"file": "bundle.js", "count": 1}]
