"""Regression tests for xls_conversion/ai_parser.py's crossed-out-entry
handling in normalize_rows() -- the row-level note that flags an entry the
AI extraction marked crossed_out."""

from __future__ import annotations

from xls_conversion.ai_parser import CROSSED_OUT_NOTE, RECORD_TYPES, normalize_rows

BATTESIMI = RECORD_TYPES["battesimi"]


def test_crossed_out_note_does_not_claim_no_reason_was_given():
    # Regression: an earlier version of CROSSED_OUT_NOTE unconditionally
    # asserted "reason not stated in source", even when the AI's own
    # extracted notes explicitly state one -- a false statement landing in
    # the exported spreadsheet.
    assert "reason not stated" not in CROSSED_OUT_NOTE.lower()
    assert CROSSED_OUT_NOTE == "Entry crossed out by scribe in original record."


def test_crossed_out_row_preserves_a_stated_reason_instead_of_contradicting_it():
    records = [
        {
            "crossed_out": "true",
            "notes": "Marked invalid by the scribe; duplicate of the previous entry.",
        }
    ]
    rows = normalize_rows(BATTESIMI, records, image_number="12")
    notes = rows[0]["notes"]
    assert notes.startswith(CROSSED_OUT_NOTE)
    assert "duplicate of the previous entry" in notes
    assert "reason not stated" not in notes.lower()


def test_crossed_out_row_with_no_stated_reason_gets_only_the_neutral_marker():
    records = [{"crossed_out": "true", "notes": ""}]
    rows = normalize_rows(BATTESIMI, records, image_number="12")
    assert rows[0]["notes"] == CROSSED_OUT_NOTE


def test_non_crossed_out_row_notes_are_untouched():
    records = [{"crossed_out": "false", "notes": "An ordinary correction, not a cancellation."}]
    rows = normalize_rows(BATTESIMI, records, image_number="12")
    assert rows[0]["notes"] == "An ordinary correction, not a cancellation."
    assert CROSSED_OUT_NOTE not in rows[0]["notes"]


def test_crossed_out_flag_is_not_duplicated_if_the_ai_already_wrote_it():
    records = [{"crossed_out": "true", "notes": CROSSED_OUT_NOTE + " Duplicate of prior entry."}]
    rows = normalize_rows(BATTESIMI, records, image_number="12")
    assert rows[0]["notes"].lower().count(CROSSED_OUT_NOTE.lower()) == 1
