"""Real DOCX table cells keep nested content through both document tools."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch


@contextmanager
def _document_server(path):
    data = path.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/report.docx"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
@pytest.mark.parametrize("nested", [False, True])
def test_word_cell_blocks_keep_their_order(tmp_path, monkeypatch, tool_name, nested):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Report beginning")
    table = document.add_table(rows=1, cols=2)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "Before nested table"
    expected = ["Report beginning", "Before nested table"]
    if nested:
        inner = cell.add_table(rows=2, cols=2)
        for row, texts in zip(inner.rows, (("Region", "Budget"), ("North", "11 million"))):
            for target, text in zip(row.cells, texts):
                target.text = text
        # A second nesting level must use the same traversal.
        deeper = inner.cell(1, 1).add_table(rows=1, cols=1)
        deeper.cell(0, 0).text = "Approved allocation"
        expected += ["Region\tBudget", "North\t11 million", "Approved allocation"]
    cell.add_paragraph("After nested table")
    table.cell(0, 1).text = "Right-hand cell"
    document.add_paragraph("Report ending")
    expected += ["After nested table", "Right-hand cell", "Report ending"]
    path = tmp_path / "report.docx"
    document.save(path)

    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        text = result.result.get("content", "")
    else:
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        with _document_server(path) as url:
            result = WebFetch({"cwd": str(tmp_path)}).execute({"url": url})
        text = result.result

    assert result.status == "success", result.result
    positions = [text.index(piece) for piece in expected]
    assert positions == sorted(positions)
    assert text.count("Approved allocation") == (1 if nested else 0)
