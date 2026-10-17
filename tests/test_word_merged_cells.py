"""Merged Word cells must not multiply text sent to the model."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import pytest
from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch
from common.office_text import iter_docx_body_text


def _document(layout):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Report begins")
    table = document.add_table(rows=3, cols=3)
    if layout == "horizontal":
        table.cell(0, 0).merge(table.cell(0, 2)).text = "Approved allocation"
    elif layout == "vertical":
        table.cell(0, 0).merge(table.cell(2, 0)).text = "Approved allocation"
    elif layout == "rectangle":
        table.cell(0, 0).merge(table.cell(1, 1)).text = "Approved allocation"
    else:
        cell = table.cell(0, 0)
        cell.paragraphs[0].text = "Before nested allocation"
        nested = cell.add_table(rows=2, cols=2)
        nested.cell(0, 0).merge(nested.cell(1, 1)).text = "Approved allocation"
        cell.add_paragraph("After nested allocation")
    table.cell(2, 1).text = "Repeat label"
    table.cell(2, 2).text = "Repeat label"
    document.add_paragraph("Report ends")
    return document


@contextmanager
def _serve(path):
    body = path.read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/report.docx"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("layout", ["horizontal", "vertical", "rectangle", "nested"])
@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
def test_merged_cells_read_once_but_equal_text_survives(tmp_path, monkeypatch, layout, tool_name):
    path = tmp_path / "report.docx"
    _document(layout).save(path)
    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        text = result.result.get("content", "")
    else:
        # Policy opt-out only: HTTP, streaming and DOCX parser remain real.
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        with _serve(path) as url:
            result = WebFetch({"cwd": str(tmp_path)}).execute({"url": url})
        text = result.result
    assert result.status == "success", result.result
    assert text.count("Approved allocation") == 1
    assert text.count("Repeat label") == 2
    assert text.index("Report begins") < text.index("Approved allocation") < text.index("Report ends")
    if layout == "nested":
        assert text.index("Before nested allocation") < text.index("Approved allocation") < text.index("After nested allocation")


def test_covered_slots_stay_empty_and_flat_table_output_is_unchanged():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Heading"
    table.cell(0, 2).text = "Right column"
    for cell, value in zip(table.rows[1].cells, ["Same", "Same", "Last"]):
        cell.text = value
    assert list(iter_docx_body_text(document)) == ["Heading\t\tRight column", "Same\tSame\tLast"]
