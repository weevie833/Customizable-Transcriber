"""CSV export must not hand a spreadsheet a cell it will evaluate as a formula
(reviews/CODEX_REVIEW.md M-1). XLSX is safe by construction (inline strings)."""
import csv
import io

import pytest

from xls_conversion.spreadsheet_export import _csv_safe_cell, rows_to_csv


@pytest.mark.parametrize("value", [
    "=1+1", "+1", "-1", "@SUM(A1)",
    "\t=1+1", "\r=1+1", "\n=1+1", "  =1+1", " =1+1",
    "\tplain text", "＝HYPERLINK(\"x\")",
])
def test_formula_like_cells_are_prefixed_and_otherwise_unchanged(value):
    assert _csv_safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", [
    "", "Giuseppe de Natale", "1753", "0034", "di Bella, Maria",
    "He said \"=\" once", "line one\nline two", "a=b", " Rosa",
])
def test_ordinary_text_is_untouched(value):
    assert _csv_safe_cell(value) == value


def test_round_trip_keeps_quotes_delimiters_and_newlines():
    rows = [
        {"a": "\t=cmd|' /C calc'!A0", "b": 'x, "quoted"\nsecond line'},
        {"a": "Maria", "b": "  -2+3"},
    ]
    text = rows_to_csv(["G", "G"], ["A", "B"], ["a", "b"], rows)
    parsed = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert parsed[2] == ["'\t=cmd|' /C calc'!A0", 'x, "quoted"\nsecond line']
    assert parsed[3] == ["Maria", "'  -2+3"]
