"""Regression tests for call_ai_json()'s transient-error retry/backoff and
for the widened per-image exception handling in parse_generic()'s loop --
see docs/DESIGN.md's "Security hardening history" section on the "batch
failures not bounded" finding these close."""

from __future__ import annotations

from unittest import mock

import anthropic
import pytest
from google.genai import errors as genai_errors

from xls_conversion import ai_parser


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    # Retries call time.sleep() for backoff -- stub it out so these tests
    # run instantly instead of actually waiting several seconds.
    monkeypatch.setattr(ai_parser.time, "sleep", lambda _seconds: None)


def _rate_limit_error():
    return anthropic.RateLimitError(
        "rate limited", response=mock.Mock(status_code=429, headers={}), body=None
    )


def _server_error():
    return anthropic.InternalServerError(
        "server error", response=mock.Mock(status_code=500, headers={}), body=None
    )


def _client_error_400():
    return anthropic.BadRequestError(
        "bad request", response=mock.Mock(status_code=400, headers={}), body=None
    )


def test_transient_429_is_retried_and_eventually_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_once(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _rate_limit_error()
        return [{"ok": True}]

    monkeypatch.setattr(ai_parser, "_call_ai_json_once", fake_once)
    result = ai_parser.call_ai_json("key", "claude-sonnet-5", "sys", "user")
    assert result == [{"ok": True}]
    assert calls["n"] == 3


def test_persistent_429_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def fake_once(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        raise _rate_limit_error()

    monkeypatch.setattr(ai_parser, "_call_ai_json_once", fake_once)
    with pytest.raises(anthropic.RateLimitError):
        ai_parser.call_ai_json("key", "claude-sonnet-5", "sys", "user")
    assert calls["n"] == ai_parser.MAX_TRANSIENT_RETRIES + 1


def test_non_transient_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_once(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        calls["n"] += 1
        raise _client_error_400()

    monkeypatch.setattr(ai_parser, "_call_ai_json_once", fake_once)
    with pytest.raises(anthropic.BadRequestError):
        ai_parser.call_ai_json("key", "claude-sonnet-5", "sys", "user")
    assert calls["n"] == 1


def test_is_transient_provider_error_classification():
    assert ai_parser._is_transient_provider_error(_rate_limit_error())
    assert ai_parser._is_transient_provider_error(_server_error())
    assert not ai_parser._is_transient_provider_error(_client_error_400())
    assert ai_parser._is_transient_provider_error(genai_errors.ServerError(503, {}, None))
    assert ai_parser._is_transient_provider_error(genai_errors.ClientError(429, {}, None))
    assert not ai_parser._is_transient_provider_error(genai_errors.ClientError(400, {}, None))
    assert not ai_parser._is_transient_provider_error(ValueError("unrelated"))


def test_parse_generic_one_image_failure_does_not_abort_whole_batch(monkeypatch):
    """The exact reported bug: parse_generic()'s loop only caught
    RuntimeError, so a native SDK exception on one image used to propagate
    and abort every remaining image in the batch instead of being recorded
    as a single failed image."""
    config = ai_parser.RECORD_TYPES["battesimi"]
    text = (
        "--- START OF RECORD: image_001.jpg ---\n\nfirst block\n\n"
        "--- START OF RECORD: image_002.jpg ---\n\nsecond block\n"
    )

    call_count = {"n": 0}

    def fake_call_ai(api_key, model, system_prompt, user_message, *_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [{"some_field": "ok"}]
        raise genai_errors.ServerError(503, {"error": "overloaded"}, None)

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    result = ai_parser.parse_generic(
        config=config,
        text=text,
        image_range="",
        image_overrides="",
        api_key="key",
        model="gemini-2.5-pro",
        target_language="English",
        target_role="",
        process_all=True,
    )
    # Both images were attempted (call_count == 2) rather than the second
    # one's failure raising out of the function entirely.
    assert call_count["n"] == 2
    assert any("AI extraction failed" in entry for entry in result["exception_log"])
