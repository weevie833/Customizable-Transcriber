"""Regression test for the sandboxed_user_data fixture's own correctness,
for the specific new footgun the Handler-method modularization pass
introduced -- see docs/DESIGN.md's "Codebase structure" section and
tests/conftest.py's own docstring.

run_support.py, handlers/test_mode_run.py, and handlers/settings.py each
import PROFILES_DIR/USER_OUTPUTS_DIR *by value* from
profiles_store.py/app_state.py, creating independent module-level bindings
a future refactor could silently leave unpatched -- unlike a function
reference (save_source_folder(), load_profile(), etc.), which always reads
its own *defining* module's globals no matter which module's copy of the
name called it, and so is never at risk this way. Mirrors
test_app_state_sandboxing.py's own pattern (same fixture-correctness
concern, one refactor pass earlier), using the exact functions/attributes
most likely to regress silently if a future refactor moves any of this
again without updating the fixture to match."""

from __future__ import annotations

import app_state
import handlers.settings
import handlers.test_mode_run
import profiles_store
import run_support


def test_run_support_directory_constants_match_the_sandbox(sandboxed_user_data):
    # Equality against profiles_store's/app_state's own copies -- not just
    # "some directory under sandboxed_user_data" -- is the real contract:
    # every module's copy of these names must point at the exact same
    # sandboxed directory the fixture set up, the same way they'd all point
    # at the exact same real directory in production.
    assert run_support.PROFILES_DIR == profiles_store.PROFILES_DIR
    assert run_support.USER_OUTPUTS_DIR == app_state.USER_OUTPUTS_DIR


def test_run_support_output_path_helpers_stay_in_sandbox(sandboxed_user_data):
    # Functional check, not just an attribute comparison: these are the
    # actual functions run_job()/run_test_job() call to decide where a real
    # transcription DOCX gets written -- proving they land inside the
    # sandbox is what actually rules out silently writing into the real
    # per-user outputs directory during a test run.
    output_file = run_support.destination_output_file("some-profile")
    assert output_file.is_relative_to(sandboxed_user_data)

    test_output_file = run_support.test_destination_output_file(
        "some-profile", "run-1", "gemini-3.1-pro-preview", "some-stem"
    )
    assert test_output_file.is_relative_to(sandboxed_user_data)


def test_handler_mixin_output_dirs_match_the_sandbox(sandboxed_user_data):
    # handlers/test_mode_run.py's run_test() builds its own markdown_file
    # path directly from this name, and handlers/settings.py's
    # open_outputs_folder() passes it straight to
    # open_folder_in_file_manager() -- both read their own imported copy,
    # not app_state's.
    assert handlers.test_mode_run.USER_OUTPUTS_DIR == app_state.USER_OUTPUTS_DIR
    assert handlers.settings.USER_OUTPUTS_DIR == app_state.USER_OUTPUTS_DIR
