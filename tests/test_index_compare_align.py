"""Regression tests for index_compare/align.py -- row alignment between a
ground-truth index and a candidate index by locator (Page #/Act #) plus
occurrence order, with an explicit missing/extra accounting instead of
ever silently dropping or misaligning a row."""

from __future__ import annotations

from xls_conversion.ai_parser import RECORD_TYPES

from index_compare.align import align_rows

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


def test_blank_and_illegible_locators_fall_back_to_positional_matching():
    truth = [_row("", "Giuseppe"), _row("[illegible]", "Marco")]
    candidate = [_row("", "Giuseppe-AI"), _row("", "Marco-AI")]
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
    truth = [_row("", "Blank Page Entry"), _row("0", "Page Zero Entry")]
    candidate = [_row("", "Blank Page Entry"), _row("0", "Page Zero Entry")]
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


def test_locator_matches_take_priority_over_identity_fallback():
    # When locator-based matching already pairs everything, the identity
    # pass has nothing left to do and must not second-guess it.
    truth = [_row("34", "Giuseppe")]
    candidate = [_row("34", "Giuseppe")]
    result = align_rows(truth, candidate, MATRIMONI)
    assert len(result.matched) == 1
    assert result.matched[0][0] is truth[0]
    assert result.matched[0][1] is candidate[0]
