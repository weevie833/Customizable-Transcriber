"""Shared pytest fixtures for the regression tests added alongside a
security/reliability review (see docs/DESIGN.md's "Security hardening
history" section). Scope note: this suite
targets the specific defects that review found and fixed -- it is not full
coverage of the app (ai_parser.py's semantic AI extraction in particular
can't be exercised offline; see xls_conversion/tests/run_parser_test.py for
the existing offline regression suite, which covers different ground: the
orphaned baptism-parser.js path)."""

from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

import app as ctapp
import app_state
import handlers.settings
import handlers.test_mode_run
import profiles_store
import run_support
import transcript_translation


@pytest.fixture
def sandboxed_user_data(tmp_path, monkeypatch):
    """Redirects every path this app writes user data to into a pytest
    tmp_path, so tests can freely save/update/delete profiles and outputs
    without ever touching the real per-user data directory (~/Library/
    Application Support/Customizable Transcriber/ on macOS, etc.) or this
    repo's own files.

    Patches every module that actually OWNS one of these names, not just
    app.py's re-exported copy of it -- app.py does `from profiles_store
    import USER_DATA_DIR` / `from app_state import APP_SETTINGS_FILE` etc.,
    each of which binds a second, independent name in app's own module
    namespace pointing at the same object at import time. A function reads
    a bare global name from the globals of the module where *that function
    was defined*, not wherever it's called from -- so save_custom_profile()
    (defined in profiles_store.py) always reads profiles_store's own
    USER_PROFILES_DIR, and load_source_folder() (defined in app_state.py)
    always reads app_state's own APP_SETTINGS_FILE, regardless of what
    app.ctapp's copy of that name has been patched to. Patching only one
    side silently writes test data into the real directory while tests
    still appear to pass -- caught once already by inspection (profiles_store),
    and fixed proactively here a second time when app_state.py was split out
    with its own copies of USER_OUTPUTS_DIR/APP_SETTINGS_FILE, and a third
    time when the Handler-method modularization pass (see docs/DESIGN.md's
    "Codebase structure" section) gave run_support.py its own copies of
    PROFILES_DIR/USER_OUTPUTS_DIR (run_job()/run_test_job()/
    destination_output_file() all read these as plain module-level values,
    not through a function call that would re-read app_state's/
    profiles_store's own patched copy at call time) and gave
    handlers/test_mode_run.py and handlers/settings.py their own copies of
    USER_OUTPUTS_DIR for the same reason. Functions imported by reference
    (load_source_folder(), save_custom_profile(), etc.) are NOT at risk here
    even when several modules each hold their own binding of the *function*
    -- calling any of those bindings still runs the original function's own
    code body, which reads its *own* defining module's globals internally.
    Only a raw value (a Path constant) captured into a second module's
    namespace via `from x import SOME_PATH` needs a matching patch in every
    module that imported it that way; see docs/DESIGN.md's "Codebase
    structure" section for this exact failure mode."""
    user_data_dir = tmp_path / "user-data"
    profiles_dir = user_data_dir / "profiles"
    outputs_dir = user_data_dir / "outputs"
    settings_file = user_data_dir / "app_settings.json"
    off_peak_job_file = user_data_dir / "off_peak_job.json"

    # PROFILES_DIR (the read-only shipped-examples directory) is also
    # sandboxed, even though nothing ever writes to it, so tests don't
    # depend on whatever this repo's own profiles/ folder happens to
    # contain -- that's this repo's own state (currently one shipped
    # example profile, see docs/DESIGN.md's "Profile storage" section),
    # not a contract these tests should rely on.
    shipped_dir = tmp_path / "shipped-profiles"
    shipped_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(profiles_store, "PROFILES_DIR", shipped_dir)
    monkeypatch.setattr(ctapp, "PROFILES_DIR", shipped_dir)
    monkeypatch.setattr(run_support, "PROFILES_DIR", shipped_dir)

    monkeypatch.setattr(profiles_store, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(profiles_store, "USER_PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(ctapp, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(ctapp, "USER_PROFILES_DIR", profiles_dir)

    # USER_OUTPUTS_DIR/APP_SETTINGS_FILE are defined in app_state.py (see its
    # module docstring); app.py only re-exports them. load_source_folder()/
    # save_source_folder()/clear_source_folder() -- called both directly by
    # app.py's Handler and indirectly via reset_ui_state()/
    # reset_test_ui_state() -- all read APP_SETTINGS_FILE from app_state's
    # own globals, so that copy must be patched too.
    monkeypatch.setattr(app_state, "USER_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(app_state, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(ctapp, "USER_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(ctapp, "APP_SETTINGS_FILE", settings_file)
    # OFF_PEAK_JOB_FILE (see reviews/CODEX_REVIEW.md finding H-1) is also defined in
    # app_state.py, and read_off_peak_job_state()/write_off_peak_job_state()/
    # clear_off_peak_job_state()/surface_stale_off_peak_job() are all
    # DEFINED there too -- unlike USER_OUTPUTS_DIR above, no other module
    # captures this Path as a raw value (batch_transcription.py and app.py
    # only import the *functions*, which always read their own defining
    # module's globals -- see this fixture's own docstring on why that's
    # safe), so patching app_state's copy alone is enough.
    monkeypatch.setattr(app_state, "OFF_PEAK_JOB_FILE", off_peak_job_file)
    # USER_OUTPUTS_DIR specifically is also captured by value (not read via a
    # function call back into app_state) in run_support.py -- run_job()/
    # run_test_job()/destination_output_file()/test_destination_output_file()
    # all build paths from their own imported copy of this name -- and in
    # handlers/test_mode_run.py's run_test() (its own markdown_file path) and
    # handlers/settings.py's open_outputs_folder(). Each needs its own patch.
    monkeypatch.setattr(run_support, "USER_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(handlers.test_mode_run, "USER_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(handlers.settings, "USER_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(transcript_translation, "USER_OUTPUTS_DIR", outputs_dir)

    profiles_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return user_data_dir


@pytest.fixture
def live_server(monkeypatch):
    """Runs the real app.py Handler on an ephemeral local port, with
    ALLOWED_HOSTS/ALLOWED_ORIGINS patched to match it -- those are normally
    fixed to the app's real HOST/PORT (127.0.0.1:8765) at import time, which
    a test must not bind to (that's the user's own real, possibly-running
    instance). Yields (host, port)."""
    host = "127.0.0.1"
    server = ThreadingHTTPServer((host, 0), ctapp.Handler)
    port = server.server_address[1]
    monkeypatch.setattr(ctapp, "ALLOWED_HOSTS", {f"{host}:{port}"})
    monkeypatch.setattr(ctapp, "ALLOWED_ORIGINS", {f"http://{host}:{port}"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
