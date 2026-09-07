from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

import openpyxl
from rapidfuzz import fuzz

from xls_conversion.ai_parser import RECORD_TYPES, RecordTypeConfig

Row = dict[str, str]

# Zip-bomb defenses for an uploaded .xlsx -- an XLSX is a zip archive of XML
# parts (worksheets, sharedStrings.xml, styles.xml, ...), and a tiny,
# deliberately-repetitive entry can decompress to gigabytes before openpyxl
# ever gets a chance to reject anything on content grounds. Same technique
# and reasoning as app.py's extract_docx_text() DOCX guard -- ZipInfo.file_size
# is the archive's own *declared* uncompressed size, checked before ever
# calling .read() or handing the bytes to openpyxl.load_workbook() (which
# decompresses every part up front, even in read_only mode). Verified against
# a real crafted file: a ~20KB zip entry that declared, and unguarded would
# have produced, a ~20MB decompressed XML payload.
_MAX_ZIP_ENTRY_BYTES = 50_000_000  # 50MB -- generous for any one part of a legitimate index spreadsheet
_MAX_ZIP_TOTAL_BYTES = 100_000_000  # 100MB decompressed, summed across every part in the archive

# Caps a worksheet's own claimed dimensions. openpyxl trusts a sheet's own
# <dimension> declaration in its XML, so a workbook can claim an enormous
# row/column extent (up to Excel's own A1:XFD1048576 ceiling) for almost no
# bytes -- passing the zip-size check above with room to spare while still
# costing real time/memory to iterate. No real record-type template this app
# ships even approaches these counts.
_MAX_WORKSHEET_ROWS = 100_000
_MAX_WORKSHEET_COLUMNS = 200

# Below this score (rapidfuzz's 0-100 token_sort_ratio), suggest_mapping()
# leaves a field unmapped rather than guessing wrong -- an unmapped field
# just reads as blank for every row (see read_rows()), which is safer than
# silently pairing two unrelated columns.
_SUGGESTION_THRESHOLD = 60.0

# A cell whose number_format is all zeros ("000", "00", ...) is a
# zero-padded column (Image #) -- openpyxl's own .value for such a cell is
# the raw int (5), not the padded display text ("005"), because number
# formats are display-only. Reconstructed in _cell_text() below; this
# regex identifies that specific format shape.
_ZERO_PAD_FORMAT = re.compile(r"^0+$")


def _normalize_header(value: object) -> str:
    """Whitespace-collapsed, case-insensitive comparison key for header text."""
    return " ".join(str(value or "").split()).casefold()


def _cell_text(cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return str(value)
        number_format = str(cell.number_format or "")
        if _ZERO_PAD_FORMAT.match(number_format):
            return str(int(value)).zfill(len(number_format))
        return str(int(value))
    return str(value).strip()


def _trim_trailing_blanks(row: list[str]) -> list[str]:
    trimmed = list(row)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def _check_zip_bomb_safety(file_bytes: bytes) -> None:
    """Rejects an upload whose declared (pre-decompression) size is already
    unreasonable, before any part of it is decompressed -- see the
    _MAX_ZIP_*_BYTES comment above for why this has to happen at the zip
    layer rather than after openpyxl has already expanded the content."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            total = 0
            for info in archive.infolist():
                if info.file_size > _MAX_ZIP_ENTRY_BYTES:
                    raise RuntimeError("This file's content is too large to process.")
                total += info.file_size
                if total > _MAX_ZIP_TOTAL_BYTES:
                    raise RuntimeError("This file's content is too large to process.")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Could not read this file as an XLSX workbook.") from exc


def _open_workbook(file_bytes: bytes):
    # read_only=True was tried and deliberately not adopted here: it makes
    # openpyxl trust a worksheet's own <dimension> XML tag for max_row/
    # max_column rather than recalculating from the sheet's real cell data --
    # and this app's own hand-rolled XLSX writer (spreadsheet_export.py)
    # never emits a <dimension> tag at all, so every file this app has ever
    # generated came back with max_row/max_column as None under read_only
    # mode, breaking round-trip reads of this app's own output (confirmed:
    # reproduced against a real spreadsheet_export.py-written file). Plain
    # (non-read-only) mode instead recomputes real bounds from actual
    # populated cells regardless of what a sheet's own <dimension> tag
    # claims -- confirmed against a crafted file declaring dimension
    # "A1:XFD1048576" with only one real cell: max_row/max_column came back
    # 1/1, not 1048576/16384 -- so the caps below still do real work without
    # needing read_only mode to get there.
    _check_zip_bomb_safety(file_bytes)
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as exc:  # openpyxl raises several distinct exception types
        raise RuntimeError("Could not read this file as an XLSX workbook.") from exc
    for worksheet in workbook.worksheets:
        if worksheet.max_row and worksheet.max_row > _MAX_WORKSHEET_ROWS:
            raise RuntimeError("This file has more rows than this tool supports.")
        if worksheet.max_column and worksheet.max_column > _MAX_WORKSHEET_COLUMNS:
            raise RuntimeError("This file has more columns than this tool supports.")
    return workbook


@dataclass(frozen=True)
class WorksheetInfo:
    """One worksheet's header rows, as read for record-type detection and
    (when detection fails) for the manual column-mapping UI."""

    name: str
    header_row1: list[str]
    header_row2: list[str]
    row_count: int  # data rows below the two header rows


def list_worksheets(file_bytes: bytes) -> list[WorksheetInfo]:
    workbook = _open_workbook(file_bytes)
    infos: list[WorksheetInfo] = []
    for worksheet in workbook.worksheets:
        if worksheet.max_row < 3 or worksheet.max_column < 1:
            continue  # no data rows below a 2-row header -- not a candidate sheet
        width = worksheet.max_column
        header_row1 = [_cell_text(worksheet.cell(row=1, column=col)) for col in range(1, width + 1)]
        header_row2 = [_cell_text(worksheet.cell(row=2, column=col)) for col in range(1, width + 1)]
        infos.append(
            WorksheetInfo(
                name=worksheet.title,
                header_row1=header_row1,
                header_row2=header_row2,
                row_count=worksheet.max_row - 2,
            )
        )
    return infos


def detect_schema(header_row1: list[str], header_row2: list[str]) -> tuple[str, dict[str, int]] | None:
    """Exact (whitespace/case-tolerant) match against one of the 6 known
    record-type schemas. Trims trailing blank columns first, since a sheet
    re-saved by a different tool can carry extra empty trailing columns
    with no content difference. Returns (record_type, field -> column
    index) on a match; None if no schema matches, or more than one would
    (ambiguous -- treated the same as no match, since a caller can't safely
    pick a schema an unmatched file didn't actually declare)."""
    actual1 = _trim_trailing_blanks([_normalize_header(v) for v in header_row1])
    actual2 = _trim_trailing_blanks([_normalize_header(v) for v in header_row2])
    matches: list[str] = []
    for record_type, config in RECORD_TYPES.items():
        expected1 = [_normalize_header(v) for v in config.group_headers]
        expected2 = [_normalize_header(v) for v in config.column_headers]
        if actual1 == expected1 and actual2 == expected2:
            matches.append(record_type)
    if len(matches) != 1:
        return None
    record_type = matches[0]
    fields = RECORD_TYPES[record_type].fields
    return record_type, {field: index for index, field in enumerate(fields)}


def suggest_mapping(
    record_type: str, header_row1: list[str], header_row2: list[str]
) -> dict[str, int | None]:
    """Best-guess field -> column-index mapping for a sheet that
    detect_schema() couldn't place automatically, once the user has picked
    which of the 6 record types this file actually is. Scores every real
    column's combined (group, column) header text against every field's own
    label -- matching on the combined text, not the column header alone,
    since a column header like "Given Name" repeats across groups (Groom vs
    Bride in Matrimoni) and only the group row disambiguates which is
    which.

    Assignment is global-best-first (score every field/column pair, then
    take pairs in descending score order, skipping a field or column once
    either side is already claimed) rather than resolving one field at a
    time in a fixed order -- resolving field-by-field let an earlier field
    with only a mediocre match grab a column that a later field actually
    matched near-perfectly (reproduced: "groom_father_given_name", with no
    good match of its own, stole the "Bride Given Name" column out from
    under "bride_given_name" simply by being scored first). Global-best-
    first locks in every confident match before any ambiguous one is
    considered. A field left with no sufficiently similar, still-available
    column maps to None -- left for the user to fill in by hand rather than
    guessed."""
    config = RECORD_TYPES[record_type]
    width = max(len(header_row1), len(header_row2))
    combined_actual = [
        _normalize_header(header_row1[i] if i < len(header_row1) else "")
        + " "
        + _normalize_header(header_row2[i] if i < len(header_row2) else "")
        for i in range(width)
    ]

    candidates: list[tuple[float, str, int]] = []
    for field, group_label, column_label in zip(config.fields, config.group_headers, config.column_headers):
        target = f"{_normalize_header(group_label)} {_normalize_header(column_label)}".strip()
        for index, actual in enumerate(combined_actual):
            if not actual.strip():
                continue
            score = fuzz.token_sort_ratio(target, actual)
            if score >= _SUGGESTION_THRESHOLD:
                candidates.append((score, field, index))
    candidates.sort(key=lambda item: item[0], reverse=True)

    mapping: dict[str, int | None] = {field: None for field in config.fields}
    used_columns: set[int] = set()
    assigned_fields: set[str] = set()
    for _score, field, index in candidates:
        if field in assigned_fields or index in used_columns:
            continue
        mapping[field] = index
        used_columns.add(index)
        assigned_fields.add(field)
    return mapping


def read_rows(
    file_bytes: bytes,
    sheet_name: str,
    config: RecordTypeConfig,
    field_to_column: dict[str, int],
) -> list[dict[str, str]]:
    """Extract data rows (everything from row 3 down) as {field: text}
    dicts, using an explicit column mapping -- the same function whether
    that mapping came from detect_schema()'s exact match or a
    user-confirmed suggest_mapping() result. A field with no mapped column
    (field_to_column.get(field) is None) reads as "" for every row rather
    than raising -- many fields are legitimately blank in real registers
    anyway, and align.py's own locator fallback already handles a blank
    locator field explicitly."""
    workbook = _open_workbook(file_bytes)
    if sheet_name not in workbook.sheetnames:
        raise RuntimeError(f'Worksheet "{sheet_name}" was not found in this file.')
    worksheet = workbook[sheet_name]
    rows: list[dict[str, str]] = []
    for row_index in range(3, worksheet.max_row + 1):
        row: dict[str, str] = {}
        has_value = False
        for field in config.fields:
            column_index = field_to_column.get(field)
            if column_index is None:
                row[field] = ""
                continue
            text = _cell_text(worksheet.cell(row=row_index, column=column_index + 1))
            if text:
                has_value = True
            row[field] = text
        if has_value:
            rows.append(row)
    return rows


class NeedsMapping(Exception):
    """Raised by resolve_index_file() when a file's headers don't match any
    of the 6 known schemas -- carries what a mapping UI needs to ask the
    user for a record type and confirm/adjust a suggested column mapping,
    rather than being just an error message."""

    def __init__(self, worksheets: list[WorksheetInfo]):
        super().__init__("This file's columns don't match any of the 6 known record-type layouts.")
        self.worksheets = worksheets


def resolve_index_file(
    file_bytes: bytes, explicit_mapping: dict[str, object] | None = None
) -> tuple[RecordTypeConfig, list[Row], str]:
    """One call that turns raw uploaded file bytes into (config, rows,
    sheet_name actually used) -- the orchestration every caller of this
    module actually wants, built from list_worksheets()/detect_schema()/
    read_rows() above.

    `explicit_mapping`, when given, is `{"record_type": ..., "sheet_name":
    ..., "mapping": {field: column_index_or_None}}` -- the result of a user
    confirming (and possibly editing) a suggest_mapping() suggestion for a
    file that failed auto-detection on a prior call. Supplying it skips
    auto-detection entirely and reads directly from the named sheet with
    that mapping.

    Without one, every worksheet is tried against detect_schema() in file
    order; the first exact match wins (the overwhelmingly common case is
    one relevant data sheet per uploaded file, even when the workbook also
    carries other tabs like a Scorecard or a Compare-<model> analysis
    sheet, which detect_schema() will simply never match). If nothing
    matches, raises NeedsMapping with every worksheet's own headers, for a
    caller to hand to suggest_mapping() once the user has picked which of
    the 6 record types this file actually is.
    """
    worksheets = list_worksheets(file_bytes)

    if explicit_mapping is not None:
        record_type = str(explicit_mapping["record_type"])
        sheet_name = str(explicit_mapping["sheet_name"])
        config = RECORD_TYPES[record_type]
        raw_mapping = explicit_mapping.get("mapping") or {}
        field_to_column = {
            field: int(column) for field, column in raw_mapping.items() if column is not None and field in config.fields
        }
        rows = read_rows(file_bytes, sheet_name, config, field_to_column)
        return config, rows, sheet_name

    for worksheet in worksheets:
        detected = detect_schema(worksheet.header_row1, worksheet.header_row2)
        if detected is None:
            continue
        record_type, field_to_column = detected
        config = RECORD_TYPES[record_type]
        rows = read_rows(file_bytes, worksheet.name, config, field_to_column)
        return config, rows, worksheet.name

    raise NeedsMapping(worksheets)
