"""Regression tests for index_compare/reader.py's ingestion-safety guards
against a malicious .xlsx upload: an oversized declared (pre-decompression)
zip entry or total, and an implausibly large worksheet dimension. Same
technique and reasoning as tests/test_docx_security.py's DOCX guards --
build a real, highly-compressible payload just over each cap rather than
faking the check, since the guard has to work on declared/actual size, not
on trusting the caller."""

from __future__ import annotations

import io
import zipfile

import pytest

from index_compare import reader
from xls_conversion.ai_parser import RECORD_TYPES
from xls_conversion.spreadsheet_export import rows_to_xlsx

MATRIMONI = RECORD_TYPES["matrimoni"]


def _matrimoni_xlsx() -> bytes:
    row = {field: "" for field in MATRIMONI.fields}
    row.update({"page_number": "34", "groom_given_name": "Giuseppe"})
    return rows_to_xlsx(
        MATRIMONI.group_headers,
        MATRIMONI.column_headers,
        MATRIMONI.fields,
        [row],
        MATRIMONI.sheet_name,
        numeric_columns=MATRIMONI.numeric_columns,
        padded_column=MATRIMONI.padded_column,
        column_widths=list(MATRIMONI.column_widths),
    )


def _zip_with_one_entry(entry_bytes: bytes, name: str = "xl/worksheets/sheet1.xml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, entry_bytes)
    return buffer.getvalue()


def test_legitimate_small_file_is_not_rejected_by_the_size_guards():
    infos = reader.list_worksheets(_matrimoni_xlsx())
    assert len(infos) == 1


def test_not_a_zip_file_is_rejected():
    with pytest.raises(RuntimeError):
        reader.list_worksheets(b"this is not a zip file at all")


def test_oversized_declared_zip_entry_is_rejected_before_decompression():
    """A zip entry whose *declared* (ZipInfo.file_size) uncompressed size
    exceeds _MAX_ZIP_ENTRY_BYTES must be rejected -- and it has to be a real
    declared size, not something the check trusts the caller about, or a
    highly-compressible repetitive payload (a real "zip bomb" shape) defeats
    it. This payload compresses to a few KB but declares itself larger than
    the cap."""
    huge_repetitive = b"<a>" + b"x" * 1024 + b"</a>" * (reader._MAX_ZIP_ENTRY_BYTES // 1024 + 1)
    payload = _zip_with_one_entry(huge_repetitive)
    with pytest.raises(RuntimeError):
        reader.list_worksheets(payload)


def test_total_declared_zip_size_across_entries_is_capped(monkeypatch):
    """No single entry needs to be huge -- several entries that each pass
    the per-entry cap but sum past the total cap must still be rejected."""
    monkeypatch.setattr(reader, "_MAX_ZIP_TOTAL_BYTES", 10_000)
    monkeypatch.setattr(reader, "_MAX_ZIP_ENTRY_BYTES", 6_000)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("part1.xml", b"x" * 5_000)
        archive.writestr("part2.xml", b"x" * 5_000)
        archive.writestr("part3.xml", b"x" * 5_000)  # 15,000 total > 10,000 cap, each part under 6,000
    with pytest.raises(RuntimeError):
        reader.list_worksheets(buffer.getvalue())


def test_worksheet_row_count_over_the_cap_is_rejected(monkeypatch):
    monkeypatch.setattr(reader, "_MAX_WORKSHEET_ROWS", 0)
    with pytest.raises(RuntimeError):
        reader.list_worksheets(_matrimoni_xlsx())


def test_worksheet_column_count_over_the_cap_is_rejected(monkeypatch):
    monkeypatch.setattr(reader, "_MAX_WORKSHEET_COLUMNS", 0)
    with pytest.raises(RuntimeError):
        reader.list_worksheets(_matrimoni_xlsx())
