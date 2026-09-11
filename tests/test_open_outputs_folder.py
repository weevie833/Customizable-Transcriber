"""Tests for the "Open Outputs Folder" feature added after the 2026-09
security/reliability review: outputs moved out of the app folder into
USER_OUTPUTS_DIR (a per-user data directory, hidden under ~/Library on
macOS), which made them harder for a non-technical user to find directly in
Finder/Explorer than printing the raw path on the page. open_folder_in_file_manager()
mirrors pick_source_folder_dialog()'s existing per-OS subprocess dispatch
pattern; /api/open-outputs-folder is the HTTP endpoint the "Open Outputs
Folder" button on both the Transcribe and Test Mode pages calls."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import pytest

import handlers.settings as settings_handlers


def _fake_result(returncode=0, stderr=""):
    result = mock.Mock()
    result.returncode = returncode
    result.stderr = stderr
    return result


def test_macos_dispatch_uses_open(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_result()

    monkeypatch.setattr(settings_handlers.subprocess, "run", fake_run)
    settings_handlers.open_folder_in_file_manager(tmp_path / "outputs")
    assert calls[0][0] == "open"


def test_windows_dispatch_ignores_nonzero_exit(tmp_path, monkeypatch):
    """explorer.exe routinely exits 1 even on success -- must not be treated
    as a failure the way the macOS/Linux branches treat it."""
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Windows")
    monkeypatch.setattr(settings_handlers.subprocess, "run", lambda args, **kwargs: _fake_result(returncode=1))
    settings_handlers.open_folder_in_file_manager(tmp_path / "outputs")  # must not raise


def test_linux_dispatch_uses_xdg_open(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Linux")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_result()

    monkeypatch.setattr(settings_handlers.subprocess, "run", fake_run)
    settings_handlers.open_folder_in_file_manager(tmp_path / "outputs")
    assert calls[0][0] == "xdg-open"


def test_linux_missing_xdg_open_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Linux")

    def fake_run(args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(settings_handlers.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        settings_handlers.open_folder_in_file_manager(tmp_path / "outputs")


def test_macos_nonzero_exit_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        settings_handlers.subprocess, "run", lambda args, **kwargs: _fake_result(returncode=1, stderr="denied")
    )
    with pytest.raises(RuntimeError):
        settings_handlers.open_folder_in_file_manager(tmp_path / "outputs")


def test_folder_is_created_if_missing(tmp_path, monkeypatch):
    """A brand-new install (or one where no transcription has run yet) has
    no outputs directory at all -- opening it should create an empty one
    rather than erroring, matching ensure_profiles_dir()'s own
    mkdir(exist_ok=True) pattern for the analogous profiles directory."""
    target = tmp_path / "not-yet-created" / "outputs"
    monkeypatch.setattr(settings_handlers.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(settings_handlers.subprocess, "run", lambda args, **kwargs: _fake_result())
    settings_handlers.open_folder_in_file_manager(target)
    assert target.is_dir()


def test_open_outputs_folder_endpoint_success(live_server, sandboxed_user_data, monkeypatch):
    host, port = live_server
    monkeypatch.setattr(settings_handlers, "open_folder_in_file_manager", lambda path: None)

    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(
        urllib.request.Request(f"http://{host}:{port}/", headers={"Host": f"{host}:{port}"}), timeout=5
    )
    response = opener.open(
        urllib.request.Request(
            f"http://{host}:{port}/api/open-outputs-folder",
            data=b"",
            method="POST",
            headers={"Host": f"{host}:{port}"},
        ),
        timeout=5,
    )
    assert response.status == 200
    assert json.loads(response.read())["ok"] is True


def test_open_outputs_folder_endpoint_requires_csrf_token(live_server, sandboxed_user_data):
    """Same protection as every other state-changing endpoint -- this one
    triggers a real local side effect (a Finder/Explorer window), so it must
    not be reachable by a cross-site request either."""
    host, port = live_server
    opener = urllib.request.build_opener()
    req = urllib.request.Request(
        f"http://{host}:{port}/api/open-outputs-folder",
        data=b"",
        method="POST",
        headers={"Host": f"{host}:{port}"},
    )
    try:
        opener.open(req, timeout=5)
        assert False, "expected an HTTPError"
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
