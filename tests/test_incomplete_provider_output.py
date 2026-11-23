"""reviews/CODEX_REVIEW_8.md H-5: empty or token-limited provider output must
never be saved as a complete page, in either off-peak adapter or in
real-time Claude, and a truncated page shows in the run summary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from google.genai import types

import batch_transcription as bt
from customizable_transcriber import core


def _gemini_item(index, text, finish=None):
    response = SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish)] if finish is not None else [],
        usage_metadata=None,
    )
    return SimpleNamespace(metadata={"index": str(index)}, error=None, response=response)


def test_gemini_batch_blank_blocked_and_truncated():
    job = SimpleNamespace(dest=SimpleNamespace(inlined_responses=[
        _gemini_item(0, "", types.FinishReason.STOP),
        _gemini_item(1, None, types.FinishReason.SAFETY),
        _gemini_item(2, "Partial entry", types.FinishReason.MAX_TOKENS),
        _gemini_item(3, "Full entry", types.FinishReason.STOP),
    ]))
    results = bt.collect_gemini_batch_results(job)
    assert results[0][0] == "" and "no transcription text" in results[0][1]
    assert results[1][0] == "" and "SAFETY" in results[1][1]
    assert results[2][1] == "" and results[2][0].startswith("Partial entry")
    assert core.TRUNCATION_MARKER in results[2][0]
    assert results[3] == ("Full entry", "")


def _claude_item(index, blocks, stop_reason):
    message = SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=None)
    return SimpleNamespace(custom_id=str(index), result=SimpleNamespace(type="succeeded", message=message))


def test_claude_batch_blank_refusal_and_truncated():
    text = lambda t: SimpleNamespace(type="text", text=t)  # noqa: E731
    items = [
        _claude_item(0, [], "end_turn"),
        _claude_item(1, [text("")], "refusal"),
        _claude_item(2, [text("Partial")], "max_tokens"),
        _claude_item(3, [text("Full")], "end_turn"),
    ]
    client = mock.Mock()
    client.messages.batches.results.return_value = items
    results = bt.collect_claude_batch_results(client, "batch")
    assert results[0][0] == "" and results[0][1]
    assert results[1][0] == "" and "refusal" in results[1][1]
    assert core.TRUNCATION_MARKER in results[2][0] and results[2][1] == ""
    assert results[3] == ("Full", "")


def test_realtime_claude_blank_response_raises(monkeypatch):
    final = SimpleNamespace(content=[], stop_reason="refusal", usage=None)
    stream = mock.MagicMock()
    stream.__enter__.return_value.get_final_message.return_value = final
    client = mock.Mock()
    client.messages.stream.return_value = stream
    monkeypatch.setattr(core.usage_ledger, "record_claude", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="no transcription text"):
        core._transcribe_image_claude(client, b"x", "image/png", "sys", "claude-opus-5-5")


def test_summary_suffix_counts_truncated_pages():
    results = [
        core.ImageResult("a", True, "ok"),
        core.ImageResult("b", True, "partial" + core._TRUNCATION_NOTICE),
        core.ImageResult("c", False, "ERROR: x"),
    ]
    assert core.count_incomplete(results) == 1
    assert core.incomplete_summary_suffix(results) == ", 1 incomplete (the model stopped before finishing)"
    assert core.incomplete_summary_suffix(results[:1]) == ""


# CODEX_REVIEW_2.md H-5: a reply WITH text but a refusal, safety or
# context-limit status must never be saved as a complete page.

def test_claude_batch_nonempty_refusal_and_context_limit():
    text = lambda t: SimpleNamespace(type="text", text=t)  # noqa: E731
    items = [
        _claude_item(0, [text("I can't help with that.")], "refusal"),
        _claude_item(1, [text("Entry 1 ...")], "model_context_window_exceeded"),
        _claude_item(2, [text("Entry 1 ...")], "pause_turn"),
    ]
    client = mock.Mock()
    client.messages.batches.results.return_value = items
    results = bt.collect_claude_batch_results(client, "batch")
    assert results[0][0] == "" and "refusal" in results[0][1]
    assert results[1][1] == "" and "model_context_window_exceeded" in results[1][0]
    assert results[2][1] == "" and "[INCOMPLETE:" in results[2][0]
    pages = [core.ImageResult(str(i), not err, txt or err) for i, (txt, err) in sorted(results.items())]
    assert core.count_failures(pages) == 1 and core.count_incomplete(pages) == 2


def test_gemini_batch_nonempty_block_and_other():
    job = SimpleNamespace(dest=SimpleNamespace(inlined_responses=[
        _gemini_item(0, "Some text", types.FinishReason.RECITATION),
        _gemini_item(1, "Some text", types.FinishReason.OTHER),
        _gemini_item(2, "Some text", None),
    ]))
    results = bt.collect_gemini_batch_results(job)
    assert results[0][0] == "" and "RECITATION" in results[0][1]
    assert results[1][1] == "" and "stop reason: OTHER" in results[1][0]
    assert results[2][1] == "" and "[INCOMPLETE:" in results[2][0]


@pytest.mark.parametrize("stop_reason, outcome", [
    ("refusal", "error"), ("model_context_window_exceeded", "incomplete"), ("end_turn", "complete"),
])
def test_realtime_claude_nonempty_terminal_statuses(monkeypatch, stop_reason, outcome):
    final = SimpleNamespace(content=[SimpleNamespace(type="text", text="Entry 1 ...")], stop_reason=stop_reason, usage=None)
    stream = mock.MagicMock()
    stream.__enter__.return_value.get_final_message.return_value = final
    client = mock.Mock()
    client.messages.stream.return_value = stream
    monkeypatch.setattr(core.usage_ledger, "record_claude", lambda *a, **k: None)
    if outcome == "error":
        with pytest.raises(RuntimeError, match="refusal"):
            core._transcribe_image_claude(client, b"x", "image/png", "sys", "claude-opus-5-5")
        return
    text = core._transcribe_image_claude(client, b"x", "image/png", "sys", "claude-opus-5-5")
    assert ("[INCOMPLETE:" in text) == (outcome == "incomplete")


def test_realtime_gemini_nonempty_safety_block(monkeypatch):
    response = SimpleNamespace(text="Some text", candidates=[SimpleNamespace(finish_reason=types.FinishReason.SAFETY)])
    client = mock.Mock()
    client.models.generate_content.return_value = response
    monkeypatch.setattr(core.usage_ledger, "record_gemini", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="SAFETY"):
        core._transcribe_image_gemini(client, b"x", "image/png", "sys", "gemini-3.1-pro-preview", False)


def test_ledger_records_outcome(tmp_path, monkeypatch):
    import json
    from customizable_transcriber import usage_ledger
    monkeypatch.setattr(usage_ledger, "_ledger_dir", tmp_path)
    run = usage_ledger.start_run(mode="off_peak", stage="transcribe", provider="claude", model="m")
    usage_ledger.record_call(provider="claude", model="m", usage=None, finish_reason="refusal", run=run, image="a")
    usage_ledger.record_call(provider="claude", model="m", usage=None, finish_reason="end_turn", run=run, image="b")
    lines = [json.loads(line) for f in tmp_path.rglob("*.jsonl") for line in f.read_text().splitlines()]
    outcomes = [line["outcome"] for line in lines if line.get("type") == "call"]
    assert outcomes == ["blocked", "complete"]
