# encoding:utf-8
"""
Regression tests for the Write tool's line endings.

Write saved its content in text mode, which turns every '\n' into os.linesep.
On Windows that meant:

* rewriting an LF file turned the whole file into CRLF, the defect
  test_edit_line_endings.py pins for the edit tool: `#!/bin/sh\r` is not a
  valid shebang, and every line of the file changes;
* content that already used CRLF came out with '\r\r\n' line breaks;
* bytes_written counted the content it was given, not what reached the disk.

LF content now follows the file's own line endings, as it does with edit.
Content that already uses CRLF is written as given, and a file with no line
ending yet still gets the platform's.

Every assertion here is made on bytes: reading the file back in text mode
would translate CRLF to LF and hide the difference.
"""
import os

from agent.tools.write.write import Write


def _write(tmp_path, name, content, existing=None):
    """Seed the file with exact bytes if given, then run the write tool."""
    target = tmp_path / name
    if existing is not None:
        # A text-mode write would translate these bytes on Windows.
        target.write_bytes(existing)
    result = Write({"cwd": str(tmp_path)}).execute({"path": name, "content": content})
    assert result.status == "success", result.result
    return target, result


def test_rewriting_an_lf_file_keeps_it_lf(tmp_path):
    target, _ = _write(
        tmp_path, "run.sh", "#!/bin/sh\necho one\necho two\n",
        existing=b"#!/bin/sh\necho one\n",
    )

    assert target.read_bytes() == b"#!/bin/sh\necho one\necho two\n"


def test_rewriting_a_crlf_file_keeps_it_crlf(tmp_path):
    # The model sends LF, so writing it verbatim would turn a Windows script
    # into LF: the file's own ending has to be put back.
    target, _ = _write(
        tmp_path, "run.bat", "@echo off\necho one\necho two\n",
        existing=b"@echo off\r\necho one\r\n",
    )

    assert target.read_bytes() == b"@echo off\r\necho one\r\necho two\r\n"


def test_content_that_uses_crlf_is_written_as_given(tmp_path):
    content = "@echo off\r\necho one\r\n"
    new, _ = _write(tmp_path, "new.bat", content)
    over_lf, _ = _write(tmp_path, "old.bat", content, existing=b"@echo off\n")

    assert new.read_bytes() == b"@echo off\r\necho one\r\n"
    assert over_lf.read_bytes() == b"@echo off\r\necho one\r\n"


def test_a_file_without_line_endings_still_gets_the_platform_ones(tmp_path):
    # Unchanged: a new file, an empty one or a single unterminated line has no
    # ending to keep, so LF content gets os.linesep as text mode gave it.
    expected = "one\ntwo\n".replace("\n", os.linesep).encode()
    new, _ = _write(tmp_path, "new.txt", "one\ntwo\n")
    empty, _ = _write(tmp_path, "empty.txt", "one\ntwo\n", existing=b"")
    single, _ = _write(tmp_path, "single.txt", "one\ntwo\n", existing=b"one")

    assert new.read_bytes() == expected
    assert empty.read_bytes() == expected
    assert single.read_bytes() == expected


def test_bytes_written_is_the_size_on_disk(tmp_path):
    cases = [
        ("lf.sh", "#!/bin/sh\necho one\n", b"#!/bin/sh\n"),
        ("crlf.bat", "@echo off\necho one\n", b"@echo off\r\n"),
        ("new.bat", "@echo off\r\necho one\r\n", None),
        ("new.txt", "one\ntwo\n", None),
    ]
    for name, content, existing in cases:
        target, result = _write(tmp_path, name, content, existing)
        assert result.result["bytes_written"] == os.path.getsize(target), name
