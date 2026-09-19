"""A transcription block that opens with a flagged continuation fragment (the
tail of the previous image's last act) is split into fragment + remainder and
the fragment is merged into the previous row in its own AI call.

Regression for a real Napoli Stella Matrimoni 1823 run: image 3 held the end
of act 1 followed by all of act 2. Handing the whole block to the model with
the previous row as context let it drop the fragment (act 1 lost its four
witnesses). Image 4 then held the end of act 2, but act 2's row had lost its
"continues on the next image" note during extraction, and the fragment's own
note said "previous page" instead of "previous image", so neither merge
trigger fired and an orphaned blank "act 2" row was exported.
"""

from __future__ import annotations

import xls_conversion.ai_parser as ai_parser

CONFIG = ai_parser.RECORD_TYPES["civil_marriage"]

TEXT = (
    "--- START OF RECORD: img_002.jpg ---\n\n"
    "Date: 2 Gennaro 1823 [2 January 1823]\n\n"
    "Notes: Entry appears to continue on the next image.\n\n"
    "Italian Transcription: Numero d'Ordine Uno. ACT-ONE-OPENING\n\n"
    "English Translation: On the 2nd day of January 1823. ACT-ONE-OPENING-EN\n\n"
    "Church Wedding Record: ACT-ONE-COLUMN\n\n\n"
    "--- START OF RECORD: img_003.jpg ---\n\n"
    "Notes: Entry appears to continue from the previous image.\n\n"
    "Italian Transcription: ACT-ONE-ENDING witnesses Chianese\n\n"
    "English Translation: ACT-ONE-ENDING-EN\n\n"
    "Date: 2 Gennaro 1823 [2 January 1823]\n\n"
    "Notes: Entry appears to continue on the next image.\n\n"
    "Italian Transcription: Numero d'Ordine 2 ACT-TWO-OPENING\n\n"
    "English Translation: On the 2nd day of January 1823. ACT-TWO-OPENING-EN\n\n\n"
    "--- START OF RECORD: img_004.jpg ---\n\n"
    "Notes: Entry appears to continue from the previous image.\n\n"
    "Italian Transcription: ACT-TWO-ENDING witnesses Negro\n\n"
    "English Translation: ACT-TWO-ENDING-EN\n"
)


def _run(monkeypatch, fake_call_ai):
    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    return ai_parser.parse_generic(
        config=CONFIG, text=TEXT, image_range="", image_overrides="", api_key="key",
        model="gemini-2.5-pro", target_language="English", target_role="", process_all=True,
    )


def test_split_leading_continuation_separates_fragment_from_next_act():
    block = ai_parser.split_image_blocks(TEXT, process_all=True)[1]["text"]
    fragment, remainder = ai_parser.split_leading_continuation(block)
    assert "ACT-ONE-ENDING" in fragment and "ACT-TWO-OPENING" not in fragment
    assert "ACT-TWO-OPENING" in remainder and "ACT-ONE-ENDING" not in remainder
    assert remainder.startswith("--- START OF RECORD: img_003.jpg ---")


def test_split_leaves_a_block_without_a_flagged_fragment_alone():
    block = ai_parser.split_image_blocks(TEXT, process_all=True)[0]["text"]
    assert ai_parser.split_leading_continuation(block) == (None, block)


def test_whole_block_fragment_has_no_remainder():
    block = ai_parser.split_image_blocks(TEXT, process_all=True)[2]["text"]
    fragment, remainder = ai_parser.split_leading_continuation(block)
    assert fragment == block and remainder == ""


def test_fragments_merge_even_when_the_model_drops_flags_and_paraphrases(monkeypatch):
    calls = []

    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        calls.append(user_message)
        if "ACT-ONE-OPENING" in user_message and "PREVIOUS RECORD" not in user_message:
            return [{"act_number": "1", "notes": "Church wedding on 2 January."}]  # no continuation flag kept
        if "PREVIOUS RECORD WAS FLAGGED" in user_message:
            # The model's own wording is deliberately unconventional ("page").
            prior = "act 1" if "ACT-ONE-ENDING" in user_message else "act 2"
            return [{"act_number": prior[-1], "notes": f"Entry continues from previous page; witnesses ({prior})"}]
        assert "ACT-TWO-OPENING" in user_message
        # The rest-of-block call must not carry merge context.
        assert "PREVIOUS RECORD WAS FLAGGED" not in user_message
        assert "ACT-ONE-ENDING" not in user_message
        return [{"act_number": "2", "notes": "no continuation flag kept"}]

    result = _run(monkeypatch, fake_call_ai)

    assert [row["act_number"] for row in result["rows"]] == ["1", "2"]
    # Real information survives; the "continues from previous page" bookkeeping
    # clause does not.
    assert result["rows"][0]["notes"] == "witnesses (act 1)"
    assert result["rows"][1]["notes"] == "witnesses (act 2)"
    # The act starts on its departure image: that stays the row's image link.
    assert [row["image_link"] for row in result["rows"]] == ["002", "003"]
    assert result["missing_images"] == []
    assert len(calls) == 4  # act 1 | fragment 1 | rest of image 3 | fragment 2


def test_failed_fragment_merge_falls_back_to_extracting_the_whole_block(monkeypatch):
    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        if "PREVIOUS RECORD WAS FLAGGED" in user_message:
            return []
        return [{"act_number": "9", "notes": ""}]

    result = _run(monkeypatch, fake_call_ai)

    assert any("continuation merge failed" in line for line in result["exception_log"])
    assert len(result["rows"]) >= 2  # nothing silently dropped


def test_civil_marriage_prompt_keeps_the_church_wedding_out_of_notes():
    prompt = ai_parser.CIVIL_MARRIAGE_SYSTEM_PROMPT
    assert "Never record the church wedding in notes" in prompt
    assert "Church Wedding Record" in prompt


# --- an entry still open at the end of the run gets flagged ----------------

OPEN_TEXT = (
    "--- START OF RECORD: img_003.jpg ---\n\n"
    "Date: 2 Gennaro 1823\n\n"
    "Notes: Entry appears to continue on the next image.\n\n"
    "Italian Transcription: Numero d'Ordine 3 ACT-THREE-OPENING\n\n"
    "English Translation: On the 2nd day of January 1823. ACT-THREE-EN\n"
)


def _run_text(monkeypatch, text, fake_call_ai, language="English"):
    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    return ai_parser.parse_generic(
        config=CONFIG, text=text, image_range="", image_overrides="", api_key="key",
        model="gemini-2.5-pro", target_language=language, target_role="", process_all=True,
    )


def test_open_last_entry_gets_a_flag_even_when_the_model_drops_the_note(monkeypatch):
    def fake_call_ai(*args, **kwargs):
        return [{"act_number": "3", "notes": "Church wedding on 26 January"}]

    result = _run_text(monkeypatch, OPEN_TEXT, fake_call_ai)

    assert result["rows"][-1]["notes"].endswith(ai_parser.OPEN_ENTRY_NOTE)
    assert "Entry continues on the next image (not included" in result["rows"][-1]["notes"]


def test_open_entry_flag_replaces_the_models_own_wording_and_follows_the_language(monkeypatch):
    def fake_call_ai(*args, **kwargs):
        return [{"act_number": "3", "notes": "Entry continues on the next image; bride is a widow"}]

    result = _run_text(monkeypatch, OPEN_TEXT, fake_call_ai, language="Italian")

    assert result["rows"][-1]["notes"] == (
        "bride is a widow; " + ai_parser.OPEN_ENTRY_NOTE_TRANSLATIONS["italian"]
    )


def test_a_completed_last_entry_is_not_flagged(monkeypatch):
    closed = OPEN_TEXT.replace("Notes: Entry appears to continue on the next image.\n\n", "")

    def fake_call_ai(*args, **kwargs):
        return [{"act_number": "3", "notes": ""}]

    result = _run_text(monkeypatch, closed, fake_call_ai)
    assert result["rows"][-1]["notes"] == ""


def test_block_ends_with_open_entry_ignores_a_flag_on_an_earlier_entry():
    text = (
        "Notes: Entry appears to continue on the next image.\n\n"
        "Italian Transcription: a\n\nEnglish Translation: a\n\n"
        "Date: 1 Gennaro 1823\n\n"
        "Notes: bride is a widow\n\n"
        "Italian Transcription: b\n\nEnglish Translation: b\n"
    )
    assert ai_parser.block_ends_with_open_entry(text) is False
    assert ai_parser.block_ends_with_open_entry(OPEN_TEXT) is True


def test_occupations_start_with_a_capital_but_keep_the_rest():
    rows = ai_parser.normalize_rows(
        CONFIG,
        [{"groom_occupation": "buyer", "bride_occupation": "Marble worker"}, {"groom_occupation": "city Officer"}],
        "002",
    )
    assert [r["groom_occupation"] for r in rows] == ["Buyer", "City Officer"]
    assert rows[0]["bride_occupation"] == "Marble worker"


# --- preflight counts entries, not continuation fragments or side blocks ----

def _preflight(monkeypatch, entries_by_image):
    def fake_call_ai_json(api_key, model, prompt, user_message, *_a, **_k):
        for image, entries in entries_by_image.items():
            if f"Requested image number: {image}" in user_message:
                return {"entries": entries}
        return {"entries": []}

    monkeypatch.setattr(ai_parser, "call_ai_json", fake_call_ai_json)
    return ai_parser.preflight_generic(
        text=TEXT, image_range="", api_key="key", model="gemini-2.5-pro",
        target_language="English", target_role="translation", process_all=True,
    )


def test_preflight_prompt_tells_the_model_about_side_blocks_and_fragments():
    prompt = ai_parser.preflight_prompt_for("English", "translation")
    assert "Church Wedding Record" in prompt
    assert "continues_previous_entry" in prompt


def test_preflight_does_not_count_a_continuation_fragment_as_an_entry(monkeypatch):
    result = _preflight(monkeypatch, {
        "002": [{"entry_identifier": "1", "target_material_present": True}],
        "003": [
            {"entry_identifier": "continuation", "continues_previous_entry": True, "target_material_present": True},
            {"entry_identifier": "2", "continues_previous_entry": False, "target_material_present": True},
        ],
        "004": [
            {"entry_identifier": "continuation", "continues_previous_entry": True, "target_material_present": True},
        ],
    })
    assert result["entries_reviewed"] == 2
    assert result["target_material_found"] == 2
    assert result["issues"] == []


def test_preflight_still_reports_a_continuation_with_no_translation(monkeypatch):
    result = _preflight(monkeypatch, {
        "002": [{"entry_identifier": "1", "target_material_present": True}],
        "003": [{"entry_identifier": "", "continues_previous_entry": True, "target_material_present": False}],
        "004": [{"entry_identifier": "3", "target_material_present": True}],
    })
    assert result["entries_reviewed"] == 2
    assert [i["code"] for i in result["issues"]] == ["target_material_missing"]
    assert result["issues"][0]["entry_identifier"] == "(continuation)"
