"""Regression tests for xls_conversion.ai_parser.parse_image_range()'s
input caps -- see docs/DESIGN.md's "Security hardening history" section on
the unbounded-range-expansion finding this closes (both here and its
client-side mirror in
xls_conversion/app.js's countImageRangeClientSide(), which isn't
independently unit-testable without a browser)."""

from __future__ import annotations

import pytest

from xls_conversion.ai_parser import (
    MAX_IMAGE_RANGE_SPAN,
    MAX_IMAGES_PER_REQUEST,
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
