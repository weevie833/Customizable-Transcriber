"""Regression test for the sandboxed_user_data fixture's own correctness --
see its docstring in conftest.py. save_source_folder()/load_source_folder()/
clear_source_folder() are defined in app_state.py (not app.py), so they read
APP_SETTINGS_FILE from app_state's own module globals regardless of what
app.APP_SETTINGS_FILE has been patched to. This proves the fixture patches
the module that actually matters, using the exact functions most likely to
regress silently if a future refactor moves them again without updating the
fixture to match."""

from __future__ import annotations

from pathlib import Path

import app_state


def test_source_folder_round_trip_stays_in_sandbox(sandboxed_user_data):
    assert app_state.load_source_folder() is None

    some_folder = Path("/tmp/example-source-folder")
    app_state.save_source_folder(some_folder)

    assert app_state.APP_SETTINGS_FILE.exists()
    assert app_state.APP_SETTINGS_FILE.is_relative_to(sandboxed_user_data)
    assert app_state.load_source_folder() == some_folder

    app_state.clear_source_folder()
    assert app_state.load_source_folder() is None


def test_reset_ui_state_clears_source_folder_in_sandbox(sandboxed_user_data):
    app_state.save_source_folder(Path("/tmp/another-folder"))
    assert app_state.load_source_folder() is not None

    app_state.reset_ui_state()

    assert app_state.load_source_folder() is None
    # The settings file itself may still exist (emptied, not deleted) or be
    # gone entirely depending on what else was in it -- either is fine, the
    # only contract here is that it's the sandboxed file, not the real one.
    if app_state.APP_SETTINGS_FILE.exists():
        assert app_state.APP_SETTINGS_FILE.is_relative_to(sandboxed_user_data)


# --- off-peak job persistence (CODEX_REVIEW.md finding H-1) ----------------
# write_off_peak_job_state()/read_off_peak_job_state()/clear_off_peak_job_state()/
# surface_stale_off_peak_job() are all defined in app_state.py, same as the
# source-folder functions above -- same reasoning, same regression-test
# shape: prove the sandbox fixture patches the copy that actually matters.


def test_off_peak_job_state_round_trip_stays_in_sandbox(sandboxed_user_data):
    assert app_state.read_off_peak_job_state() is None

    app_state.write_off_peak_job_state(
        provider="gemini", model="gemini-2.5-pro", job_id="batches/abc123",
        submitted_at="2026-09-17T12:00:00", status="running",
    )

    assert app_state.OFF_PEAK_JOB_FILE.exists()
    assert app_state.OFF_PEAK_JOB_FILE.is_relative_to(sandboxed_user_data)
    job = app_state.read_off_peak_job_state()
    assert job == {
        "provider": "gemini", "model": "gemini-2.5-pro", "job_id": "batches/abc123",
        "submitted_at": "2026-09-17T12:00:00", "status": "running",
    }
    # Never persisted, on principle -- see OFF_PEAK_JOB_FILE's own comment.
    assert "api_key" not in job and "key" not in job

    app_state.clear_off_peak_job_state()
    assert app_state.read_off_peak_job_state() is None


def test_reset_ui_state_clears_off_peak_job_state_in_sandbox(sandboxed_user_data):
    app_state.write_off_peak_job_state(
        provider="claude", model="claude-sonnet-5", job_id="msgbatch_xyz",
        submitted_at="2026-09-17T12:00:00", status="status_unknown",
    )
    assert app_state.read_off_peak_job_state() is not None

    app_state.reset_ui_state()

    assert app_state.read_off_peak_job_state() is None


def test_surface_stale_off_peak_job_logs_and_sets_summary(sandboxed_user_data):
    app_state.write_off_peak_job_state(
        provider="gemini", model="gemini-2.5-pro", job_id="batches/stale789",
        submitted_at="2026-09-17T12:00:00", status="cancellation_requested",
    )
    with app_state.lock:
        app_state.state["log"] = []
        app_state.state["summary"] = ""

    app_state.surface_stale_off_peak_job()

    with app_state.lock:
        log = app_state.state["log"]
        summary = app_state.state["summary"]
    assert any("batches/stale789" in line for line in log)
    assert any("cannot resume watching it automatically" in line for line in log)
    assert "batches/stale789" in summary


def test_surface_stale_off_peak_job_does_nothing_when_no_job_is_stale(sandboxed_user_data):
    with app_state.lock:
        app_state.state["log"] = []
        app_state.state["summary"] = ""

    app_state.surface_stale_off_peak_job()

    with app_state.lock:
        assert app_state.state["log"] == []
        assert app_state.state["summary"] == ""
