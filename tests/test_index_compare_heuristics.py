"""Regression tests for index_compare/heuristics.py -- the deterministic
(no-AI) diff classifier. Real-example cases are pulled straight from the
two hand-built example workbooks the user shared (San Mango D'Aquino
Matrimoni, Grimaldi Morti), so a future threshold tweak that breaks one of
these is a real regression against the app's own worked examples, not a
hypothetical."""

from __future__ import annotations

import pytest

from index_compare.heuristics import (
    DIFFERS,
    LATIN_FORM,
    MATCH,
    MISSING,
    SPELLING_VARIANT,
    UNCLASSIFIED,
    WRONG_VALUE,
    classify_diff,
)


def test_exact_match_after_normalization():
    assert classify_diff("groom_given_name", "Giuseppe", " giuseppe ", is_numeric=False) == MATCH


@pytest.mark.parametrize(
    "truth,candidate",
    [
        ("", "34"),
        ("34", ""),
        ("34", "[illegible]"),
    ],
)
def test_missing_when_exactly_one_side_is_blank_or_illegible(truth, candidate):
    assert classify_diff("page_number", truth, candidate, is_numeric=False) == MISSING


@pytest.mark.parametrize(
    "truth,candidate",
    [
        ("", ""),
        ("[illegible]", "[Illegible]"),
    ],
)
def test_both_sides_blank_or_illegible_is_a_match_not_a_diff(truth, candidate):
    # Neither side having data for an optional field (Witnesses, Notes, an
    # unrecorded parent) is the common case, not a disagreement worth
    # surfacing -- see classify_diff()'s own docstring, check #1.
    assert classify_diff("page_number", truth, candidate, is_numeric=False) == MATCH


def test_wrong_value_for_a_differing_numeric_field():
    # Real example: image 194 both AIs read the marriage day as 20, ORIG
    # says 30.
    assert classify_diff("marriage_day", "30", "20", is_numeric=True) == WRONG_VALUE


@pytest.mark.parametrize(
    "truth,candidate",
    [
        ("fu Pauli", "Paulus"),  # groom's father, San Mango R3
        ("Nicola", "Nicolaus"),  # groom given name, San Mango R8
        ("Gabriele", "Gabriel"),  # groom given name, San Mango R14
        ("Josephi", "Joseph"),  # bride's father, San Mango R7
        ("D. Felix Antonius", "Felix Antonius"),  # groom given name, San Mango R4
        ("Mag. D. Teresia", "Teresia"),  # bride given name, San Mango R4
        ("Mag. Nicolai", "Nicolaus"),  # bride's father, San Mango R4
    ],
)
def test_latin_form_variants_from_the_example_workbook(truth, candidate):
    assert classify_diff("some_name_field", truth, candidate, is_numeric=False) == LATIN_FORM


@pytest.mark.parametrize(
    "truth,candidate",
    [
        ("Mauritzius", "Mauritius"),  # groom given name, San Mango R5
        ("Francesca Maria", "Francisca Maria"),  # bride given name, San Mango R13
        ("Marturana", "Martorana"),  # a real, noted spelling-variant surname pair
    ],
)
def test_spelling_variants_from_the_example_workbook(truth, candidate):
    assert classify_diff("some_name_field", truth, candidate, is_numeric=False) == SPELLING_VARIANT


def test_confidently_different_name_is_differs():
    # Real example: San Mango R6 bride's last name -- an outright wrong
    # reading (different person), not a spelling drift.
    assert classify_diff("bride_last_name", "Trunzo", "de Franco", is_numeric=False) == DIFFERS


@pytest.mark.parametrize(
    "truth,candidate",
    [
        ("Colosimo", "Rosimo"),  # San Mango R11 -- the human called this "Wrong name"
        ("Ianni", "Janne"),  # San Mango R15 -- the human called this "Spelling"
    ],
)
def test_genuinely_ambiguous_pairs_are_deferred_not_guessed(truth, candidate):
    # These two land close enough in edit-distance that a single threshold
    # can't separate "different person" from "spelling drift" reliably --
    # the human reviewer classified them as opposite categories despite
    # similar edit distance (see the module docstring's threshold comment).
    # The heuristic must defer rather than confidently guess either way.
    assert classify_diff("some_name_field", truth, candidate, is_numeric=False) == UNCLASSIFIED
