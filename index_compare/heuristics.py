from __future__ import annotations

from rapidfuzz import fuzz

from index_compare.text_utils import is_blank_or_illegible, normalize_for_comparison

# rapidfuzz fuzz.ratio() score (0-100) bands. Calibrated against real
# examples from the two hand-built example workbooks the user shared
# (San Mango D'Aquino Matrimoni, Grimaldi Morti) -- notably, a real "wrong
# name" pair the human reviewer flagged ("Colosimo"/"Rosimo") scores 71.4,
# while a real accepted spelling variant ("Ianni"/"Janne") scores only
# 60.0. Those two overlap, so no single threshold can cleanly separate
# "spelling variant" from "different person" purely from edit distance --
# both ended up landing in the `unclassified` band on purpose: this
# heuristic would rather defer an ambiguous case to a human's own by-eye
# review than confidently mislabel it either way.
_SPELLING_VARIANT_THRESHOLD = 88.0
_DIFFERS_THRESHOLD = 45.0

# Leading honorific/status markers that can precede a Latin given name
# without being part of it -- stripped before comparing. Deliberately small
# and explicit -- not an attempt at general Latin morphological parsing,
# just the common patterns actually seen in these registers (see
# docs/DESIGN.md's "XLS Conversion" section).
_LATIN_PREFIXES = ("fu ", "mag d ", "mag ", "d ", "don ", "dr ", "rev ")

# Common Latin case-ending / vernacular-ending suffixes -- tried longest
# first so "us" doesn't get pre-empted by a shorter, wrong match. Stripped
# at most once per side; see _latin_stem()'s own docstring for why a single
# pass (not recursive stripping) is the right amount of aggressiveness.
_LATIN_SUFFIXES = ("um", "us", "ae", "is", "a", "i", "o", "e")

# How much of the longer of two single-stripped stems the shorter one must
# cover, as a prefix, to still count as the same underlying name (handles
# "nicola" -> stem "nicol" vs "nicolaus" -> stem "nicola": not equal, but
# "nicol" covers 5/6 of "nicola").
_STEM_PREFIX_COVERAGE = 0.7


def _strip_latin_prefix(text: str) -> str:
    # Periods removed first ("Mag. D. Teresia" -> "mag d teresia") so
    # _LATIN_PREFIXES only needs one plain-text form per marker, not every
    # abbreviation-punctuation variant a scribe or transcript might use.
    unpunctuated = text.replace(".", "")
    for prefix in _LATIN_PREFIXES:
        if unpunctuated.startswith(prefix):
            return unpunctuated[len(prefix):]
    return unpunctuated


def _latin_stem(text: str) -> str:
    """Strip at most one trailing Latin-suffix candidate. Single-pass, not
    recursive: recursively stripping every matching suffix in turn would
    eventually erode most short names down to nothing and start matching
    unrelated names as "the same stem" -- one pass is enough to normalize
    an actual case ending without over-stripping."""
    for suffix in _LATIN_SUFFIXES:
        if len(text) > len(suffix) + 2 and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _is_latin_form_variant(truth_norm: str, candidate_norm: str) -> bool:
    truth_stem = _latin_stem(_strip_latin_prefix(truth_norm))
    candidate_stem = _latin_stem(_strip_latin_prefix(candidate_norm))
    if not truth_stem or not candidate_stem:
        return False
    if truth_stem == candidate_stem:
        return True
    shorter, longer = sorted((truth_stem, candidate_stem), key=len)
    if not longer.startswith(shorter):
        return False
    return len(shorter) / len(longer) >= _STEM_PREFIX_COVERAGE


# Kept in this order deliberately -- see classify_diff()'s docstring for why
# each check has to run before the ones after it.
MATCH = "match"
LATIN_FORM = "latin_form"
MISSING = "missing"
WRONG_VALUE = "wrong_value"
SPELLING_VARIANT = "spelling_variant"
DIFFERS = "differs"
UNCLASSIFIED = "unclassified"


def classify_diff(field: str, truth_value: str, candidate_value: str, *, is_numeric: bool = False) -> str:
    """Deterministic, no-AI classification of one field's truth-vs-candidate
    difference. `is_numeric` is supplied by the caller (scoring.py), derived
    from RecordTypeConfig.numeric_columns -- field-name pattern-matching
    (e.g. "contains '_year'") was tried first and rejected: baptism_month
    and birth_month contain "month" but hold a spelled-out month name, not
    a number, so numeric_columns (an explicit per-column set the config
    already carries) is the only reliable source of truth here.

    Check order matters and is intentional:
      1. both sides blank/"[illegible]" -- treated as `match` (not surfaced
         as a diff at all). Neither side has data for this field, and
         *both* independently saying so isn't a disagreement worth putting
         in front of a human -- it's the common, expected state for a
         field this register just doesn't fill in (Witnesses, Notes, an
         unrecorded parent). Checked before the general exact-match
         comparison below because it's judged on missingness, not on the
         literal string "[illegible]" happening to equal itself.
      2. missing -- blank or "[illegible]" on exactly one side. This IS a
         real signal: either the candidate invented a value the ground
         truth doesn't have, or missed one the ground truth does. Checked
         before the general exact-match/similarity checks below because an
         empty string compared against real text is not "0% similar text",
         it's a different kind of difference than a specific wrong reading.
      3. exact match (after whitespace/case normalization) -- not really a
         "diff" at all, just counted.
      4. wrong_value -- numeric/date-like fields. A misread digit isn't
         better explained by string-similarity banding (spelling
         variant/differs) than by just being wrong.
      5. latin_form -- checked before the ratio bands below because a
         genuine Latin-declension pair like "Nicola"/"Nicolaus" can score
         in the same numeric range as an unrelated name pair; the affix/
         suffix check is more specific evidence than raw edit distance.
      6. spelling_variant / differs / unclassified -- see the threshold
         comment above _SPELLING_VARIANT_THRESHOLD for how those bands were
         picked, and why the gap between them is deliberately wide.
    """
    truth_norm = normalize_for_comparison(truth_value)
    candidate_norm = normalize_for_comparison(candidate_value)

    truth_missing = is_blank_or_illegible(truth_value)
    candidate_missing = is_blank_or_illegible(candidate_value)
    if truth_missing and candidate_missing:
        return MATCH
    if truth_missing or candidate_missing:
        return MISSING

    if truth_norm == candidate_norm:
        return MATCH

    if is_numeric:
        return WRONG_VALUE

    if _is_latin_form_variant(truth_norm, candidate_norm):
        return LATIN_FORM

    ratio = fuzz.ratio(truth_norm, candidate_norm)
    if ratio >= _SPELLING_VARIANT_THRESHOLD:
        return SPELLING_VARIANT
    if ratio < _DIFFERS_THRESHOLD:
        return DIFFERS
    return UNCLASSIFIED
