"""Index Compare's downloadable report -- a DOCX distilling each
candidate's statistical accuracy against a corrected/ground-truth index,
shaped after test_mode/report_docx.py's own transcript-comparison report
(same report_docx_builder.py building blocks, same "ranking table + plain-
language explanation" structure) rather than the hand-built example
workbooks (Scorecard + Compare-Gemini/Compare-Claude tabs) this feature
was originally designed around.

Deliberately does NOT include a per-candidate table of individual field
differences (what report_xlsx.py's now-deleted Compare-<label> tabs showed).
The user's own indexing workflow reviews every row of the corrected index
against each AI-generated index by eye regardless -- a per-entry error list
adds no value on top of that, and would only turn this into a second
XLSX-shaped tool. What this report answers instead is the one question a
row-by-row read can't: which candidate is, in aggregate, statistically
closer to the corrected index -- so the user can decide which AI model to
run for real, before doing that by-eye pass. Category counts (Spelling
variant / Latin form / Wrong value / Differs / Missing) are kept, but only
as aggregate totals per candidate, not tied to any individual row -- same
distinction test_mode/report_docx.py already draws between "how much
correction is needed" and "why", just applied to spreadsheet fields instead
of transcript characters.

Accuracy mode only (a ground-truth file is required) -- Agreement mode
(candidates compared only to each other, no ground truth) and AI-assisted
diff classification were both dropped when this report was rebuilt as a
DOCX; see docs/DESIGN.md's "Index Compare" section for why."""

from __future__ import annotations

from datetime import datetime

from report_docx_builder import assemble_docx_bytes, report_document_xml, report_paragraph, report_table
from xls_conversion.ai_parser import RecordTypeConfig

Row = dict[str, str]

# Human-readable labels for heuristics.py's category codes -- shown in the
# report, not the internal wire format.
_CATEGORY_LABELS = {
    "spelling_variant": "Spelling variant",
    "latin_form": "Latin form / title (not an error)",
    "missing": "Missing (blank / illegible on one side)",
    "wrong_value": "Wrong value",
    "differs": "Different person/value",
    "unclassified": "Unclassified (couldn't be auto-bucketed)",
}
_CATEGORY_ORDER = ["differs", "wrong_value", "unclassified", "spelling_variant", "latin_form", "missing"]


def _field_labels(config: RecordTypeConfig | None) -> dict[str, str]:
    """field -> a human-readable label ("Father Given Name" rather than
    "father_given_name"), combining the group header with the column
    header -- used only for the excluded-fields note below, so a reader
    sees real column names rather than internal snake_case field keys.
    Skipped (falls back to the raw field name) when config isn't available.

    group_headers repeats "" for every column after a group's first (the
    same shape the XLSX export itself renders as one merged header cell
    spanning several columns) -- forward-filled here so "Father Last Name"
    gets its "Father" prefix instead of rendering as a bare "Last Name"
    just because it's not literally the first column under that group.

    Skipped entirely when the column header already restates the group
    header's own words (case-insensitively) -- two real cases in this
    app's own templates: group "Notes" + column "Notes" would otherwise
    render as "Notes Notes", and group "Image Link" + column "Link to
    Image" would render as "Image Link Link to Image"."""
    if config is None:
        return {}
    labels: dict[str, str] = {}
    current_group = ""
    for field, group_label, column_label in zip(config.fields, config.group_headers, config.column_headers):
        if group_label:
            current_group = group_label
        group_words = current_group.casefold().split()
        column_words = set(column_label.casefold().split())
        if current_group and not all(word in column_words for word in group_words):
            labels[field] = f"{current_group} {column_label}"
        else:
            labels[field] = column_label
    return labels


def _error_rate_display(error_rate: float | None) -> str:
    """None (score_candidate()'s signal that matched_count was 0 -- nothing
    was actually compared) must never render as 0% or be silently blank;
    both read as "perfect" or "no data either way", when the real meaning
    is "not computed, because nothing matched". Otherwise formatted the
    same way test_mode/report_docx.py already formats CER/WER/WER-BoW, so
    a reader who has seen that report finds this one familiar."""
    if error_rate is None:
        return "N/A (0 matched)"
    return f"{error_rate * 100:.2f}%"


def build_index_compare_report(result: dict, ground_truth_label: str = "", config: RecordTypeConfig | None = None) -> bytes:
    """Downloadable DOCX report for one compare_indexes() result. Accuracy
    mode only -- `result["mode"]` must be "accuracy" (compare_indexes()
    itself now requires a ground-truth file, so this should always be true
    for a result it produced; the check below is a defensive guard against
    a caller handing in something else, not a real code path).

    `config` (the record type's RecordTypeConfig) is optional only for
    callers that genuinely have no better option -- when given, the
    excluded-fields note names real column labels ("Father's Given Name")
    rather than the internal snake_case wire format ("father_given_name")."""
    if result.get("mode") != "accuracy":
        raise RuntimeError("Index Compare reports require a corrected/ground-truth index to compare against.")

    candidates = result["candidates"]
    labels = [entry["label"] for entry in candidates]
    truth_label = ground_truth_label or "the ground truth"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    field_labels = _field_labels(config)

    elements = [
        report_paragraph("Index Comparison Report", bold=True, size_half_points=32, space_after_twips=80),
        report_paragraph(f"Generated {generated}", space_after_twips=40),
        report_paragraph(f"Ground truth used: {truth_label}", space_after_twips=300),
    ]

    # Fields the ground truth never fills in are excluded from every number
    # in this report (see scoring.py's fields_with_ground_truth_data()) --
    # named here so that's visible, not just true.
    excluded_fields = candidates[0].get("excluded_fields", []) if candidates else []
    if excluded_fields:
        excluded_display = ", ".join(field_labels.get(f, f) for f in excluded_fields)
        elements.append(
            report_paragraph(
                f"{truth_label} never fills in {len(excluded_fields)} field(s), so they're excluded from every "
                "number in this report -- comparing a field with no ground-truth value would only measure how "
                f"much text a candidate invented, not accuracy: {excluded_display}.",
                space_after_twips=200,
            )
        )

    zero_matched_labels = [entry["label"] for entry in candidates if entry["matched_count"] == 0]
    if zero_matched_labels:
        elements.append(
            report_paragraph(
                "⚠ "
                + ", ".join(zero_matched_labels)
                + " had 0 matched rows against "
                + truth_label
                + " -- ranked last, not scored, since nothing was actually compared. Check that both files "
                "cover the same records before trusting this comparison.",
                space_after_twips=200,
            )
        )

    elements.append(
        report_paragraph(
            "Results: Character Error Rate (lower = closer to " + truth_label + ", less correction required)",
            bold=True,
            size_half_points=26,
            space_after_twips=120,
        )
    )
    ranked = sorted(
        candidates,
        key=lambda entry: (
            entry["overall_error_rate"] is None,
            entry["overall_error_rate"] if entry["overall_error_rate"] is not None else 0,
        ),
    )
    elements.append(
        report_table(
            [["Rank", "Candidate", "Error rate (CER)", "Est. character edits", "Reference characters"]]
            + [
                [
                    str(rank),
                    entry["label"],
                    _error_rate_display(entry["overall_error_rate"]),
                    str(entry["overall_edits"]),
                    str(entry["overall_ref_chars"]),
                ]
                for rank, entry in enumerate(ranked, start=1)
            ]
        )
    )

    elements.append(report_paragraph("", space_after_twips=200))
    elements.append(
        report_paragraph(
            "Rows matched / missing from candidate / extra in candidate",
            bold=True,
            size_half_points=26,
            space_after_twips=120,
        )
    )
    elements.append(
        report_table(
            [["Candidate", "Matched", "Missing from candidate", "Extra in candidate"]]
            + [
                [
                    entry["label"],
                    str(entry["matched_count"]),
                    str(entry["missing_from_candidate"]),
                    str(entry["extra_in_candidate"]),
                ]
                for entry in candidates
            ]
        )
    )

    # Groups with no scored field at all never appear in any candidate's
    # group_error_rate (see scoring.py's score_candidate()) -- collected
    # here in first-seen order across candidates rather than assumed from
    # config, so a group only shows up when there's real data behind it.
    group_names: list[str] = []
    for entry in candidates:
        for group in entry["group_error_rate"]:
            if group not in group_names:
                group_names.append(group)
    if group_names:
        elements.append(report_paragraph("", space_after_twips=200))
        elements.append(
            report_paragraph(
                "Field-Group Error Rate (lower = closer match)",
                bold=True,
                size_half_points=26,
                space_after_twips=120,
            )
        )
        elements.append(
            report_table(
                [["Group"] + labels]
                + [
                    [group]
                    + [
                        _error_rate_display(entry["group_error_rate"].get(group, {}).get("error_rate"))
                        for entry in candidates
                    ]
                    for group in group_names
                ]
            )
        )

    elements.append(report_paragraph("", space_after_twips=200))
    elements.append(
        report_paragraph(
            "Category Counts (why fields differ, not how much correction each needs)",
            bold=True,
            size_half_points=26,
            space_after_twips=120,
        )
    )
    category_rows = [["Category"] + labels]
    for category in _CATEGORY_ORDER:
        counts = [entry["category_counts"].get(category, 0) for entry in candidates]
        if not any(counts):
            continue
        category_rows.append([_CATEGORY_LABELS.get(category, category)] + [str(c) for c in counts])
    if len(category_rows) > 1:
        elements.append(report_table(category_rows))
    else:
        elements.append(
            report_paragraph(
                f"No differences to categorize -- every candidate matched {truth_label} exactly on every "
                "scored field.",
                space_after_twips=200,
            )
        )

    elements.append(report_paragraph("", space_after_twips=200))
    elements.append(report_paragraph("What these numbers mean", bold=True, size_half_points=26, space_after_twips=120))
    elements.append(
        report_paragraph(
            "Error rate (CER) is Levenshtein edit distance -- the number of single-character insertions, "
            "deletions, or substitutions needed to turn a candidate's field values into " + truth_label + "'s -- "
            "divided by " + truth_label + "'s own character count for that field or group. 0% means an exact "
            "match; higher is worse, and it CAN exceed 100% when a candidate wrote much more text than the "
            "reference has (an invented value in a field " + truth_label + " left blank, for instance). This is "
            "the same metric the transcript-comparison report uses.",
            space_after_twips=200,
        )
    )
    elements.append(
        report_paragraph(
            "“N/A (0 matched)” means no rows could be paired between this candidate and " + truth_label
            + " at all (see the matched/missing/extra table above) -- there was nothing to score, which is a "
            "different problem than a high error rate and needs checking separately (wrong file uploaded, "
            "non-overlapping page ranges, or a locator field neither side filled in).",
            space_after_twips=200,
        )
    )
    elements.append(
        report_paragraph(
            "Missing from candidate = a " + truth_label + " record this candidate has no matching row for. "
            "Extra in candidate = a candidate row with no matching " + truth_label + " record. Both are "
            "counted separately from the error rate above, since there's no candidate value to compare against "
            "for a row that was never matched in the first place.",
            space_after_twips=200,
        )
    )
    elements.append(
        report_paragraph(
            "Category counts describe WHY fields differ, in aggregate, not how much correction is needed or "
            "which rows are involved: “Different person/value” and “Wrong value” are real "
            "errors; “Spelling variant” and “Latin form / title” are flagged but not counted "
            "as errors (a scribal spelling or a Latin case ending, not a misreading); “Missing” means "
            "one side had no value at all; “Unclassified” is a difference too ambiguous for the "
            "automatic pass to confidently bucket.",
            space_after_twips=200,
        )
    )
    elements.append(
        report_paragraph(
            "This report intentionally does not list individual field differences row by row -- use it to "
            "decide which model's output is worth running with, then review that candidate's index against "
            + truth_label
            + " by eye to find and fix the specific entries a prompt profile is getting wrong.",
            space_after_twips=0,
        )
    )

    document_xml_bytes = report_document_xml(elements)
    return assemble_docx_bytes(document_xml_bytes)
