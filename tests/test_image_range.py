"""Regression tests for xls_conversion.ai_parser.parse_image_range()'s
input caps -- see docs/DESIGN.md's "Security hardening history" section on
the unbounded-range-expansion finding this closes (both here and its
client-side mirror in
xls_conversion/app.js's countImageRangeClientSide(), which isn't
independently unit-testable without a browser)."""

from __future__ import annotations

import pytest

from xls_conversion import ai_parser
from xls_conversion.ai_parser import (
    MAX_IMAGE_RANGE_SPAN,
    MAX_IMAGES_PER_REQUEST,
    all_image_numbers_capped,
    parse_image_range,
)


def test_simple_range_expands_correctly():
    assert parse_image_range("3-5") == ["003", "004", "005"]


def test_single_numbers_and_ranges_combine_and_dedupe():
    result = parse_image_range("1, 3-4, 4")
    assert result == ["001", "003", "004"]


def test_huge_range_is_rejected_not_expanded():
    """The exact input reported: a typo like this used to build a
    billion-element list before anything validated it."""
    with pytest.raises(RuntimeError):
        parse_image_range("1-1000000000")


def test_range_exactly_at_span_cap_is_allowed():
    end = MAX_IMAGE_RANGE_SPAN
    result = parse_image_range(f"1-{end}")
    assert len(result) == end


def test_range_one_past_span_cap_is_rejected():
    end = MAX_IMAGE_RANGE_SPAN + 1
    with pytest.raises(RuntimeError):
        parse_image_range(f"1-{end}")


def test_descending_range_is_rejected():
    with pytest.raises(RuntimeError):
        parse_image_range("50-10")


def test_malformed_fragment_is_rejected_not_silently_dropped():
    with pytest.raises(RuntimeError):
        parse_image_range("abc")


def test_total_images_cap_across_multiple_parts():
    span = MAX_IMAGE_RANGE_SPAN
    # Two ranges that individually pass the per-range span cap, but whose
    # combined total exceeds MAX_IMAGES_PER_REQUEST.
    parts = ",".join(
        f"{block * span + 1}-{(block + 1) * span}"
        for block in range((MAX_IMAGES_PER_REQUEST // span) + 2)
    )
    with pytest.raises(RuntimeError):
        parse_image_range(parts)


def test_empty_and_blank_input_returns_empty_list():
    assert parse_image_range("") == []
    assert parse_image_range("   ") == []


def _synthetic_transcript(image_count: int) -> str:
    return "\n\n".join(
        f"--- START OF RECORD: page_{number}.jpg ---\nEntry text." for number in range(1, image_count + 1)
    )


def test_process_all_within_cap_is_allowed():
    text = _synthetic_transcript(5)
    assert all_image_numbers_capped(text) == [f"{n:03d}" for n in range(1, 6)]


def test_process_all_over_cap_is_rejected_not_silently_processed():
    """"Process all" used to derive its image count straight from the
    document with no ceiling at all, unlike parse_image_range()'s typed-range
    path -- a genuinely large document could trigger thousands of sequential,
    billable AI calls in one request with no server-side stop."""
    text = _synthetic_transcript(MAX_IMAGES_PER_REQUEST + 1)
    with pytest.raises(RuntimeError):
        all_image_numbers_capped(text)


def test_repeated_marker_numbers_still_hit_the_block_cap(monkeypatch):
    """reviews/CODEX_REVIEW_2.md finding M-2: all_image_numbers_capped() dedupes
    marker numbers before comparing against the cap, but
    split_image_blocks() (which parse_generic() actually loops over, one AI
    call per entry) emits one block per marker OCCURRENCE, not per distinct
    number. A transcription with the same image number repeated past the
    cap used to sail through the deduped-numbers check while still driving
    thousands of AI calls -- parse_generic() must reject this before making
    any of them, not partway through."""
    repeated_count = MAX_IMAGES_PER_REQUEST + 1
    text = "\n\n".join(
        "--- START OF RECORD: page_001.jpg ---\nEntry text." for _ in range(repeated_count)
    )
    # Confirms the premise: the deduped-numbers check alone does NOT catch
    # this -- every occurrence shares the same number.
    assert all_image_numbers_capped(text) == ["001"]

    calls = {"n": 0}

    def fake_call_ai(*args, **kwargs):
        calls["n"] += 1
        return []

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    with pytest.raises(RuntimeError):
        ai_parser.parse_generic(
            config=ai_parser.RECORD_TYPES["battesimi"],
            text=text,
            image_range="",
            image_overrides="",
            api_key="key",
            model="gemini-3.1-pro-preview",
            target_language="English",
            target_role="",
            process_all=True,
        )
    assert calls["n"] == 0
