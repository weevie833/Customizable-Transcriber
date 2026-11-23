"""reviews/CODEX_REVIEW_8.md H-1: a typed image range must never widen to the
whole document, and an excluded "Index" record must still end the record
before it, so no unselected text reaches the provider."""

from __future__ import annotations

import pytest

from xls_conversion import ai_parser

TEXT = (
    "--- START OF RECORD: reg_001.jpg ---\n\nPAGE-ONE-TEXT\n\n"
    "--- START OF RECORD: Index reg_050.jpg ---\n\nINDEX-PAGE-TEXT\n\n"
    "--- START OF RECORD: reg_002.jpg ---\n\nPAGE-TWO-TEXT\n"
)


def test_unmatched_range_raises_instead_of_returning_whole_document():
    with pytest.raises(RuntimeError, match="None of the selected images"):
        ai_parser.split_image_blocks(TEXT, "3")


def test_unmarked_document_with_range_raises():
    with pytest.raises(RuntimeError, match="no START OF RECORD"):
        ai_parser.split_image_blocks("plain text with no markers", "1")


def test_unmarked_document_allowed_only_with_process_all():
    blocks = ai_parser.split_image_blocks("plain text with no markers", process_all=True)
    assert blocks == [{"image_number": "", "text": "plain text with no markers"}]


def test_excluded_index_page_ends_preceding_block():
    blocks = ai_parser.split_image_blocks(TEXT, "1")
    assert len(blocks) == 1
    assert "PAGE-ONE-TEXT" in blocks[0]["text"]
    assert "INDEX-PAGE-TEXT" not in blocks[0]["text"]


def test_process_all_skips_index_page():
    blocks = ai_parser.split_image_blocks(TEXT, process_all=True)
    joined = "\n".join(block["text"] for block in blocks)
    assert "INDEX-PAGE-TEXT" not in joined
    assert [block["image_number"] for block in blocks] == ["001", "002"]
    assert "050" not in ai_parser.all_image_numbers(TEXT)


def test_requested_image_blocks_stops_at_index_page():
    blocks = ai_parser.requested_image_blocks(TEXT, ["001"])
    assert "INDEX-PAGE-TEXT" not in blocks["001"][0]


def test_language_detection_makes_no_call_for_unmatched_range(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ai_parser, "call_ai_json", lambda *a, **k: calls.append(a[3]) or {"languages": []})
    with pytest.raises(RuntimeError):
        ai_parser.detect_languages(TEXT, "3", "key", "gemini-3.1-pro-preview")
    assert calls == []


def test_language_detection_sample_excludes_index_text(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ai_parser, "call_ai_json", lambda *a, **k: calls.append(a[3]) or {"languages": []})
    ai_parser.detect_languages(TEXT, "1", "key", "gemini-3.1-pro-preview")
    assert len(calls) == 1
    assert "PAGE-ONE-TEXT" in calls[0]
    assert "INDEX-PAGE-TEXT" not in calls[0] and "PAGE-TWO-TEXT" not in calls[0]


# CODEX_REVIEW_2.md H-1: an unnumbered heading ("Appendix.jpg") must end the
# selected record before it, through detection, preflight and conversion.
UNNUMBERED = (
    "--- START OF RECORD: reg_001.jpg ---\n\nPAGE-ONE-TEXT\n\n"
    "--- START OF RECORD: Appendix.jpg ---\n\nAPPENDIX-TEXT\n\n"
    "--- START OF RECORD: reg_002.jpg ---\n\nPAGE-TWO-TEXT\n"
)


@pytest.mark.parametrize("text, leak", [(UNNUMBERED, "APPENDIX-TEXT"), (TEXT, "INDEX-PAGE-TEXT")])
def test_selected_block_stops_at_any_neighbouring_heading(text, leak):
    blocks = ai_parser.split_image_blocks(text, "1")
    assert [block["image_number"] for block in blocks] == ["001"]
    assert leak not in blocks[0]["text"] and "PAGE-TWO-TEXT" not in blocks[0]["text"]
    assert leak not in ai_parser.requested_image_blocks(text, ["001"])["001"][0]


def test_process_all_never_sends_unnumbered_record():
    blocks = ai_parser.split_image_blocks(UNNUMBERED, process_all=True)
    assert [block["image_number"] for block in blocks] == ["001", "002"]
    assert "APPENDIX-TEXT" not in "\n".join(block["text"] for block in blocks)


def test_blank_range_without_process_all_is_rejected():
    with pytest.raises(RuntimeError, match="Select an image range"):
        ai_parser.split_image_blocks(UNNUMBERED, "")


def test_blank_range_language_detection_makes_no_call(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ai_parser, "call_ai_json", lambda *a, **k: calls.append(a[3]) or {"languages": []})
    with pytest.raises(RuntimeError):
        ai_parser.detect_languages(UNNUMBERED, "", "key", "gemini-3.1-pro-preview")
    assert calls == []


def test_language_detection_sample_excludes_unnumbered_neighbour(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ai_parser, "call_ai_json", lambda *a, **k: calls.append(a[3]) or {"languages": []})
    ai_parser.detect_languages(UNNUMBERED, "1", "key", "gemini-3.1-pro-preview")
    assert "APPENDIX-TEXT" not in calls[0] and "PAGE-TWO-TEXT" not in calls[0]


def _capture_provider_messages(monkeypatch):
    sent: list[str] = []

    def fake_call(api_key, model, system_prompt, message, *args, **kwargs):
        sent.append(message)
        return {"entries": [], "records": [], "rows": []}

    monkeypatch.setattr(ai_parser, "call_ai_json", fake_call)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    monkeypatch.setattr(ai_parser.usage_ledger, "run", lambda **k: __import__("contextlib").nullcontext())
    return sent


def test_preflight_sends_only_the_selected_record(monkeypatch):
    sent = _capture_provider_messages(monkeypatch)
    ai_parser.preflight_records_with_ai(
        "civil_death", UNNUMBERED, "1", "key", "gemini-3.1-pro-preview", "English", "translation",
    )
    assert sent and all("APPENDIX-TEXT" not in m and "PAGE-TWO-TEXT" not in m for m in sent)


def test_conversion_sends_only_the_selected_record(monkeypatch):
    sent = _capture_provider_messages(monkeypatch)
    try:
        ai_parser.parse_records_with_ai(
            "civil_death", UNNUMBERED, "1", "", "key", "gemini-3.1-pro-preview", "English", "translation",
        )
    except RuntimeError:
        pass  # an empty fake extraction may be reported as a failure; only what was sent matters
    assert sent and all("APPENDIX-TEXT" not in m and "PAGE-TWO-TEXT" not in m for m in sent)
