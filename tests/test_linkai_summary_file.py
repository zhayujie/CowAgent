"""LinkSummary must name, close and classify the file it is handed correctly.

Three defects on the same two small methods, all of which the surrounding code
already gets right:

- the multipart name came from ``file_path.split("/")[-1]``, which on Windows
  keeps the whole path (the separator is a backslash), and the handle passed as
  ``"file"`` made ``requests`` send that same full path as the multipart
  filename too;
- ``open(file_path, "rb")`` was handed to ``requests`` and never closed --
  ``requests`` does not own it -- so every summary leaked a descriptor and kept
  the file locked on Windows;
- the extension was compared case-sensitively, so ``REPORT.PDF`` was reported
  unsupported and silently skipped, while the media classifier next door already
  lowercases before matching (``models/linkai/link_ai_bot.py``,
  ``tests/test_linkai_media_urls.py::test_uppercase_extension_is_recognized``).
"""

from unittest.mock import Mock, patch

import pytest

import plugins

# plugins/linkai/__init__.py also imports the registered plugin, which refuses to
# load without a plugin path -- same idiom as test_linkai_midjourney_send.py.
plugins.instance.current_plugin_path = "./plugins/linkai"
import plugins.linkai.summary as summary_module  # noqa: E402
plugins.instance.current_plugin_path = None

LinkSummary = summary_module.LinkSummary


def _ok_response():
    response = Mock(status_code=200)
    response.json.return_value = {"code": 200, "data": {"summary": "s", "summary_id": "id-1"}}
    return response


def _record_post(record):
    def post(url, **kwargs):
        parts = kwargs["files"]
        record["name"] = parts["name"]
        file_part = parts["file"]
        if isinstance(file_part, tuple):
            record["filename"], record["handle"] = file_part
        else:  # the pre-fix shape: a bare file object
            record["filename"], record["handle"] = getattr(file_part, "name", ""), file_part
        return _ok_response()

    return post


def _summary_report(tmp_path, record):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"pdf-bytes")
    with patch.object(summary_module.requests, "post", side_effect=_record_post(record)), \
            patch.object(summary_module, "conf", lambda: {"linkai_api_key": "k"}):
        return LinkSummary().summary_file(str(report), "app-1")


def test_the_file_name_sent_to_the_api_is_a_bare_filename(tmp_path):
    record = {}

    result = _summary_report(tmp_path, record)

    assert record["name"] == "report.pdf", "the API's own name field must be a bare name"
    assert record["filename"] == "report.pdf", "so must the multipart filename"
    assert result == {"summary": "s", "summary_id": "id-1"}


def test_the_upload_handle_is_closed_afterwards(tmp_path):
    """The handle is opened per call and handed to requests, which does not own
    it: a long-running bot leaked one descriptor per summarized file."""
    record = {}

    _summary_report(tmp_path, record)

    assert record["handle"].closed is True


def test_the_handle_is_open_while_the_request_is_sent(tmp_path):
    """Control: closing it before the upload would send an empty body."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"pdf-bytes")
    record = {}

    def post(url, **kwargs):
        parts = kwargs["files"]
        handle = parts["file"][1] if isinstance(parts["file"], tuple) else parts["file"]
        record["read"] = handle.read()
        return _ok_response()

    with patch.object(summary_module.requests, "post", side_effect=post), \
            patch.object(summary_module, "conf", lambda: {"linkai_api_key": "k"}):
        LinkSummary().summary_file(str(report), "app-1")

    assert record["read"] == b"pdf-bytes"


@pytest.mark.parametrize("name", ["report.pdf", "REPORT.PDF", "Notes.MD", "scan.JPEG"])
def test_an_uppercase_extension_is_supported(tmp_path, name):
    target = tmp_path / name
    target.write_bytes(b"x")

    assert LinkSummary().check_file(str(target), {}) is True


def test_an_unsupported_extension_is_still_rejected(tmp_path):
    """Control: lowercasing must not turn into accepting anything."""
    target = tmp_path / "archive.zip"
    target.write_bytes(b"x")

    assert LinkSummary().check_file(str(target), {}) is False
