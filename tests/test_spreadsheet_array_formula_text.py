"""Keep native Excel array formula source visible when no cache exists."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

import pytest

from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
@pytest.mark.parametrize("cached_value", [None, 0, False, 42])
def test_native_array_formula_source_and_cached_values(tmp_path, monkeypatch, tool_name, cached_value):
    openpyxl = pytest.importorskip("openpyxl")
    ArrayFormula = pytest.importorskip("openpyxl.worksheet.formula").ArrayFormula

    formula = "=SUM(C2:C11*D2:D11)"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["E2"] = ArrayFormula("E2:E11", formula)
    sheet["A1"] = "Array calculation"
    sheet["A2"] = "=SUM(1,2)"
    sheet["B2"] = "Following text"
    path = tmp_path / "array-calculations.xlsx"
    workbook.save(path)
    workbook.close()

    if cached_value is not None:
        # Add the real OOXML cached result; openpyxl deliberately evaluates none.
        with ZipFile(path) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        xml = ET.fromstring(members["xl/worksheets/sheet1.xml"])
        cell = xml.find(".//s:c[@r='E2']", namespace)
        if cached_value is False:
            cell.set("t", "b")
            cell.find("s:v", namespace).text = "0"
        else:
            cell.find("s:v", namespace).text = str(cached_value)
        members["xl/worksheets/sheet1.xml"] = ET.tostring(xml)
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)

    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        text = result.result.get("content", "")
    else:
        payload = path.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        # Permit only this loopback test server; production SSRF defaults stay on.
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = WebFetch({"cwd": str(tmp_path)}).execute(
                {"url": f"http://127.0.0.1:{server.server_port}/array-calculations.xlsx"}
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        text = result.result

    assert result.status == "success", result.result
    assert "=SUM(1,2) (not calculated)" in text
    assert "Following text" in text
    assert "object at 0x" not in text
    if cached_value is None:
        assert f"[Formula: {formula} (not calculated)]" in text
    else:
        assert formula not in text
        row = next(line for line in text.splitlines() if "Following text" in line)
        assert row.rstrip().endswith(str(cached_value))
