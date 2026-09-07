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
import profiles_store


@pytest.fixture
def sandboxed_user_data(tmp_path, monkeypatch):
    """Redirects every path this app writes user data to into a pytest
    tmp_path, so tests can freely save/update/delete profiles and outputs
    without ever touching the real per-user data directory (~/Library/
    Application Support/Customizable Transcription/ on macOS, etc.) or this
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
    with its own copies of USER_OUTPUTS_DIR/APP_SETTINGS_FILE. See
    docs/DESIGN.md's "Codebase structure" section for both."""
    user_data_dir = tmp_path / "user-data"
    profiles_dir = user_data_dir / "profiles"
    outputs_dir = user_data_dir / "outputs"
    settings_file = user_data_dir / "app_settings.json"

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
