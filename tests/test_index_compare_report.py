"""Regression tests for index_compare/report_docx.py -- the downloadable
DOCX report, rebuilt to distill statistical accuracy (a ranking table,
field-group error rates, aggregate category counts) rather than the
per-candidate Compare-<label> diff tabs the earlier XLSX version had. See
that module's own docstring for why the per-row detail was dropped."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest
from xls_conversion.ai_parser import RECORD_TYPES

from index_compare.report_docx import build_index_compare_report
from index_compare.scoring import compare_indexes

MATRIMONI = RECORD_TYPES["matrimoni"]
_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _row(**fields) -> dict[str, str]:
    row = {field: "" for field in MATRIMONI.fields}
    row.update(fields)
    return row


def _paragraph_text(p: ElementTree.Element) -> str:
    return "".join(t.text or "" for t in p.findall(f".//{_NS}t"))


def _blocks(data: bytes) -> list[tuple[str, object]]:
    """Every direct child of the document body, in order: ("p", text) for a
    paragraph, ("tbl", rows) for a table (each row a list of cell strings)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{_NS}body")
    blocks: list[tuple[str, object]] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            blocks.append(("p", _paragraph_text(child)))
        elif tag == "tbl":
            rows = [
                [_paragraph_text(tc.find(f"{_NS}p")) for tc in tr.findall(f"{_NS}tc")]
                for tr in child.findall(f"{_NS}tr")
            ]
            blocks.append(("tbl", rows))
    return blocks


def _all_text(data: bytes) -> str:
    return " ".join(text for kind, text in _blocks(data) if kind == "p") + " " + " ".join(
        " ".join(cell for row in rows for cell in row) for kind, rows in _blocks(data) if kind == "tbl"
    )


def _table_after(data: bytes, heading_contains: str) -> list[list[str]]:
    blocks = _blocks(data)
    for index, (kind, value) in enumerate(blocks):
        if kind == "p" and heading_contains in value:
            for later_kind, later_value in blocks[index + 1 :]:
                if later_kind == "tbl":
                    return later_value
    raise AssertionError(f"No table found after a heading containing {heading_contains!r}")


def test_report_is_a_real_docx_and_has_no_title_at_top():
    truth = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo")]
    candidate = [_row(page_number="34", groom_given_name="Marco", bride_last_name="de Franco")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG")
    assert data[:2] == b"PK"
    blocks = _blocks(data)
    assert blocks[0] == ("p", "Index Comparison Report")


def test_report_has_no_per_candidate_diff_table():
    # This is the central behavior change: no "Compare Gemini"/"Compare
    # Claude" section listing individual field differences row by row.
    truth = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo")]
    gemini = [_row(page_number="34", groom_given_name="Marco", bride_last_name="de Franco")]
    claude = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", gemini), ("Claude", claude)])
    data = build_index_compare_report(result, "ORIG")
    text = _all_text(data)
    assert "Compare Gemini" not in text
    assert "Compare Claude" not in text
    assert "Marco" not in text  # a candidate's actual field value never appears
    assert "AI rationale" not in text


def test_ranking_table_ranks_candidates_by_error_rate_best_first():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    close = [_row(page_number="34", groom_given_name="Giuseppe")]  # exact match -- 0% error
    far = [_row(page_number="34", groom_given_name="Someone Else Entirely")]  # high error
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Far", far), ("Close", close)])
    data = build_index_compare_report(result, "ORIG")
    table = _table_after(data, "Character Error Rate")
    assert table[0] == ["Rank", "Candidate", "Error rate (CER)", "Est. character edits", "Reference characters"]
    assert table[1][:2] == ["1", "Close"]
    assert table[2][:2] == ["2", "Far"]


def test_shows_na_and_a_warning_for_a_zero_matched_candidate_never_a_negative_number():
    truth = [_row(page_number="34", groom_given_name="Giuseppe", notes="")]
    unrelated = [_row(page_number="99", groom_given_name="Nobody")]  # no locator overlap -- 0 matched
    overwritten_blank = [_row(page_number="34", groom_given_name="Giuseppe", notes="a long note truth lacks")]
    result = compare_indexes(
        MATRIMONI, ("ORIG", truth), [("ZeroMatch", unrelated), ("Overwrite", overwritten_blank)]
    )
    data = build_index_compare_report(result, "ORIG")
    text = _all_text(data)
    assert "N/A (0 matched)" in text
    assert "⚠" in text and "ZeroMatch" in text


def test_field_group_error_rate_table_present():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Marco")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG")
    table = _table_after(data, "Field-Group Error Rate")
    assert table[0] == ["Group", "Gemini"]
    assert any(row[0] == "Groom" for row in table[1:])


def test_category_counts_are_aggregate_totals_not_per_row():
    truth = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo")]
    candidate = [_row(page_number="34", groom_given_name="Marco", bride_last_name="Someone Totally Different")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG")
    table = _table_after(data, "Category Counts")
    assert table[0] == ["Category", "Gemini"]
    rows_by_label = {row[0]: row[1] for row in table[1:]}
    assert rows_by_label["Different person/value"] == "2"


def test_excluded_fields_note_names_real_column_labels():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Giuseppe", bride_given_name="Anna")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG", MATRIMONI)
    text = _all_text(data)
    assert "Bride" in text and "Given Name" in text


def test_report_requires_accuracy_mode():
    with pytest.raises(RuntimeError, match="corrected/ground-truth"):
        build_index_compare_report({"mode": "agreement", "field_reliability": []})


def test_control_characters_in_a_candidate_label_do_not_crash_report_generation():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Marco")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini\x00bad", candidate)])
    data = build_index_compare_report(result, "ORIG")  # must not raise
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document_xml = archive.read("word/document.xml")
    assert b"\x00" not in document_xml
