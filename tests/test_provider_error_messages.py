"""Regression tests for humanize_provider_error() and the retry wrappers
(transcribe_image_with_retry/validate_api_key_with_retry) in
customizable_transcription/core.py.

Context: a real Gemini 503 ("This model is currently experiencing high
demand... Please try again later.") used to surface verbatim as
"Fatal error: 503 UNAVAILABLE. {'error': {...}}" -- a raw provider error
dict a non-technical user can't act on -- and wasn't retried at all on the
main Transcribe/Test Mode batch path (only xls_conversion/ai_parser.py's
call_ai_json() had retry-with-backoff). These tests cover: the message
rewrite, that _is_transient_provider_error()/MAX_TRANSIENT_RETRIES/etc. now
live in core.py as the single shared copy (ai_parser.py imports them rather
than duplicating), and that the two new *_with_retry() wrappers actually
retry transient failures and give up after MAX_TRANSIENT_RETRIES.
"""

from __future__ import annotations

from unittest import mock

import anthropic
import pytest
from google.genai import errors as genai_errors

import customizable_transcription.core as core
import xls_conversion.ai_parser as ai_parser


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)


def _gemini_503():
    return genai_errors.ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": (
                    "This model is currently experiencing high demand. Spikes in demand "
                    "are usually temporary. Please try again later."
                ),
                "status": "UNAVAILABLE",
            }
        },
        None,
    )


def _gemini_429():
    return genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, None)


def _claude_500():
    return anthropic.InternalServerError(
        "server error", response=mock.Mock(status_code=500, headers={}), body=None
    )


def test_humanize_provider_error_503_names_model_and_explains():
    message = core.humanize_provider_error(_gemini_503(), "gemini-3.1-pro-preview")
    assert "gemini-3.1-pro-preview" in message
    assert "not a problem with your API key or this app" in message
    assert "UNAVAILABLE" in message  # original error text preserved, not hidden


def test_humanize_provider_error_429_says_rate_limited():
    message = core.humanize_provider_error(_gemini_429(), "gemini-3.1-pro-preview")
    assert "rate-limiting" in message
    assert "gemini-3.1-pro-preview" in message


def test_humanize_provider_error_passes_through_unknown_exceptions_unchanged():
    exc = RuntimeError("Select a model before running transcription.")
    assert core.humanize_provider_error(exc, "gemini-3.1-pro-preview") == str(exc)


def test_ai_parser_reuses_shared_constants_not_its_own_copy():
    # Same object, not just an equal value -- confirms xls_conversion/ai_parser.py
    # imports these from core.py rather than keeping a second definition that
    # could silently drift out of sync with it.
    assert ai_parser.MAX_TRANSIENT_RETRIES is core.MAX_TRANSIENT_RETRIES
    assert ai_parser._is_transient_provider_error is core._is_transient_provider_error


def test_transcribe_image_with_retry_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    progress_messages = []

    def fake_transcribe_image(client, image_path, system_prompt, model, include_thoughts=False, max_thinking_level=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _gemini_503()
        return "real transcription text"

    monkeypatch.setattr(core, "transcribe_image", fake_transcribe_image)
    result = core.transcribe_image_with_retry(
        client=object(),
        image_path=core.Path("image_001.jpg"),
        system_prompt="sys",
        model="gemini-3.1-pro-preview",
        progress=progress_messages.append,
    )
    assert result == "real transcription text"
    assert calls["n"] == 3
    assert any("temporary error" in msg for msg in progress_messages)


def test_transcribe_image_with_retry_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def always_fails(client, image_path, system_prompt, model, include_thoughts=False, max_thinking_level=None):
        calls["n"] += 1
        raise _gemini_503()

    monkeypatch.setattr(core, "transcribe_image", always_fails)
    with pytest.raises(genai_errors.ServerError):
        core.transcribe_image_with_retry(
            client=object(), image_path=core.Path("image_001.jpg"), system_prompt="sys", model="gemini-3.1-pro-preview"
        )
    assert calls["n"] == core.MAX_TRANSIENT_RETRIES + 1


def test_validate_api_key_with_retry_retries_transient_claude_error(monkeypatch):
    calls = {"n": 0}

    def fake_validate(project_dir, model, api_key_override=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _claude_500()
        return None

    monkeypatch.setattr(core, "validate_api_key", fake_validate)
    core.validate_api_key_with_retry(core.Path("."), "claude-sonnet-5")
    assert calls["n"] == 2


def test_validate_api_key_with_retry_does_not_retry_non_transient_error(monkeypatch):
    calls = {"n": 0}

    def fake_validate(project_dir, model, api_key_override=None):
        calls["n"] += 1
        raise RuntimeError("The GEMINI_API_KEY is still set to the placeholder value.")

    monkeypatch.setattr(core, "validate_api_key", fake_validate)
    with pytest.raises(RuntimeError):
        core.validate_api_key_with_retry(core.Path("."), "gemini-3.1-pro-preview")
    assert calls["n"] == 1


def test_run_batch_writes_humanized_error_for_persistent_transient_failure(tmp_path, monkeypatch):
    """End-to-end: a real run_batch() call whose only image hits a
    persistent 503 should record a humanized ERROR line, not a raw dict
    string, and should still finish the batch (one failed image, not an
    unhandled exception that aborts the run)."""
    image_folder = tmp_path / "images"
    image_folder.mkdir()
    (image_folder / "image_001.jpg").write_bytes(b"not a real image, just a placeholder")

    monkeypatch.setattr(core, "make_client", lambda *args, **kwargs: core.LLMClient(provider="gemini"))
    monkeypatch.setattr(core, "transcribe_image", lambda *args, **kwargs: (_ for _ in ()).throw(_gemini_503()))

    config = core.TranscriptionConfig(
        image_folder=image_folder,
        output_file=tmp_path / "out.md",
        prompt_file=tmp_path / "unused-prompt-file.txt",
        model="gemini-3.1-pro-preview",
        delay_seconds=0,
        system_prompt="sys",
    )
    results = core.run_batch(config, tmp_path)
    assert len(results) == 1
    assert not results[0].ok
    assert "not a problem with your API key or this app" in results[0].text
    assert "gemini-3.1-pro-preview" in results[0].text
