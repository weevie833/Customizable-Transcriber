"""Regression tests for two silent-loss paths: an extraction response cut off
at the output-token cap (now split and retried), and an empty/blocked Gemini
transcription (now an error instead of a saved blank record)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from google.genai import types

from customizable_transcription import core
from xls_conversion import ai_parser


def _block(entries: int) -> str:
    return "\n\n".join(f"Page 1 - Entry {n}:\n\nLatin Transcription: text {n}" for n in range(1, entries + 1))


def _build(image_number, context, block_text):
    return f"{image_number}|{context}|{block_text}"


def test_truncated_gemini_json_response_raises_truncated_error(monkeypatch):
    response = SimpleNamespace(
        text='[{"a": ',
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)],
    )
    fake_client = mock.Mock()
    fake_client.models.generate_content.return_value = response
    monkeypatch.setattr(ai_parser.genai, "Client", lambda **_kw: fake_client)
    monkeypatch.setattr(ai_parser.usage_ledger, "record_gemini", lambda *a, **k: None)
    with pytest.raises(ai_parser.TruncatedResponseError):
        ai_parser.call_gemini_json("key", "gemini-3.1-pro-preview", "sys", "user")


def test_truncated_block_is_split_and_all_rows_returned(monkeypatch):
    seen = []

    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        count = user_message.count("Entry ")
        seen.append(count)
        if count > 4:
            raise ai_parser.TruncatedResponseError("cut off")
        return [{"entry": n} for n in range(count)]

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    records = ai_parser.call_ai_splitting_on_truncation(
        "key", "m", "sys", _build, "7", "CTX", _block(8)
    )
    assert len(records) == 8
    assert seen[0] == 8 and seen[1:] == [4, 4]


def test_context_goes_only_to_first_half(monkeypatch):
    messages = []

    def fake_call_ai(api_key, model, system_prompt, user_message, *_a, **_k):
        messages.append(user_message)
        if user_message.count("Entry ") > 2:
            raise ai_parser.TruncatedResponseError("cut off")
        return []

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    ai_parser.call_ai_splitting_on_truncation("key", "m", "sys", _build, "7", "CTX", _block(4))
    assert "CTX" in messages[1] and "CTX" not in messages[2]


def test_unsplittable_truncation_still_raises(monkeypatch):
    def fake_call_ai(*_a, **_k):
        raise ai_parser.TruncatedResponseError("cut off")

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    with pytest.raises(ai_parser.TruncatedResponseError):
        ai_parser.call_ai_splitting_on_truncation("key", "m", "sys", _build, "7", "", _block(1))


def _gemini_client_returning(response):
    client = mock.Mock()
    client.models.generate_content.return_value = response
    return client


def _transcribe(client):
    return core._transcribe_image_gemini(
        client, b"\xff\xd8\xff\xd9", "image/jpeg", "sys", "gemini-3.1-pro-preview", False
    )


def test_empty_gemini_response_raises(monkeypatch):
    monkeypatch.setattr(core.usage_ledger, "record_gemini", lambda *a, **k: None)
    response = SimpleNamespace(
        text="", candidates=[SimpleNamespace(finish_reason=types.FinishReason.SAFETY)]
    )
    with pytest.raises(RuntimeError, match="SAFETY"):
        _transcribe(_gemini_client_returning(response))


def test_response_with_no_candidates_raises(monkeypatch):
    monkeypatch.setattr(core.usage_ledger, "record_gemini", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="no transcription text"):
        _transcribe(_gemini_client_returning(SimpleNamespace(text=None, candidates=None)))


def test_normal_and_truncated_text_still_returned(monkeypatch):
    monkeypatch.setattr(core.usage_ledger, "record_gemini", lambda *a, **k: None)
    ok = SimpleNamespace(text="hello", candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    assert _transcribe(_gemini_client_returning(ok)) == "hello"
    cut = SimpleNamespace(text="hel", candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)])
    assert _transcribe(_gemini_client_returning(cut)).endswith(core._TRUNCATION_NOTICE)
