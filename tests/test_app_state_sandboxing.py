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
