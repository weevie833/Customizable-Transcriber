"""Regression tests for humanize_provider_error() and the retry wrappers
(transcribe_image_with_retry/validate_api_key_with_retry) in
customizable_transcriber/core.py.

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

from customizable_transcriber import core
from xls_conversion import ai_parser


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


def _claude_401():
    return anthropic.AuthenticationError(
        "invalid x-api-key",
        response=mock.Mock(status_code=401, headers={}),
        body={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
    )


def _claude_403():
    return anthropic.PermissionDeniedError(
        "permission denied",
        response=mock.Mock(status_code=403, headers={}),
        body={"type": "error", "error": {"type": "permission_error", "message": "permission denied"}},
    )


def _gemini_invalid_key():
    return genai_errors.ClientError(
        400,
        {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}},
        None,
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


def test_humanize_provider_error_401_names_provider_and_console():
    message = core.humanize_provider_error(_claude_401(), "claude-opus-5")
    assert "Anthropic rejected the API key" in message
    assert "claude-opus-5" in message
    assert "console.anthropic.com" in message
    assert "invalid x-api-key" in message  # original error text preserved, not hidden
    assert "not a bug in this app" in message


def test_humanize_provider_error_403_explains_permission_denied():
    message = core.humanize_provider_error(_claude_403(), "claude-opus-5")
    assert "denied it access" in message
    assert "claude-opus-5" in message
    assert "billing" in message


def test_humanize_provider_error_gemini_invalid_key_is_treated_as_auth_error():
    message = core.humanize_provider_error(_gemini_invalid_key(), "gemini-3.1-pro-preview")
    assert "Google AI rejected the API key" in message
    assert "aistudio.google.com" in message


def test_humanize_provider_error_401_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_validate(project_dir, model, api_key_override=None, timeout_seconds=None):
        calls["n"] += 1
        raise _claude_401()

    monkeypatch.setattr(core, "validate_api_key", fake_validate)
    with pytest.raises(anthropic.AuthenticationError):
        core.validate_api_key_with_retry(core.Path("."), "claude-opus-5")
    assert calls["n"] == 1  # fails fast -- a bad key will never succeed on retry


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

    def fake_transcribe_image(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
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

    def always_fails(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
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

    def fake_validate(project_dir, model, api_key_override=None, timeout_seconds=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _claude_500()

    monkeypatch.setattr(core, "validate_api_key", fake_validate)
    core.validate_api_key_with_retry(core.Path("."), "claude-sonnet-5")
    assert calls["n"] == 2


def test_validate_api_key_with_retry_does_not_retry_non_transient_error(monkeypatch):
    calls = {"n": 0}

    def fake_validate(project_dir, model, api_key_override=None, timeout_seconds=None):
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


# --- Truncation auto-retry (transcribe_image_with_retry) -------------------
# See core.py's _TRUNCATION_NOTICE / _gemini_thinking_is_cappable() comments:
# a gemini-3.x response cut off by MAX_TOKENS is often the model's own
# (uncapped-by-default, on this real-batch path) thinking budget eating the
# shared output-token pool, not genuinely-too-long content. These cover the
# retry-with-capped-thinking behavior transcribe_image_with_retry() now does
# on top of the existing transient-error retry above.


def test_truncated_gemini_response_retries_with_lower_thinking_and_succeeds(monkeypatch):
    calls = []

    def fake_transcribe_image(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
        calls.append(max_thinking_level)
        if max_thinking_level is None:
            return "Entry 8:\n\nDate: 10 Julii 1761 [10 July" + core._TRUNCATION_NOTICE
        return "Entry 8:\n\nDate: 10 Julii 1761 [10 July 1761]. ... full transcription."

    monkeypatch.setattr(core, "transcribe_image", fake_transcribe_image)
    progress_messages = []
    result = core.transcribe_image_with_retry(
        client=core.LLMClient(provider="gemini"),
        image_path=core.Path("image_194.jpg"),
        system_prompt="sys",
        model="gemini-3.1-pro-preview",
        progress=progress_messages.append,
    )
    assert calls == [None, "LOW"]
    assert result == "Entry 8:\n\nDate: 10 Julii 1761 [10 July 1761]. ... full transcription."
    assert not result.endswith(core._TRUNCATION_NOTICE)
    assert any("retrying once with a lower thinking budget" in msg for msg in progress_messages)
    assert any("finished without truncation" in msg for msg in progress_messages)


def test_truncated_gemini_response_keeps_original_if_retry_still_truncated(monkeypatch):
    calls = []

    def fake_transcribe_image(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
        calls.append(max_thinking_level)
        return "partial text" + core._TRUNCATION_NOTICE

    monkeypatch.setattr(core, "transcribe_image", fake_transcribe_image)
    progress_messages = []
    result = core.transcribe_image_with_retry(
        client=core.LLMClient(provider="gemini"),
        image_path=core.Path("image_194.jpg"),
        system_prompt="sys",
        model="gemini-3.1-pro-preview",
        progress=progress_messages.append,
    )
    assert calls == [None, "LOW"]
    assert result == "partial text" + core._TRUNCATION_NOTICE_AFTER_RETRY
    assert any("still hit the output token limit" in msg for msg in progress_messages)


def test_truncated_claude_response_is_not_retried(monkeypatch):
    calls = []

    def fake_transcribe_image(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
        calls.append(max_thinking_level)
        return "partial text" + core._TRUNCATION_NOTICE

    monkeypatch.setattr(core, "transcribe_image", fake_transcribe_image)
    result = core.transcribe_image_with_retry(
        client=core.LLMClient(provider="claude"),
        image_path=core.Path("image_001.jpg"),
        system_prompt="sys",
        model="claude-opus-5",
    )
    # Claude has no shared thinking/output budget in this code path (see
    # _transcribe_image_claude()), so a truncated response is never retried.
    assert calls == [None]
    assert result == "partial text" + core._TRUNCATION_NOTICE


def test_truncated_gemini_25_pro_response_is_not_retried(monkeypatch):
    """gemini-2.5-pro has no ThinkingLevel to cap (_gemini_thinking_is_cappable()
    gates on the gemini-3/gemini-4 prefixes) -- retrying would just spend a
    second API call for no effect."""
    calls = []

    def fake_transcribe_image(
        client,
        image_path,
        system_prompt,
        model,
        include_thoughts=False,
        max_thinking_level=None,
        cached_content=None,
        use_prompt_cache=False,
        **_kwargs,
    ):
        calls.append(max_thinking_level)
        return "partial text" + core._TRUNCATION_NOTICE

    monkeypatch.setattr(core, "transcribe_image", fake_transcribe_image)
    result = core.transcribe_image_with_retry(
        client=core.LLMClient(provider="gemini"),
        image_path=core.Path("image_001.jpg"),
        system_prompt="sys",
        model="gemini-2.5-pro",
    )
    assert calls == [None]
    assert result == "partial text" + core._TRUNCATION_NOTICE


def test_gemini_thinking_cappable_covers_3_and_4_but_not_25():
    assert core._gemini_thinking_is_cappable("gemini-3.1-pro-preview")
    assert core._gemini_thinking_is_cappable("gemini-4-argon")
    assert not core._gemini_thinking_is_cappable("gemini-2.5-pro")
    assert not core._gemini_thinking_is_cappable("claude-opus-5-5")
