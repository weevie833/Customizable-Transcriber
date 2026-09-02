from __future__ import annotations

import json
from collections import Counter

from test_mode.comparison import character_edit_stats
from xls_conversion.ai_parser import RecordTypeConfig, call_ai

from index_compare.align import align_rows, identity_fields
from index_compare.heuristics import (
    DIFFERS,
    LATIN_FORM,
    SPELLING_VARIANT,
    UNCLASSIFIED,
    WRONG_VALUE,
    classify_diff,
)
from index_compare.text_utils import is_blank_or_illegible, normalize_for_comparison

Row = dict[str, str]

# The only categories the AI-assisted pass is allowed to hand back --
# "match"/"missing" are already resolved deterministically before this ever
# runs (see classify_diff()'s own check order), and "unclassified" is what
# we're trying to replace, not a valid answer.
_AI_ASSIST_CATEGORIES = (SPELLING_VARIANT, LATIN_FORM, WRONG_VALUE, DIFFERS)

_AI_SYSTEM_PROMPT = (
    "You are assisting a genealogical indexer by classifying differences between a "
    "corrected/ground-truth spreadsheet index and an AI-generated candidate index. A "
    "deterministic first pass already resolved every difference it could; you are only "
    "shown the ones it could not confidently bucket.\n\n"
    "For each difference, decide which single category best describes it:\n"
    f'- "{SPELLING_VARIANT}": the same name/word, spelled differently (transliteration, '
    "minor letter differences) -- not a different name.\n"
    f'- "{LATIN_FORM}": a Latin-declension or honorific-title difference, not a real error '
    '(e.g. "Paulus" vs "fu Pauli", "D. Felix" vs "Felix").\n'
    f'- "{WRONG_VALUE}": a genuinely incorrect value (a misread digit, date, or other fact).\n'
    f'- "{DIFFERS}": the two values name or describe a different person/thing entirely.\n\n'
    "Return only a JSON array with one object per difference, in the same order given, each "
    'with exactly these fields: "index" (the integer index from the input, copied back '
    'unchanged), "category" (one of the four values above, spelled exactly as shown), and '
    '"rationale" (one short sentence explaining the call).'
)


def _numeric_fields(config: RecordTypeConfig) -> set[str]:
    """Field names whose column is one of config.numeric_columns (1-indexed
    column positions) -- the authoritative source for "is this a number
    field", since a name like baptism_month contains "month" but holds a
    spelled-out month name, not a number (see classify_diff()'s own
    docstring for why pattern-matching the field name was rejected)."""
    return {field for index, field in enumerate(config.fields, start=1) if index in config.numeric_columns}


def fields_with_ground_truth_data(truth_rows: list[Row], config: RecordTypeConfig) -> set[str]:
    """Fields the ground truth actually populates at least once, across
    every row (not just matched ones -- this is a property of the ground-
    truth file itself, independent of any one candidate, so every
    candidate is scored against the identical field set for a fair
    ranking). Comparing a field the ground truth never fills in can only
    ever produce noise, never a real accuracy signal: there is nothing to
    check a candidate's value against.

    This is the mechanism behind "only compare what the corrected index
    actually provides" -- confirmed against a real ground-truth file
    (an indexer's own corrected index, tracked by name and date only) where
    17 of 20 fields were blank in every single row; scoring those inflated
    the error rate past 900%, drowning out the 2 fields the indexer
    actually cares about and corrected by hand."""
    present: set[str] = set()
    for row in truth_rows:
        for field in config.fields:
            if field not in present and not is_blank_or_illegible(row.get(field, "")):
                present.add(field)
    return present


def _field_groups(config: RecordTypeConfig) -> dict[str, str]:
    """field -> its group label, forward-filled from group_headers (which
    repeats "" for every column after a group's first, the same shape the
    XLSX export itself renders as a merged header cell)."""
    groups: dict[str, str] = {}
    current = ""
    for field, group_label in zip(config.fields, config.group_headers):
        if group_label:
            current = group_label
        groups[field] = current
    return groups


def _error_rate(edits: int, ref_chars: int) -> float:
    """Character error rate (CER): edits / reference length -- the same
    metric and the same zero-length convention test_mode/comparison.py's
    score_transcription() already uses for the DOCX transcript-comparison
    report (0.0 when both sides are empty, 1.0 when the reference is empty
    but the candidate wrote something, otherwise the raw ratio, which CAN
    exceed 1.0 when a candidate's text is much longer than the reference).

    Deliberately an error rate (lower = better, never negative), not its
    inverse "accuracy" (1 - error_rate) -- an earlier version of this
    function returned that inverse, which reads fine right up until a
    candidate writes real content into a field the ground truth left blank
    (ref_chars small or zero, edits large): 1 - edits/ref_chars then goes
    sharply negative (reproduced: -1.25, -0.36 in a real report), which is
    not a sensible thing to show a user under a column labeled "accuracy".
    CER itself has no such failure mode, and it's the exact metric the
    user's DOCX comparison report already explains -- reusing it here
    means one explanation covers both report types instead of two."""
    if ref_chars == 0:
        return 0.0 if edits == 0 else 1.0
    return round(edits / ref_chars, 4)


def score_candidate(truth_rows: list[Row], candidate_rows: list[Row], config: RecordTypeConfig) -> dict:
    """Accuracy-mode scoring for one candidate against ground truth: aligns
    rows, then per matched pair scores every field the ground truth
    actually populates (see fields_with_ground_truth_data() -- a field
    blank in every truth row is excluded from scoring entirely, not just
    from this one candidate's diffs, so every candidate is judged against
    the identical, fair field set) two ways -- character-level edit
    distance (reusing test_mode/comparison.py's own character_edit_stats(),
    the same Levenshtein primitive Test Mode's transcript CER already
    uses, deliberately not reimplemented here) for the "how many keystrokes
    to fix" number, and classify_diff() for the error-taxonomy bucket. Rows
    in missing_from_candidate/extra_in_candidate are counted but excluded
    from character-accuracy (there's no candidate value to diff against),
    which is why those counts are reported separately rather than folded
    into the per-field numbers."""
    alignment = align_rows(truth_rows, candidate_rows, config)
    field_groups = _field_groups(config)
    numeric_fields = _numeric_fields(config)
    locator_field = config.carry_forward_fields[0] if config.carry_forward_fields else None
    given_field, last_field, _year_field = identity_fields(config)

    scored_fields = fields_with_ground_truth_data(truth_rows, config)
    excluded_fields = [f for f in config.fields if f not in scored_fields]

    field_totals: dict[str, dict[str, int]] = {field: {"edits": 0, "ref_chars": 0} for field in scored_fields}
    diffs: list[dict[str, object]] = []

    for truth_row, candidate_row in alignment.matched:
        locator = truth_row.get(locator_field, "") if locator_field else ""
        if not locator:
            # No Page #/Act # to show (the real case this exists for: a
            # ground truth tracked by name and date, never a page number --
            # see align.py's identity-matching fallback). Fall back to the
            # record's own name so a diff-table row is still identifiable,
            # rather than a blank "Locator" cell for every single row.
            given = truth_row.get(given_field, "") if given_field else ""
            last = truth_row.get(last_field, "") if last_field else ""
            locator = f"{given} {last}".strip()
        for field in scored_fields:
            truth_value = truth_row.get(field, "")
            candidate_value = candidate_row.get(field, "")
            edits, ref_chars = character_edit_stats(truth_value, candidate_value)
            field_totals[field]["edits"] += edits
            field_totals[field]["ref_chars"] += ref_chars
            category = classify_diff(field, truth_value, candidate_value, is_numeric=field in numeric_fields)
            if category != "match":
                diffs.append(
                    {
                        "locator": locator,
                        "field": field,
                        "truth_value": truth_value,
                        "candidate_value": candidate_value,
                        "category": category,
                    }
                )

    matched_count = len(alignment.matched)

    # When nothing matched, every field's edits/ref_chars are 0/0 -- under
    # _error_rate()'s own zero-length convention that computes as 0.0 (a
    # PERFECT score), which is exactly backwards: zero matched rows means
    # nothing was actually compared, not that the candidate is flawless.
    # Reproduced in a real report: a candidate with 0 matched rows showed
    # 100% accuracy across every field group. error_rate is None here
    # instead, and callers (report_xlsx.py) must treat that as "not
    # computed", not as a real 0%.
    def rate_or_none(edits: int, ref_chars: int) -> float | None:
        return _error_rate(edits, ref_chars) if matched_count > 0 else None

    field_error_rate = {
        field: {
            "edits": totals["edits"],
            "ref_chars": totals["ref_chars"],
            "error_rate": rate_or_none(totals["edits"], totals["ref_chars"]),
        }
        for field, totals in field_totals.items()
    }

    # Groups with no scored field at all (every field in that group was
    # excluded -- e.g. Grimaldi's real Father/Mother/Spouse groups, which
    # the ground truth never fills in) simply never appear here, rather
    # than showing an empty/zero row that would misleadingly look scored.
    group_totals: dict[str, dict[str, int]] = {}
    for field, group in field_groups.items():
        if field not in field_totals:
            continue
        bucket = group_totals.setdefault(group, {"edits": 0, "ref_chars": 0})
        bucket["edits"] += field_totals[field]["edits"]
        bucket["ref_chars"] += field_totals[field]["ref_chars"]
    group_error_rate = {
        group: {**totals, "error_rate": rate_or_none(totals["edits"], totals["ref_chars"])}
        for group, totals in group_totals.items()
    }

    overall_edits = sum(totals["edits"] for totals in field_totals.values())
    overall_ref_chars = sum(totals["ref_chars"] for totals in field_totals.values())

    return {
        "matched_count": matched_count,
        "missing_from_candidate": len(alignment.missing_from_candidate),
        "extra_in_candidate": len(alignment.extra_in_candidate),
        "overall_error_rate": rate_or_none(overall_edits, overall_ref_chars),
        "overall_edits": overall_edits,
        "overall_ref_chars": overall_ref_chars,
        "excluded_fields": excluded_fields,
        "field_error_rate": field_error_rate,
        "group_error_rate": group_error_rate,
        "category_counts": dict(Counter(d["category"] for d in diffs)),
        "diffs": diffs,
    }


def _recount_categories(result: dict) -> None:
    result["category_counts"] = dict(Counter(d["category"] for d in result["diffs"]))


def apply_ai_classification(result: dict, api_key: str, model: str) -> None:
    """Mutates `result` (a score_candidate() return value) in place: sends
    only its `unclassified` diffs to the model, batched into ONE call (never
    one call per diff -- see CLAUDE.md's own review notes on why per-record
    AI calls don't scale), and reclassifies whichever ones come back with a
    recognized category. Never raises: if the call fails outright, or comes
    back malformed, the affected diffs are simply left `unclassified` rather
    than losing the rest of an otherwise-complete comparison over one
    optional enhancement."""
    unclassified = [diff for diff in result["diffs"] if diff["category"] == UNCLASSIFIED]
    if not unclassified:
        return
    payload = [
        {
            "index": index,
            "field": diff["field"],
            "truth_value": diff["truth_value"],
            "candidate_value": diff["candidate_value"],
        }
        for index, diff in enumerate(unclassified)
    ]
    user_message = "Differences to classify:\n" + json.dumps(payload, ensure_ascii=False)
    try:
        records = call_ai(api_key, model, _AI_SYSTEM_PROMPT, user_message)
    except Exception:
        return

    resolved: dict[int, tuple[str, str]] = {}
    for record in records:
        index = record.get("index")
        category = record.get("category")
        if isinstance(index, int) and 0 <= index < len(unclassified) and category in _AI_ASSIST_CATEGORIES:
            resolved[index] = (category, str(record.get("rationale") or ""))

    for index, diff in enumerate(unclassified):
        if index in resolved:
            category, rationale = resolved[index]
            diff["category"] = category
            diff["ai_assisted"] = True
            diff["ai_rationale"] = rationale
    _recount_categories(result)


def _field_agreement_counts(rows_a: list[Row], rows_b: list[Row], config: RecordTypeConfig) -> dict[str, dict[str, int]]:
    alignment = align_rows(rows_a, rows_b, config)
    counts = {field: {"agree": 0, "disagree": 0, "with_data": 0} for field in config.fields}
    for row_a, row_b in alignment.matched:
        for field in config.fields:
            value_a = row_a.get(field, "")
            value_b = row_b.get(field, "")
            if is_blank_or_illegible(value_a) and is_blank_or_illegible(value_b):
                continue  # neither side has data for this field -- not informative either way
            counts[field]["with_data"] += 1
            if normalize_for_comparison(value_a) == normalize_for_comparison(value_b):
                counts[field]["agree"] += 1
            else:
                counts[field]["disagree"] += 1
    return counts


def score_agreement(config: RecordTypeConfig, candidates: list[tuple[str, list[Row]]]) -> dict:
    """Agreement mode: no ground truth needed. Every pair of candidates is
    aligned and compared field-by-field (simple normalized-equality, not the
    full classify_diff() taxonomy -- "do these two agree" is a coarser,
    binary question than "why do they differ"), and the counts are summed
    across all pairs into one field-reliability ranking, worst-agreement-
    first -- the same shape and sort order as the Grimaldi example
    workbook's own "Model Disagreements" tab. Useful before a corrected
    index even exists: fields where models already agree are lower-priority
    for a human to double-check than fields where they don't."""
    if len(candidates) < 2:
        raise RuntimeError("Agreement mode needs at least 2 candidates to compare against each other.")

    totals = {field: {"agree": 0, "disagree": 0, "with_data": 0} for field in config.fields}
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            pair_counts = _field_agreement_counts(candidates[i][1], candidates[j][1], config)
            for field, counts in pair_counts.items():
                totals[field]["agree"] += counts["agree"]
                totals[field]["disagree"] += counts["disagree"]
                totals[field]["with_data"] += counts["with_data"]

    field_reliability = [
        {
            "field": field,
            "with_data": counts["with_data"],
            "agree": counts["agree"],
            "disagree": counts["disagree"],
            "agree_pct": round(counts["agree"] / counts["with_data"], 4),
        }
        for field, counts in totals.items()
        if counts["with_data"] > 0
    ]
    field_reliability.sort(key=lambda entry: entry["agree_pct"])

    return {"mode": "agreement", "field_reliability": field_reliability}


def compare_indexes(
    config: RecordTypeConfig,
    ground_truth: tuple[str, list[Row]] | None,
    candidates: list[tuple[str, list[Row]]],
    *,
    use_ai: bool = False,
    api_key: str = "",
    model: str = "",
) -> dict:
    """Top-level entry point: Accuracy mode when a ground-truth (label,
    rows) pair is given, Agreement mode otherwise. AI-assisted
    classification only applies in Accuracy mode -- Agreement mode's
    agree/disagree counting has no `unclassified` bucket to begin with."""
    if not candidates:
        raise RuntimeError("Upload at least one candidate index to compare.")

    if ground_truth is None:
        return score_agreement(config, candidates)

    ground_truth_label, ground_truth_rows = ground_truth
    results = []
    for label, rows in candidates:
        result = score_candidate(ground_truth_rows, rows, config)
        if use_ai and api_key and model:
            apply_ai_classification(result, api_key, model)
        results.append({"label": label, **result})

    return {"mode": "accuracy", "ground_truth_label": ground_truth_label, "candidates": results}
