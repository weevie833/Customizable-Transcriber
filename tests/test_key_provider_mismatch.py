"""reviews/CODEX_REVIEW_8.md M-1: a key recognizably for the other provider
is rejected locally, before any SDK client is constructed or called."""

from __future__ import annotations

import pytest

import batch_transcription as bt
from customizable_transcriber import core
from xls_conversion import ai_parser


def _forbid_sdks(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("SDK client constructed")

    monkeypatch.setattr(core.anthropic, "Anthropic", boom)
    monkeypatch.setattr(core.genai, "Client", boom)
    monkeypatch.setattr(ai_parser.anthropic, "Anthropic", boom)
    monkeypatch.setattr(ai_parser.genai, "Client", boom)
    monkeypatch.setattr(bt, "_claude_client", boom)
    monkeypatch.setattr(bt, "_gemini_client", boom)


def test_mismatch_rules():
    assert core.key_provider_mismatch("claude-opus-5-5", "AIzaSyExample")
    assert core.key_provider_mismatch("gemini-3.1-pro-preview", "sk-ant-abc")
    assert core.key_provider_mismatch("claude-opus-5-5", "sk-ant-abc") == ""
    assert core.key_provider_mismatch("gemini-3.1-pro-preview", "AIzaSyExample") == ""
    assert core.key_provider_mismatch("gemini-3.1-pro-preview", "") == ""


def test_realtime_client_rejects_before_construction(monkeypatch, tmp_path):
    _forbid_sdks(monkeypatch)
    with pytest.raises(RuntimeError, match="Claude key"):
        core.make_client(tmp_path, "gemini-3.1-pro-preview", "sk-ant-abc")
    with pytest.raises(RuntimeError, match="Claude key"):
        core.make_client(tmp_path, "claude-opus-5-5", "AIzaSyExample")


def test_xls_json_calls_reject_before_construction(monkeypatch):
    _forbid_sdks(monkeypatch)
    with pytest.raises(RuntimeError, match="Claude key"):
        ai_parser.call_claude_json("AIzaSyExample", "claude-opus-5-5", "s", "u")
    with pytest.raises(RuntimeError, match="Claude key"):
        ai_parser.call_gemini_json("sk-ant-abc", "gemini-3.1-pro-preview", "s", "u")


def test_offpeak_submission_rejects_before_construction(monkeypatch, tmp_path):
    _forbid_sdks(monkeypatch)
    image = tmp_path / "a.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    with pytest.raises(RuntimeError, match="Claude key"):
        bt._validate_and_submit(
            project_dir=tmp_path, image_folder=tmp_path, extensions=(".png",),
            model="gemini-3.1-pro-preview", provider="gemini", system_prompt="s",
            api_key_override="sk-ant-abc", reverse_order=False, zoom_pages=False,
        )
