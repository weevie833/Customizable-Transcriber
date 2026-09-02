from __future__ import annotations

import io

import openpyxl
from openpyxl.styles import Alignment, Font

from docx_package import strip_xml_illegal_chars
from xls_conversion.ai_parser import RecordTypeConfig
from xls_conversion.spreadsheet_export import sanitize_sheet_name

_BOLD = Font(bold=True)
_WRAP = Alignment(wrap_text=True, vertical="top")


def _field_labels(config: RecordTypeConfig | None) -> dict[str, str]:
    """field -> a human-readable label ("Father Given Name" rather than
    "father_given_name"), combining the group header with the column
    header -- skipped (falls back to the raw field name) when config isn't
    available, which only happens for callers that never pass one
    (existing tests).

    group_headers repeats "" for every column after a group's first (the
    same shape the XLSX export itself renders as one merged header cell
    spanning several columns) -- forward-filled here the same way
    scoring.py's _field_groups() already does, so "Father Last Name" gets
    its "Father" prefix instead of rendering as a bare "Last Name" just
    because it's not literally the first column under that group.

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

# Human-readable labels for heuristics.py's category codes -- shown in the
# report, not the internal wire format.
_CATEGORY_LABELS = {
    "spelling_variant": "Spelling variant",
    "latin_form": "Latin form / title (not an error)",
    "missing": "Missing (blank / illegible on one side)",
    "wrong_value": "Wrong value",
    "differs": "Different person/value",
    "unclassified": "Unclassified (needs review)",
}
_CATEGORY_ORDER = ["differs", "wrong_value", "unclassified", "spelling_variant", "latin_form", "missing"]


def _cell_value(value: object) -> object:
    # Numbers stay numbers (real counts/percentages a user can sum, sort,
    # or filter on in Excel, not text that merely looks numeric) --
    # everything else is coerced to a string and run through
    # strip_xml_illegal_chars() first, since openpyxl raises outright on a
    # raw control character rather than silently dropping it (confirmed:
    # IllegalCharacterError), and this report's cell content ultimately
    # comes from transcribed field values and AI-written rationale text,
    # neither of which is guaranteed clean.
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return strip_xml_illegal_chars(str(value if value is not None else ""))


def _write_row(worksheet, row: int, values: list[object], *, bold: bool = False) -> None:
    for column, value in enumerate(values, start=1):
        cell = worksheet.cell(row=row, column=column, value=_cell_value(value))
        if bold:
            cell.font = _BOLD


def _write_paragraph(worksheet, row: int, text: str, *, span_columns: int, bold: bool = False) -> None:
    """One block of wrapped prose spanning span_columns, for the "what
    these numbers mean" explanatory section -- merged so it reads as a
    paragraph rather than being clipped by column width the way a normal
    cell would be. Row height is set from a rough characters-per-line
    estimate (openpyxl doesn't measure rendered text) so the paragraph is
    visible without the reader having to double-click the row border to
    auto-fit it themselves first."""
    worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span_columns)
    cell = worksheet.cell(row=row, column=1, value=_cell_value(text))
    cell.alignment = _WRAP
    if bold:
        cell.font = _BOLD
    chars_per_line = 16 * max(1, span_columns)  # ~16 chars per narrow column width
    line_count = max(1, -(-len(text) // chars_per_line))  # ceil division
    worksheet.row_dimensions[row].height = 15 * line_count


def _autofit(worksheet, widths: list[int]) -> None:
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = width


def _error_rate_display(error_rate: float | None) -> object:
    """None (score_candidate()'s signal that matched_count was 0 -- nothing
    was actually compared) must never render as 0% or be silently blank;
    both read as "perfect" or "no data either way", when the real meaning
    is "not computed, because nothing matched"."""
    if error_rate is None:
        return "N/A (0 matched)"
    return error_rate


def _build_scorecard_sheet(workbook, result: dict, ground_truth_label: str, config: RecordTypeConfig | None) -> None:
    sheet = workbook.create_sheet(sanitize_sheet_name("Scorecard"))
    candidates = result["candidates"]
    labels = [entry["label"] for entry in candidates]
    truth_label = ground_truth_label or "ground truth"
    span = max(2, len(labels) + 1)
    field_labels = _field_labels(config)

    row = 1
    _write_row(sheet, row, [f"Accuracy Scorecard: {' vs. '.join(labels)} (vs. {truth_label})"], bold=True)
    row += 1
    _write_paragraph(
        sheet,
        row,
        "Ranking below is by character error rate (CER) across every field, the same metric the DOCX "
        "transcript-comparison report uses -- lower is closer to " + truth_label + ". See \"What these "
        "numbers mean\" near the bottom of this sheet before reading too much into any single figure.",
        span_columns=span,
    )
    row += 1

    # Fields the ground truth never fills in are excluded from every number
    # on this sheet (see scoring.py's fields_with_ground_truth_data()) --
    # named here so that's visible, not just true.
    excluded_fields = candidates[0].get("excluded_fields", []) if candidates else []
    if excluded_fields:
        excluded_display = ", ".join(field_labels.get(f, f) for f in excluded_fields)
        _write_paragraph(
            sheet,
            row,
            f"{truth_label} never fills in {len(excluded_fields)} field(s), so they're excluded from every "
            "number on this sheet -- comparing a field with no ground-truth value would only measure how "
            f"much text a candidate invented, not accuracy: {excluded_display}.",
            span_columns=span,
        )
        row += 1
    row += 1

    # --- Overall ranking: the "at a glance, which one is closest" table --
    zero_matched_labels = [entry["label"] for entry in candidates if entry["matched_count"] == 0]
    _write_row(sheet, row, ["Overall Ranking (all fields combined)"], bold=True)
    row += 1
    if zero_matched_labels:
        _write_row(
            sheet,
            row,
            [
                "⚠ "
                + ", ".join(zero_matched_labels)
                + " had 0 matched rows against "
                + truth_label
                + " -- ranked last, not scored, since nothing was actually compared. Check that both "
                "files cover the same records before trusting this comparison."
            ],
        )
        row += 1
    ranked = sorted(
        candidates,
        key=lambda entry: (
            entry["overall_error_rate"] is None,
            entry["overall_error_rate"] if entry["overall_error_rate"] is not None else 0,
        ),
    )
    _write_row(sheet, row, ["Rank", "Candidate", "Error rate (CER)", "Est. character edits", "Reference characters"], bold=True)
    row += 1
    for rank, entry in enumerate(ranked, start=1):
        _write_row(
            sheet,
            row,
            [
                rank,
                entry["label"],
                _error_rate_display(entry["overall_error_rate"]),
                entry["overall_edits"],
                entry["overall_ref_chars"],
            ],
        )
        row += 1
    row += 1

    _write_row(sheet, row, ["Category Counts (why fields differ, not how much correction each needs)"], bold=True)
    row += 1
    _write_row(sheet, row, ["Category"] + labels, bold=True)
    row += 1
    for category in _CATEGORY_ORDER:
        counts = [entry["category_counts"].get(category, 0) for entry in candidates]
        if not any(counts):
            continue
        _write_row(sheet, row, [_CATEGORY_LABELS.get(category, category)] + counts)
        row += 1
    row += 1

    _write_row(sheet, row, ["Rows matched / missing from candidate / extra in candidate"], bold=True)
    row += 1
    _write_row(sheet, row, [""] + labels, bold=True)
    row += 1
    for metric_key, metric_label in (
        ("matched_count", "Matched"),
        ("missing_from_candidate", "Missing from candidate"),
        ("extra_in_candidate", "Extra in candidate"),
    ):
        _write_row(sheet, row, [metric_label] + [entry[metric_key] for entry in candidates])
        row += 1
    row += 1

    _write_row(sheet, row, ["Field-Group Error Rate (character-level; lower = closer match)"], bold=True)
    row += 1
    group_names: list[str] = []
    for entry in candidates:
        for group in entry["group_error_rate"]:
            if group not in group_names:
                group_names.append(group)
    _write_row(sheet, row, ["Group"] + labels, bold=True)
    row += 1
    for group in group_names:
        _write_row(
            sheet,
            row,
            [group]
            + [
                _error_rate_display(entry["group_error_rate"].get(group, {}).get("error_rate"))
                for entry in candidates
            ],
        )
        row += 1
    row += 2

    _write_row(sheet, row, ["What these numbers mean"], bold=True)
    row += 1
    for paragraph in (
        "Error rate (CER) is Levenshtein edit distance -- the number of single-character insertions, "
        "deletions, or substitutions needed to turn a candidate's text into " + truth_label + "'s -- "
        "divided by " + truth_label + "'s own character count for that field or group. 0% means an exact "
        "match; higher is worse, and it CAN exceed 100% when a candidate wrote much more text than the "
        "reference has (an invented value in a field " + truth_label + " left blank, for instance).",
        "\"N/A (0 matched)\" means no rows could be paired between this candidate and " + truth_label + " "
        "at all (see the matched/missing/extra table above) -- there was nothing to score, which is a "
        "different problem than a high error rate and needs checking separately (wrong file uploaded, "
        "non-overlapping page ranges, or a locator field neither side filled in).",
        "\"Est. character edits\" and \"Reference characters\" are the raw counts behind the error rate "
        "percentage -- roughly how many individual character corrections " + truth_label + " would take to "
        "reach, out of how many characters it has in total across every compared field.",
        "Category counts describe WHY a field differs, not how much correction it needs: \"Different "
        "person/value\" and \"Wrong value\" are real errors; \"Spelling variant\" and \"Latin form / title\" "
        "are flagged but not counted as errors (a scribal spelling or a Latin case ending, not a "
        "misreading); \"Missing\" means one side had no value at all; \"Unclassified\" is a difference the "
        "automatic pass couldn't confidently bucket -- turn on AI-assisted classification and run again to "
        "resolve most of these, or check the Compare-<candidate> tab directly. See each Compare-<candidate> "
        "tab for the individual field-by-field differences behind every number on this sheet.",
        "Missing from candidate = a " + truth_label + " record this candidate has no matching row for. "
        "Extra in candidate = a candidate row with no matching " + truth_label + " record. Both are counted "
        "separately from the error rate above, since there's no candidate value to compare against for a "
        "row that was never matched in the first place.",
    ):
        _write_paragraph(sheet, row, paragraph, span_columns=span)
        row += 1

    # Column A is wide enough to carry the explanatory paragraphs above
    # (merged across every column, but width is still set from column A);
    # the candidate columns stay narrow, matching the data tables.
    sheet.column_dimensions["A"].width = 60
    for index in range(2, span + 1):
        sheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = 18


def _build_agreement_sheet(workbook, result: dict) -> None:
    sheet = workbook.create_sheet(sanitize_sheet_name("Disagreements"))
    _write_row(
        sheet,
        1,
        ["Field reliability -- sorted least-agreement first (check these fields hardest)"],
        bold=True,
    )
    _write_row(sheet, 3, ["Field", "Records w/ data", "Agree", "Disagree", "Agree %"], bold=True)
    row = 4
    for entry in result["field_reliability"]:
        _write_row(
            sheet,
            row,
            [entry["field"], entry["with_data"], entry["agree"], entry["disagree"], entry["agree_pct"]],
        )
        row += 1
    _autofit(sheet, [28, 16, 10, 10, 10])


def _build_candidate_sheet(workbook, entry: dict, used_names: list[str], config: RecordTypeConfig | None) -> None:
    field_labels = _field_labels(config)
    name = sanitize_sheet_name(f"Compare {entry['label']}", used=used_names)
    used_names.append(name)
    sheet = workbook.create_sheet(name)
    _write_row(sheet, 1, [f"Ground truth vs. {entry['label']} -- field differences"], bold=True)
    _write_row(sheet, 3, ["Locator", "Field", "Ground truth", entry["label"], "Category", "AI rationale"], bold=True)
    row = 4
    for diff in entry["diffs"]:
        raw_field = diff.get("field", "")
        _write_row(
            sheet,
            row,
            [
                diff.get("locator", ""),
                field_labels.get(raw_field, raw_field),
                diff.get("truth_value", ""),
                diff.get("candidate_value", ""),
                _CATEGORY_LABELS.get(diff.get("category", ""), diff.get("category", "")),
                diff.get("ai_rationale", "") if diff.get("ai_assisted") else "",
            ],
        )
        row += 1
    _autofit(sheet, [12, 26, 26, 26, 30, 40])


def build_index_compare_report(result: dict, ground_truth_label: str = "", config: RecordTypeConfig | None = None) -> bytes:
    """Downloadable XLSX report for one compare_indexes() result -- a
    Scorecard tab plus one Compare-<label> tab per candidate in Accuracy
    mode (result["mode"] == "accuracy"), or a single Disagreements tab in
    Agreement mode. Shaped after the two hand-built example workbooks
    (Scorecard + Compare Gemini/Compare Claude tabs; a Model Disagreements
    tab for the no-ground-truth case) the user shared when this feature was
    designed -- automating what they were building by hand.

    `config` (the record type's RecordTypeConfig) is optional only for
    callers that genuinely have no better option -- when given, field names
    render as their real column labels ("Father's Given Name") rather than
    the internal snake_case wire format ("father_given_name"), everywhere
    a field name appears on this report."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # default blank sheet -- every real sheet is added explicitly below

    if result["mode"] == "agreement":
        _build_agreement_sheet(workbook, result)
    else:
        _build_scorecard_sheet(workbook, result, ground_truth_label, config)
        used_names = ["Scorecard"]
        for entry in result["candidates"]:
            _build_candidate_sheet(workbook, entry, used_names, config)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
