"""Test Mode's Off-Peak option (batch_transcription.run_test_off_peak_job() +
/test-mode/run-offpeak). No real network calls: the Gemini batch client and
its status polling are fakes, as in tests/test_offpeak_batch.py."""

from __future__ import annotations

import threading
import types as pytypes

import app as ctapp
import app_state
import batch_transcription as bt
import handlers.test_mode_run as test_mode_handlers
import run_support
from tests.test_offpeak_batch import _FakeGeminiClient, _write_jpeg
from tests.test_post_redirect_get import _get_csrf_cookie, _post_no_redirect


class _Form:
    def __init__(self, **fields):
        self.fields = fields

    def getfirst(self, name, default=None):
        return self.fields.get(name, default)


def _succeeded_job(count):
    return pytypes.SimpleNamespace(
        state=bt.genai_types.JobState.JOB_STATE_SUCCEEDED,
        completion_stats=pytypes.SimpleNamespace(successful_count=count, failed_count=0, incomplete_count=0),
        dest=pytypes.SimpleNamespace(
            inlined_responses=[
                pytypes.SimpleNamespace(
                    metadata={"index": str(i)}, error=None, response=pytypes.SimpleNamespace(text=f"Entry {i}")
                )
                for i in range(count)
            ]
        ),
    )


def _setup(tmp_path, monkeypatch, run_ids):
    source = tmp_path / "source"
    source.mkdir()
    _write_jpeg(source / "a.jpg")
    _write_jpeg(source / "b.jpg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source)
    monkeypatch.setattr(bt, "approved_profile", lambda form, profile: {"id": "p", "label": "Profile", "role_context": "r"})
    monkeypatch.setattr(bt, "build_system_prompt", lambda tool, profile: "system prompt")
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    specs = []
    runs = {}
    for run_id in run_ids:
        markdown = tmp_path / f"{run_id}.md"
        docx = tmp_path / f"{run_id}.docx"
        specs.append((run_id, f"Batch 1 · {run_id}", "gemini-3.1-pro-preview", "fake-key", markdown, docx))
        run_state = app_state.new_test_run_state()
        run_state.update({"label": run_id, "model": "gemini-3.1-pro-preview", "output": str(docx)})
        runs[run_id] = run_state
    with app_state.test_lock:
        app_state.test_state["running"] = True
        app_state.test_state["off_peak"] = True
        app_state.test_state["log"] = []
        app_state.test_state["runs"] = runs
    return specs


def test_every_run_is_submitted_and_collected(tmp_path, monkeypatch, sandboxed_user_data):
    specs = _setup(tmp_path, monkeypatch, ["b1-a", "b1-b"])
    clients = []

    def make_client(**kwargs):
        client = _FakeGeminiClient()
        clients.append(client)
        return client

    monkeypatch.setattr(bt.genai, "Client", make_client)
    monkeypatch.setattr(bt, "poll_gemini_batch", lambda client, name: _succeeded_job(2))

    bt.run_test_off_peak_job(_Form(file_type="jpeg", order="oldest"), specs)

    submitted = [c for c in clients if c.batches.created_with is not None]
    assert len(submitted) == 2
    with app_state.test_lock:
        assert app_state.test_state["running"] is False
        assert app_state.test_state["off_peak"] is False
        assert app_state.test_state["summary"] == "2/2 run(s) complete."
        runs = {k: dict(v) for k, v in app_state.test_state["runs"].items()}
        log = list(app_state.test_state["log"])
    for run_id, *_rest, markdown, docx in specs:
        assert runs[run_id]["download"] == str(docx)
        assert runs[run_id]["markdown"] == str(markdown)
        assert "processed 2 image(s), 0 failure(s)" in runs[run_id]["summary"]
        assert "Entry 0" in markdown.read_text(encoding="utf-8")
    # Each run's log lines carry its own tag.
    assert any(line.startswith("[Batch 1 · b1-a: gemini-3.1-pro-preview]") for line in log)
    assert any(line.startswith("[Batch 1 · b1-b: gemini-3.1-pro-preview]") for line in log)
    # Fully resolved jobs leave no record to surface after a restart.
    assert app_state.read_test_off_peak_jobs() == {}


def test_one_runs_failure_does_not_stop_the_others(tmp_path, monkeypatch, sandboxed_user_data):
    specs = _setup(tmp_path, monkeypatch, ["b1-a", "b1-b"])
    real_submit = bt.submit_gemini_batch
    calls = {"n": 0}
    calls_lock = threading.Lock()

    def flaky_submit(client, model, system_prompt, images, zoom_pages=False, **kwargs):
        with calls_lock:
            calls["n"] += 1
            first = calls["n"] == 1
        if first:
            raise RuntimeError("provider rejected the batch")
        return real_submit(client, model, system_prompt, images, zoom_pages=zoom_pages, **kwargs)

    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())
    monkeypatch.setattr(bt, "submit_gemini_batch", flaky_submit)
    monkeypatch.setattr(bt, "poll_gemini_batch", lambda client, name: _succeeded_job(2))

    bt.run_test_off_peak_job(_Form(file_type="jpeg", order="oldest"), specs)

    with app_state.test_lock:
        summaries = [run["summary"] for run in app_state.test_state["runs"].values()]
        downloads = [run["download"] for run in app_state.test_state["runs"].values()]
        overall = app_state.test_state["summary"]
        assert app_state.test_state["running"] is False
    assert sum(1 for s in summaries if s.startswith("Failed:")) == 1
    assert sum(1 for d in downloads if d) == 1
    assert overall == "1/2 run(s) complete, 1 failed."


def test_unresolved_job_is_recorded_per_run_and_surfaced_then_reset(tmp_path, monkeypatch, sandboxed_user_data):
    specs = _setup(tmp_path, monkeypatch, ["b1-a"])
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: _FakeGeminiClient())

    def broken_poll(client, name):
        raise ValueError("not a transient error")

    monkeypatch.setattr(bt, "poll_gemini_batch", broken_poll)

    bt.run_test_off_peak_job(_Form(file_type="jpeg", order="oldest"), specs)

    jobs = app_state.read_test_off_peak_jobs()
    assert len(jobs) == 1
    (key, job), = jobs.items()
    assert key.startswith("b1-a#")  # keyed per job, not just per run id (M-3)
    assert job["status"] == "status_unknown"
    assert job["job_id"] == "batches/fake123"
    assert "api_key" not in job

    with app_state.test_lock:
        app_state.test_state["log"] = []
        app_state.test_state["summary"] = ""
    app_state.surface_stale_test_off_peak_jobs()
    with app_state.test_lock:
        log = "\n".join(app_state.test_state["log"])
    assert "batches/fake123" in log

    app_state.reset_test_ui_state()
    assert not app_state.TEST_OFF_PEAK_JOBS_FILE.exists()


def test_stop_while_waiting_to_submit_sends_nothing(tmp_path, monkeypatch, sandboxed_user_data):
    specs = _setup(tmp_path, monkeypatch, ["b1-a"])
    created = []
    monkeypatch.setattr(bt.genai, "Client", lambda **kwargs: created.append(_FakeGeminiClient()) or created[-1])
    lock = threading.Lock()
    app_state.test_stop_event.set()
    try:
        _run_id, _label, model, key, markdown, docx = specs[0]
        bt.run_off_peak_job(
            project_dir=tmp_path,
            image_folder=run_support.load_source_folder(),
            extensions=frozenset({".jpg"}),
            model=model,
            provider="gemini",
            system_prompt="system prompt",
            api_key_override=key,
            markdown_file=markdown,
            docx_file=docx,
            profile={"label": "Profile"},
            sink=bt.TestModeOffPeakSink("b1-a", "[tag]", markdown),
            submit_lock=lock,
        )
    finally:
        app_state.test_stop_event.clear()
        with app_state.test_lock:
            # run_off_peak_job() with a Test Mode sink never frees the run slot
            # itself (run_test_off_peak_job() does), so free it here.
            app_state.test_state["running"] = False
            app_state.test_state["off_peak"] = False
    assert created == []
    with app_state.test_lock:
        assert app_state.test_state["runs"]["b1-a"]["summary"] == "Stopped before this off-peak batch was submitted."


def test_run_offpeak_route_starts_the_off_peak_job(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    source = tmp_path / "source"
    source.mkdir()
    (source / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source)
    started = threading.Event()
    monkeypatch.setattr(test_mode_handlers, "run_test_off_peak_job", lambda form, run_specs, *_: started.set())
    monkeypatch.setattr(test_mode_handlers, "run_test_job", lambda form, run_specs, *_: None)

    profile = ctapp.save_custom_profile("Off-Peak Route Profile", "role", "reference", "format")
    try:
        response = _post_no_redirect(
            host,
            port,
            jar,
            "/test-mode/run-offpeak",
            {
                "api_key_gemini": "fake-key-gemini",
                "profile_id": profile["id"],
                "order": "oldest",
                "file_type": "jpeg",
                "model_a": "gemini-3.1-pro-preview",
                "model_b": "gemini-4-argon",
            },
        )
        assert response.status == 303
        assert response.getheader("Location") == "/test-mode"
        assert started.wait(5), ctapp.test_state["summary"]
        with ctapp.test_lock:
            assert ctapp.test_state["off_peak"] is True
            assert "off-peak" in ctapp.test_state["summary"]
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
            ctapp.test_state["off_peak"] = False
