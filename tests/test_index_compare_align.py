"""Regression tests for index_compare/align.py -- row alignment between a
ground-truth index and a candidate index by locator (Page #/Act #) plus
occurrence order, with an explicit missing/extra accounting instead of
ever silently dropping or misaligning a row."""

from __future__ import annotations

from index_compare.align import align_rows
from xls_conversion.ai_parser import RECORD_TYPES

MATRIMONI = RECORD_TYPES["matrimoni"]  # locator field: page_number


def _row(page_number: str, name: str) -> dict[str, str]:
    return {"page_number": page_number, "groom_given_name": name}


def test_same_order_one_entry_per_page_matches_cleanly():
    truth = [_row("34", "Giuseppe"), _row("35", "Marco")]
    candidate = [_row("34", "Giuseppe"), _row("35", "Marco")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    assert result.missing_from_candidate == []
    assert result.extra_in_candidate == []
    assert result.matched[0][0]["groom_given_name"] == "Giuseppe"
    assert result.matched[1][0]["groom_given_name"] == "Marco"


def test_multiple_entries_on_the_same_page_align_by_occurrence_order():
    truth = [_row("34", "Giuseppe"), _row("34", "Marco"), _row("34", "Paolo")]
    candidate = [_row("34", "Giuseppe-AI"), _row("34", "Marco-AI"), _row("34", "Paolo-AI")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 3
    # 1st truth entry on page 34 pairs with the 1st candidate entry on page
    # 34, not scrambled by locator value alone.
    assert [t["groom_given_name"] for t, _ in result.matched] == ["Giuseppe", "Marco", "Paolo"]
    assert [c["groom_given_name"] for _, c in result.matched] == ["Giuseppe-AI", "Marco-AI", "Paolo-AI"]


def test_missing_and_extra_rows_are_reported_not_dropped_or_misaligned():
    truth = [_row("34", "Giuseppe"), _row("35", "Marco")]
    candidate = [_row("34", "Giuseppe"), _row("36", "Someone Else")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1
    assert result.matched[0][0]["groom_given_name"] == "Giuseppe"
    assert len(result.missing_from_candidate) == 1
    assert result.missing_from_candidate[0]["groom_given_name"] == "Marco"
    assert len(result.extra_in_candidate) == 1
    assert result.extra_in_candidate[0]["groom_given_name"] == "Someone Else"


def test_blank_and_illegible_locators_pair_by_corroborated_name():
    # Blank and "[illegible]" locators share the no-locator bucket, where rows
    # pair by name only -- and, since CODEX_REVIEW_2.md M-15 / HD-1, only when
    # both rows give a surname or a year (here: a surname).
    truth = [dict(_row("", "Giuseppe"), groom_last_name="Rossi"), dict(_row("[illegible]", "Marco"), groom_last_name="Bianchi")]
    candidate = [dict(_row("", "Giuseppe-AI"), groom_last_name="Rossi"), dict(_row("", "Marco-AI"), groom_last_name="Bianchi")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    assert result.matched[0][0]["groom_given_name"] == "Giuseppe"
    assert result.matched[0][1]["groom_given_name"] == "Giuseppe-AI"
    assert result.matched[1][0]["groom_given_name"] == "Marco"
    assert result.matched[1][1]["groom_given_name"] == "Marco-AI"


def test_leading_zeros_do_not_prevent_a_locator_match():
    truth = [_row("034", "Giuseppe")]
    candidate = [_row("34", "Giuseppe")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1
    assert result.missing_from_candidate == []
    assert result.extra_in_candidate == []


def test_unlocated_rows_never_collide_with_a_real_locator_value():
    # A blank locator must not accidentally key the same as a real page "0"
    # or an empty-string page value some other file might legitimately use.
    truth = [dict(_row("", "Blank Page Entry"), groom_last_name="Rossi"), _row("0", "Page Zero Entry")]
    candidate = [dict(_row("", "Blank Page Entry"), groom_last_name="Rossi"), _row("0", "Page Zero Entry")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    names = {t["groom_given_name"] for t, _ in result.matched}
    assert names == {"Blank Page Entry", "Page Zero Entry"}


# ---- Identity fallback (name + date): added after a real ground-truth
# file (an indexer's own corrected index, tracked by name and date only,
# Page #/Image # never filled in) produced 0 matched rows under
# locator-only matching, even though every record was genuinely present in
# both files.


def _id_row(given: str, last: str, year: str, page: str = "") -> dict[str, str]:
    return {
        "page_number": page,
        "groom_given_name": given,
        "groom_last_name": last,
        "marriage_year": year,
    }


def test_identity_fallback_matches_when_ground_truth_has_no_locator_at_all():
    truth = [_id_row("Giuseppe", "Rossi", "1775"), _id_row("Anna", "Bianchi", "1775")]
    candidate = [_id_row("Giuseppe", "Rossi", "1775", page="4"), _id_row("Anna", "Bianchi", "1775", page="4")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    assert result.missing_from_candidate == []
    assert result.extra_in_candidate == []


def test_identity_fallback_tolerates_latin_declension_spelling_differences():
    # Real example from the Grimaldi Morti ground truth: "Pietro"/"Petrus",
    # "Lucrezia"/"Laurentia" -- same person, Latin-declension spelling.
    truth = [_id_row("Pietro", "Nigro", "1775")]
    candidate = [_id_row("Petrus", "Nigro", "1775", page="5")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1


def test_identity_fallback_does_not_cross_match_different_years():
    # Same name, different year -- must never be treated as the same record
    # even though the name matches exactly.
    truth = [_id_row("Giuseppe", "Rossi", "1775")]
    candidate = [_id_row("Giuseppe", "Rossi", "1780", page="9")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert result.matched == []
    assert len(result.missing_from_candidate) == 1
    assert len(result.extra_in_candidate) == 1


def test_identity_fallback_does_not_match_dissimilar_names_in_the_same_year():
    truth = [_id_row("Giovanni", "Giardino", "1775")]
    candidate = [_id_row("Joannes", "Gagliardo", "1775", page="4")]  # a different person, same year
    result = align_rows(truth, candidate, MATRIMONI)
    assert result.matched == []


def test_identity_fallback_uses_global_best_first_assignment():
    # An earlier, weaker match must not steal a row a later pair would have
    # matched almost perfectly -- same failure mode reader.py's
    # suggest_mapping() had to fix, reproduced here for align_rows().
    truth = [_id_row("Giovanni", "Rollo", "1775"), _id_row("Giovanni", "Gagliardi", "1775")]
    candidate = [
        _id_row("Joannes", "Gagliardi", "1775", page="5"),  # true match for truth[1]
        _id_row("Joannes", "Rollo", "1775", page="4"),  # true match for truth[0]
    ]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    pairs = {(t["groom_last_name"], c["groom_last_name"]) for t, c in result.matched}
    assert pairs == {("Rollo", "Rollo"), ("Gagliardi", "Gagliardi")}


def test_missing_first_entry_on_a_repeated_page_does_not_cascade_misalignment():
    # Regression for a real defect: matching by (page, occurrence-index)
    # alone paired truth's 2nd/3rd entries against the candidate's 1st/2nd
    # once the candidate dropped the page's first entry, reporting the
    # wrong person (the true last entry) as missing instead of the real
    # gap, and silently mis-pairing everyone in between.
    truth = [_row("34", "Alice"), _row("34", "Bob"), _row("34", "Carol")]
    candidate = [_row("34", "Bob"), _row("34", "Carol")]  # Alice never made it into the candidate
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    pairs = {(t["groom_given_name"], c["groom_given_name"]) for t, c in result.matched}
    assert pairs == {("Bob", "Bob"), ("Carol", "Carol")}
    assert len(result.missing_from_candidate) == 1
    assert result.missing_from_candidate[0]["groom_given_name"] == "Alice"
    assert result.extra_in_candidate == []


def test_missing_middle_entry_on_a_repeated_page_does_not_cascade_misalignment():
    truth = [_row("34", "Alice"), _row("34", "Bob"), _row("34", "Carol")]
    candidate = [_row("34", "Alice"), _row("34", "Carol")]  # Bob never made it into the candidate
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 2
    pairs = {(t["groom_given_name"], c["groom_given_name"]) for t, c in result.matched}
    assert pairs == {("Alice", "Alice"), ("Carol", "Carol")}
    assert len(result.missing_from_candidate) == 1
    assert result.missing_from_candidate[0]["groom_given_name"] == "Bob"
    assert result.extra_in_candidate == []


def test_locator_matches_take_priority_over_identity_fallback():
    # When locator-based matching already pairs everything, the identity
    # pass has nothing left to do and must not second-guess it.
    truth = [_row("34", "Giuseppe")]
    candidate = [_row("34", "Giuseppe")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1
    assert result.matched[0][0] is truth[0]
    assert result.matched[0][1] is candidate[0]


# reviews/CODEX_REVIEW_8.md M-7: name matching has an overall budget,
# charged before any comparison runs.
import pytest as _pytest

import index_compare.align as _align


def test_pair_budget_rejects_oversized_alignment(monkeypatch):
    monkeypatch.setattr(_align, "MAX_IDENTITY_PAIR_VISITS", 10)
    calls = []
    monkeypatch.setattr(_align.fuzz, "ratio", lambda a, b: calls.append(1) or 0)
    truth = [_row("", f"Name{i}") for i in range(5)]
    candidate = [_row("", f"Other{i}") for i in range(5)]
    with _pytest.raises(_align.AlignmentTooLargeError, match="too large"):
        align_rows(truth, candidate, MATRIMONI)
    assert calls == []  # refused before doing the work


def test_pair_budget_allows_small_alignment(monkeypatch):
    monkeypatch.setattr(_align, "MAX_IDENTITY_PAIR_VISITS", 100)
    truth = [dict(_row("", f"Name{i}"), groom_last_name="Rossi") for i in range(5)]
    result = align_rows(truth, list(truth), MATRIMONI)
    assert len(result.matched) == 5


def test_year_partition_skips_cross_year_visits(monkeypatch):
    calls = []
    real_ratio = _align.fuzz.ratio
    monkeypatch.setattr(_align.fuzz, "ratio", lambda a, b: calls.append(1) or real_ratio(a, b))
    year_field = _align.identity_fields(MATRIMONI)[2]
    truth = [{"page_number": "", "groom_given_name": "Giuseppe", year_field: "1800"}]
    candidate = [{"page_number": "", "groom_given_name": "Giuseppe", year_field: str(1801 + i)} for i in range(50)]
    align_rows(truth, candidate, MATRIMONI)
    assert calls == []


# reviews/CODEX_REVIEW_8.md M-15 / HD-1 (maintainer chose option 3): rows with
# no page/act number pair by name (and year) only, never by order; pairs made
# by order within one page are counted so the report can show them.

def _unlocated(given: str, last: str, year: str) -> dict[str, str]:
    return {"page_number": "", "groom_given_name": given, "groom_last_name": last, "marriage_year": year}


def test_unlocated_rows_with_conflicting_identity_are_not_paired_by_order():
    truth = [_unlocated("Paolo", "Rossi", "1800")]
    candidate = [_unlocated("Anne", "Smith", "1900")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert result.matched == []
    assert len(result.missing_from_candidate) == 1
    assert len(result.extra_in_candidate) == 1
    assert result.position_only_pairs == 0


def test_unlocated_shifted_rows_still_pair_by_identity():
    truth = [_unlocated("Paolo", "Rossi", "1800"), _unlocated("Maria", "Bruno", "1801")]
    candidate = [_unlocated("Maria", "Bruno", "1801"), _unlocated("Paolo", "Rossi", "1800")]
    result = align_rows(truth, candidate, MATRIMONI)
    pairs = {(t["groom_last_name"], c["groom_last_name"]) for t, c in result.matched}
    assert pairs == {("Rossi", "Rossi"), ("Bruno", "Bruno")}
    assert result.position_only_pairs == 0


def test_same_page_order_fallback_is_kept_and_counted():
    truth = [_row("34", "Giuseppe")]
    candidate = [_row("34", "Zzyzx")]  # badly misread name on the same page
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1
    assert result.position_only_pairs == 1


# CODEX_REVIEW_2.md M-15 / HD-1 (maintainer: a lone given name is not
# identity evidence for rows with no page or act number).

def test_unlocated_given_name_only_rows_stay_missing_and_extra():
    truth = [_unlocated("Paolo", "", "")]
    candidate = [_unlocated("Paolo", "", "")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert result.matched == []
    assert len(result.missing_from_candidate) == 1 and len(result.extra_in_candidate) == 1


def test_unlocated_given_name_with_matching_year_pairs():
    result = align_rows([_unlocated("Paolo", "", "1800")], [_unlocated("Paolo", "", "1800")], MATRIMONI)
    assert len(result.matched) == 1 and result.position_only_pairs == 0


def test_unlocated_full_name_without_year_pairs():
    result = align_rows([_unlocated("Paolo", "Rossi", "")], [_unlocated("Paolo", "Rossi", "")], MATRIMONI)
    assert len(result.matched) == 1


def test_located_given_name_only_still_pairs_on_same_page():
    truth = [{"page_number": "4", "groom_given_name": "Paolo", "groom_last_name": "", "marriage_year": ""}]
    candidate = [dict(truth[0])]
    assert len(align_rows(truth, candidate, MATRIMONI).matched) == 1


def test_cross_page_fallback_needs_more_than_a_given_name():
    truth = [{"page_number": "4", "groom_given_name": "Paolo", "groom_last_name": "", "marriage_year": ""}]
    candidate = [{"page_number": "9", "groom_given_name": "Paolo", "groom_last_name": "", "marriage_year": ""}]
    result = align_rows(truth, candidate, MATRIMONI)
    assert result.matched == []


# CODEX_REVIEW_2.md M-7: the budget is charged from integer counts, row by
# row, and the comparison is refused before any candidate list is copied
# or any name compared.

def test_budget_rejection_does_no_list_copies_or_comparisons(monkeypatch):
    monkeypatch.setattr(_align, "MAX_IDENTITY_PAIR_VISITS", 50)
    compared = {"n": 0}
    monkeypatch.setattr(_align.fuzz, "ratio", lambda a, b: compared.__setitem__("n", compared["n"] + 1) or 0)
    spends: list[int] = []
    real_spend = _align._PairBudget.spend

    def counting_spend(self, visits):
        spends.append(visits)
        real_spend(self, visits)

    monkeypatch.setattr(_align._PairBudget, "spend", counting_spend)
    truth = [_unlocated(f"Name{i}", "Rossi", "1800") for i in range(1000)]
    candidate = [_unlocated(f"Name{i}", "Rossi", "1800") for i in range(1000)]
    with _pytest.raises(_align.AlignmentTooLargeError):
        align_rows(truth, candidate, MATRIMONI)
    assert compared["n"] == 0
    # Stopped at the first truth row that exceeded the budget, not after all 1000.
    assert len(spends) == 1 and spends[0] == 1000
