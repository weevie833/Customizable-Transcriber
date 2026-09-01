"""Shared, in-memory run state and machine-local settings -- the pieces
app.py's Handler class and the page-render modules in pages/ both need,
split out specifically to avoid the app.py <-> pages circular import that
would otherwise result (pages/*.py needs to read `state`/`test_state` to
render the current run status; app.py needs to import the render functions
from pages/*.py; something has to sit below both). See CLAUDE.md's
app.py-modularization section.

Two kinds of thing live here, both "this running process's own transient or
machine-local state" rather than anything a user would think of as their
data (that's profiles_store.py's job):

- `state`/`test_state` and their locks/events: the live Transcribe/Test Mode
  run status, held only in memory -- lost on restart, by design (there is
  no persistence story for "a run was in progress").
- `USER_OUTPUTS_DIR`/`APP_SETTINGS_FILE` and the source-folder read/write
  functions: small bits of machine-local configuration (the remembered
  source folder) and the generated-output location, persisted to disk but
  not meant to sync between machines the way a profile is.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from customizable_transcription.core import DEFAULT_MODEL
from profiles_store import USER_DATA_DIR

# Generated DOCX/Markdown output lives outside PROJECT_DIR for the same
# reason USER_PROFILES_DIR does (see profiles_store.py's module docstring):
# this app's documented update path is "download a fresh copy, replace the
# old folder" (see README's Setup section), which would otherwise silently
# delete every transcription a user has ever run.
USER_OUTPUTS_DIR = USER_DATA_DIR / "outputs"
# Holds the last-used source folder. Also moved out of PROJECT_DIR for the
# same folder-replace-safety reason -- a full folder replace would otherwise
# reset it silently instead of just failing to find it.
APP_SETTINGS_FILE = USER_DATA_DIR / "app_settings.json"

state = {
    "running": False,
    "log": [],
    "output": "",
    "download": "",
    "summary": "",
    "model": DEFAULT_MODEL,
    "order": "oldest",
    "file_type": "jpeg",
    "profile_id": "",
    "new_profile_name": "",
    "role_context": "",
    "reference_context": "",
    "output_format": "",
}
lock = threading.Lock()
stop_event = threading.Event()
xls_preflight_lock = threading.Lock()
xls_preflight_cache: dict[str, dict[str, object]] = {}


def new_test_run_state() -> dict[str, str]:
    return {
        "batch_label": "",
        "label": "",
        "model": "",
        "output": "",
        "download": "",
        "markdown": "",
        "summary": "",
    }


test_state = {
    "running": False,
    "current_run_id": "",
    "log": [],
    "summary": "",
    "model_a": DEFAULT_MODEL,
    "model_b": DEFAULT_MODEL,
    "order": "oldest",
    "file_type": "jpeg",
    "profile_id": "",
    "queue": [],
    "runs": {},
}
test_lock = threading.Lock()
test_stop_event = threading.Event()


def add_log(message: str) -> None:
    with lock:
        state["log"].append(message)
        state["log"] = state["log"][-300:]


def add_test_log(message: str) -> None:
    with test_lock:
        test_state["log"].append(message)
        test_state["log"] = test_state["log"][-300:]


def load_source_folder() -> Path | None:
    """The active source folder, picked via the native folder dialog (or typed
    manually as a fallback) and persisted to APP_SETTINGS_FILE (gitignored —
    machine-specific). Returns None when nothing has been picked yet or the
    settings file is missing/corrupt — this app is shared across users on
    different machines, so there is deliberately no hardcoded personal-path
    default to fall back to. Callers must treat None as "no folder selected"
    and refuse to run rather than silently picking a path."""
    if APP_SETTINGS_FILE.exists():
        try:
            data = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
            raw = str(data.get("source_folder", "")).strip()
            if raw:
                return Path(raw)
        except (OSError, json.JSONDecodeError):
            pass
    return None


def save_source_folder(path: Path) -> None:
    data: dict[str, object] = {}
    if APP_SETTINGS_FILE.exists():
        try:
            data = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["source_folder"] = str(path)
    APP_SETTINGS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def clear_source_folder() -> None:
    """Used by Reset All on both pages — source folder is one shared,
    persisted setting, not per-page state, so clearing it resets it
    everywhere, matching "Reset All" rather than just this page's view."""
    if not APP_SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        APP_SETTINGS_FILE.unlink(missing_ok=True)
        return
    data.pop("source_folder", None)
    if data:
        APP_SETTINGS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        APP_SETTINGS_FILE.unlink(missing_ok=True)


def reset_ui_state() -> None:
    with lock:
        state["running"] = False
        state["log"] = []
        state["output"] = ""
        state["download"] = ""
        state["summary"] = ""
        state["model"] = DEFAULT_MODEL
        state["order"] = "oldest"
        state["file_type"] = "jpeg"
        state["profile_id"] = ""
        state["new_profile_name"] = ""
        state["role_context"] = ""
        state["reference_context"] = ""
        state["output_format"] = ""
    clear_source_folder()


def reset_test_ui_state() -> None:
    with test_lock:
        test_state["running"] = False
        test_state["current_run_id"] = ""
        test_state["log"] = []
        test_state["summary"] = ""
        test_state["model_a"] = DEFAULT_MODEL
        test_state["model_b"] = DEFAULT_MODEL
        test_state["order"] = "oldest"
        test_state["file_type"] = "jpeg"
        test_state["profile_id"] = ""
        test_state["queue"] = []
        test_state["runs"] = {}
    clear_source_folder()


def status_payload() -> dict[str, object]:
    with lock:
        return {
            "running": bool(state["running"]),
            "log": "\n".join(state["log"]),
            "output": str(state["output"]),
            "download": bool(state["download"]),
            "completed": bool(state["download"]) and not bool(state["running"]),
            "summary": str(state["summary"]),
        }


def test_status_payload() -> dict[str, object]:
    with test_lock:
        runs = {
            run_id: {
                "batch_label": run["batch_label"],
                "label": run["label"],
                "model": run["model"],
                "summary": run["summary"],
                "download": bool(run["download"]),
            }
            for run_id, run in test_state["runs"].items()
        }
        all_complete = bool(runs) and all(run["download"] for run in test_state["runs"].values())
        return {
            "running": bool(test_state["running"]),
            "current_run_id": str(test_state["current_run_id"]),
            "log": "\n".join(test_state["log"]),
            "summary": str(test_state["summary"]),
            "completed": all_complete and not bool(test_state["running"]),
            "runs": runs,
        }
