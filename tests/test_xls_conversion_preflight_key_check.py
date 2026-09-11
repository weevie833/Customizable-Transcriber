"""Regression tests: XLS Conversion's three AI-calling endpoints --
preflight_xls_source() (/api/xls-conversion/preflight),
detect_xls_languages() (/api/xls-conversion/detect-languages), and
parse_xls_source() (/api/xls-conversion/parse) -- all run the same cheap
(max_tokens=4) API-key check, bounded to PREFLIGHT_TIMEOUT_SECONDS, before
their own real (and more expensive) AI call. See
tests/test_prompt_builder_preflight.py for the equivalent coverage of
Prompt Builder's Preflight Test -- this same cheap-key-check pattern was
later extended to these three handlers too.

Exercises the real Handler on an ephemeral port (see tests/conftest.py's
live_server fixture), the same way tests/test_index_compare_http.py does."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import anthropic
import pytest

import app as ctapp


def _get(host, port, path, cookiejar):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(f"http://{host}:{port}{path}", headers={"Host": f"{host}:{port}"})
    return opener.open(req, timeout=5)


def _post_json(host, port, cookiejar, path, payload):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": "application/json"},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def _auth_error() -> anthropic.AuthenticationError:
    return anthropic.AuthenticationError(
        "invalid x-api-key",
        response=mock.Mock(status_code=401, headers={}),
        body={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
    )


@pytest.fixture
def jar(live_server):
    host, port = live_server
    cookiejar = CookieJar()
    _get(host, port, "/", cookiejar)
    return host, port, cookiejar


def test_preflight_fails_fast_on_bad_key_without_the_expensive_call(jar, monkeypatch):
    host, port, cookiejar = jar
    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(side_effect=_auth_error()))
    expensive_call = mock.Mock(side_effect=AssertionError("preflight_records_with_ai() should not run after a bad key"))
    monkeypatch.setattr(ctapp, "preflight_records_with_ai", expensive_call)

    response = _post_json(
        host,
        port,
        cookiejar,
        "/api/xls-conversion/preflight",
        {"model": "claude-opus-5", "gemini_api_key": "sk-ant-not-a-real-key", "record_type": "battesimi", "text": "x"},
    )
    assert response.status == 400
    data = json.loads(response.read())
    assert "Anthropic rejected the API key" in data["error"]
    expensive_call.assert_not_called()


def test_detect_languages_fails_fast_on_bad_key_without_the_expensive_call(jar, monkeypatch):
    host, port, cookiejar = jar
    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(side_effect=_auth_error()))
    expensive_call = mock.Mock(side_effect=AssertionError("detect_languages() should not run after a bad key"))
    monkeypatch.setattr(ctapp, "detect_languages", expensive_call)

    response = _post_json(
        host,
        port,
        cookiejar,
        "/api/xls-conversion/detect-languages",
        {"model": "claude-opus-5", "gemini_api_key": "sk-ant-not-a-real-key", "text": "x"},
    )
    assert response.status == 400
    data = json.loads(response.read())
    assert "Anthropic rejected the API key" in data["error"]
    expensive_call.assert_not_called()


def test_parse_fails_fast_on_bad_key_without_the_expensive_call(jar, monkeypatch):
    host, port, cookiejar = jar
    # parse_xls_source() checks the earlier /preflight run's saved token
    # before the key check -- stub that out so this test isolates the key
    # check itself, the same way a real preflight pass followed by a
    # changed/bad key at Convert time would.
    monkeypatch.setattr(ctapp, "validate_xls_preflight", mock.Mock(return_value=None))
    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(side_effect=_auth_error()))
    expensive_call = mock.Mock(side_effect=AssertionError("parse_records_with_ai() should not run after a bad key"))
    monkeypatch.setattr(ctapp, "parse_records_with_ai", expensive_call)

    response = _post_json(
        host,
        port,
        cookiejar,
        "/api/xls-conversion/parse",
        {"model": "claude-opus-5", "gemini_api_key": "sk-ant-not-a-real-key", "record_type": "battesimi", "text": "x"},
    )
    assert response.status == 400
    data = json.loads(response.read())
    assert "Anthropic rejected the API key" in data["error"]
    expensive_call.assert_not_called()


def test_detect_languages_honors_a_blank_key_via_env_fallback(jar, monkeypatch):
    """CODEX_REVIEW_2.md finding M-3: validate_api_key_with_retry() already
    resolves a blank pasted key to a configured .env key internally (see
    make_client()'s own fallback) and validates THAT -- but the handler
    used to then call detect_languages() with the original, still-blank
    api_key_value, which immediately rejected it with "Paste an API key
    before detecting languages." even though validation had just
    succeeded using a real (env-sourced) key. This confirms the actual
    resolved key reaches detect_languages(), not the blank pasted value."""
    host, port, cookiejar = jar
    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(return_value=None))
    monkeypatch.setattr(ctapp, "api_key", lambda project_dir: "env-sourced-gemini-key")
    monkeypatch.setattr(
        ctapp, "claude_api_key", mock.Mock(side_effect=AssertionError("wrong provider resolver called"))
    )

    captured = {}

    def fake_detect_languages(**kwargs):
        captured.update(kwargs)
        return {"languages": []}

    monkeypatch.setattr(ctapp, "detect_languages", fake_detect_languages)

    response = _post_json(
        host,
        port,
        cookiejar,
        "/api/xls-conversion/detect-languages",
        {"model": "gemini-2.5-pro", "gemini_api_key": "", "text": "x"},
    )
    assert response.status == 200
    assert captured["api_key"] == "env-sourced-gemini-key"


@pytest.mark.parametrize(
    "attr_name",
    ["validate_api_key_with_retry"],
)
def test_all_three_endpoints_bound_the_key_check_to_preflight_timeout(jar, monkeypatch, attr_name):
    """Confirms the actual kwarg, not just that some timeout was set --
    catches a future edit that silently drops the bound and falls back to
    the SDK's own (much longer, or absent) default for these foreground,
    single-request handlers."""
    host, port, cookiejar = jar
    calls: list[dict] = []

    def fake_validate(project_dir, model, api_key_override=None, progress=None, timeout_seconds=None):
        calls.append({"model": model, "timeout_seconds": timeout_seconds})
        raise _auth_error()

    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", fake_validate)
    monkeypatch.setattr(ctapp, "validate_xls_preflight", mock.Mock(return_value=None))

    for path, extra in (
        ("/api/xls-conversion/preflight", {"record_type": "battesimi", "text": "x"}),
        ("/api/xls-conversion/detect-languages", {"text": "x"}),
        ("/api/xls-conversion/parse", {"record_type": "battesimi", "text": "x"}),
    ):
        payload = {"model": "claude-opus-5", "gemini_api_key": "sk-ant-not-a-real-key", **extra}
        response = _post_json(host, port, cookiejar, path, payload)
        assert response.status == 400

    assert len(calls) == 3
    for call in calls:
        assert call["timeout_seconds"] == ctapp.PREFLIGHT_TIMEOUT_SECONDS
