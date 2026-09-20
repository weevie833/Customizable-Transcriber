"""Regression tests for Off-Peak Mode (batch_transcription.py +
handlers/transcribe_offpeak.py). No real network calls -- every provider
client is a fake with just enough surface (batches.create/get/cancel,
messages.batches.create/retrieve/cancel/results) to prove request shape,
result mapping, and state transitions, matching the conventions already
used by tests/test_prompt_caching.py (fake SDK clients) and
tests/test_run_concurrency.py (live_server for the HTTP-layer reservation
check)."""

from __future__ import annotations

import json
import threading
import time
import types as pytypes
import urllib.error
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

import app as ctapp
import app_state
import batch_transcription as bt
import handlers.transcribe_offpeak as offpeak_handlers
from tests.test_run_concurrency import _get, _post


def _write_jpeg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)


# --- estimate_off_peak_savings() ------------------------------------------


def test_estimate_zero_images():
    assert bt.estimate_off_peak_savings(0, "two_facing", "gemini-2.5-pro") == (
        "Select a source folder to see an off-peak cost estimate."
    )


def test_estimate_varies_with_volume_and_page_layout():
    one_page = bt.estimate_off_peak_savings(100, "one_page", "gemini-2.5-pro")
    two_facing = bt.estimate_off_peak_savings(100, "two_facing", "gemini-2.5-pro")
    assert "100" in one_page and "1 register page" in one_page
    assert "100" in two_facing and "2 facing pages" in two_facing
    assert one_page != two_facing


def test_estimate_names_the_model_implicitly_via_token_constant():
    gemini_text = bt.estimate_off_peak_savings(10, "", "gemini-2.5-pro")
    claude_text = bt.estimate_off_peak_savings(10, "", "claude-sonnet-5")
    assert str(10 * bt.GEMINI_IMAGE_TOKENS_ESTIMATE) in gemini_text.replace(",", "")
    assert str(10 * bt.CLAUDE_IMAGE_TOKENS_ESTIMATE) in claude_text.replace(",", "")


# --- submit_gemini_batch() / submit_claude_batch() -------------------------


class _FakeGeminiBatches:
    def __init__(self, name="batches/fake123"):
        self._name = name
        self.created_with = None
        self.cancelled = []

    def create(self, model, src, config=None):
        self.created_with = (model, src, config)
        return pytypes.SimpleNamespace(name=self._name)

    def cancel(self, name):
        self.cancelled.append(name)


class _FakeGeminiClient:
    def __init__(self):
        self.batches = _FakeGeminiBatches()


def test_submit_gemini_batch_tags_each_request_with_a_positional_index(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    _write_jpeg(a)
    _write_jpeg(b)
    client = _FakeGeminiClient()

    job_name = bt.submit_gemini_batch(client, "gemini-2.5-pro", "system prompt", [a, b])

    assert job_name == "batches/fake123"
    model, src, _config = client.batches.created_with
    assert model == "gemini-2.5-pro"
    assert [req.metadata["index"] for req in src] == ["0", "1"]


def test_submit_gemini_batch_rejects_a_mislabeled_file_before_submission(tmp_path):
    fake = tmp_path / "not_a_jpeg.jpg"
    fake.write_bytes(b"this is not an image")
    client = _FakeGeminiClient()

    with pytest.raises(bt.BatchSubmissionError, match="does not look like"):
        bt.submit_gemini_batch(client, "gemini-2.5-pro", "system prompt", [fake])
    assert client.batches.created_with is None


class _FakeClaudeBatches:
    def __init__(self, batch_id="msgbatch_fake456"):
        self._id = batch_id
        self.created_with = None
        self.cancelled = []

    def create(self, requests):
        self.created_with = requests
        return pytypes.SimpleNamespace(id=self._id)

    def cancel(self, batch_id):
        self.cancelled.append(batch_id)


class _FakeClaudeClient:
    def __init__(self):
        self.messages = pytypes.SimpleNamespace(batches=_FakeClaudeBatches())
        self.options_used = []

    def with_options(self, **options):
        # Real SDK returns a re-configured copy; the fake shares state so tests can inspect it.
        self.options_used.append(options)
        return self


def test_submit_claude_batch_tags_each_request_with_custom_id(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    _write_jpeg(a)
    _write_jpeg(b)
    client = _FakeClaudeClient()

    batch_id = bt.submit_claude_batch(client, "claude-sonnet-5", "system prompt", [a, b])

    assert batch_id == "msgbatch_fake456"
    requests = client.messages.batches.created_with
    assert [req["custom_id"] for req in requests] == ["0", "1"]
    assert requests[0]["params"]["system"] == "system prompt"
    # H-1: batch creation is not idempotent, so the SDK must never auto-retry it.
    assert client.options_used == [{"max_retries": 0}]


# --- reverse_order (CODEX_REVIEW.md finding M-1) ---------------------------


def test_validated_images_honors_reverse_order(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    _write_jpeg(folder / "a.jpg")
    _write_jpeg(folder / "b.jpg")

    oldest_first = bt.validated_images(folder, frozenset({".jpg"}))
    newest_first = bt.validated_images(folder, frozenset({".jpg"}), reverse_order=True)

    assert [p.name for p in oldest_first] == ["a.jpg", "b.jpg"]
    assert [p.name for p in newest_first] == ["b.jpg", "a.jpg"]


# --- aggregate batch-capacity caps (CODEX_REVIEW.md finding M-2) -----------


def test_validated_images_rejects_over_item_count_cap(tmp_path, monkeypatch):
    folder = tmp_path / "source"
    folder.mkdir()
    _write_jpeg(folder / "a.jpg")
    monkeypatch.setattr(bt, "MAX_BATCH_IMAGE_COUNT", 1)
    _write_jpeg(folder / "b.jpg")  # 2 files, over the (patched) 1-image cap

    with pytest.raises(bt.BatchSubmissionError, match="over the 1-image limit"):
        bt.validated_images(folder, frozenset({".jpg"}))


def test_validated_images_rejects_over_aggregate_byte_cap(tmp_path, monkeypatch):
    folder = tmp_path / "source"
    folder.mkdir()
    _write_jpeg(folder / "a.jpg")  # 20 bytes, see _write_jpeg()
    _write_jpeg(folder / "b.jpg")
    monkeypatch.setattr(bt, "MAX_BATCH_AGGREGATE_BYTES", 25)  # a.jpg alone fits; both don't

    with pytest.raises(bt.BatchSubmissionError, match="over the aggregate limit"):
        bt.validated_images(folder, frozenset({".jpg"}))


def test_validated_images_accepts_a_batch_within_both_caps(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    _write_jpeg(folder / "a.jpg")
    _write_jpeg(folder / "b.jpg")

    # Defaults are generous (1000 images / ~2GB) -- two tiny fixture files
    # must pass through untouched.
    images = bt.validated_images(folder, frozenset({".jpg"}))
    assert [p.name for p in images] == ["a.jpg", "b.jpg"]


# --- run_off_peak_job() end to end (Gemini) --------------------------------


def test_run_off_peak_job_success_writes_output_and_resets_state(tmp_path, monkeypatch, sandboxed_user_data):
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")
    _write_jpeg(source_folder / "b.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    poll_calls = {"n": 0}

    def fake_poll(client, job_name):
        poll_calls["n"] += 1
        terminal = poll_calls["n"] >= 2
        state_value = bt.genai_types.JobState.JOB_STATE_SUCCEEDED if terminal else bt.genai_types.JobState.JOB_STATE_RUNNING
        stats = pytypes.SimpleNamespace(successful_count=2 if terminal else 0, failed_count=0, incomplete_count=0 if terminal else 2)
        dest = pytypes.SimpleNamespace(
            inlined_responses=[
                pytypes.SimpleNamespace(metadata={"index": "0"}, error=None, response=pytypes.SimpleNamespace(text="Entry A")),
                pytypes.SimpleNamespace(metadata={"index": "1"}, error=None, response=pytypes.SimpleNamespace(text="Entry B")),
            ]
        ) if terminal else None
        return pytypes.SimpleNamespace(state=state_value, completion_stats=stats, dest=dest)

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    markdown_file = tmp_path / "output.md"
    docx_file = tmp_path / "output.docx"

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=markdown_file,
        docx_file=docx_file,
        profile={"label": "Test Profile"},
    )

    with app_state.lock:
        assert app_state.state["running"] is False
        assert app_state.state["off_peak"] is False
        summary = app_state.state["summary"]
        download = app_state.state["download"]
        log = app_state.state["log"]

    assert "processed 2 image(s), 0 failure(s)" in summary
    assert download == str(docx_file)
    assert docx_file.exists()
    text = markdown_file.read_text(encoding="utf-8")
    assert "Entry A" in text and "Entry B" in text

    # CODEX_REVIEW.md finding H-1: a fully-resolved job leaves nothing
    # behind to (falsely) recover after a restart.
    assert app_state.read_off_peak_job_state() is None

    # Regression coverage for the real bug: the console log used to only
    # ever get the initial "submitted" line -- a run that finished cleanly
    # left it looking exactly like a still-hanging run, with no indication
    # anything had happened since. There must now be a submitted line, at
    # least one progress line, and a completion line, each timestamped.
    assert any("Off-peak batch submitted" in line for line in log)
    assert any("Off-peak progress:" in line for line in log)
    assert any("processed 2 image(s), 0 failure(s)" in line for line in log)
    import re

    assert all(re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", line) for line in log)


def test_run_off_peak_job_persists_running_state_before_the_first_poll(tmp_path, monkeypatch, sandboxed_user_data):
    """CODEX_REVIEW.md finding H-1: the job's non-secret identity must be on
    disk (for restart recovery) as soon as it exists, not only once it
    resolves -- checked from inside the very first poll call, i.e. before
    the job has had any chance to finish."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    seen_mid_run: dict[str, object] = {}

    def fake_poll(client, job_name):
        if not seen_mid_run:
            seen_mid_run.update(app_state.read_off_peak_job_state() or {})
        return pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
            completion_stats=pytypes.SimpleNamespace(successful_count=1, failed_count=0, incomplete_count=0),
            dest=pytypes.SimpleNamespace(inlined_responses=[]),
        )

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    assert seen_mid_run == {
        "provider": "gemini", "model": "gemini-2.5-pro", "job_id": "batches/fake123",
        "submitted_at": seen_mid_run.get("submitted_at"), "status": "running",
    }
    assert seen_mid_run.get("submitted_at")  # non-empty ISO timestamp
    assert "api_key" not in seen_mid_run and "fake-key" not in str(seen_mid_run)


def test_run_off_peak_job_progress_log_dedups_unchanged_counts(tmp_path, monkeypatch, sandboxed_user_data):
    """A multi-hour job polls every 30s -- if the counts haven't changed
    since the last poll, that must not append another near-identical
    progress line (hundreds of them over a real overnight run)."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    poll_calls = {"n": 0}

    def fake_poll(client, job_name):
        poll_calls["n"] += 1
        # Same "incomplete" reading three times in a row, then terminal --
        # only the first "incomplete" poll and the final terminal poll
        # should produce a progress line.
        terminal = poll_calls["n"] >= 4
        state_value = (
            bt.genai_types.JobState.JOB_STATE_SUCCEEDED if terminal else bt.genai_types.JobState.JOB_STATE_RUNNING
        )
        stats = pytypes.SimpleNamespace(
            successful_count=1 if terminal else 0, failed_count=0, incomplete_count=0 if terminal else 1
        )
        dest = (
            pytypes.SimpleNamespace(
                inlined_responses=[
                    pytypes.SimpleNamespace(metadata={"index": "0"}, error=None, response=pytypes.SimpleNamespace(text="Entry A")),
                ]
            )
            if terminal
            else None
        )
        return pytypes.SimpleNamespace(state=state_value, completion_stats=stats, dest=dest)

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True
        # run_off_peak_job() only ever appends to state["log"] -- resetting
        # it here (the real HTTP handler does this before spawning the job
        # thread) keeps this test's count assertion scoped to this run, not
        # polluted by whatever an earlier test in this module left behind.
        app_state.state["log"] = []

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    assert poll_calls["n"] == 4
    with app_state.lock:
        log = app_state.state["log"]
    progress_lines = [line for line in log if "Off-peak progress:" in line]
    # One for the first "incomplete 1" reading, one for the terminal
    # "succeeded 1" reading -- NOT one per poll (would be 4).
    assert len(progress_lines) == 2


def test_run_off_peak_job_tolerates_a_transient_poll_failure_then_succeeds(tmp_path, monkeypatch, sandboxed_user_data):
    """Regression test for the overnight-run bug: a single transient error
    from a *status check* used to abort the whole job even though the job
    itself was healthy. A poll that fails twice with a transient 503, then
    starts succeeding, must not abort the run at all."""
    from google.genai import errors as genai_errors

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    poll_calls = {"n": 0}

    def fake_poll(client, job_name):
        poll_calls["n"] += 1
        if poll_calls["n"] <= 2:
            raise genai_errors.APIError(503, {"error": {"message": "unavailable"}})
        dest = pytypes.SimpleNamespace(
            inlined_responses=[
                pytypes.SimpleNamespace(metadata={"index": "0"}, error=None, response=pytypes.SimpleNamespace(text="Entry A")),
            ]
        )
        stats = pytypes.SimpleNamespace(successful_count=1, failed_count=0, incomplete_count=0)
        return pytypes.SimpleNamespace(state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED, completion_stats=stats, dest=dest)

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    markdown_file = tmp_path / "output.md"
    docx_file = tmp_path / "output.docx"

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=markdown_file,
        docx_file=docx_file,
        profile={"label": "Test Profile"},
    )

    assert poll_calls["n"] == 3  # 2 failures tolerated, 3rd succeeds
    with app_state.lock:
        summary = app_state.state["summary"]
        assert not summary.startswith("Fatal error")
        assert "processed 1 image(s), 0 failure(s)" in summary


def test_run_off_peak_job_gives_up_after_sustained_poll_failures(tmp_path, monkeypatch, sandboxed_user_data):
    """A poll that NEVER recovers must still eventually give up (not poll
    forever with no way for the user to know) -- and the resulting fatal
    message must accurately describe what happened, unlike the real
    incident's misleading "already retried 3 times" text, which came from
    humanize_provider_error()'s generic 5xx wording built for the real-time
    per-image retry path, not this polling loop (which made 21 real
    attempts, not 3, before giving up)."""
    from google.genai import errors as genai_errors

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    def always_fails(client, job_name):
        raise genai_errors.APIError(503, {"error": {"message": "unavailable"}})

    monkeypatch.setattr(bt, "poll_gemini_batch", always_fails)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    with app_state.lock:
        assert app_state.state["running"] is False
        assert app_state.state["off_peak"] is False
        summary = app_state.state["summary"]
    assert summary.startswith("Fatal error")
    assert "batches/fake123" in summary  # names the job id so it can be checked manually
    assert "keeps running on the provider's own servers" in summary
    assert "already retried 3 times" not in summary  # the misleading text from the real incident


# --- honest cancellation confirmation (CODEX_REVIEW.md finding H-1) --------
#
# The single test that used to live here, test_run_off_peak_job_cancellation_
# survives_a_poll_failure, is gone -- it asserted the exact bug H-1 flagged:
# "One test deliberately treats a post-cancel poll failure as successful
# local completion" (CODEX_REVIEW.md finding L-1). A poll failure racing
# right after Stop says nothing about whether the provider actually stopped
# the job; the two tests below replace it with the corrected, honest
# behavior -- a transient failure is retried like any other (and confirms
# normally once polling recovers), and a cancellation that genuinely never
# confirms is reported as unconfirmed, never as a false "cancelled" success.


def test_run_off_peak_job_cancellation_tolerates_a_transient_poll_failure_then_confirms(tmp_path, monkeypatch, sandboxed_user_data):
    from google.genai import errors as genai_errors

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    poll_calls = {"n": 0}

    def fake_poll(client, job_name):
        poll_calls["n"] += 1
        if poll_calls["n"] <= 2:
            raise genai_errors.APIError(503, {"error": {"message": "unavailable"}})
        return pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_CANCELLED,
            completion_stats=pytypes.SimpleNamespace(successful_count=0, failed_count=0, incomplete_count=1),
            dest=None,
        )

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    app_state.stop_event.set()
    try:
        with app_state.lock:
            app_state.state["running"] = True
            app_state.state["off_peak"] = True

        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=source_folder,
            extensions=frozenset({".jpg", ".jpeg"}),
            model="gemini-2.5-pro",
            provider="gemini",
            system_prompt="system prompt",
            api_key_override="fake-key",
            markdown_file=tmp_path / "output.md",
            docx_file=tmp_path / "output.docx",
            profile={"label": "Test Profile"},
        )

        assert poll_calls["n"] == 3  # 2 transient failures tolerated, 3rd confirms
        with app_state.lock:
            assert app_state.state["running"] is False
            summary = app_state.state["summary"]
        assert not summary.startswith("Fatal error")
        assert "Off-peak batch cancelled" in summary
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_cancellation_that_never_confirms_is_not_reported_as_success(tmp_path, monkeypatch, sandboxed_user_data):
    """The exact false-success shape H-1 flagged: cancellation was
    requested, but every status check after that fails -- this app truly
    cannot confirm the provider ever stopped the job, so it must say so
    (or, as here, eventually give up watching) rather than silently
    reporting "cancelled" as if it were confirmed."""
    from google.genai import errors as genai_errors

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    def always_fails(client, job_name):
        raise genai_errors.APIError(503, {"error": {"message": "unavailable"}})

    monkeypatch.setattr(bt, "poll_gemini_batch", always_fails)

    app_state.stop_event.set()
    try:
        with app_state.lock:
            app_state.state["running"] = True
            app_state.state["off_peak"] = True

        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=source_folder,
            extensions=frozenset({".jpg", ".jpeg"}),
            model="gemini-2.5-pro",
            provider="gemini",
            system_prompt="system prompt",
            api_key_override="fake-key",
            markdown_file=tmp_path / "output.md",
            docx_file=tmp_path / "output.docx",
            profile={"label": "Test Profile"},
        )

        with app_state.lock:
            assert app_state.state["running"] is False
            summary = app_state.state["summary"]
        # The old bug's exact shape: reporting a clean "cancelled" success
        # while nothing was ever actually confirmed.
        assert summary != "Off-peak batch cancelled after 0 image(s), 0 failure(s)."
        assert summary.startswith("Fatal error")
        assert "batches/fake123" in summary
        assert "never able to confirm" in summary

        job_state = app_state.read_off_peak_job_state()
        assert job_state is not None
        assert job_state["status"] == "status_unknown"
        assert job_state["job_id"] == "batches/fake123"
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_reports_unconfirmed_when_cancellation_never_reaches_a_terminal_state(
    tmp_path, monkeypatch, sandboxed_user_data
):
    """Distinct from the "polls keep failing" test above: here every poll
    *succeeds*, but the job simply never reports a terminal state within
    the confirmation window -- e.g. the provider's cancel silently no-opped
    and the job just keeps running. Must give up and say so honestly
    (bt.CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS), not wait forever and
    not report a false "cancelled" success either."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    # A fake monotonic clock, advancing one POLL_INTERVAL_SECONDS per call --
    # time.sleep() is stubbed out above, so a real clock would never move
    # far enough (in test time) to cross the confirmation deadline.
    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += bt.POLL_INTERVAL_SECONDS
        return clock["t"]

    monkeypatch.setattr(bt.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(
        bt,
        "poll_gemini_batch",
        lambda client, job_name: pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_RUNNING,
            completion_stats=pytypes.SimpleNamespace(successful_count=0, failed_count=0, incomplete_count=1),
            dest=None,
        ),
    )

    app_state.stop_event.set()
    try:
        with app_state.lock:
            app_state.state["running"] = True
            app_state.state["off_peak"] = True

        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=source_folder,
            extensions=frozenset({".jpg", ".jpeg"}),
            model="gemini-2.5-pro",
            provider="gemini",
            system_prompt="system prompt",
            api_key_override="fake-key",
            markdown_file=tmp_path / "output.md",
            docx_file=tmp_path / "output.docx",
            profile={"label": "Test Profile"},
        )

        with app_state.lock:
            assert app_state.state["running"] is False
            summary = app_state.state["summary"]
            download = app_state.state["download"]
        assert not summary.startswith("Fatal error")
        assert "could not be confirmed" in summary
        assert "may still be running (and billing)" in summary
        assert "batches/fake123" in summary
        assert download == ""  # nothing terminal to collect results from

        job_state = app_state.read_off_peak_job_state()
        assert job_state is not None
        assert job_state["status"] == "status_unknown"
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_cancellation_calls_provider_cancel(tmp_path, monkeypatch, sandboxed_user_data):
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    app_state.stop_event.set()
    try:
        monkeypatch.setattr(
            bt,
            "poll_gemini_batch",
            lambda client, job_name: pytypes.SimpleNamespace(
                state=bt.genai_types.JobState.JOB_STATE_CANCELLED,
                completion_stats=pytypes.SimpleNamespace(successful_count=0, failed_count=0, incomplete_count=1),
                dest=None,
            ),
        )
        with app_state.lock:
            app_state.state["running"] = True
            app_state.state["off_peak"] = True

        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=source_folder,
            extensions=frozenset({".jpg", ".jpeg"}),
            model="gemini-2.5-pro",
            provider="gemini",
            system_prompt="system prompt",
            api_key_override="fake-key",
            markdown_file=tmp_path / "output.md",
            docx_file=tmp_path / "output.docx",
            profile={"label": "Test Profile"},
        )

        assert fake_client.batches.cancelled == ["batches/fake123"]
        with app_state.lock:
            assert app_state.state["running"] is False
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_reports_honestly_when_it_finishes_before_cancellation_takes_effect(
    tmp_path, monkeypatch, sandboxed_user_data
):
    """CODEX_REVIEW.md finding H-1: Stop was pressed, but the provider's own
    terminal state is SUCCEEDED, not CANCELLED -- the job simply finished
    before the cancel request took effect. Real, complete results exist;
    reporting this as "cancelled" would be just as dishonest as the
    original false-success bug, in the opposite direction."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        bt,
        "poll_gemini_batch",
        lambda client, job_name: pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
            completion_stats=pytypes.SimpleNamespace(successful_count=1, failed_count=0, incomplete_count=0),
            dest=pytypes.SimpleNamespace(
                inlined_responses=[
                    pytypes.SimpleNamespace(
                        metadata={"index": "0"}, error=None, response=pytypes.SimpleNamespace(text="Entry A")
                    ),
                ]
            ),
        ),
    )

    app_state.stop_event.set()
    try:
        with app_state.lock:
            app_state.state["running"] = True
            app_state.state["off_peak"] = True

        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=source_folder,
            extensions=frozenset({".jpg", ".jpeg"}),
            model="gemini-2.5-pro",
            provider="gemini",
            system_prompt="system prompt",
            api_key_override="fake-key",
            markdown_file=tmp_path / "output.md",
            docx_file=tmp_path / "output.docx",
            profile={"label": "Test Profile"},
        )

        with app_state.lock:
            summary = app_state.state["summary"]
            download = app_state.state["download"]
        assert "cancelled" not in summary.lower()
        assert "finished processing before cancellation took effect" in summary
        assert "1 image(s), 0 failure(s)" in summary
        assert download  # real results were still written
        assert app_state.read_off_peak_job_state() is None  # fully resolved
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_honors_newest_first_order(tmp_path, monkeypatch, sandboxed_user_data):
    """Regression test for CODEX_REVIEW.md finding M-1: the confirmation UI
    can promise "Newest-to-oldest" while the batch was always submitted (and
    its output therefore written) oldest-to-newest, because the selected
    order was validated and stored but never threaded through to the job."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")
    _write_jpeg(source_folder / "b.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    submitted_names: list[str] = []
    real_submit = bt.submit_gemini_batch

    def spying_submit(client, model, system_prompt, images):
        submitted_names.extend(path.name for path in images)
        return real_submit(client, model, system_prompt, images)

    monkeypatch.setattr(bt, "submit_gemini_batch", spying_submit)
    monkeypatch.setattr(
        bt,
        "poll_gemini_batch",
        lambda client, job_name: pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
            completion_stats=pytypes.SimpleNamespace(successful_count=2, failed_count=0, incomplete_count=0),
            dest=pytypes.SimpleNamespace(inlined_responses=[]),
        ),
    )

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
        reverse_order=True,
    )

    assert submitted_names == ["b.jpg", "a.jpg"]


# --- explicit provider timeouts (CODEX_REVIEW.md finding M-3) --------------


def test_run_off_peak_job_uses_explicit_heavy_and_light_gemini_timeouts(tmp_path, monkeypatch, sandboxed_user_data):
    """Before this, submission/status/cancel all shared one client built
    with no explicit timeout at all, so a network stall anywhere could hang
    indefinitely and delay Stop (which this loop only checks between
    polls). Submission/results now get a generous bound; polling/cancel get
    a much shorter one so a hang is caught quickly."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    created_timeouts_ms: list[int] = []

    def fake_client_factory(**kwargs):
        created_timeouts_ms.append(kwargs["http_options"].timeout)
        return _FakeGeminiClient()

    monkeypatch.setattr(bt.genai, "Client", fake_client_factory)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        bt,
        "poll_gemini_batch",
        lambda client, job_name: pytypes.SimpleNamespace(
            state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
            completion_stats=pytypes.SimpleNamespace(successful_count=1, failed_count=0, incomplete_count=0),
            dest=pytypes.SimpleNamespace(inlined_responses=[]),
        ),
    )

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    # Two clients constructed: one heavy (submit/collect), one light (poll/cancel).
    assert created_timeouts_ms == [
        bt.BATCH_SUBMIT_TIMEOUT_SECONDS * 1000,
        bt.BATCH_STATUS_TIMEOUT_SECONDS * 1000,
    ]


def test_run_off_peak_job_submission_timeout_produces_a_clear_error(tmp_path, monkeypatch, sandboxed_user_data):
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    def raise_timeout(client, model, system_prompt, images):
        raise bt.httpx.TimeoutException("connect timed out")

    monkeypatch.setattr(bt, "submit_gemini_batch", raise_timeout)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    with app_state.lock:
        summary = app_state.state["summary"]
    assert summary.startswith("Fatal error")
    assert "did not finish within" in summary
    assert str(bt.BATCH_SUBMIT_TIMEOUT_SECONDS) in summary


def test_run_off_peak_job_tolerates_a_gemini_poll_timeout(tmp_path, monkeypatch, sandboxed_user_data):
    """Regression test for CODEX_REVIEW.md finding M-3: Gemini's SDK lets a
    timeout escape as a bare httpx.TimeoutException rather than wrapping it
    in genai_errors.APIError (confirmed: xls_conversion/ai_parser.py and
    handlers/profiles.py already catch httpx.TimeoutException directly for
    the same reason), so before _is_transient_poll_error() existed, a
    single poll timeout aborted the whole job instead of being retried the
    same way every other transient status-check failure already is."""
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    poll_calls = {"n": 0}

    def fake_poll(client, job_name):
        poll_calls["n"] += 1
        if poll_calls["n"] <= 2:
            raise bt.httpx.TimeoutException("read timed out")
        dest = pytypes.SimpleNamespace(
            inlined_responses=[
                pytypes.SimpleNamespace(metadata={"index": "0"}, error=None, response=pytypes.SimpleNamespace(text="Entry A")),
            ]
        )
        stats = pytypes.SimpleNamespace(successful_count=1, failed_count=0, incomplete_count=0)
        return pytypes.SimpleNamespace(state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED, completion_stats=stats, dest=dest)

    monkeypatch.setattr(bt, "poll_gemini_batch", fake_poll)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="gemini-2.5-pro",
        provider="gemini",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    assert poll_calls["n"] == 3  # 2 timeouts tolerated, 3rd succeeds
    with app_state.lock:
        summary = app_state.state["summary"]
    assert not summary.startswith("Fatal error")
    assert "processed 1 image(s), 0 failure(s)" in summary


def test_run_off_peak_job_collect_results_timeout_produces_a_clear_error(tmp_path, monkeypatch, sandboxed_user_data):
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    monkeypatch.setattr(bt.anthropic, "Anthropic", lambda **kwargs: _FakeClaudeClient())
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        bt,
        "poll_claude_batch",
        lambda client, batch_id: pytypes.SimpleNamespace(
            processing_status="ended",
            request_counts=pytypes.SimpleNamespace(
                succeeded=1, errored=0, processing=0, canceled=0, expired=0
            ),
        ),
    )

    def raise_timeout(client, batch_id):
        raise bt.httpx.TimeoutException("read timed out")

    monkeypatch.setattr(bt, "collect_claude_batch_results", raise_timeout)

    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True

    bt.run_off_peak_job(
        project_dir=tmp_path,
        image_folder=source_folder,
        extensions=frozenset({".jpg", ".jpeg"}),
        model="claude-sonnet-5",
        provider="claude",
        system_prompt="system prompt",
        api_key_override="fake-key",
        markdown_file=tmp_path / "output.md",
        docx_file=tmp_path / "output.docx",
        profile={"label": "Test Profile"},
    )

    with app_state.lock:
        summary = app_state.state["summary"]
    assert summary.startswith("Fatal error")
    assert "downloading its results did not finish" in summary


# --- /api/offpeak-cost-estimate (HTTP layer) -------------------------------


def test_cost_estimate_endpoint_handles_a_stale_missing_source_folder(live_server, sandboxed_user_data, monkeypatch):
    """Regression test for a real bug caught during this feature's own live
    verification: a stored source folder that no longer exists on disk
    (moved/renamed/unmounted, or a settings file left over from a different
    machine) made count_source_files_by_type() raise FileNotFoundError,
    which this endpoint didn't catch -- crashing the connection
    (net::ERR_EMPTY_RESPONSE in the browser) instead of degrading to a
    "0 images found" estimate."""
    host, port = live_server
    monkeypatch.setattr(ctapp, "load_source_folder", lambda: Path("/does/not/exist/anywhere"))

    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _get(
        host, port, "/api/offpeak-cost-estimate?model=gemini-2.5-pro&file_type=jpeg&profile_id=", jar
    )
    assert response.status == 200
    data = json.loads(response.read())
    assert data["image_count"] == 0


def test_cost_estimate_endpoint_rejects_invalid_model(live_server, sandboxed_user_data):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)
    # urllib's default opener raises HTTPError (not a normal return) for a
    # non-2xx response -- matches how the other tests in this suite that
    # expect an error status are written.
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(host, port, "/api/offpeak-cost-estimate?model=not-a-real-model&file_type=jpeg&profile_id=", jar)
    assert excinfo.value.code == 400


# --- /run-offpeak reservation (HTTP layer) ---------------------------------


def test_run_offpeak_rejected_while_already_running(live_server, sandboxed_user_data):
    host, port = live_server
    with ctapp.lock:
        ctapp.state["running"] = True
    try:
        jar = CookieJar()
        _get(host, port, "/", jar, retries=3)
        response = _post(
            host, port, jar, "/run-offpeak",
            {"gemini_api_key": "fake-key", "profile_id": "does-not-matter", "order": "oldest", "file_type": "jpeg"},
            timeout=3, retries=3,
        )
        assert response.status == 200  # redirected, not hung -- same as /run's own busy path
    finally:
        with ctapp.lock:
            ctapp.state["running"] = False


def test_run_offpeak_spawns_a_job_and_reserves_the_shared_run_slot(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")
    monkeypatch.setattr(offpeak_handlers, "load_source_folder", lambda: source_folder)

    profile = ctapp.save_custom_profile("Off-Peak Test Profile", "role", "reference", "format")

    job_started = threading.Event()
    job_calls = []

    def fake_run_off_peak_job(**kwargs):
        job_calls.append(kwargs)
        job_started.set()
        # Mirrors run_off_peak_job()'s own finally block without doing any
        # real provider work -- this test only cares that the HTTP layer
        # reserved the slot and handed off to the background job correctly.
        with app_state.lock:
            app_state.state["running"] = False
            app_state.state["off_peak"] = False

    monkeypatch.setattr(offpeak_handlers, "run_off_peak_job", fake_run_off_peak_job)

    with ctapp.lock:
        ctapp.state["running"] = False

    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _post(
        host, port, jar, "/run-offpeak",
        {
            "gemini_api_key": "fake-key",
            "profile_id": profile["id"],
            "profile_action": "use",
            "order": "oldest",
            "file_type": "jpeg",
        },
    )
    assert response.status == 200

    assert job_started.wait(timeout=2)
    assert len(job_calls) == 1
    assert job_calls[0]["provider"] == "gemini"
    assert job_calls[0]["image_folder"] == source_folder
    assert job_calls[0]["reverse_order"] is False

    time.sleep(0.2)
    with ctapp.lock:
        ctapp.state["running"] = False


def test_run_offpeak_forwards_newest_first_order_to_the_job(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    """Regression test for CODEX_REVIEW.md finding M-1 at the HTTP layer:
    the /run-offpeak handler validated and stored the selected order in
    state, but never passed it to the background job -- see
    test_run_off_peak_job_honors_newest_first_order for the job-level half
    of this same fix."""
    host, port = live_server
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")
    monkeypatch.setattr(offpeak_handlers, "load_source_folder", lambda: source_folder)

    profile = ctapp.save_custom_profile("Off-Peak Order Test Profile", "role", "reference", "format")

    job_started = threading.Event()
    job_calls = []

    def fake_run_off_peak_job(**kwargs):
        job_calls.append(kwargs)
        job_started.set()
        with app_state.lock:
            app_state.state["running"] = False
            app_state.state["off_peak"] = False

    monkeypatch.setattr(offpeak_handlers, "run_off_peak_job", fake_run_off_peak_job)

    with ctapp.lock:
        ctapp.state["running"] = False

    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _post(
        host, port, jar, "/run-offpeak",
        {
            "gemini_api_key": "fake-key",
            "profile_id": profile["id"],
            "profile_action": "use",
            "order": "newest",
            "file_type": "jpeg",
        },
    )
    assert response.status == 200

    assert job_started.wait(timeout=2)
    assert job_calls[0]["reverse_order"] is True

    time.sleep(0.2)
    with ctapp.lock:
        ctapp.state["running"] = False


def test_gemini_batches_get_a_unique_display_name(tmp_path):
    a = tmp_path / "a.jpg"
    _write_jpeg(a)
    names = []

    class _Batches:
        def create(self, model, src, config):
            names.append(config.display_name)
            return pytypes.SimpleNamespace(name="batches/x")

    client = pytypes.SimpleNamespace(batches=_Batches())
    bt.submit_gemini_batch(client, "gemini-2.5-pro", "system prompt", [a])
    bt.submit_gemini_batch(client, "gemini-2.5-pro", "system prompt", [a])
    assert names[0] != names[1]
    assert all(n.startswith("customizable-transcription-offpeak-") for n in names)


def test_aggregate_cap_is_conservative():
    assert bt.MAX_BATCH_AGGREGATE_BYTES == 500_000_000


def test_failed_job_state_write_is_reported_not_silent(tmp_path, monkeypatch, sandboxed_user_data):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(app_state, "atomic_write_text", boom)
    assert app_state.write_off_peak_job_state(job_id="j1") is False
    with app_state.lock:
        assert any("could not save the off-peak job record" in line for line in app_state.state["log"])
