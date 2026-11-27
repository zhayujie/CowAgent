"""Tracked Word insertions retain the text displayed in the document."""

from io import BytesIO

import pytest
import requests

from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch
from common.office_text import docx_text_plain, iter_docx_body_text


@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
@pytest.mark.parametrize("placement", ["body", "cell"])
@pytest.mark.parametrize("in_control", [False, True])
def test_tracked_insertions_are_read(tmp_path, monkeypatch, tool_name, placement, in_control):
    docx = pytest.importorskip("docx")
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = docx.Document()
    paragraph = (document.add_paragraph() if placement == "body"
                 else document.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0])
    paragraph.add_run("Amount: ")
    inserted = paragraph.add_run("42\tUSD\nApproved")
    insertion = OxmlElement("w:ins")
    insertion.set(qn("w:id"), "1")
    insertion.set(qn("w:author"), "Reviewer")
    insertion.set(qn("w:date"), "2026-11-26T00:00:00Z")
    paragraph._p.append(insertion)
    insertion.append(inserted._r)
    if in_control:
        control = OxmlElement("w:sdt")
        content = OxmlElement("w:sdtContent")
        control.append(content)
        insertion.addprevious(control)
        content.append(insertion)
    deleted = OxmlElement("w:del")
    run = OxmlElement("w:r")
    text = OxmlElement("w:delText")
    text.text = "Rejected value"
    run.append(text)
    deleted.append(run)
    paragraph._p.append(deleted)
    paragraph.add_run(" end")
    path = tmp_path / "review-42.docx"
    document.save(path)
    expected = "Amount: 42\tUSD\nApproved end"
    assert docx_text_plain(path) == expected

    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        output = result.result.get("content", "")
    else:
        tool = WebFetch({"cwd": str(tmp_path)})
        response = requests.Response()
        response.status_code = 200
        response.raw = BytesIO(path.read_bytes())
        response.headers["Content-Length"] = str(path.stat().st_size)
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        monkeypatch.setattr(tool, "_safe_get", lambda *_args, **_kwargs: response)
        result = tool.execute({"url": "https://example.test/review-42.docx"})
        output = result.result

    assert result.status == "success", result.result
    assert "Amount: 42\tUSD" in output
    assert "Approved end" in output
    assert output.index("Amount: 42\tUSD") < output.index("Approved end")
    assert output.count("Amount: 42\tUSD") == 1
    assert "Rejected value" not in output
    loaded = docx.Document(path)
    original = loaded.element.xml
    assert list(iter_docx_body_text(loaded)) == [expected]
    assert list(iter_docx_body_text(loaded)) == [expected]
    assert loaded.element.xml == original
