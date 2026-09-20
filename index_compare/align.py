from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from index_compare.text_utils import is_blank_or_illegible, normalize_for_comparison
from xls_conversion.ai_parser import RecordTypeConfig

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


def _group_rows_by_locator(rows: list[Row], locator_field: str | None) -> dict[str, list[Row]]:
    """Groups rows by normalized locator value (Page #/Act #), preserving
    each row's original file order within its bucket -- e.g. all of page
    34's entries together, in the order they appear in the file. Rows with
    no usable locator (blank, `[illegible]`, or locator_field is None) all
    land in the same "" bucket."""
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        locator = _normalize_locator(row.get(locator_field, "")) if locator_field else ""
        buckets.setdefault(locator, []).append(row)
    return buckets


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


def _score_identity_pairs(
    truth_rows: list[Row],
    candidate_rows: list[Row],
    given_field: str | None,
    last_field: str | None,
    year_field: str | None,
) -> list[tuple[float, int, int]]:
    """Every (truth index, candidate index) pair whose primary-person name
    scores at or above _NAME_MATCH_THRESHOLD -- fuzzy, to tolerate the same
    real-transcript variation the rest of this app already tolerates (Latin
    declension, spelling: "Giovanni" vs "Joannes") -- gated by year when
    both sides state one, since two different people sharing a similar name
    in the same register year is the real collision risk this guards
    against; cross-year name coincidences are exactly what the gate rules
    out instead. Sorted highest-score-first for _assign_best_first()."""
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
    return scored


def _assign_best_first(
    scored: list[tuple[float, int, int]]
) -> tuple[set[int], set[int], list[tuple[int, int]]]:
    """Claims pairs highest-score-first, skipping a row already claimed --
    the same pattern and the same reason as reader.py's suggest_mapping():
    resolving row-by-row in a fixed order would let a mediocre match claim
    a row a later pair would have matched almost perfectly."""
    used_truth: set[int] = set()
    used_candidate: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _score, t_index, c_index in scored:
        if t_index in used_truth or c_index in used_candidate:
            continue
        pairs.append((t_index, c_index))
        used_truth.add(t_index)
        used_candidate.add(c_index)
    return used_truth, used_candidate, pairs


def _match_within_bucket(
    truth_rows: list[Row],
    candidate_rows: list[Row],
    given_field: str | None,
    last_field: str | None,
    year_field: str | None,
) -> tuple[list[tuple[Row, Row]], list[Row], list[Row]]:
    """Pairs the rows sharing one locator value (e.g. every entry on page
    34) by identity first, falling back to position only for whatever
    identity couldn't place (no usable name fields, or no confident match).

    This guards against the exact failure position-only matching had: if
    the candidate is missing the first of three entries on a page, pairing
    purely by position shifts every later row on that page out of sync --
    truth's 2nd entry pairs against the candidate's 1st, the 3rd against
    the 2nd, and the true gap (truth's 1st entry) never gets reported as
    the actual miss. Matching by name (+ year, when available) first
    re-anchors same-identity rows correctly regardless of a hole earlier in
    the page; position is only used to fill in rows identity had nothing to
    say about."""
    scored = _score_identity_pairs(truth_rows, candidate_rows, given_field, last_field, year_field)
    used_truth, used_candidate, pairs = _assign_best_first(scored)

    remaining_truth = [i for i in range(len(truth_rows)) if i not in used_truth]
    remaining_candidate = [i for i in range(len(candidate_rows)) if i not in used_candidate]
    pair_count = min(len(remaining_truth), len(remaining_candidate))
    for i in range(pair_count):
        pairs.append((remaining_truth[i], remaining_candidate[i]))

    # Sorted by the truth row's original position so a bucket's output order
    # always matches its input order, regardless of which rows identity
    # matching happened to resolve first (fuzzy-match score order is not
    # file order) -- keeps behavior independent of scoring internals.
    pairs.sort(key=lambda pair: pair[0])
    matched = [(truth_rows[t], candidate_rows[c]) for t, c in pairs]

    missing = [truth_rows[i] for i in remaining_truth[pair_count:]]
    extra = [candidate_rows[i] for i in remaining_candidate[pair_count:]]
    return matched, missing, extra


def _match_by_identity(
    truth_rows: list[Row], candidate_rows: list[Row], config: RecordTypeConfig
) -> tuple[list[tuple[Row, Row]], list[Row], list[Row]]:
    """Final-pass fallback for whatever per-locator-bucket matching in
    align_rows() couldn't pair -- most often because the ground truth never
    filled in a locator at all (a real case: an indexer tracking records by
    name and date has no reason to also fill in a page-number column just
    for this app's benefit), so every row lands in the shared "" bucket.
    Unlike _match_within_bucket(), there is no positional fallback here:
    rows reaching this pass came from potentially different locator
    buckets, so their relative order carries no meaning to fall back to --
    an identity match or nothing."""
    given_field, last_field, year_field = identity_fields(config)
    if not given_field and not last_field:
        return [], truth_rows, candidate_rows

    scored = _score_identity_pairs(truth_rows, candidate_rows, given_field, last_field, year_field)
    used_truth, used_candidate, pairs = _assign_best_first(scored)
    matched = [(truth_rows[t], candidate_rows[c]) for t, c in pairs]

    still_missing = [row for index, row in enumerate(truth_rows) if index not in used_truth]
    still_extra = [row for index, row in enumerate(candidate_rows) if index not in used_candidate]
    return matched, still_missing, still_extra


@dataclass(frozen=True)
class AlignmentResult:
    matched: list[tuple[Row, Row]] = field(default_factory=list)
    missing_from_candidate: list[Row] = field(default_factory=list)
    extra_in_candidate: list[Row] = field(default_factory=list)


def align_rows(truth_rows: list[Row], candidate_rows: list[Row], config: RecordTypeConfig) -> AlignmentResult:
    """Pair up truth_rows and candidate_rows in two passes. First, group
    both sides by locator (Page #/Act #, per config.carry_forward_fields[0]
    -- reliably the locator field for all 6 real record types, verified
    against RECORD_TYPES) and match *within* each locator bucket by name
    identity first, position only as a fallback (see _match_within_bucket())
    -- matching by position alone, before identity, let one missing entry
    on a page silently shift every later entry on that same page out of
    sync (truth's 2nd/3rd entries pairing against the candidate's 1st/2nd,
    with the true gap never reported). Second, whatever no bucket could
    pair gets one more attempt by name + date identity across the whole
    file instead (see _match_by_identity()) -- added after a real
    ground-truth file (an indexer's own corrected index, tracked by name
    and date, Page #/Image # never filled in at all) produced 0 matched
    rows under locator-only matching, even though every record was
    genuinely present in both files.

    Never silently drops or shifts a row out of sync: a truth row neither
    pass could place ends up in missing_from_candidate, a candidate row
    neither pass could place ends up in extra_in_candidate -- both lists a
    caller can surface to the user rather than a comparison that quietly
    ran short of what it claimed to compare."""
    locator_field = config.carry_forward_fields[0] if config.carry_forward_fields else None
    given_field, last_field, year_field = identity_fields(config)
    truth_buckets = _group_rows_by_locator(truth_rows, locator_field)
    candidate_buckets = _group_rows_by_locator(candidate_rows, locator_field)

    # Truth's own bucket order first, then any locator value that appears
    # only on the candidate side -- deterministic regardless of dict
    # insertion-order quirks, and every bucket on either side gets visited.
    locator_keys = list(truth_buckets) + [key for key in candidate_buckets if key not in truth_buckets]

    matched: list[tuple[Row, Row]] = []
    missing_from_candidate: list[Row] = []
    extra_in_candidate: list[Row] = []
    for key in locator_keys:
        bucket_matched, bucket_missing, bucket_extra = _match_within_bucket(
            truth_buckets.get(key, []), candidate_buckets.get(key, []), given_field, last_field, year_field
        )
        matched.extend(bucket_matched)
        missing_from_candidate.extend(bucket_missing)
        extra_in_candidate.extend(bucket_extra)

    identity_matched, missing_from_candidate, extra_in_candidate = _match_by_identity(
        missing_from_candidate, extra_in_candidate, config
    )
    matched.extend(identity_matched)

    return AlignmentResult(
        matched=matched,
        missing_from_candidate=missing_from_candidate,
        extra_in_candidate=extra_in_candidate,
    )
