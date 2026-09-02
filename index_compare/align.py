from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from xls_conversion.ai_parser import RecordTypeConfig

from index_compare.text_utils import is_blank_or_illegible, normalize_for_comparison

Row = dict[str, str]

# rapidfuzz fuzz.ratio() score (0-100) below which a candidate name+date
# fallback pair (see _match_by_identity()) is not trusted as the same
# record. Calibrated against a real ground-truth file with zero locators
# (Grimaldi Morti): genuine same-person Latin-declension/spelling pairs in
# that data scored 74-100 ("Pietro Nigro"/"Petrus Nigro" = 83.3, "Lucrezia
# Santo"/"Laurentia Santo" = 82.8), while a real different-person collision
# in the same year scored 64.7 ("Giovanni Giardino"/"Joannes Gagliardo") --
# 70 sits in the gap between them.
_NAME_MATCH_THRESHOLD = 70.0


def _normalize_locator(value: object) -> str:
    """Comparison key for one row's locator value (Page #/Act #). Blank and
    an honestly-flagged "[illegible]" both collapse to the same empty-string
    bucket -- see align_rows() for what that bucket means for matching.
    Leading zeros are stripped for a purely-numeric locator ("034" and "34"
    must key the same, since which of the two a given file uses is a
    formatting choice, not a different page)."""
    if is_blank_or_illegible(value):
        return ""
    text = str(value).strip()
    if text.isdigit():
        return str(int(text))
    return text


def _keyed_rows(rows: list[Row], locator_field: str | None) -> dict[tuple[str, int], Row]:
    """Key every row by (locator value, occurrence index) -- occurrence
    index counts repeats of that same locator value in file order, so
    multiple entries on one page/act key uniquely (page 34's 1st, 2nd, 3rd
    entry) instead of colliding. Rows with no usable locator (blank,
    `[illegible]`, or locator_field is None) all normalize to the same ""
    bucket, so they key purely by position among each other -- this IS the
    "sequential position-matching among the other unlocated rows only"
    fallback; no separate code path is needed, just this normalization."""
    counts: dict[str, int] = {}
    keyed: dict[tuple[str, int], Row] = {}
    for row in rows:
        locator = _normalize_locator(row.get(locator_field, "")) if locator_field else ""
        occurrence = counts.get(locator, 0)
        counts[locator] = occurrence + 1
        keyed[(locator, occurrence)] = row
    return keyed


def identity_fields(config: RecordTypeConfig) -> tuple[str | None, str | None, str | None]:
    """(given-name field, last-name field, year field) for the record's
    primary person. The first given/last-name pair in field order is
    always that person for every one of the 6 record types (verified
    against RECORD_TYPES: individual_* for baptism/death/civil records,
    groom_* for marriage records -- father/mother/spouse names always come
    later in field order); the year field is always carry_forward_fields'
    own date element."""
    given_field = next((f for f in config.fields if "given_name" in f), None)
    last_field = next((f for f in config.fields if "last_name" in f), None)
    year_field = next((f for f in config.carry_forward_fields if f.endswith("_year")), None)
    return given_field, last_field, year_field


def _identity_key(
    row: Row, given_field: str | None, last_field: str | None, year_field: str | None
) -> tuple[str, str]:
    given = normalize_for_comparison(row.get(given_field, "")) if given_field else ""
    last = normalize_for_comparison(row.get(last_field, "")) if last_field else ""
    year = str(row.get(year_field, "")).strip() if year_field else ""
    return f"{given} {last}".strip(), year


def _match_by_identity(
    truth_rows: list[Row], candidate_rows: list[Row], config: RecordTypeConfig
) -> tuple[list[tuple[Row, Row]], list[Row], list[Row]]:
    """Second-pass fallback for whatever the locator pass in align_rows()
    couldn't pair -- most often because the ground truth never filled in a
    locator at all (a real case: an indexer tracking records by name and
    date has no reason to also fill in a page-number column just for this
    app's benefit). Matches by the primary person's name -- fuzzy, to
    tolerate the same real-transcript variation the rest of this app
    already tolerates (Latin declension, spelling: "Giovanni" vs
    "Joannes") -- gated by year when both sides state one, since two
    different people sharing a similar name in the same register year is
    the real collision risk this is guarding against; cross-year name
    coincidences are exactly what the gate rules out instead.

    Global-best-first assignment (score every remaining pair, take the
    highest-scoring pairs first, skip a row once claimed): the same
    pattern and the same reason as reader.py's suggest_mapping() --
    resolving row-by-row in a fixed order let a mediocre match claim a row
    a later pair would have matched almost perfectly."""
    given_field, last_field, year_field = identity_fields(config)
    if not given_field and not last_field:
        return [], truth_rows, candidate_rows

    scored: list[tuple[float, int, int]] = []
    for t_index, truth_row in enumerate(truth_rows):
        t_name, t_year = _identity_key(truth_row, given_field, last_field, year_field)
        if not t_name:
            continue
        for c_index, candidate_row in enumerate(candidate_rows):
            c_name, c_year = _identity_key(candidate_row, given_field, last_field, year_field)
            if not c_name:
                continue
            if t_year and c_year and t_year != c_year:
                continue  # different years -- never the same record, regardless of name similarity
            score = fuzz.ratio(t_name, c_name)
            if score >= _NAME_MATCH_THRESHOLD:
                scored.append((score, t_index, c_index))
    scored.sort(key=lambda item: item[0], reverse=True)

    matched: list[tuple[Row, Row]] = []
    used_truth: set[int] = set()
    used_candidate: set[int] = set()
    for _score, t_index, c_index in scored:
        if t_index in used_truth or c_index in used_candidate:
            continue
        matched.append((truth_rows[t_index], candidate_rows[c_index]))
        used_truth.add(t_index)
        used_candidate.add(c_index)

    still_missing = [row for index, row in enumerate(truth_rows) if index not in used_truth]
    still_extra = [row for index, row in enumerate(candidate_rows) if index not in used_candidate]
    return matched, still_missing, still_extra


@dataclass(frozen=True)
class AlignmentResult:
    matched: list[tuple[Row, Row]] = field(default_factory=list)
    missing_from_candidate: list[Row] = field(default_factory=list)
    extra_in_candidate: list[Row] = field(default_factory=list)


def align_rows(truth_rows: list[Row], candidate_rows: list[Row], config: RecordTypeConfig) -> AlignmentResult:
    """Pair up truth_rows and candidate_rows in two passes. First, by
    locator (Page #/Act #, per config.carry_forward_fields[0] -- reliably
    the locator field for all 6 real record types, verified against
    RECORD_TYPES) plus occurrence order within that locator. Second,
    whatever the locator pass leaves unpaired gets one more attempt by
    name + date identity instead (see _match_by_identity()) -- added after
    a real ground-truth file (an indexer's own corrected index, tracked by
    name and date, Page #/Image # never filled in at all) produced 0
    matched rows under locator-only matching, even though every record was
    genuinely present in both files.

    Never silently drops or shifts a row out of sync: a truth row neither
    pass could place ends up in missing_from_candidate, a candidate row
    neither pass could place ends up in extra_in_candidate -- both lists a
    caller can surface to the user rather than a comparison that quietly
    ran short of what it claimed to compare."""
    locator_field = config.carry_forward_fields[0] if config.carry_forward_fields else None
    truth_keyed = _keyed_rows(truth_rows, locator_field)
    candidate_keyed = _keyed_rows(candidate_rows, locator_field)

    matched: list[tuple[Row, Row]] = []
    missing_from_candidate: list[Row] = []
    for key, truth_row in truth_keyed.items():
        candidate_row = candidate_keyed.pop(key, None)
        if candidate_row is None:
            missing_from_candidate.append(truth_row)
        else:
            matched.append((truth_row, candidate_row))
    extra_in_candidate = list(candidate_keyed.values())

    identity_matched, missing_from_candidate, extra_in_candidate = _match_by_identity(
        missing_from_candidate, extra_in_candidate, config
    )
    matched.extend(identity_matched)

    return AlignmentResult(
        matched=matched,
        missing_from_candidate=missing_from_candidate,
        extra_in_candidate=extra_in_candidate,
    )
