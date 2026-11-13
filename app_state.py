"""Shared, in-memory run state and machine-local settings -- the pieces
app.py's Handler class and the page-render modules in pages/ both need,
split out specifically to avoid the app.py <-> pages circular import that
would otherwise result (pages/*.py needs to read `state`/`test_state` to
render the current run status; app.py needs to import the render functions
from pages/*.py; something has to sit below both). See docs/DESIGN.md's
"Codebase structure" section.

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

from customizable_transcriber.core import DEFAULT_MODEL
from profiles_store import USER_DATA_DIR, atomic_write_text

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
# Non-secret metadata (provider, model, job id, submission time, status) for
# whatever Off-Peak batch job is currently in flight -- see reviews/CODEX_REVIEW.md
# finding H-1 / reviews/HUMAN_DECISIONS.md HD-1. batch_transcription.py writes this
# at each stage of a job's lifecycle and deletes it once the job is fully
# resolved, so a job that's still unconfirmed (or that the app never got to
# resolve at all, because it crashed or was closed) leaves a real, visible
# trace after a restart -- see surface_stale_off_peak_job() below -- instead
# of silently vanishing along with the in-memory `state` dict above. The API
# key is never written here, or anywhere else this app persists to disk.
OFF_PEAK_JOB_FILE = USER_DATA_DIR / "off_peak_job.json"

state = {
    "running": False,
    "log": [],
    "output": "",
    "download": "",
    # The report DOCX of the last "Translate completed transcript" run
    # (transcript_translation.py); its translated DOCX is "download" above.
    "report_download": "",
    "summary": "",
    "model": DEFAULT_MODEL,
    "order": "oldest",
    "file_type": "jpeg",
    # Transcribe page's Page zoom checkbox, remembered like order/file_type.
    "zoom_pages": False,
    "profile_id": "",
    "new_profile_name": "",
    "role_context": "",
    "reference_context": "",
    "output_format": "",
    # Off-Peak Mode (batch_transcription.py) -- unused by a real-time run,
    # which leaves all four at their defaults below. off_peak is the one
    # other code reads to decide "is the currently-running job a batch job",
    # e.g. stop_job()'s cancellation branch and the Progress Console's
    # "Off-peak progress:" label swap. batch_job_id is this run's own
    # provider-issued job id/name (opaque string, provider-specific format)
    # -- never a filename or anything else user-controlled, see
    # batch_transcription.py's own module docstring on why. batch_counts
    # mirrors whichever of the two providers' aggregate-progress shapes is
    # in play (Gemini: successful/failed/incomplete; Anthropic:
    # succeeded/errored/processing/canceled/expired), plus "total" -- the
    # Progress Console renders whatever keys are present rather than
    # assuming one fixed shape.
    "off_peak": False,
    "batch_provider": "",
    "batch_job_id": "",
    "batch_counts": {},
}
lock = threading.Lock()
stop_event = threading.Event()
xls_preflight_lock = threading.Lock()
xls_preflight_cache: dict[str, dict[str, object]] = {}
# Guards against two concurrent AI-backed XLS Conversion requests (Parse,
# Preflight, Detect Languages) running at once -- see reviews/CODEX_REVIEW.md
# finding M-2 / reviews/HUMAN_DECISIONS.md. Unlike lock/test_lock above, this isn't
# reserving a *background job*: each of these three endpoints blocks its
# own request thread for the AI call(s) it makes, with no persistent
# "running" state to poll, so the guard is just "reject a second request
# while one is still in flight" rather than a full run/reset/status
# lifecycle. Deliberately one shared lock across all three endpoints, not
# one each -- a user has no real reason to run two of them at once, and a
# single lock is the simplest way to bound concurrent AI-provider cost/load
# from this page without a larger job-queue rework (left as a documented,
# deferred decision -- see reviews/HUMAN_DECISIONS.md's M-2 entry).
xls_ai_lock = threading.Lock()


def new_test_run_state() -> dict[str, str | bool]:
    return {
        "batch_label": "",
        "label": "",
        "model": "",
        "output": "",
        "download": "",
        "markdown": "",
        "summary": "",
        # Page zoom for this run (page_zoom.py); read by run_test_job().
        "zoom_pages": False,
    }


test_state = {
    "running": False,
    "current_run_id": "",
    "log": [],
    "summary": "",
    "model_a": DEFAULT_MODEL,
    "model_b": DEFAULT_MODEL,
    "zoom_a": False,
    "zoom_b": False,
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
    atomic_write_text(APP_SETTINGS_FILE, json.dumps(data, indent=2) + "\n")


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
        atomic_write_text(APP_SETTINGS_FILE, json.dumps(data, indent=2) + "\n")
    else:
        APP_SETTINGS_FILE.unlink(missing_ok=True)


def write_off_peak_job_state(**fields: object) -> bool:
    """Best-effort persistence of non-secret off-peak batch job metadata --
    see OFF_PEAK_JOB_FILE's own comment above. Never fatal to the run itself
    if the write fails (a full disk, a permissions problem): losing this
    file only means a crash won't be recoverable, not that the in-flight
    job breaks, matching delete_gemini_prompt_cache()'s own best-effort
    philosophy (core.py). Returns whether the write succeeded, so a caller
    never tells the user a job id "is saved" when it isn't (reviews/CODEX_REVIEW.md
    L-1); a failure is also written to the run log."""
    try:
        atomic_write_text(OFF_PEAK_JOB_FILE, json.dumps(fields, indent=2) + "\n")
    except OSError as exc:
        add_log(
            f"Warning: could not save the off-peak job record to disk ({exc}). "
            "If this app closes, the job id will not be shown again -- copy it from this log now."
        )
        return False
    return True


def clear_off_peak_job_state() -> None:
    try:
        OFF_PEAK_JOB_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def read_off_peak_job_state() -> dict[str, object] | None:
    if not OFF_PEAK_JOB_FILE.exists():
        return None
    try:
        data = json.loads(OFF_PEAK_JOB_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def surface_stale_off_peak_job() -> None:
    """Called once at app startup (main(), before serving any request). If
    an off-peak job's persisted state file survived a restart -- Stop was
    requested but never confirmed, or the app was closed/crashed mid-batch
    -- this app has no way to resume watching it automatically (see
    reviews/CODEX_REVIEW.md finding H-1 / reviews/HUMAN_DECISIONS.md HD-1: automatic
    reconnect-and-resume was explicitly scoped out in favor of this, a real
    but manual recovery path -- the job still needs a live API key to poll,
    which this app never persists). Surfacing it into the ordinary log/
    summary is enough to make sure it's never silently forgotten. Dismissed
    the same way any other leftover run state is, via Reset All -- see
    reset_ui_state()'s own call to clear_off_peak_job_state() below."""
    job = read_off_peak_job_state()
    if not job:
        if OFF_PEAK_JOB_FILE.exists():
            # A record is on disk but unreadable (corrupt/permissions) -- say so
            # rather than silently forgetting a possibly-still-billing job.
            with lock:
                state["log"].append(
                    f"An off-peak job record exists at {OFF_PEAK_JOB_FILE} but could not be read. "
                    "It may describe a batch still running on the provider's servers -- open the file "
                    "or check the provider's own console/dashboard."
                )
                state["log"] = state["log"][-300:]
        return
    message = (
        "An off-peak batch job from a previous session may still be unresolved: "
        f"provider {job.get('provider', 'unknown')}, model {job.get('model', 'unknown')}, "
        f"job id {job.get('job_id', 'unknown')}, submitted {job.get('submitted_at', 'an unknown time')}, "
        f"last known status \"{job.get('status', 'unknown')}\". This app cannot resume watching it "
        "automatically after a restart -- check the provider's own console/dashboard for its actual "
        "status. Once resolved there, click Reset All to dismiss this notice."
    )
    with lock:
        state["log"].append(message)
        state["log"] = state["log"][-300:]
        if not state["summary"]:
            state["summary"] = message


def reset_ui_state() -> None:
    with lock:
        state["running"] = False
        state["log"] = []
        state["output"] = ""
        state["download"] = ""
        state["report_download"] = ""
        state["summary"] = ""
        state["model"] = DEFAULT_MODEL
        state["order"] = "oldest"
        state["file_type"] = "jpeg"
        state["zoom_pages"] = False
        state["profile_id"] = ""
        state["new_profile_name"] = ""
        state["role_context"] = ""
        state["reference_context"] = ""
        state["output_format"] = ""
        state["off_peak"] = False
        state["batch_provider"] = ""
        state["batch_job_id"] = ""
        state["batch_counts"] = {}
    clear_source_folder()
    clear_off_peak_job_state()


def reset_test_ui_state() -> None:
    with test_lock:
        test_state["running"] = False
        test_state["current_run_id"] = ""
        test_state["log"] = []
        test_state["summary"] = ""
        test_state["model_a"] = DEFAULT_MODEL
        test_state["model_b"] = DEFAULT_MODEL
        test_state["zoom_a"] = False
        test_state["zoom_b"] = False
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
            "report": bool(state["report_download"]),
            "completed": bool(state["download"]) and not bool(state["running"]),
            "summary": str(state["summary"]),
            "off_peak": bool(state["off_peak"]),
            "batch_counts": dict(state["batch_counts"]),
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
