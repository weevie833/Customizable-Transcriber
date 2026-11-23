"""Regression tests for Excel sheet-name safety -- see docs/DESIGN.md's
"Security hardening history" section on the sheet-name-injection finding
this closes. Reproduced before the
fix: combine_language_xlsx("battesimi", [("Latin/Italian", rows)]) produced
a workbook openpyxl itself refuses to open (`ValueError: Invalid character /
found in sheet title`)."""

from __future__ import annotations

import base64
import io

import openpyxl
import pytest

from xls_conversion.ai_parser import combine_language_xlsx
from xls_conversion.spreadsheet_export import sanitize_sheet_name


@pytest.mark.parametrize(
    "raw,forbidden_chars",
    [
        ("Latin/Italian", "/"),
        ("Latin\\Italian", "\\"),
        ("Sicilian [dialect]", "[]"),
        ("Question? Mark", "?"),
        ("Star*Wildcard", "*"),
        ("Colon:Here", ":"),
    ],
)
def test_forbidden_characters_are_stripped(raw, forbidden_chars):
    cleaned = sanitize_sheet_name(raw)
    for char in forbidden_chars:
        assert char not in cleaned


def test_leading_and_trailing_apostrophes_are_stripped():
    assert not sanitize_sheet_name("'Quoted'").startswith("'")
    assert not sanitize_sheet_name("'Quoted'").endswith("'")


def test_name_is_truncated_to_excel_limit():
    long_name = "A" * 50
    assert len(sanitize_sheet_name(long_name)) <= 31


def test_duplicate_names_are_deduplicated_case_insensitively():
    first = sanitize_sheet_name("Battesimi")
    second = sanitize_sheet_name("Battesimi", used=[first])
    third = sanitize_sheet_name("BATTESIMI", used=[first, second])
    assert len({first, second, third}) == 3


def test_deduplication_suffix_still_respects_length_limit():
    used = [sanitize_sheet_name("A" * 31)]
    candidate = sanitize_sheet_name("A" * 31, used=used)
    assert len(candidate) <= 31
    assert candidate not in used


def test_empty_or_fully_forbidden_name_gets_a_fallback():
    assert sanitize_sheet_name("") == "Sheet"
    assert sanitize_sheet_name("///???") == "Sheet"


def test_combine_language_xlsx_with_slash_in_language_is_openpyxl_readable():
    """End-to-end reproduction of the exact reported failure."""
    rows = [{"field": "value"}]
    xlsx_b64 = combine_language_xlsx(
        "battesimi",
        [("Latin/Italian", rows), ("Latin/Italian", rows)],
    )
    workbook_bytes = base64.b64decode(xlsx_b64)
    workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes))
    assert len(workbook.sheetnames) == 2
    for name in workbook.sheetnames:
        assert "/" not in name


# reviews/CODEX_REVIEW_8.md M-12: a quote, ampersand or non-ASCII label in a
# sheet name must still produce a readable workbook.
import io as _io

import openpyxl as _openpyxl
import pytest as _pytest

from xls_conversion.spreadsheet_export import SheetSpec as _SheetSpec
from xls_conversion.spreadsheet_export import rows_to_xlsx_multi as _rows_to_xlsx_multi


@_pytest.mark.parametrize("title", ['Latin "A"', "Latin & Italian", "Latino 'B' \"C\"", "Italiano àèì"])
def test_quoted_and_special_sheet_titles_round_trip(title):
    spec = _SheetSpec(group_headers=["G"], column_headers=["C"], fields=["c"], rows=[{"c": "v"}],
                      sheet_name=title, numeric_columns=frozenset(), padded_column=None, column_widths=[10])
    workbook = _openpyxl.load_workbook(_io.BytesIO(_rows_to_xlsx_multi([spec])))
    assert workbook.sheetnames[0].replace("'", "") == title.replace("'", "").strip()
