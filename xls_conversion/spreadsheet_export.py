from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from xml.sax.saxutils import escape


NUMERIC_BODY_COLUMNS = frozenset({2, 3, 5, 6, 8})


def rows_to_csv(
    group_headers: Sequence[str],
    column_headers: Sequence[str],
    fields: Sequence[str],
    rows: Iterable[dict[str, str]],
) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(group_headers)
    writer.writerow(column_headers)
    for row in rows:
        writer.writerow([row.get(field, "") for field in fields])
    return "\ufeff" + output.getvalue()


def rows_to_xlsx(
    group_headers: Sequence[str],
    column_headers: Sequence[str],
    fields: Sequence[str],
    rows: Iterable[dict[str, str]],
    sheet_name: str,
) -> bytes:
    data_rows = [[row.get(field, "") for field in fields] for row in rows]
    all_rows = [list(group_headers), list(column_headers), *data_rows]
    worksheet_xml = _worksheet_xml(all_rows)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "docProps/app.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Customizable Transcription Interface</Application>
</Properties>""",
        )
        archive.writestr(
            "docProps/core.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Customizable Transcription Interface</dc:creator>
</cp:coreProperties>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        archive.writestr("xl/styles.xml", _styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return output.getvalue()


def _worksheet_xml(rows: Sequence[Sequence[str]]) -> str:
    row_xml: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        style = 1 if row_number == 1 else 2 if row_number == 2 else 0
        cells = "".join(
            _worksheet_cell(row_number, column_number, value, style)
            for column_number, value in enumerate(row, start=1)
        )
        height = ' ht="24" customHeight="1"' if row_number <= 2 else ""
        row_xml.append(f'<row r="{row_number}"{height}>{cells}</row>')

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>
      <selection pane="bottomLeft" activeCell="A3" sqref="A3"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="2" width="12" customWidth="1"/>
    <col min="3" max="8" width="11" customWidth="1"/>
    <col min="9" max="10" width="19" customWidth="1"/>
    <col min="11" max="11" width="11" customWidth="1"/>
    <col min="12" max="13" width="19" customWidth="1"/>
    <col min="14" max="14" width="32" customWidth="1"/>
    <col min="15" max="16" width="19" customWidth="1"/>
    <col min="17" max="17" width="32" customWidth="1"/>
    <col min="18" max="18" width="34" customWidth="1"/>
    <col min="19" max="19" width="26" customWidth="1"/>
    <col min="20" max="20" width="42" customWidth="1"/>
  </cols>
  <sheetData>{''.join(row_xml)}</sheetData>
</worksheet>"""


def _worksheet_cell(row: int, column: int, value: object, style: int) -> str:
    reference = _cell_reference(row, column)
    if row >= 3 and column in NUMERIC_BODY_COLUMNS:
        numeric_style = 3 if column == 2 else 4
        return _numeric_cell(reference, value, numeric_style)
    return _inline_string_cell(reference, value, style)


def _numeric_cell(reference: str, value: object, style: int) -> str:
    text = str(value or "").strip()
    if not text:
        return f'<c r="{reference}" s="{style}"/>'
    if re.fullmatch(r"[+-]?\d+", text):
        return f'<c r="{reference}" s="{style}"><v>{int(text)}</v></c>'
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)", text):
        return f'<c r="{reference}" s="{style}"><v>{text}</v></c>'
    return _inline_string_cell(reference, text, style)


def _inline_string_cell(reference: str, value: object, style: int) -> str:
    text = str(value or "")
    preserve = ' xml:space="preserve"' if text != text.strip() else ""
    return (
        f'<c r="{reference}" t="inlineStr" s="{style}">'
        f"<is><t{preserve}>{escape(text)}</t></is></c>"
    )


def _cell_reference(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1">
    <numFmt numFmtId="164" formatCode="000"/>
  </numFmts>
  <fonts count="2">
    <font><sz val="11"/><name val="Aptos"/></font>
    <font><b/><color rgb="FF000000"/><sz val="11"/><name val="Aptos"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="5">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center"/>
    </xf>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
