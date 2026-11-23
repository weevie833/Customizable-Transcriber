"""reviews/CODEX_REVIEW_8.md H-2: a run uses the folder the submitting page
showed, and is refused if the shared setting changed since (another tab)."""

from __future__ import annotations

import threading

import pytest

import app as ctapp
import handlers.transcribe_run as transcribe_handlers
import run_support
from http_utils import FormData
from tests.test_post_redirect_get import _get_csrf_cookie, _post_no_redirect


def _form(**fields):
    return FormData({k: [v] for k, v in fields.items()})


def test_bind_accepts_matching_folder_and_pins_it(tmp_path, monkeypatch):
    monkeypatch.setattr(run_support, "load_source_folder", lambda: tmp_path)
    form = _form(source_folder=str(tmp_path))
    assert run_support.bind_source_folder(form) == tmp_path
    # A later settings change can't move the worker to another folder.
    other = tmp_path / "other"
    monkeypatch.setattr(run_support, "load_source_folder", lambda: other)
    assert run_support.resolved_source_folder(form) == tmp_path


@pytest.mark.parametrize("submitted", ["", "/somewhere/else"])
def test_bind_rejects_missing_or_stale_folder(tmp_path, monkeypatch, submitted):
    monkeypatch.setattr(run_support, "load_source_folder", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="changed after this page was loaded"):
        run_support.bind_source_folder(_form(source_folder=submitted))


def test_bind_rejects_forged_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(run_support, "load_source_folder", lambda: tmp_path)
    form = _form(source_folder=str(tmp_path), _resolved_source_folder="/etc")
    run_support.bind_source_folder(form)
    assert run_support.resolved_source_folder(form) == tmp_path


def test_run_with_other_tabs_folder_is_refused(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    folder_a, folder_b = tmp_path / "a", tmp_path / "b"
    for folder in (folder_a, folder_b):
        folder.mkdir()
        (folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: folder_b)  # changed in another tab
    started = threading.Event()
    monkeypatch.setattr(transcribe_handlers, "run_job", lambda form, output_file, *_: started.set())
    profile = ctapp.save_custom_profile("Binding Profile", "role", "reference", "format")
    try:
        _post_no_redirect(host, port, jar, "/run", {
            "source_folder": str(folder_a),  # what this tab showed
            "gemini_api_key": "fake-key", "profile_id": profile["id"],
            "profile_action": "use", "order": "oldest", "file_type": "jpeg",
        })
        assert not started.is_set()
        with ctapp.lock:
            assert ctapp.state["running"] is False
            assert "changed after this page was loaded" in ctapp.state["summary"]
    finally:
        with ctapp.lock:
            ctapp.state["running"] = False
