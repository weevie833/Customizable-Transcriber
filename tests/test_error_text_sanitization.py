"""reviews/CODEX_REVIEW_8.md M-2: raw exception text (which for an SDK error
can echo request content) never reaches the usage ledger, a transcript, an
off-peak document or the translation report."""

from __future__ import annotations


import anthropic
import httpx

import batch_transcription as bt
from customizable_transcriber import core, usage_ledger

SECRET = "SYNTHETIC-SENSITIVE-TEXT-42"


def _sdk_error(status=400):
    request = httpx.Request("POST", "https://api.example.invalid/v1")
    response = httpx.Response(status, request=request)
    return anthropic.BadRequestError(f"bad request echo {SECRET}", response=response, body=None)


def test_safe_summary_has_class_and_status_only():
    summary = core.safe_error_summary(_sdk_error())
    assert SECRET not in summary and "BadRequestError" in summary and "400" in summary


def test_humanize_without_original_drops_sdk_text():
    message = core.humanize_provider_error(_sdk_error(), "claude-opus-5-5", include_original=False)
    assert SECRET not in message
    # The live (non-durable) form still carries it for the Progress Console.
    assert SECRET in core.humanize_provider_error(_sdk_error(), "claude-opus-5-5")
    # Messages this app wrote from safe fields are kept as written...
    assert core.humanize_provider_error(core.SafeMessageError("Plain"), "m", include_original=False) == "Plain"
    # ...but any other exception's text is not (CODEX_REVIEW_2.md M-2).
    durable = core.humanize_provider_error(OSError(f"/Users/someone/{SECRET}"), "m", include_original=False)
    assert SECRET not in durable and "OSError" in durable


def test_humanize_auth_error_without_original(monkeypatch):
    request = httpx.Request("POST", "https://api.example.invalid/v1")
    exc = anthropic.AuthenticationError(f"nope {SECRET}", response=httpx.Response(401, request=request), body=None)
    message = core.humanize_provider_error(exc, "claude-opus-5-5", include_original=False)
    assert SECRET not in message and "rejected the API key" in message


def test_ledger_retry_event_has_no_exception_text(tmp_path, monkeypatch):
    usage_ledger.configure(tmp_path / "usage")
    run = usage_ledger.start_run(mode="regular", stage="transcribe", provider="claude", model="claude-opus-5-5")
    token = usage_ledger.activate(run)
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _sdk_error(529)
        return "ok"

    try:
        assert core._with_transient_retry(flaky) == "ok"
    finally:
        usage_ledger.deactivate(token)
        usage_ledger.end_run(run)
        usage_ledger.configure(None)
    written = "".join(p.read_text() for p in (tmp_path / "usage").rglob("*") if p.is_file())
    assert "transient_retry" in written
    assert SECRET not in written


def test_offpeak_item_error_is_not_saved_verbatim():
    assert SECRET not in bt.safe_batch_item_error(f"provider said {SECRET}")
    # A raw provider string that starts like one of our own sentences is
    # still not trusted: only a typed ItemError is (CODEX_REVIEW_2.md M-2).
    assert SECRET not in bt.safe_batch_item_error(f"Request was rejected: {SECRET}")
    own = bt.ItemError("The model returned no transcription text (stop reason: SAFETY).")
    assert bt.safe_batch_item_error(own) == own
    provider = bt.provider_item_error(f"Request was rejected: {SECRET}")
    assert SECRET not in bt.safe_batch_item_error(provider)
    assert SECRET in bt.item_error_for_log(provider)


def test_offpeak_document_and_ledger_drop_prefixed_provider_text(tmp_path, monkeypatch, sandboxed_user_data):
    """Through run_off_peak_job(): a provider message beginning with one of
    our own phrases ("Request was") reaches neither the transcript nor the
    usage ledger (CODEX_REVIEW_2.md M-2)."""
    import types as pytypes

    import app_state

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)

    class _Batches:
        def create(self, model, src, config):
            return pytypes.SimpleNamespace(name="batches/fake")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: pytypes.SimpleNamespace(batches=_Batches()))
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)
    error = pytypes.SimpleNamespace(message=f"Request was rejected: {SECRET} /Users/someone/private")
    job = pytypes.SimpleNamespace(
        state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
        completion_stats=pytypes.SimpleNamespace(successful_count=0, failed_count=1, incomplete_count=0),
        dest=pytypes.SimpleNamespace(inlined_responses=[
            pytypes.SimpleNamespace(metadata={"index": "0"}, error=error, response=None),
        ]),
    )
    monkeypatch.setattr(bt, "poll_gemini_batch", lambda client, name: job)
    usage_ledger.configure(tmp_path / "usage")
    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True
    try:
        bt.run_off_peak_job(
            project_dir=tmp_path, image_folder=source, extensions=frozenset({".jpg"}),
            model="gemini-3.1-pro-preview", provider="gemini", system_prompt="sys",
            api_key_override="fake-key", markdown_file=tmp_path / "out.md",
            docx_file=tmp_path / "out.docx", profile={"label": "P"},
        )
    finally:
        usage_ledger.configure(None)
    document = (tmp_path / "out.md").read_text(encoding="utf-8")
    ledger = "".join(p.read_text() for p in (tmp_path / "usage").rglob("*") if p.is_file())
    assert "ERROR:" in document
    assert SECRET not in document and "/Users/someone" not in document
    assert ledger and SECRET not in ledger
    with app_state.lock:
        assert any(SECRET in line for line in app_state.state["log"])  # live console keeps it


def test_realtime_document_drops_unexpected_exception_text(tmp_path, monkeypatch):
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "image_001.jpg").write_bytes(b"\xff\xd8\xff\xe0placeholder")
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini"))

    def boom(*a, **k):
        raise OSError(f"cannot open /Users/someone/{SECRET}")

    monkeypatch.setattr(core, "transcribe_image_with_retry", boom)
    usage_ledger.configure(tmp_path / "usage")
    logged: list[str] = []
    config = core.TranscriptionConfig(
        image_folder=folder, output_file=tmp_path / "out.md", prompt_file=tmp_path / "p.txt",
        model="gemini-3.1-pro-preview", delay_seconds=0, system_prompt="sys",
    )
    try:
        core.run_batch(config, tmp_path, progress=logged.append)
    finally:
        usage_ledger.configure(None)
    document = (tmp_path / "out.md").read_text(encoding="utf-8")
    ledger = "".join(p.read_text() for p in (tmp_path / "usage").rglob("*") if p.is_file())
    assert "ERROR:" in document and SECRET not in document and SECRET not in ledger
    assert any(SECRET in line for line in logged)
