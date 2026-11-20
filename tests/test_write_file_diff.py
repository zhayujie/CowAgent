# encoding:utf-8
"""Write reports the same kind of unified diff that edit already returns."""

from agent.tools.write.write import Write


def test_overwriting_a_file_includes_the_diff(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_bytes(b"alpha\nbeta\n")
    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "notes.txt",
        "content": "alpha\ngamma\n",
    })
    assert result.status == "success", result.result
    diff = result.result["diff"]
    assert "-beta" in diff
    assert "+gamma" in diff
    assert result.result["first_changed_line"] == 1
    assert target.read_bytes() == b"alpha\ngamma\n"


def test_a_new_file_is_all_additions(tmp_path):
    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "fresh.txt",
        "content": "hello\n",
    })
    assert result.status == "success", result.result
    assert "+hello" in result.result["diff"]
    assert (tmp_path / "fresh.txt").read_text(encoding="utf-8") == "hello\n"


def test_rewriting_without_a_change_has_no_diff(tmp_path):
    target = tmp_path / "same.txt"
    target.write_bytes(b"same\n")
    result = Write({"cwd": str(tmp_path)}).execute({
        "path": "same.txt",
        "content": "same\n",
    })
    assert result.status == "success", result.result
    assert "diff" not in result.result
