"""An image block with more than MAX_ENTRIES_PER_CALL entries is split at
entry-locator lines so no single AI call sees an oversized block. Blocks with
no recognisable locators are never split (a wrong cut halves an entry).
"""

from __future__ import annotations

from xls_conversion import ai_parser


def _block(n: int, locator: str = "Page 3 - Entry {i}:") -> str:
    parts = ["--- START OF RECORD: img_007.jpg ---"]
    for i in range(1, n + 1):
        parts.append(locator.format(i=i))
        parts.append(f"Date: day {i}")
        parts.append(f"English Translation: ENTRY-{i}-BODY")
    return "\n\n".join(parts)


def test_small_block_is_not_split():
    text = _block(ai_parser.MAX_ENTRIES_PER_CALL)
    assert ai_parser.chunk_block_by_entries(text) == [text]


def test_large_block_splits_at_locators_and_loses_nothing():
    n = ai_parser.MAX_ENTRIES_PER_CALL * 2 + 3
    chunks = ai_parser.chunk_block_by_entries(_block(n))
    assert len(chunks) == 3
    for chunk in chunks[1:]:
        assert chunk.startswith("Page 3 - Entry ")
    joined = "\n".join(chunks)
    assert all(f"ENTRY-{i}-BODY" in joined for i in range(1, n + 1))
    # every entry's body sits in exactly one chunk, with its own locator
    for i in range(1, n + 1):
        owners = [c for c in chunks if f"ENTRY-{i}-BODY" in c]
        assert len(owners) == 1 and f"Entry {i}:" in owners[0]


def test_act_locators_are_recognised():
    chunks = ai_parser.chunk_block_by_entries(_block(12, "Act {i}:"), max_entries=5)
    assert len(chunks) == 3


def test_block_without_locator_lines_is_left_whole():
    text = "\n\n".join(f"Date: d{i}\n\nEnglish Translation: body {i}" for i in range(30))
    assert ai_parser.chunk_block_by_entries(text) == [text]


def test_parse_generic_makes_one_call_per_chunk(monkeypatch):
    n = ai_parser.MAX_ENTRIES_PER_CALL + 2
    seen = []

    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        seen.append(user_message)
        return []

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    ai_parser.parse_generic(
        config=ai_parser.RECORD_TYPES["battesimi"], text=_block(n), image_range="", image_overrides="",
        api_key="k", model="gemini-3.1-pro-preview", target_language="English", target_role="", process_all=True,
    )
    assert len(seen) == 2
    assert all("Image number for every record in this source block: 007" in m or "007" in m for m in seen)


def test_entry_count_warning_flags_mismatch_only():
    text = _block(4)
    assert ai_parser.entry_count_warning("007", text, 4) is None
    msg = ai_parser.entry_count_warning("007", text, 3)
    assert msg and "4 entries" in msg and "3 row" in msg
    assert ai_parser.entry_count_warning("007", "no locators here", 5) is None


def test_parse_generic_logs_dropped_entry(monkeypatch):
    monkeypatch.setattr(ai_parser, "call_ai", lambda *a, **k: [{"page_number": "3"}] * 2)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    result = ai_parser.parse_generic(
        config=ai_parser.RECORD_TYPES["battesimi"], text=_block(3), image_range="", image_overrides="",
        api_key="k", model="gemini-3.1-pro-preview", target_language="English", target_role="", process_all=True,
    )
    assert any("3 entries but the AI returned 2" in line for line in result["exception_log"])
