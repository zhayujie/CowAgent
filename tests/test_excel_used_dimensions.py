"""Read real XLSX cells even when the producer records a stale used range."""
import re
from zipfile import ZipFile
import pytest
openpyxl = pytest.importorskip("openpyxl")
from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch

@pytest.mark.parametrize('dimension', ['A1:A1', 'A1:B2', 'A1:A4', 'A1:B4', None])
def test_office_tools_preserve_cells_beyond_stale_declared_dimensions(tmp_path, dimension):
    original = tmp_path / 'original.xlsx'
    path = tmp_path / 'report.xlsx'
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(['Item', 'Amount'])
    sheet.append(['Revenue', 120])
    sheet.append(['Expenses', 45])
    sheet.append(['Net', '=B2-B3'])
    book.save(original)
    book.close()
    with ZipFile(original) as src, ZipFile(path, 'w') as dst:
        for entry in src.infolist():
            body = src.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                replacement = b'' if dimension is None else f'<dimension ref="{dimension}"/>'.encode()
                body = re.sub(rb'<dimension\b[^>]*/>', replacement, body)
            dst.writestr(entry, body)
    read = Read({'cwd': str(tmp_path)}).execute({'path': str(path)})
    assert read.status == 'success', read.result
    text = read.result['content']
    assert 'Expenses\t45' in text
    assert 'Net\t[Formula: =B2-B3 (not calculated)]' in text
    fetched = WebFetch({'cwd': str(tmp_path)})._parse_document(str(path), '.xlsx')
    assert 'Expenses | 45' in fetched
    assert 'Net | [Formula: =B2-B3 (not calculated)]' in fetched
