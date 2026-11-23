"""CODEX_REVIEW_2.md M-4: a Stop acknowledged before an off-peak batch is
sent must prevent the billable create call -- on worker entry, during image
preparation, and at the last check before sending -- with or without Test
Mode's submit_lock, for both providers."""

from __future__ import annotations

import types as pytypes

import pytest

import app_state
import batch_transcription as bt


def _source(tmp_path, count=3):
    folder = tmp_path / "source"
    folder.mkdir()
    for index in range(count):
        (folder / f"img_{index:03d}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    return folder


class _GeminiClient:
    def __init__(self):
        self.created = 0
        self.batches = self

    def create(self, **kwargs):
        self.created += 1
        return pytypes.SimpleNamespace(name="batches/should-not-exist")


class _ClaudeClient:
    def __init__(self):
        self.created = 0
        self.messages = pytypes.SimpleNamespace(batches=self)

    def with_options(self, **kwargs):
        return self

    def create(self, **kwargs):
        self.created += 1
        return pytypes.SimpleNamespace(id="msgbatch_should_not_exist")


def _run(tmp_path, monkeypatch, provider, client):
    if provider == "claude":
        monkeypatch.setattr(bt, "_claude_client", lambda key, timeout: client)
        model, key = "claude-opus-5-5", "sk-ant-fake"
    else:
        monkeypatch.setattr(bt, "_gemini_client", lambda key, timeout: client)
        model, key = "gemini-3.1-pro-preview", "AIzaFake"
    monkeypatch.setattr(bt, "ensure_key_matches_model", lambda *a: None)
    monkeypatch.setattr(bt, "check_claude_batch_envelope", lambda *a: None)
    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True
    bt.run_off_peak_job(
        project_dir=tmp_path, image_folder=_source(tmp_path), extensions=frozenset({".jpg"}),
        model=model, provider=provider, system_prompt="sys", api_key_override=key,
        markdown_file=tmp_path / "out.md", docx_file=tmp_path / "out.docx", profile={"label": "P"},
    )
    with app_state.lock:
        return app_state.state["summary"]


@pytest.fixture(autouse=True)
def _clear_stop():
    app_state.stop_event.clear()
    yield
    app_state.stop_event.clear()
    with app_state.lock:
        app_state.state["running"] = False
        app_state.state["off_peak"] = False
        app_state.state["batch_submitting"] = False


@pytest.mark.parametrize("provider, client_cls", [("gemini", _GeminiClient), ("claude", _ClaudeClient)])
def test_stop_set_before_worker_entry_without_lock(tmp_path, monkeypatch, sandboxed_user_data, provider, client_cls):
    client = client_cls()
    app_state.stop_event.set()
    summary = _run(tmp_path, monkeypatch, provider, client)
    assert client.created == 0
    assert "Stopped before" in summary
    assert app_state.read_off_peak_job_state() is None


@pytest.mark.parametrize("provider, client_cls", [("gemini", _GeminiClient), ("claude", _ClaudeClient)])
def test_stop_during_preparation(tmp_path, monkeypatch, sandboxed_user_data, provider, client_cls):
    client = client_cls()
    real_sniff = bt.sniff_file_type
    calls = {"n": 0}

    def sniff_then_stop(data):
        calls["n"] += 1
        if calls["n"] == 1:
            app_state.stop_event.set()  # Stop pressed while image 1 is prepared
        return real_sniff(data)

    monkeypatch.setattr(bt, "sniff_file_type", sniff_then_stop)
    summary = _run(tmp_path, monkeypatch, provider, client)
    assert client.created == 0 and calls["n"] == 1
    assert "Stopped before" in summary


@pytest.mark.parametrize("provider, client_cls", [("gemini", _GeminiClient), ("claude", _ClaudeClient)])
def test_stop_between_preparation_and_send(tmp_path, monkeypatch, sandboxed_user_data, provider, client_cls):
    """Every image is prepared, then Stop lands just before the create call."""
    client = client_cls()
    real_check = bt._send_if_not_stopped

    def stop_then_check(before_send):
        app_state.stop_event.set()
        return real_check(before_send)

    monkeypatch.setattr(bt, "_send_if_not_stopped", stop_then_check)
    summary = _run(tmp_path, monkeypatch, provider, client)
    assert client.created == 0
    assert "Stopped before" in summary
    with app_state.lock:
        assert not app_state.state.get("batch_submitting")


def test_stop_handler_reports_send_in_progress(sandboxed_user_data):
    """A Stop that arrives after the last check is reported as such; the
    poll loop then cancels the job (existing reconciliation path)."""
    sink = bt.TranscribeOffPeakSink()
    assert sink.begin_submission()
    with app_state.lock:
        assert app_state.state["batch_submitting"] is True
    sink.end_submission()
    app_state.stop_event.set()
    assert sink.begin_submission() is False
