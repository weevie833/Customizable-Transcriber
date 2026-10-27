"""CODEX_REVIEW.md M-3: the initial API-key check is always bounded and reports a stall
plainly (Stop cannot interrupt it while it blocks)."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from customizable_transcriber import core


def test_default_key_check_timeout_is_passed_to_the_client(monkeypatch):
    seen = {}

    def fake_make_client(project_dir, model, api_key_override=None, timeout_seconds=None):
        seen["timeout"] = timeout_seconds
        gemini = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_k: None))
        return SimpleNamespace(provider="gemini", gemini=gemini)

    monkeypatch.setattr(core, "make_client", fake_make_client)
    core.validate_api_key(Path("."), "gemini-2.5-pro", "key")
    assert seen["timeout"] == core.KEY_CHECK_TIMEOUT_SECONDS == 60


def test_stalled_key_check_raises_a_clear_error_and_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def stalled(**_k):
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out")

    def fake_make_client(project_dir, model, api_key_override=None, timeout_seconds=None):
        return SimpleNamespace(
            provider="gemini", gemini=SimpleNamespace(models=SimpleNamespace(generate_content=stalled))
        )

    monkeypatch.setattr(core, "make_client", fake_make_client)
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="did not finish within 60s"):
        core.validate_api_key_with_retry(Path("."), "gemini-2.5-pro", "key")
    assert calls["n"] == 1
