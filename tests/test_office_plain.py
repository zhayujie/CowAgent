"""Word and PowerPoint read with the standard library match what python-docx / python-pptx give."""

import sys

import pytest

from common.office_text import docx_text_plain, iter_docx_body_text, iter_pptx_shape_text, pptx_slides_plain


def test_docx_plain_matches_python_docx(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "a.docx"
    doc = docx.Document()
    doc.add_paragraph("First paragraph")
    table = doc.add_table(rows=2, cols=2)
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            cell.text = f"r{r}c{c}"
    doc.add_paragraph("Last 段落")
    doc.save(path)

    assert docx_text_plain(path) == "\n".join(iter_docx_body_text(docx.Document(path)))


def test_pptx_plain_follows_slide_order(tmp_path):
    pptx = pytest.importorskip("pptx")
    from pptx.util import Inches

    path = tmp_path / "a.pptx"
    prs = pptx.Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "Title one"
    first.placeholders[1].text = "Point A"
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "Title two"
    grid = second.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    for r in range(2):
        for c in range(2):
            grid.cell(r, c).text = f"r{r}c{c}"
    # Moving the second slide first keeps its file name, so order must come from presentation.xml.
    ids = prs.slides._sldIdLst
    ids.insert(0, ids[-1])
    prs.save(path)

    expected = [list(iter_pptx_shape_text(s.shapes)) for s in pptx.Presentation(path).slides]
    assert pptx_slides_plain(path) == expected
    assert expected[0][0] == "Title two"


def test_web_fetch_reads_office_without_the_libraries(tmp_path, monkeypatch):
    docx = pytest.importorskip("docx")
    pptx = pytest.importorskip("pptx")
    from agent.tools.web_fetch.web_fetch import WebFetch

    word = tmp_path / "a.docx"
    doc = docx.Document()
    doc.add_paragraph("Fetched 段落")
    doc.save(word)
    slides = tmp_path / "a.pptx"
    prs = pptx.Presentation()
    prs.slides.add_slide(prs.slide_layouts[1]).shapes.title.text = "Fetched title"
    prs.save(slides)

    monkeypatch.setitem(sys.modules, "docx", None)
    monkeypatch.setitem(sys.modules, "pptx", None)
    tool = WebFetch()
    assert tool._parse_word(str(word)) == "Fetched 段落"
    assert tool._parse_ppt(str(slides)) == "--- Slide 1/1 ---\nFetched title"
