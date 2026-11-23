"""reviews/CODEX_REVIEW_8.md M-5 (Claude part): a Claude off-peak batch whose
encoded request would exceed Anthropic's per-request limit is refused before
any file is read or sent."""

from __future__ import annotations

import pytest

import batch_transcription as bt


def test_estimate_counts_base64_and_repeated_prompt(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x" * 300)
    estimate = bt.estimated_claude_batch_bytes([image, image], "P" * 1000)
    assert estimate >= 2 * (400 + 1000)


def test_oversized_claude_batch_is_refused(tmp_path, monkeypatch):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x" * 3000)
    monkeypatch.setattr(bt, "CLAUDE_BATCH_MAX_REQUEST_BYTES", 5000)
    with pytest.raises(bt.BatchSubmissionError, match="Split the folder"):
        bt.check_claude_batch_envelope([image], "system prompt")


def test_small_batch_passes(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x" * 3000)
    bt.check_claude_batch_envelope([image], "system prompt")
