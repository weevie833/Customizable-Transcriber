"""Regression tests for index_compare/scoring.py -- the orchestration layer
tying align.py + heuristics.py + test_mode/comparison.py's Levenshtein
primitive together into Accuracy mode. A ground-truth file is required
(compare_indexes() raises without one) -- this module used to also offer an
Agreement mode (candidates compared only to each other, no ground truth)
plus an optional AI-assisted pass to reclassify ambiguous diffs; both were
dropped when the downloadable report was rebuilt as a DOCX distilling
statistical accuracy rather than per-row detail. See compare_indexes()'s
own docstring."""

from __future__ import annotations

import pytest

from index_compare.scoring import compare_indexes, fields_with_ground_truth_data, score_candidate
from xls_conversion.ai_parser import RECORD_TYPES

MATRIMONI = RECORD_TYPES["matrimoni"]


def _row(**fields) -> dict[str, str]:
    row = {field: "" for field in MATRIMONI.fields}
    row.update(fields)
    return row


def test_score_candidate_reports_real_diffs_and_skips_both_blank_fields():
    truth = [_row(page_number="34", groom_given_name="Mauritzius", bride_last_name="Trunzo", marriage_day="23")]
    candidate = [_row(page_number="34", groom_given_name="Mauritius", bride_last_name="de Franco", marriage_day="23")]

    result = score_candidate(truth, candidate, MATRIMONI)

    assert result["matched_count"] == 1
    assert result["missing_from_candidate"] == 0
    assert result["extra_in_candidate"] == 0
    assert result["category_counts"] == {"spelling_variant": 1, "differs": 1}
    fields_in_diffs = {diff["field"] for diff in result["diffs"]}
    # Every other field is blank on both sides (image_number, witnesses,
    # notes, ...) -- must not show up as noise.
    assert fields_in_diffs == {"groom_given_name", "bride_last_name"}


def test_score_candidate_falls_back_to_name_as_locator_when_page_number_is_blank():
    # Real case: a ground truth tracked by name and date, Page # never
    # filled in (see align.py's identity-matching fallback) -- each diff's
    # Locator value must still identify the row, not be blank for every
    # single one of them.
    truth = [_row(groom_given_name="Giuseppe", groom_last_name="Rossi", bride_last_name="Bianchi")]
    candidate = [_row(groom_given_name="Giuseppe", groom_last_name="Rossi", bride_last_name="Verdi")]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["diffs"][0]["locator"] == "Giuseppe Rossi"


def test_score_candidate_reports_a_real_numeric_wrong_value():
    truth = [_row(page_number="34", marriage_day="11")]
    candidate = [_row(page_number="34", marriage_day="17")]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["category_counts"] == {"wrong_value": 1}
    assert result["diffs"][0]["field"] == "marriage_day"


def test_score_candidate_field_error_rate_and_group_error_rate_shape():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Giuseppe")]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["field_error_rate"]["groom_given_name"]["error_rate"] == 0.0
    # "Groom" group_headers span covers groom_given_name..groom_mother_last_name.
    assert "Groom" in result["group_error_rate"]
    assert result["group_error_rate"]["Groom"]["error_rate"] == 0.0
    assert result["overall_error_rate"] == 0.0


def test_score_candidate_error_rate_is_never_negative_when_candidate_overwrites_a_blank_field():
    # Regression: the previous "accuracy" framing (1 - edits/ref_chars) went
    # sharply negative when a candidate wrote real content into a field the
    # ground truth left blank (reproduced in a real report: -1.25, -0.36).
    # error_rate (edits/ref_chars, uninverted) can exceed 1.0 but must never
    # go below 0. "notes" has real ground-truth data in one row (so the
    # field-scoping fix, tested separately below, doesn't exclude it here)
    # and is blank in a second row the candidate fills in anyway.
    truth = [
        _row(page_number="34", notes="ok"),
        _row(page_number="35", notes=""),
    ]
    candidate = [
        _row(page_number="34", notes="ok"),
        _row(page_number="35", notes="A long note the ground truth does not have at all"),
    ]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["field_error_rate"]["notes"]["error_rate"] > 1.0
    assert result["overall_error_rate"] >= 0.0


def test_score_candidate_zero_matched_rows_reports_error_rate_as_none_not_perfect():
    # Regression: with 0 matched rows every field's edits/ref_chars were
    # 0/0, and the old formula's zero-length convention returned 1.0
    # ("perfect accuracy") -- reproduced in a real report where a candidate
    # with 0 matched rows showed 100% accuracy across every field group.
    # None must be used instead, since nothing was actually compared.
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="99", groom_given_name="Someone Else")]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["matched_count"] == 0
    assert result["overall_error_rate"] is None
    assert all(entry["error_rate"] is None for entry in result["field_error_rate"].values())
    assert all(entry["error_rate"] is None for entry in result["group_error_rate"].values())


def test_score_candidate_counts_missing_and_extra_rows_separately():
    truth = [_row(page_number="34", groom_given_name="A"), _row(page_number="35", groom_given_name="B")]
    candidate = [_row(page_number="34", groom_given_name="A"), _row(page_number="99", groom_given_name="C")]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert result["matched_count"] == 1
    assert result["missing_from_candidate"] == 1
    assert result["extra_in_candidate"] == 1


def test_compare_indexes_accuracy_mode_end_to_end():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    candidate = [_row(page_number="34", groom_given_name="Marco")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", candidate)])
    assert result["mode"] == "accuracy"
    assert result["ground_truth_label"] == "ORIG"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["label"] == "Gemini"
    assert result["candidates"][0]["category_counts"] == {"differs": 1}


def test_compare_indexes_requires_a_ground_truth_file():
    candidate_a = [_row(page_number="34", groom_given_name="Giuseppe")]
    with pytest.raises(RuntimeError, match="corrected/ground-truth"):
        compare_indexes(MATRIMONI, None, [("Gemini", candidate_a)])


def test_compare_indexes_requires_at_least_one_candidate():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    with pytest.raises(RuntimeError, match="at least one candidate"):
        compare_indexes(MATRIMONI, ("ORIG", truth), [])


# ---- Field scoping: "only compare what the ground truth actually
# provides" (see fields_with_ground_truth_data()'s own docstring) -- added
# after a real ground-truth file (an indexer's own corrected index,
# tracking only name and year) left 17 of 20 fields blank in every row.
# Scoring those inflated the error rate past 900%, drowning out the 2
# fields the indexer had actually corrected by hand.


def test_fields_with_ground_truth_data_excludes_a_field_blank_in_every_row():
    truth = [
        _row(page_number="34", groom_given_name="Giuseppe"),
        _row(page_number="35", groom_given_name="Marco"),
    ]
    present = fields_with_ground_truth_data(truth, MATRIMONI)
    assert "groom_given_name" in present
    assert "page_number" in present
    assert "bride_given_name" not in present  # blank in every row above


def test_fields_with_ground_truth_data_includes_a_field_present_in_only_one_row():
    truth = [
        _row(page_number="34", groom_given_name="Giuseppe"),
        _row(page_number="35", groom_given_name=""),
    ]
    present = fields_with_ground_truth_data(truth, MATRIMONI)
    assert "groom_given_name" in present  # one non-blank occurrence is enough


def test_score_candidate_excludes_fields_the_ground_truth_never_fills_in():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    # Candidate invents content for many fields truth never states.
    candidate = [
        _row(
            page_number="34",
            groom_given_name="Giuseppe",
            bride_given_name="Anna",
            bride_last_name="Rossi",
            witnesses="Someone, Someone Else",
            notes="A long invented note",
        )
    ]
    result = score_candidate(truth, candidate, MATRIMONI)
    assert "bride_given_name" in result["excluded_fields"]
    assert "witnesses" in result["excluded_fields"]
    assert "notes" in result["excluded_fields"]
    assert "groom_given_name" not in result["excluded_fields"]
    # Only the scored field (an exact match) contributes -- the invented
    # extra fields must not appear as diffs or inflate the error rate.
    assert result["diffs"] == []
    assert result["overall_error_rate"] == 0.0
    assert "bride_given_name" not in result["field_error_rate"]
    # "Bride" group has no scored field at all here -- it must not appear
    # as a zeroed/empty row that would misleadingly look scored.
    assert "Bride" not in result["group_error_rate"]


def test_compare_indexes_scopes_every_candidate_to_the_same_ground_truth_fields():
    truth = [_row(page_number="34", groom_given_name="Giuseppe")]
    gemini = [_row(page_number="34", groom_given_name="Giuseppe", bride_given_name="Anna")]
    claude = [_row(page_number="34", groom_given_name="Marco", bride_given_name="Lucia")]
    result = compare_indexes(MATRIMONI, ("ORIG", truth), [("Gemini", gemini), ("Claude", claude)])
    for entry in result["candidates"]:
        assert "bride_given_name" in entry["excluded_fields"]
