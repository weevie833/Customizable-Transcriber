"""The previous row's date is offered to the extractor only when the next
block's own text uses carry-forward wording ("same day", "ejusdem", ...).
Locator fields (page/act number) still ride along. Otherwise one misread date
could silently spread to every later row.
"""

from __future__ import annotations

from xls_conversion import ai_parser

CONFIG = ai_parser.RECORD_TYPES["battesimi"]
PREV = {"page_number": "34", "baptism_year": "1753", "baptism_month": "3", "baptism_day": "9"}


def test_wording_detected_in_english_latin_and_italian():
    for text in (
        "On the same day, a child was born.",
        "Eodem die baptizavi",
        "Ejusdem mensis",
        "nel stesso giorno",
        "il detto giorno",
        "On the aforesaid day",
    ):
        assert ai_parser.block_has_carry_forward_wording(text), text


def test_plain_dated_entry_has_no_wording():
    assert not ai_parser.block_has_carry_forward_wording("On the 23rd day of September 1752, Joseph was baptized.")


def test_dates_withheld_without_wording_but_locator_kept():
    got = ai_parser.carry_forward_for(CONFIG, PREV, "On the 23rd day of September 1752.")
    assert got == {"page_number": "34"}


def test_dates_offered_with_wording():
    got = ai_parser.carry_forward_for(CONFIG, PREV, "On the same day, Maria was baptized.")
    assert got == {k: PREV[k] for k in CONFIG.carry_forward_fields}


TEXT = (
    "--- START OF RECORD: img_001.jpg ---\n\nEnglish Translation: On the 9th day of March 1753, A.\n\n\n"
    "--- START OF RECORD: img_002.jpg ---\n\nEnglish Translation: On the 20th day of May 1753, B.\n\n\n"
    "--- START OF RECORD: img_003.jpg ---\n\nEnglish Translation: On the same day, C.\n"
)


def test_parse_generic_sends_dates_only_to_the_same_day_block(monkeypatch):
    messages = []

    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        messages.append(user_message)
        return [{"page_number": "34", "baptism_year": "1753", "baptism_month": "3", "baptism_day": "9"}]

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    result = ai_parser.parse_generic(
        config=CONFIG, text=TEXT, image_range="", image_overrides="", api_key="k",
        model="gemini-2.5-pro", target_language="English", target_role="", process_all=True,
    )
    assert len(messages) == 3
    assert "baptism_year" not in messages[1]  # dated entry: no date context
    assert "baptism_year" in messages[2]  # "same day": date context offered
    assert any("carry the previous" in str(e) for e in result["exception_log"])
