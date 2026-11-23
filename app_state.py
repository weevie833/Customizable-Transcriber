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
from datetime import datetime
import threading
import uuid
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
# Test Mode's equivalent: one record per off-peak run, keyed by run id, since
# a Test Mode off-peak run submits several provider batches at once (see
# batch_transcription.run_test_off_peak_job()). Same non-secret fields.
TEST_OFF_PEAK_JOBS_FILE = USER_DATA_DIR / "test_off_peak_jobs.json"
_test_off_peak_jobs_file_lock = threading.Lock()

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
    # True while the current run is an Off-Peak run (provider batch jobs);
    # Stop's wording and the Progress label read it.
    "off_peak": False,
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


def _read_settings() -> dict[str, object] | None:
    """The settings file as a dict; {} when it is missing; None when it exists
    but is unreadable, not valid UTF-8/JSON, or valid JSON of the wrong shape
    (an array, null, ...). One reader for load/save/clear, so a wrong-shaped
    file can't break the pages or their recovery actions
    (reviews/CODEX_REVIEW_8.md L-2)."""
    if not APP_SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_source_folder() -> Path | None:
    """The active source folder, picked via the native folder dialog (or typed
    manually as a fallback) and persisted to APP_SETTINGS_FILE (gitignored —
    machine-specific). Returns None when nothing has been picked yet or the
    settings file is missing/corrupt — this app is shared across users on
    different machines, so there is deliberately no hardcoded personal-path
    default to fall back to. Callers must treat None as "no folder selected"
    and refuse to run rather than silently picking a path."""
    data = _read_settings() or {}
    raw = data.get("source_folder")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip())
    return None


def save_source_folder(path: Path) -> None:
    # A corrupt or wrong-shaped file is replaced rather than blocking a save.
    data = _read_settings() or {}
    data["source_folder"] = str(path)
    atomic_write_text(APP_SETTINGS_FILE, json.dumps(data, indent=2) + "\n")


def clear_source_folder() -> None:
    """Used by Reset All on both pages — source folder is one shared,
    persisted setting, not per-page state, so clearing it resets it
    everywhere, matching "Reset All" rather than just this page's view."""
    if not APP_SETTINGS_FILE.exists():
        return
    data = _read_settings()
    if data is None:
        APP_SETTINGS_FILE.unlink(missing_ok=True)
        return
    data.pop("source_folder", None)
    if data:
        atomic_write_text(APP_SETTINGS_FILE, json.dumps(data, indent=2) + "\n")
    else:
        APP_SETTINGS_FILE.unlink(missing_ok=True)


_off_peak_job_file_lock = threading.Lock()
OFF_PEAK_JOBS_FORMAT = "off-peak-jobs-v2"
DEFAULT_OFF_PEAK_RECORD_KEY = "default"


def _read_off_peak_raw() -> dict[str, object] | None:
    """Every Transcribe off-peak entry exactly as stored, malformed ones
    included, keyed by the job's own record key (reviews/CODEX_REVIEW_8.md
    M-3: one key per job, so a second job never erases an unresolved first
    one). {} when there is no file, None when the file itself can't be read.
    Writers work on this raw map, so an entry this version can't interpret is
    carried over unchanged rather than dropped (CODEX_REVIEW_2.md M-3). A
    file in the old single-record format (one flat dict) reads as one entry;
    the next write converts it."""
    if not OFF_PEAK_JOB_FILE.exists():
        return {}
    try:
        data = json.loads(OFF_PEAK_JOB_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("format") == OFF_PEAK_JOBS_FORMAT:
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            return None
        return {str(k): v for k, v in jobs.items()}
    return {"legacy": data} if data else {}


def _read_off_peak_records() -> dict[str, dict[str, object]] | None:
    """The readable entries only (for display and lookup)."""
    raw = _read_off_peak_raw()
    if raw is None:
        return None
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def _set_aside_unreadable_file(path, log) -> None:
    """Keep an unreadable record file for manual recovery instead of
    overwriting it (M-3), under a name that can't collide with an earlier
    one, and say where it went."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.unreadable-{stamp}-{uuid.uuid4().hex[:8]}{path.suffix}")
    path.replace(target)
    log(
        f"An unreadable off-peak job record was kept at {target}. It may describe a batch still "
        "running on the provider's servers -- open the file or check the provider's console."
    )


def _write_off_peak_records(jobs: dict[str, object]) -> None:
    if jobs:
        atomic_write_text(
            OFF_PEAK_JOB_FILE,
            json.dumps({"format": OFF_PEAK_JOBS_FORMAT, "jobs": jobs}, indent=2) + "\n",
        )
    else:
        OFF_PEAK_JOB_FILE.unlink(missing_ok=True)


def write_off_peak_job_state(*, record_key: str = DEFAULT_OFF_PEAK_RECORD_KEY, **fields: object) -> bool:
    """Best-effort persistence of non-secret off-peak batch job metadata --
    see OFF_PEAK_JOB_FILE's own comment above. Adds or replaces only this
    job's entry (record_key); other jobs' entries are kept. Never fatal to
    the run itself if the write fails (a full disk, a permissions problem):
    losing this file only means a crash won't be recoverable, not that the
    in-flight job breaks. Returns whether the write succeeded, so a caller
    never tells the user a job id "is saved" when it isn't (reviews/CODEX_REVIEW.md
    L-1); a failure is also written to the run log."""
    try:
        with _off_peak_job_file_lock:
            jobs = _read_off_peak_raw()
            if jobs is None:
                _set_aside_unreadable_file(OFF_PEAK_JOB_FILE, add_log)
                jobs = {}
            jobs.pop(record_key, None)
            jobs[record_key] = dict(fields)  # most recent last
            _write_off_peak_records(jobs)
    except OSError as exc:
        add_log(
            f"Warning: could not save the off-peak job record to disk ({exc}). "
            "If this app closes, the job id will not be shown again -- copy it from this log now."
        )
        return False
    return True


def clear_off_peak_job_state(record_key: str | None = None) -> None:
    """Remove one job's entry once it is resolved, or every entry when
    record_key is None (Reset All, the explicit dismissal). An unreadable
    file is left in place for a single-job clear."""
    try:
        with _off_peak_job_file_lock:
            if record_key is None:
                OFF_PEAK_JOB_FILE.unlink(missing_ok=True)
                return
            jobs = _read_off_peak_raw()
            if jobs is None or record_key not in jobs:
                return
            jobs.pop(record_key)
            _write_off_peak_records(jobs)
    except OSError:
        pass


def read_off_peak_job_records() -> dict[str, dict[str, object]]:
    """Every readable Transcribe off-peak record (oldest first)."""
    return _read_off_peak_records() or {}


def read_off_peak_job_state() -> dict[str, object] | None:
    """The most recently written record, or None."""
    jobs = read_off_peak_job_records()
    return list(jobs.values())[-1] if jobs else None


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
    raw = _read_off_peak_raw()
    jobs = None if raw is None else {key: value for key, value in raw.items() if isinstance(value, dict)}
    unreadable = 0 if raw is None else len(raw) - len(jobs)
    if unreadable:
        with lock:
            state["log"].append(
                f"{unreadable} off-peak job record(s) in {OFF_PEAK_JOB_FILE} could not be read and were "
                "kept as they are. They may describe batches still running on the provider's servers -- "
                "open the file or check the provider's own console/dashboard."
            )
            state["log"] = state["log"][-300:]
    if not jobs:
        if jobs is None:
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
    messages = [
        "An off-peak batch job from a previous session may still be unresolved: "
        f"provider {job.get('provider', 'unknown')}, model {job.get('model', 'unknown')}, "
        f"job id {job.get('job_id', 'unknown')}, submitted {job.get('submitted_at', 'an unknown time')}, "
        f"last known status \"{job.get('status', 'unknown')}\". This app cannot resume watching it "
        "automatically after a restart -- check the provider's own console/dashboard for its actual "
        "status. Once resolved there, click Reset All to dismiss this notice."
        for job in jobs.values()
    ]
    with lock:
        state["log"].extend(messages)
        state["log"] = state["log"][-300:]
        if not state["summary"]:
            state["summary"] = messages[0] if len(messages) == 1 else (
                f"{len(messages)} off-peak batch jobs from a previous session may still be "
                "unresolved -- see the Progress Console."
            )


def _read_test_off_peak_raw() -> dict[str, object] | None:
    """Test Mode's entries exactly as stored ({} with no file, None when the
    file can't be read). Writers keep entries they can't interpret
    (CODEX_REVIEW_2.md M-3)."""
    if not TEST_OFF_PEAK_JOBS_FILE.exists():
        return {}
    try:
        data = json.loads(TEST_OFF_PEAK_JOBS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else None


def read_test_off_peak_jobs() -> dict[str, dict[str, object]]:
    raw = _read_test_off_peak_raw() or {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def write_test_off_peak_job_state(run_id: str, **fields: object) -> bool:
    """write_off_peak_job_state()'s Test Mode counterpart: updates this run's
    own entry in TEST_OFF_PEAK_JOBS_FILE. Best-effort; a failure is logged to
    the Test Mode log and reported by the return value."""
    try:
        with _test_off_peak_jobs_file_lock:
            jobs = _read_test_off_peak_raw()
            if jobs is None:
                _set_aside_unreadable_file(TEST_OFF_PEAK_JOBS_FILE, add_test_log)
                jobs = {}
            jobs[run_id] = fields
            atomic_write_text(TEST_OFF_PEAK_JOBS_FILE, json.dumps(jobs, indent=2) + "\n")
    except OSError as exc:
        add_test_log(
            f"Warning: could not save the off-peak job record to disk ({exc}). "
            "If this app closes, the job id will not be shown again -- copy it from this log now."
        )
        return False
    return True


def clear_test_off_peak_job_state(run_id: str | None = None) -> None:
    """Remove one run's record, or the whole file when run_id is None."""
    try:
        with _test_off_peak_jobs_file_lock:
            if run_id is None:
                TEST_OFF_PEAK_JOBS_FILE.unlink(missing_ok=True)
                return
            jobs = _read_test_off_peak_raw()
            if jobs is None or run_id not in jobs:
                return  # keep an unreadable file for recovery
            jobs.pop(run_id)
            if jobs:
                atomic_write_text(TEST_OFF_PEAK_JOBS_FILE, json.dumps(jobs, indent=2) + "\n")
            else:
                TEST_OFF_PEAK_JOBS_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def surface_stale_test_off_peak_jobs() -> None:
    """surface_stale_off_peak_job()'s Test Mode counterpart, called once at
    startup: lists any Test Mode off-peak job left unresolved by a restart in
    the Test Mode log. Dismissed with Test Mode's Reset All."""
    raw = _read_test_off_peak_raw()
    jobs = read_test_off_peak_jobs()
    if raw and len(raw) > len(jobs):
        add_test_log(
            f"{len(raw) - len(jobs)} Test Mode off-peak job record(s) in {TEST_OFF_PEAK_JOBS_FILE} could "
            "not be read and were kept as they are. They may describe batches still running on the "
            "provider's servers -- open the file or check the provider's own console/dashboard."
        )
    if not jobs:
        if raw is None:
            add_test_log(
                f"A Test Mode off-peak job record exists at {TEST_OFF_PEAK_JOBS_FILE} but could not be "
                "read. It may describe batches still running on the provider's servers -- open the file "
                "or check the provider's own console/dashboard."
            )
        return
    for job in jobs.values():
        add_test_log(
            "A Test Mode off-peak batch job from a previous session may still be unresolved: "
            f"provider {job.get('provider', 'unknown')}, model {job.get('model', 'unknown')}, "
            f"job id {job.get('job_id', 'unknown')}, submitted {job.get('submitted_at', 'an unknown time')}, "
            f"last known status \"{job.get('status', 'unknown')}\". This app cannot resume watching it "
            "automatically after a restart -- check the provider's own console/dashboard for its actual "
            "status. Once resolved there, click Reset All to dismiss this notice."
        )
    with test_lock:
        if not test_state["summary"]:
            test_state["summary"] = (
                f"{len(jobs)} Test Mode off-peak batch job(s) from a previous session may still be "
                "unresolved -- see the Progress Console."
            )


def reset_ui_state() -> bool:
    """Reset the Transcribe page, unless a run holds the slot. The idle check,
    the reset and the persistent cleanup all happen under one lock
    acquisition, so a run reserved in between can't be erased
    (reviews/CODEX_REVIEW_8.md M-4). Returns whether it reset."""
    with lock:
        if state["running"]:
            return False
        stop_event.clear()
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
    return True


def reset_test_ui_state() -> bool:
    """Test Mode's counterpart to reset_ui_state(), same single-lock rule."""
    with test_lock:
        if test_state["running"]:
            return False
        test_stop_event.clear()
        test_state["running"] = False
        test_state["current_run_id"] = ""
        test_state["log"] = []
        test_state["summary"] = ""
        test_state["model_a"] = DEFAULT_MODEL
        test_state["model_b"] = DEFAULT_MODEL
        test_state["zoom_a"] = False
        test_state["zoom_b"] = False
        test_state["off_peak"] = False
        test_state["order"] = "oldest"
        test_state["file_type"] = "jpeg"
        test_state["profile_id"] = ""
        test_state["queue"] = []
        test_state["runs"] = {}
        clear_source_folder()
        clear_test_off_peak_job_state()
    return True


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
            "off_peak": bool(test_state["off_peak"]),
            "runs": runs,
        }
