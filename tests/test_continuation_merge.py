"""Regression tests for parse_generic()'s split-entry continuation handling
-- an entry whose content spans two consecutive source images, merged
rather than exported as two separate, truncated entries (see
docs/DESIGN.md's "Test Mode scoring" section). Added after the merge logic
was found, across two follow-up review passes, to still duplicate, drop,
or silently overwrite rows in some cases.

Both the forward-flag path (previous row's own notes say "...continues on
the next image") and the backward-flag retry path (this block's first row
says "...continues from the previous image" with no forward flag ever
having fired) must:

  * replace the previous partial row with the merged row rather than
    appending it alongside the original (no duplicate spreadsheet rows for
    one historical record),
  * fall back to the original, unmerged extraction -- never silently drop
    it -- when the merge retry itself fails or comes back empty, and
  * fall back to keeping BOTH the previous row and this block's own
    extraction -- never destroy the previous row -- when a continuation
    flag fired (correctly or as a false positive) but the AI's response
    doesn't itself confirm a merge happened (see
    _confirms_continuation_merge in ai_parser.py). Trusting row position
    alone here would let a false-positive flag, or a flag the model simply
    didn't comply with, silently discard a real record.
"""

from __future__ import annotations

from xls_conversion import ai_parser

CONFIG = ai_parser.RECORD_TYPES["battesimi"]

TEXT = (
    "--- START OF RECORD: image_001.jpg ---\n\nfirst block\n\n"
    "--- START OF RECORD: image_002.jpg ---\n\nsecond block\n"
)


def _run(monkeypatch, fake_call_ai):
    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    return ai_parser.parse_generic(
        config=CONFIG,
        text=TEXT,
        image_range="",
        image_overrides="",
        api_key="key",
        model="gemini-3.1-pro-preview",
        target_language="English",
        target_role="",
        process_all=True,
    )


def test_forward_flagged_merge_replaces_not_appends(monkeypatch):
    """Image 1 flags forward ("...continues on the next image"). Image 2's
    call is instructed to return one merged row; it does. The output must
    contain exactly one row for this record, not two."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {
                    "individual_given_name": "Giuseppe",
                    "notes": "Entry appears to continue on the next image.",
                }
            ]
        assert "PREVIOUS RECORD WAS FLAGGED" in user_message
        return [
            {
                "individual_given_name": "Giuseppe",
                "notes": "continued from previous image.",
            }
        ]

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 2
    assert len(result["rows"]) == 1
    # The merge note is bookkeeping once the merge succeeded -- stripped from
    # the exported row so it doesn't clutter the index.
    assert result["rows"][0]["notes"] == ""
    # Both source images still count as found, even though only one row
    # survives the merge.
    assert result["missing_images"] == []
    assert "_source_images" not in result["rows"][0]
    assert "_image_number" not in result["rows"][0]


def test_backward_flag_retry_merge_replaces_not_appends(monkeypatch):
    """Neither image ever flags forward; image 2's first extracted row
    independently says it continues the previous one. The retry succeeds
    with a merged row -- output must be one row, not two."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"individual_given_name": "Anna", "notes": ""}]
        if calls["n"] == 2:
            # Ordinary (non-flagged) call for image 2 -- its own first row
            # says it's a continuation, with no forward flag ever set.
            return [{"individual_given_name": "Anna", "notes": "continues from the previous image."}]
        # Retry call, made with full previous-row context.
        assert "PREVIOUS RECORD WAS FLAGGED" in user_message
        return [{"individual_given_name": "Anna", "notes": "continued from previous image; merged."}]

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 3
    assert len(result["rows"]) == 1
    assert result["rows"][0]["notes"] == "merged."
    assert result["missing_images"] == []


def test_backward_flag_retry_empty_keeps_original_extraction(monkeypatch):
    """The retry call succeeds but returns zero records. The original,
    unmerged extraction for image 2 must survive -- not be discarded."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"individual_given_name": "Anna", "notes": ""}]
        if calls["n"] == 2:
            return [{"individual_given_name": "Anna", "notes": "continues from the previous image."}]
        return []  # retry returns nothing

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 3
    # Both the original image-1 row and the unmerged image-2 row survive.
    assert len(result["rows"]) == 2
    assert any("merge retry returned no records" in entry for entry in result["exception_log"])


def test_backward_flag_retry_exception_keeps_original_extraction(monkeypatch):
    """The retry call itself raises. The original, unmerged extraction for
    image 2 must survive -- not be discarded -- and the failure is logged."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"individual_given_name": "Anna", "notes": ""}]
        if calls["n"] == 2:
            return [{"individual_given_name": "Anna", "notes": "continues from the previous image."}]
        raise RuntimeError("transient failure")

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 3
    assert len(result["rows"]) == 2
    assert any("merge retry failed" in entry for entry in result["exception_log"])


def test_forward_flag_unconfirmed_merge_keeps_both_rows(monkeypatch):
    """Image 1 flags forward, but image 2's response does not itself
    confirm it performed the merge (e.g. the flag was a false positive, or
    the model simply didn't comply with the merge instruction). The
    previous row must NOT be destroyed -- both rows survive, unmerged."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {
                    "individual_given_name": "Giuseppe",
                    "notes": "Entry appears to continue on the next image.",
                }
            ]
        assert "PREVIOUS RECORD WAS FLAGGED" in user_message
        # The model was told to merge but returned an ordinary, unrelated
        # new entry instead -- its notes say nothing about continuing.
        return [{"individual_given_name": "Maria", "notes": ""}]

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 2
    assert len(result["rows"]) == 2
    assert result["rows"][0]["individual_given_name"] == "Giuseppe"
    assert result["rows"][1]["individual_given_name"] == "Maria"
    assert any("did not confirm a merge" in entry for entry in result["exception_log"])


def test_backward_flag_retry_unconfirmed_merge_keeps_unmerged_extraction(monkeypatch):
    """The backward-flag retry runs and returns records, but its own first
    row still doesn't confirm a merge either. The original (pre-retry)
    unmerged extraction must survive rather than being trusted blindly."""

    calls = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"individual_given_name": "Anna", "notes": ""}]
        if calls["n"] == 2:
            return [{"individual_given_name": "Anna", "notes": "continues from the previous image."}]
        # Retry call: still doesn't confirm a merge in its own notes.
        assert "PREVIOUS RECORD WAS FLAGGED" in user_message
        return [{"individual_given_name": "Anna", "notes": "a fresh unrelated entry"}]

    result = _run(monkeypatch, fake_call_ai)

    assert calls["n"] == 3
    assert len(result["rows"]) == 2
    assert any("did not confirm a merge" in entry for entry in result["exception_log"])
