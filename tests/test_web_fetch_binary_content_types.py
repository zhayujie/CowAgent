"""A .doc served as `application/msword` must not be decoded as a web page.

The binary check and the suffix lookup used to be two hand-maintained lists.
`application/msword` (Word 97-2003) was in neither, so the response fell through
to the HTML path: the tool decoded the OLE bytes with `errors="replace"` and
returned the result as a successful page. The same file served as
`application/octet-stream` failed cleanly, which is the inconsistency.
"""
import pytest
import requests

from agent.tools.web_fetch import web_fetch

# The OLE2 compound-file signature every .doc starts with.
OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00\x01\x02\x03" * 16


def _response(content_type, body=OLE_HEADER, url="https://example.test/download"):
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = content_type
    response.url = url
    response._content = body
    response._content_consumed = True
    return response


def _fetch(monkeypatch, content_type, body=OLE_HEADER, url="https://example.test/download"):
    """Run the tool against a stubbed response; no network, no stream to drain."""
    tool = web_fetch.WebFetch({})
    monkeypatch.setattr(tool, "_safe_get", lambda target, **kwargs: _response(content_type, body, url))
    monkeypatch.setattr(web_fetch, "read_response",
                        lambda response, limit, max_seconds=0: body)
    return tool.execute({"url": url})


@pytest.mark.parametrize("content_type", [
    "application/msword",
    "application/vnd.ms-word",
    "application/msword; charset=binary",
])
def test_a_word_97_document_is_refused_instead_of_decoded(monkeypatch, content_type):
    result = _fetch(monkeypatch, content_type)

    assert result.status == "error", (
        f"{content_type} was decoded as a web page: {result.result[:120]!r}"
    )
    assert "binary content" in result.result


def test_a_url_that_ends_in_doc_is_refused_too(monkeypatch):
    """`.doc` is not a suffix this tool can parse, whatever the URL says."""
    result = _fetch(monkeypatch, "application/msword", url="https://example.test/a.doc")

    assert result.status == "error"
    assert "binary content" in result.result


@pytest.mark.parametrize("content_type,suffix", [
    ("application/pdf", ".pdf"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    ("application/vnd.ms-excel", ".xls"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    ("application/vnd.ms-powerpoint", ".ppt"),
    ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
])
def test_a_supported_document_still_reaches_its_parser(monkeypatch, content_type, suffix):
    """Control: the shared table must keep routing every existing type."""
    tool = web_fetch.WebFetch({})
    monkeypatch.setattr(tool, "_safe_get", lambda target, **kwargs: _response(content_type))
    seen = {}

    def _fetch_document(url, suffix=None, response=None):
        seen["suffix"] = suffix
        return web_fetch.ToolResult.success("parsed")

    monkeypatch.setattr(tool, "_fetch_document", _fetch_document)
    result = tool.execute({"url": "https://example.test/download"})

    assert seen["suffix"] == suffix, f"{content_type} routed to {seen.get('suffix')}"
    assert result.status == "success"


def test_octet_stream_still_fails_as_binary(monkeypatch):
    """Control: unchanged for the generic binary type."""
    result = _fetch(monkeypatch, "application/octet-stream")

    assert result.status == "error"
    assert "binary content" in result.result


def test_html_is_still_a_page(monkeypatch):
    """Control: the document table must not swallow ordinary pages."""
    result = _fetch(monkeypatch, "text/html; charset=utf-8", body=b"<html><title>hi</title><body>x</body></html>")

    assert result.status == "success"
    assert "hi" in result.result
