"""Regression tests for Off-Peak Mode (batch_transcription.py +
handlers/transcribe_offpeak.py). No real network calls -- every provider
client is a fake with just enough surface (batches.create/get/cancel,
messages.batches.create/retrieve/cancel/results) to prove request shape,
result mapping, and state transitions, matching the conventions already
used by tests/test_prompt_caching.py (fake SDK clients) and
tests/test_run_concurrency.py (live_server for the HTTP-layer reservation
check)."""

from __future__ import annotations

import threading
import time
import types as pytypes
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

import json
import urllib.error

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


# --- run_off_peak_job() end to end (Gemini) --------------------------------


def test_run_off_peak_job_success_writes_output_and_resets_state(tmp_path, monkeypatch):
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

    assert "processed 2 image(s), 0 failure(s)" in summary
    assert download == str(docx_file)
    assert docx_file.exists()
    text = markdown_file.read_text(encoding="utf-8")
    assert "Entry A" in text and "Entry B" in text


def test_run_off_peak_job_tolerates_a_transient_poll_failure_then_succeeds(tmp_path, monkeypatch):
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


def test_run_off_peak_job_gives_up_after_sustained_poll_failures(tmp_path, monkeypatch):
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


def test_run_off_peak_job_cancellation_survives_a_poll_failure(tmp_path, monkeypatch):
    """Stop was already requested (cancel_gemini_batch() already called,
    best-effort) -- a poll failure racing right after that shouldn't be
    reported as a fatal error on top of an already-intentional stop."""
    from google.genai import errors as genai_errors

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    _write_jpeg(source_folder / "a.jpg")

    fake_client = _FakeGeminiClient()
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    app_state.stop_event.set()
    try:
        def poll_fails_once_cancelled(client, job_name):
            raise genai_errors.APIError(503, {"error": {"message": "unavailable"}})

        monkeypatch.setattr(bt, "poll_gemini_batch", poll_fails_once_cancelled)

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
            summary = app_state.state["summary"]
        assert not summary.startswith("Fatal error")
    finally:
        app_state.stop_event.clear()


def test_run_off_peak_job_cancellation_calls_provider_cancel(tmp_path, monkeypatch):
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

    time.sleep(0.2)
    with ctapp.lock:
        ctapp.state["running"] = False
