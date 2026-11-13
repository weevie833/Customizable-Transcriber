"""reviews/CODEX_REVIEW.md H-2 / HD-2: a continuation merge must not silently erase or change
fields the departure row already had -- original wins, conflicts are logged, and a
different act number means "not the same record" (both rows kept)."""

import pytest

from xls_conversion import ai_parser
from xls_conversion.ai_parser import RECORD_TYPES, apply_merge_invariants


def _row(config, **values):
    row = {field: "" for field in config.fields}
    row.update(values)
    return row


@pytest.mark.parametrize("record_type", sorted(RECORD_TYPES))
def test_blank_never_erases_and_blanks_are_filled_for_every_record_type(record_type):
    config = RECORD_TYPES[record_type]
    data_fields = [f for f in config.fields if f not in ("notes", "image_link", "image_number", "act_number", "page_number")]
    keep, fill = data_fields[0], data_fields[1]
    previous = _row(config, **{keep: "Original", fill: ""})
    merged = _row(config, **{keep: "", fill: "New fact"})

    row, conflicts = apply_merge_invariants(config, previous, merged)

    assert row[keep] == "Original"      # blank continuation value did not erase it
    assert row[fill] == "New fact"      # continuation-only fact filled a blank
    assert conflicts == []


@pytest.mark.parametrize("record_type", sorted(RECORD_TYPES))
def test_conflicting_value_keeps_original_and_is_reported(record_type):
    config = RECORD_TYPES[record_type]
    field = next(f for f in config.fields if f not in ("notes", "image_link", "image_number", "act_number", "page_number"))
    row, conflicts = apply_merge_invariants(config, _row(config, **{field: "Ferrajolo"}), _row(config, **{field: "Ferraiolo"}))
    assert row[field] == "Ferrajolo"
    assert conflicts == [f'{field}: kept "Ferrajolo" (continuation returned "Ferraiolo")']


def test_same_value_differing_only_in_case_or_spacing_is_not_a_conflict():
    config = RECORD_TYPES["civil_birth"]
    row, conflicts = apply_merge_invariants(
        config, _row(config, individual_last_name="Di  Napoli"), _row(config, individual_last_name="di napoli")
    )
    assert conflicts == []


def test_different_act_number_rejects_the_merge():
    config = RECORD_TYPES["civil_birth"]
    row, conflicts = apply_merge_invariants(config, _row(config, act_number="452"), _row(config, act_number="453"))
    assert row is None and conflicts


def test_blank_act_number_on_the_continuation_is_filled_from_the_original():
    config = RECORD_TYPES["civil_birth"]
    row, _ = apply_merge_invariants(config, _row(config, act_number="452"), _row(config, act_number=""))
    assert row["act_number"] == "452"


# --- end to end through parse_generic --------------------------------------

CONFIG = RECORD_TYPES["civil_birth"]
TEXT = (
    "--- START OF RECORD: img_002.jpg ---\n\n"
    "Date: 19 Luglio 1834\n\n"
    "Italian Transcription: Num. 451 OPENING\n\n"
    "Notes: ENTRY CONTINUES ON THE NEXT IMAGE -- the rest of this entry is in the record for img_003.jpg.\n\n\n"
    "--- START OF RECORD: img_003.jpg ---\n\n"
    "Notes: ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- the beginning of this entry is in the record for img_002.jpg.\n\n"
    "Italian Transcription: witnesses ENDING\n"
)


def _run(monkeypatch, fake_call_ai):
    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    return ai_parser.parse_generic(
        config=CONFIG, text=TEXT, image_range="", image_overrides="", api_key="key",
        model="gemini-2.5-pro", target_language="Italian", target_role="", process_all=True,
    )


def test_merge_that_drops_a_field_keeps_it_and_logs_a_conflict(monkeypatch):
    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        if "OPENING" in user_message and "PREVIOUS RECORD" not in user_message:
            return [{"act_number": "451", "father_given_name": "Filippo", "father_last_name": "Ferrajolo", "notes": ""}]
        # The merge call drops the father's surname and changes his given name.
        return [{"act_number": "451", "father_given_name": "Filipo", "father_last_name": "", "notes": "continued from previous image"}]

    result = _run(monkeypatch, fake_call_ai)

    assert len(result["rows"]) == 1
    assert result["rows"][0]["father_last_name"] == "Ferrajolo"
    assert result["rows"][0]["father_given_name"] == "Filippo"
    log = "\n".join(result["exception_log"])
    assert 'father_given_name: kept "Filippo" (continuation returned "Filipo")' in log


def test_merge_returning_a_different_act_keeps_both_rows(monkeypatch):
    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        if "PREVIOUS RECORD WAS FLAGGED" in user_message:
            return [{"act_number": "999", "notes": "continued from previous image"}]
        return [{"act_number": "451", "notes": ""}]

    result = _run(monkeypatch, fake_call_ai)

    assert len(result["rows"]) >= 2
    assert any("different act/entry number" in line for line in result["exception_log"])
