"""Regression tests for index_compare/report_xlsx.py -- the downloadable
workbook, shaped after the two hand-built example workbooks the user
shared (Scorecard + Compare-<label> tabs in Accuracy mode; a Disagreements
tab in Agreement mode)."""

from __future__ import annotations

import io

import openpyxl

from xls_conversion.ai_parser import RECORD_TYPES

from index_compare.report_xlsx import build_index_compare_report
from index_compare.scoring import compare_indexes

MATRIMONI = RECORD_TYPES["matrimoni"]


def _row(**fields) -> dict[str, str]:
    row = {field: "" for field in MATRIMONI.fields}
    row.update(fields)
    return row


def test_accuracy_mode_report_has_scorecard_and_one_tab_per_candidate():
    truth = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo", marriage_day="23")]
    gemini = [_row(page_number="34", groom_given_name="Marco", bride_last_name="de Franco", marriage_day="23")]
    claude = [_row(page_number="34", groom_given_name="Giuseppe", bride_last_name="Trunzo", marriage_day="17")]

    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", gemini), ("Claude", claude)])
    data = build_index_compare_report(result, "ORIG")
    workbook = openpyxl.load_workbook(io.BytesIO(data))

    assert workbook.sheetnames == ["Scorecard", "Compare Gemini", "Compare Claude"]

    scorecard_rows = list(workbook["Scorecard"].iter_rows(values_only=True))
    assert scorecard_rows[0][0] == "Accuracy Scorecard: Gemini vs. Claude (vs. ORIG)"

    gemini_rows = [r for r in workbook["Compare Gemini"].iter_rows(values_only=True) if any(v is not None for v in r)]
    assert gemini_rows[1] == ("Locator", "Field", "Ground truth", "Gemini", "Category", "AI rationale")
    # Gemini's row differs from truth in both groom_given_name and
    # bride_last_name -- two diff rows below the header, not zero and not
    # a re-derived/duplicated count.
    assert len(gemini_rows) == 4


def test_scorecard_ranks_candidates_by_error_rate_best_first():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    close = [_row(page_number="34", groom_given_name="Giuseppe")]  # exact match -- 0% error
    far = [_row(page_number="34", groom_given_name="Someone Else Entirely")]  # high error

    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Far", far), ("Close", close)])
    data = build_index_compare_report(result, "ORIG")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    rows = [r for r in workbook["Scorecard"].iter_rows(values_only=True) if any(v is not None for v in r)]
    header_index = rows.index(("Rank", "Candidate", "Error rate (CER)", "Est. character edits", "Reference characters"))
    assert rows[header_index + 1][:2] == (1, "Close")
    assert rows[header_index + 2][:2] == (2, "Far")


def test_scorecard_shows_na_and_a_warning_for_a_zero_matched_candidate_never_a_negative_number():
    truth = [_row(page_number="34", groom_given_name="Giuseppe", notes="")]
    unrelated = [_row(page_number="99", groom_given_name="Nobody")]  # no locator overlap -- 0 matched
    overwritten_blank = [_row(page_number="34", groom_given_name="Giuseppe", notes="a long note truth lacks")]

    result = compare_indexes(
        MATRIMONI, ("ORIG", truth), [("ZeroMatch", unrelated), ("Overwrite", overwritten_blank)]
    )
    data = build_index_compare_report(result, "ORIG")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    rows = [r for r in workbook["Scorecard"].iter_rows(values_only=True) if any(v is not None for v in r)]
    flat_text = " ".join(str(v) for row in rows for v in row if isinstance(v, str))
    assert "N/A (0 matched)" in flat_text
    assert "⚠" in flat_text and "ZeroMatch" in flat_text
    numeric_values = [v for row in rows for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)]
    assert all(v >= 0 for v in numeric_values), numeric_values


def test_agreement_mode_report_has_a_single_disagreements_tab():
    a = [_row(page_number="34", groom_given_name="Giuseppe")]
    b = [_row(page_number="34", groom_given_name="Marco")]
    result = compare_indexes(MATRIMONI, None, [("Gemini", a), ("Claude", b)])
    data = build_index_compare_report(result, "")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    assert workbook.sheetnames == ["Disagreements"]
    rows = [r for r in workbook["Disagreements"].iter_rows(values_only=True) if any(v is not None for v in r)]
    assert rows[1] == ("Field", "Records w/ data", "Agree", "Disagree", "Agree %")


def test_numeric_cells_are_written_as_real_numbers_not_text():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Marco")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    scorecard = workbook["Scorecard"]
    # "Matched" row's count cell must be a real int, so a user can sum/sort
    # it in Excel -- not a string that merely looks numeric.
    matched_row = next(
        row for row in scorecard.iter_rows() if row[0].value == "Matched"
    )
    assert isinstance(matched_row[1].value, int)


def test_control_characters_in_a_field_value_do_not_crash_report_generation():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Marco\x00bad")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    data = build_index_compare_report(result, "ORIG")  # must not raise
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    rows = [r for r in workbook["Compare Gemini"].iter_rows(values_only=True) if any(v is not None for v in r)]
    diff_row = rows[-1]
    assert "\x00" not in diff_row[3]


def test_candidate_sheet_names_are_deduplicated_when_labels_collide():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    a = [_row(page_number="34", groom_given_name="Marco")]
    b = [_row(page_number="34", groom_given_name="Paolo")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Run", a), ("Run", b)])
    data = build_index_compare_report(result, "ORIG")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    assert workbook.sheetnames == ["Scorecard", "Compare Run", "Compare Run 2"]
