"""Office document text extraction shared by the read and web_fetch tools.

The parsers are optional dependencies, so they are imported lazily (docx) or
supplied by the caller (openpyxl's ``load_workbook``). Word and PowerPoint
files can also be read with the standard library alone, for installs without
python-docx / python-pptx (which need lxml), such as the mobile apps.
"""

import posixpath
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from xml.etree import ElementTree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _open_package(file_path):
    try:
        return zipfile.ZipFile(file_path)
    except zipfile.BadZipFile:
        raise ValueError("Not a .docx/.pptx file. The older .doc/.ppt formats cannot be read; "
                         "save it as .docx/.pptx first.") from None


def docx_text_plain(file_path):
    """Paragraphs and table rows of a .docx in body order, tracked deletions left out."""
    return "\n".join(_plain_docx_body(file_path))


def _plain_docx_body(file_path):
    with _open_package(file_path) as archive:
        body = ElementTree.fromstring(archive.read("word/document.xml")).find(f"{_W}body")
    return list(_plain_docx_blocks(body)) if body is not None else []


def _plain_docx_blocks(container):
    for element in container:
        if element.tag == f"{_W}p":
            yield _plain_docx_paragraph(element)
        elif element.tag == f"{_W}sdt":
            content = element.find(f"{_W}sdtContent")
            if content is not None:
                yield from _plain_docx_blocks(content)
        elif element.tag == f"{_W}tbl":
            for row in element.findall(f"{_W}tr"):
                yield "\t".join("\n".join(_plain_docx_blocks(cell)) for cell in row.findall(f"{_W}tc"))


def _plain_docx_paragraph(paragraph):
    parts = []
    # Only what runs hold: a paragraph's own properties list tab stops as w:tab too.
    for run in paragraph.iter(f"{_W}r"):
        for node in run:
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
    return "".join(parts)


def pptx_slides_plain(file_path):
    """Lines of text per slide of a .pptx, in the presentation's slide order."""
    with _open_package(file_path) as archive:
        presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        rels = ElementTree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_REL}Relationship")}
        names = set(archive.namelist())
        slides = []
        for slide_id in presentation.iter(f"{_P}sldId"):
            target = targets.get(slide_id.get(f"{_R}id"), "")
            path = posixpath.normpath(posixpath.join("ppt", target)) if not target.startswith("/") else target[1:]
            if path in names:
                slides.append(list(_plain_pptx_shapes(ElementTree.fromstring(archive.read(path)))))
    return slides


def _plain_pptx_shapes(node):
    for child in node:
        if child.tag == f"{_A}tbl":
            for row in child.findall(f"{_A}tr"):
                # A merged cell's origin holds the text; the cells it covers add none.
                yield "\t".join(
                    "\n".join(_plain_pptx_text(p) for p in cell.iter(f"{_A}p")).strip()
                    for cell in row.findall(f"{_A}tc")
                    if cell.get("hMerge") != "1" and cell.get("vMerge") != "1"
                )
        elif child.tag == f"{_A}p":
            text = _plain_pptx_text(child).strip()
            if text:
                yield text
        else:
            yield from _plain_pptx_shapes(child)


def _plain_pptx_text(paragraph):
    return "".join(
        (node.text or "") if node.tag == f"{_A}t" else "\n"
        for node in paragraph.iter()
        if node.tag in (f"{_A}t", f"{_A}br")
    )


def iter_docx_body_text(document):
    """Yield paragraphs and table rows in body order, including content controls.

    Builds python-docx's block objects directly, which also works on versions
    that predate ``Document.iter_inner_content()``.
    """
    yield from _iter_docx_blocks(document.element.body, document)


def _iter_docx_blocks(container, parent):
    """Traverse paragraphs and tables in either a document body or a cell."""
    from docx.oxml.ns import qn
    from docx.table import Table

    for element in container.iterchildren():
        if element.tag == qn("w:p"):
            yield _docx_paragraph_text(element, parent)
        elif element.tag == qn("w:sdt"):
            content = element.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_docx_blocks(content, parent)
        elif element.tag == qn("w:tbl"):
            seen_cells = set()
            for row in Table(element, parent).rows:
                values = []
                for cell in row.cells:
                    # python-docx repeats the same XML cell for every covered
                    # grid slot, including vertical continuations. Keep those
                    # slots empty without dropping equal text in other cells.
                    if cell._tc in seen_cells:
                        values.append("")
                    else:
                        seen_cells.add(cell._tc)
                        values.append("\n".join(_iter_docx_blocks(cell._tc, cell)))
                yield "\t".join(values)


def _docx_paragraph_text(element, parent):
    """Include inline controls and cached field text without changing the source."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    tags = (qn("w:sdt"), qn("w:fldSimple"))
    if any(element.find(".//" + tag) is not None for tag in tags):
        element = deepcopy(element)
        for control in list(element.iter(*tags)):
            content = (control.find(qn("w:sdtContent"))
                       if control.tag == tags[0] else control)
            if content is not None:
                for child in list(content):
                    control.addprevious(child)
            control.getparent().remove(control)
    return Paragraph(element, parent).text


def iter_pptx_shape_text(shapes):
    """Yield slide text, including table cells and nested groups, in shape order."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from iter_pptx_shape_text(shape.shapes)
        elif shape.has_table:
            for row in shape.table.rows:
                # A merged cell's origin owns the text; covered cells add none.
                yield "\t".join(cell.text for cell in row.cells if not cell.is_spanned)
        elif shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if text:
                    yield text


def docx_blocks(file_path):
    """Paragraphs and table rows of a .docx in body order, with python-docx when it is installed."""
    try:
        from docx import Document
    except ImportError:
        return _plain_docx_body(file_path)
    return list(iter_docx_body_text(Document(file_path)))


def pptx_slides(file_path):
    """Lines of text per slide of a .pptx, with python-pptx when it is installed."""
    try:
        from pptx import Presentation
    except ImportError:
        return pptx_slides_plain(file_path)
    return [list(iter_pptx_shape_text(slide.shapes)) for slide in Presentation(file_path).slides]

def _sheet_rows(cached_sheet, formula_sheet):
    for cached_row, formula_row in zip(cached_sheet.iter_rows(), formula_sheet.iter_rows()):
        values = []
        for cached, source in zip(cached_row, formula_row):
            value = cached.value
            if value is None and source.data_type == "f":
                # openpyxl's array formulas store their source in .text.
                formula = getattr(source.value, "text", source.value)
                value = f"[Formula: {formula} (not calculated)]"
            values.append(str(value) if value is not None else "")
        yield values


@contextmanager
def spreadsheet_sheets(file_path, load_workbook):
    """Yield (sheet name, rows) pairs and close both read-only views on exit.

    Cached values win, including 0/False. A formula with no cached result is
    shown as its source, marked unevaluated; nothing is recalculated.
    """
    cached = load_workbook(file_path, read_only=True, data_only=True)
    try:
        formulas = load_workbook(file_path, read_only=True, data_only=False)
        try:
            # Some spreadsheet producers leave stale used-range metadata. In
            # read-only mode those bounds silently clip real XML cells, so let
            # both views stream their actual rows/columns before pairing them.
            for sheet in cached.worksheets:
                sheet.reset_dimensions()
                formulas[sheet.title].reset_dimensions()
            yield ((sheet.title, _sheet_rows(sheet, formulas[sheet.title])) for sheet in cached.worksheets)
        finally:
            formulas.close()
    finally:
        cached.close()
