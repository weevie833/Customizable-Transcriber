"""Generic "structured report" DOCX builder -- bold headings, prose
paragraphs, and bordered tables assembled into a minimal word/document.xml,
with no styles.xml part to resolve against (every run/table sets its own
formatting explicitly). Split out of test_mode/report_docx.py once
index_compare/report_docx.py needed the exact same building blocks for its
own downloadable report, following this app's existing docx_package.py
precedent: a shared leaf module neither report writer has to import from
the other. Both writers still layer their own report-specific content
(headings, tables, explanatory prose) on top of what lives here.

Separate from docx_package.py itself, which only holds the fixed
package-level XML parts (`[Content_Types].xml`, `_rels/.rels`) and the
XML-illegal-character sanitizer -- this module is the one layer up: actual
paragraph/table/document construction. assemble_docx_bytes() is the seam
between the two, wrapping the package-level parts around one writer's own
word/document.xml bytes."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from docx_package import content_types_xml, root_rels_xml, strip_xml_illegal_chars

_REPORT_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _report_run(text: str, bold: bool = False) -> ElementTree.Element:
    r = ElementTree.Element(f"{{{_REPORT_NS}}}r")
    if bold:
        r_pr = ElementTree.SubElement(r, f"{{{_REPORT_NS}}}rPr")
        ElementTree.SubElement(r_pr, f"{{{_REPORT_NS}}}b")
    t = ElementTree.SubElement(r, f"{{{_REPORT_NS}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    # See docx_package.strip_xml_illegal_chars(): ElementTree's serializer
    # escapes "<"/">"/"&" but not a raw control character, which isn't
    # well-formed XML no matter how it's escaped.
    t.text = strip_xml_illegal_chars(text)
    return r


def report_paragraph(
    text: str,
    bold: bool = False,
    size_half_points: int | None = None,
    space_after_twips: int = 200,
) -> ElementTree.Element:
    p = ElementTree.Element(f"{{{_REPORT_NS}}}p")
    p_pr = ElementTree.SubElement(p, f"{{{_REPORT_NS}}}pPr")
    spacing = ElementTree.SubElement(p_pr, f"{{{_REPORT_NS}}}spacing")
    spacing.set(f"{{{_REPORT_NS}}}after", str(space_after_twips))
    if bold or size_half_points:
        r_pr_default = ElementTree.SubElement(p_pr, f"{{{_REPORT_NS}}}rPr")
        if bold:
            ElementTree.SubElement(r_pr_default, f"{{{_REPORT_NS}}}b")
        if size_half_points:
            sz = ElementTree.SubElement(r_pr_default, f"{{{_REPORT_NS}}}sz")
            sz.set(f"{{{_REPORT_NS}}}val", str(size_half_points))
    run = _report_run(text, bold=bold)
    if size_half_points:
        r_pr = run.find(f"{{{_REPORT_NS}}}rPr")
        if r_pr is None:
            r_pr = ElementTree.Element(f"{{{_REPORT_NS}}}rPr")
            run.insert(0, r_pr)
        sz = ElementTree.SubElement(r_pr, f"{{{_REPORT_NS}}}sz")
        sz.set(f"{{{_REPORT_NS}}}val", str(size_half_points))
    p.append(run)
    return p


def report_table(rows: list[list[str]]) -> ElementTree.Element:
    """First row renders as a bold, shaded header. Every cell/border is drawn
    explicitly (no named table style) since this document has no styles.xml
    part for a style reference to resolve against."""
    ns = _REPORT_NS
    tbl = ElementTree.Element(f"{{{ns}}}tbl")
    tbl_pr = ElementTree.SubElement(tbl, f"{{{ns}}}tblPr")
    tbl_w = ElementTree.SubElement(tbl_pr, f"{{{ns}}}tblW")
    tbl_w.set(f"{{{ns}}}w", "0")
    tbl_w.set(f"{{{ns}}}type", "auto")
    borders = ElementTree.SubElement(tbl_pr, f"{{{ns}}}tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = ElementTree.SubElement(borders, f"{{{ns}}}{edge}")
        border.set(f"{{{ns}}}val", "single")
        border.set(f"{{{ns}}}sz", "4")
        border.set(f"{{{ns}}}space", "0")
        border.set(f"{{{ns}}}color", "999999")
    column_count = max((len(row) for row in rows), default=0)
    grid = ElementTree.SubElement(tbl, f"{{{ns}}}tblGrid")
    for _ in range(column_count):
        ElementTree.SubElement(grid, f"{{{ns}}}gridCol")
    for row_index, row in enumerate(rows):
        is_header = row_index == 0
        tr = ElementTree.SubElement(tbl, f"{{{ns}}}tr")
        for cell_text in row:
            tc = ElementTree.SubElement(tr, f"{{{ns}}}tc")
            tc_pr = ElementTree.SubElement(tc, f"{{{ns}}}tcPr")
            if is_header:
                shd = ElementTree.SubElement(tc_pr, f"{{{ns}}}shd")
                shd.set(f"{{{ns}}}val", "clear")
                shd.set(f"{{{ns}}}fill", "E7E2D8")
            tc_margins = ElementTree.SubElement(tc_pr, f"{{{ns}}}tcMar")
            for side in ("top", "left", "bottom", "right"):
                margin = ElementTree.SubElement(tc_margins, f"{{{ns}}}{side}")
                margin.set(f"{{{ns}}}w", "100")
                margin.set(f"{{{ns}}}type", "dxa")
            tc.append(report_paragraph(cell_text, bold=is_header, space_after_twips=0))
        # pad short rows so the grid stays rectangular
        for _ in range(column_count - len(row)):
            tc = ElementTree.SubElement(tr, f"{{{ns}}}tc")
            ElementTree.SubElement(tc, f"{{{ns}}}tcPr")
            tc.append(report_paragraph("", space_after_twips=0))
    return tbl


def report_document_xml(elements: list[ElementTree.Element]) -> bytes:
    ns = _REPORT_NS
    ElementTree.register_namespace("w", ns)
    document = ElementTree.Element(f"{{{ns}}}document")
    body = ElementTree.SubElement(document, f"{{{ns}}}body")
    for element in elements:
        body.append(element)
    sect_pr = ElementTree.SubElement(body, f"{{{ns}}}sectPr")
    pg_sz = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgSz")
    pg_sz.set(f"{{{ns}}}w", "12240")
    pg_sz.set(f"{{{ns}}}h", "15840")
    pg_mar = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgMar")
    pg_mar.set(f"{{{ns}}}top", "1440")
    pg_mar.set(f"{{{ns}}}right", "1440")
    pg_mar.set(f"{{{ns}}}bottom", "1440")
    pg_mar.set(f"{{{ns}}}left", "1440")
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def assemble_docx_bytes(document_xml_bytes: bytes) -> bytes:
    """Wraps one writer's own word/document.xml bytes with the fixed
    package-level parts (docx_package.py) into a complete .docx file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("[Content_Types].xml", content_types_xml())
        output.writestr("_rels/.rels", root_rels_xml())
        output.writestr("word/document.xml", document_xml_bytes)
    return buffer.getvalue()
