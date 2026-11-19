"""Encoding must succeed before a fallback opens the existing file."""

import os

import pytest

from common.atomic_write import write_json_atomic, write_text_atomic


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permission bits")
@pytest.mark.parametrize("kind", ["text", "json"])
def test_encoding_failure_in_read_only_directory_preserves_original(tmp_path, kind):
    folder = tmp_path / "locked"
    folder.mkdir()
    target = folder / "state.txt"
    original = b"previous valid state\n"
    target.write_bytes(original)
    folder.chmod(0o555)
    try:
        with pytest.raises(UnicodeEncodeError):
            if kind == "text":
                write_text_atomic(target, "invalid lone surrogate: \ud800")
            else:
                write_json_atomic(target, {"value": "\ud800"})
    finally:
        folder.chmod(0o755)
    assert target.read_bytes() == original
    assert list(folder.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permission bits")
def test_valid_multibyte_fallback_preserves_requested_newlines(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    target = folder / "state.txt"
    target.write_text("old", encoding="utf-8")
    folder.chmod(0o555)
    try:
        write_text_atomic(target, "你好\nworld\n", encoding="utf-16", newline="\r\n")
    finally:
        folder.chmod(0o755)
    assert target.read_bytes() == "你好\r\nworld\r\n".encode("utf-16")
