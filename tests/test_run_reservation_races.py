"""reviews/CODEX_REVIEW_8.md M-4: Reset, Stop and queue edits can't undo or
lose a run reservation, whatever order they arrive in."""

from __future__ import annotations

import threading

import app as ctapp
import app_state
import handlers.transcribe_run as transcribe_handlers
import run_support
from tests.test_post_redirect_get import _get_csrf_cookie, _post_no_redirect


def test_reset_refuses_while_a_run_is_reserved(sandboxed_user_data):
    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["summary"] = "Running X..."
    try:
        assert app_state.reset_ui_state() is False
        with app_state.lock:
            assert app_state.state["running"] is True
            assert app_state.state["summary"] == "Running X..."
    finally:
        with app_state.lock:
            app_state.state["running"] = False
    assert app_state.reset_ui_state() is True


def test_test_mode_reset_refuses_while_reserved(sandboxed_user_data):
    with app_state.test_lock:
        app_state.test_state["running"] = True
        app_state.test_state["queue"] = [{"batch_id": "b"}]
    try:
        assert app_state.reset_test_ui_state() is False
        with app_state.test_lock:
            assert app_state.test_state["queue"] == [{"batch_id": "b"}]
    finally:
        with app_state.test_lock:
            app_state.test_state["running"] = False
            app_state.test_state["queue"] = []


def test_stop_during_setup_is_honoured(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    source = tmp_path / "source"
    source.mkdir()
    (source / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source)
    started = threading.Event()
    monkeypatch.setattr(transcribe_handlers, "run_job", lambda form, output_file, *_: started.set())
    real_destination = transcribe_handlers.destination_output_file

    def stop_mid_setup(profile_id):
        app_state.stop_event.set()  # Stop arrives while /run is still setting up
        return real_destination(profile_id)

    monkeypatch.setattr(transcribe_handlers, "destination_output_file", stop_mid_setup)
    profile = ctapp.save_custom_profile("Race Profile", "role", "reference", "format")
    try:
        _post_no_redirect(host, port, jar, "/run", {
            "gemini_api_key": "fake-key", "profile_id": profile["id"],
            "profile_action": "use", "order": "oldest", "file_type": "jpeg",
        })
        assert not started.is_set()
        with app_state.lock:
            assert app_state.state["running"] is False
            assert app_state.state["summary"] == "Stopped before the run started."
    finally:
        app_state.stop_event.clear()
        with app_state.lock:
            app_state.state["running"] = False


def test_queue_edit_during_reservation_is_ignored(live_server, sandboxed_user_data):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    with app_state.test_lock:
        app_state.test_state["running"] = True
        app_state.test_state["queue"] = []
    try:
        _post_no_redirect(host, port, jar, "/test-mode/queue/add", {
            "model_a": "gemini-3.1-pro-preview", "model_b": "claude-opus-5-5", "batch_label": "late",
        })
        with app_state.test_lock:
            assert app_state.test_state["queue"] == []
    finally:
        with app_state.test_lock:
            app_state.test_state["running"] = False


def test_queue_edit_when_idle_still_works(live_server, sandboxed_user_data):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    try:
        _post_no_redirect(host, port, jar, "/test-mode/queue/add", {
            "model_a": "gemini-3.1-pro-preview", "model_b": "claude-opus-5-5", "batch_label": "ok",
        })
        with app_state.test_lock:
            assert [b["label"] for b in app_state.test_state["queue"]] == ["ok"]
    finally:
        with app_state.test_lock:
            app_state.test_state["queue"] = []
