"""CODEX_REVIEW_2.md N-3: a confirmed run uses the profile the handler
approved. Editing the saved profile after Run is accepted (before the worker
starts) must not change the prompt the worker sends."""

from __future__ import annotations

import types

import app as ctapp
import profiles_store
import handlers.test_mode_run as test_mode_handlers
import handlers.transcribe_run as transcribe_handlers
import run_support
from tests.test_post_redirect_get import _get_csrf_cookie, _post_no_redirect


def _thread_that_edits_first(profile_id: str):
    """Stands in for threading.Thread: when the handler starts the worker,
    the saved profile is edited first, then the worker runs inline."""

    class EditingThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            profiles_store.update_profile(profile_id, "EDITED ROLE", "EDITED REFERENCE", "EDITED FORMAT")
            self.target(*self.args, **self.kwargs)

    return types.SimpleNamespace(Thread=EditingThread)


def _source(tmp_path, monkeypatch):
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: folder)
    monkeypatch.setattr(run_support, "validate_api_key_with_retry", lambda *a, **k: None)
    return folder


def _capture_prompts(monkeypatch):
    prompts: list[str] = []

    def fake_run_batch(config, project_dir, progress=None, cancel_requested=None):
        prompts.append(config.system_prompt or "")
        return []

    monkeypatch.setattr(run_support, "run_batch", fake_run_batch)
    return prompts


def test_transcribe_run_uses_the_approved_profile(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    folder = _source(tmp_path, monkeypatch)
    prompts = _capture_prompts(monkeypatch)
    profile = ctapp.save_custom_profile("Snapshot Profile", "APPROVED ROLE", "APPROVED REFERENCE", "APPROVED FORMAT")
    monkeypatch.setattr(transcribe_handlers, "threading", _thread_that_edits_first(profile["id"]))
    try:
        _post_no_redirect(host, port, jar, "/run", {
            "source_folder": str(folder), "gemini_api_key": "fake-key", "profile_id": profile["id"],
            "profile_action": "use", "order": "oldest", "file_type": "jpeg",
        })
    finally:
        with ctapp.lock:
            ctapp.state["running"] = False
            summary = ctapp.state["summary"]
    assert profiles_store.load_profile_exact(profile["id"])["role_context"] == "EDITED ROLE", summary
    assert len(prompts) == 1, prompts
    assert "APPROVED ROLE" in prompts[0] and "APPROVED FORMAT" in prompts[0]
    assert "EDITED" not in prompts[0]


def test_test_mode_run_uses_the_approved_profile(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    folder = _source(tmp_path, monkeypatch)
    prompts = _capture_prompts(monkeypatch)
    profile = ctapp.save_custom_profile("Snapshot Test Profile", "APPROVED ROLE", "APPROVED REFERENCE", "APPROVED FORMAT")
    monkeypatch.setattr(test_mode_handlers, "threading", _thread_that_edits_first(profile["id"]))
    with ctapp.test_lock:
        ctapp.test_state["running"] = False
        ctapp.test_state["queue"] = []
    try:
        _post_no_redirect(host, port, jar, "/test-mode/run", {
            "source_folder": str(folder), "api_key_gemini": "fake-key", "profile_id": profile["id"],
            "profile_action": "use", "order": "oldest", "file_type": "jpeg",
            "model_a": "gemini-3.1-pro-preview", "model_b": "gemini-3.1-pro-preview", "zoom_b": "on",
        })
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
            ctapp.test_state["runs"] = {}
    assert profiles_store.load_profile_exact(profile["id"])["role_context"] == "EDITED ROLE"
    assert len(prompts) == 2, (prompts, ctapp.test_state["summary"])
    assert all("APPROVED ROLE" in p and "EDITED" not in p for p in prompts)


def test_new_profile_from_test_mode_is_saved_once(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    """The worker used to resolve the form again, so "create" saved the new
    profile a second time (as -2)."""
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    folder = _source(tmp_path, monkeypatch)
    _capture_prompts(monkeypatch)
    existing = ctapp.save_custom_profile("Selected Profile", "role", "reference", "format")

    class InlineThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            self.target(*self.args, **self.kwargs)

    monkeypatch.setattr(test_mode_handlers, "threading", types.SimpleNamespace(Thread=InlineThread))
    with ctapp.test_lock:
        ctapp.test_state["running"] = False
        ctapp.test_state["queue"] = []
    try:
        _post_no_redirect(host, port, jar, "/test-mode/run", {
            "source_folder": str(folder), "api_key_gemini": "fake-key", "profile_id": existing["id"], "profile_action": "create",
            "new_profile_name": "Created Once", "role_context": "role", "reference_context": "ref",
            "output_format": "fmt", "order": "oldest", "file_type": "jpeg",
            "model_a": "gemini-3.1-pro-preview", "model_b": "gemini-3.1-pro-preview", "zoom_b": "on",
        })
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
            ctapp.test_state["runs"] = {}
    labels = [p["label"] for p in profiles_store.load_custom_profiles() if p["label"].startswith("Created Once")]
    assert labels == ["Created Once"], (labels, ctapp.test_state["summary"])
