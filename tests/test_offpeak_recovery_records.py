"""reviews/CODEX_REVIEW_8.md M-3: off-peak recovery records are kept per job.
A second job must never erase an unresolved first job's record, resolving a
job removes only its own entry, an old single-record file still reads, and
an unreadable file is kept for manual recovery instead of being overwritten."""

import json

import app_state
import batch_transcription as bt


def test_second_job_keeps_unresolved_first_record(sandboxed_user_data):
    first, second = bt.TranscribeOffPeakSink(), bt.TranscribeOffPeakSink()
    first.persist(provider="gemini", job_id="batches/one", status="status_unknown")
    second.persist(provider="claude", job_id="msgbatch_two", status="running")
    second.clear_persisted()  # second job resolved

    records = app_state.read_off_peak_job_records()
    assert [r["job_id"] for r in records.values()] == ["batches/one"]


def test_restart_lists_every_outstanding_job(sandboxed_user_data):
    bt.TranscribeOffPeakSink().persist(provider="gemini", job_id="batches/one", status="status_unknown")
    bt.TranscribeOffPeakSink().persist(provider="claude", job_id="msgbatch_two", status="running")
    with app_state.lock:
        app_state.state["log"] = []
        app_state.state["summary"] = ""
    app_state.surface_stale_off_peak_job()
    with app_state.lock:
        log = "\n".join(app_state.state["log"])
    assert "batches/one" in log and "msgbatch_two" in log

    app_state.reset_ui_state()  # explicit dismissal clears all
    assert app_state.read_off_peak_job_records() == {}


def test_legacy_single_record_file_still_reads_and_is_kept(sandboxed_user_data):
    app_state.OFF_PEAK_JOB_FILE.write_text(
        json.dumps({"provider": "gemini", "job_id": "batches/old", "status": "status_unknown"}),
        encoding="utf-8",
    )
    assert app_state.read_off_peak_job_state()["job_id"] == "batches/old"

    sink = bt.TranscribeOffPeakSink()
    sink.persist(provider="claude", job_id="msgbatch_new", status="running")
    sink.clear_persisted()
    assert [r["job_id"] for r in app_state.read_off_peak_job_records().values()] == ["batches/old"]


def test_unreadable_record_file_is_set_aside_not_overwritten(sandboxed_user_data):
    app_state.OFF_PEAK_JOB_FILE.write_text("{not json", encoding="utf-8")
    bt.TranscribeOffPeakSink().clear_persisted()
    assert app_state.OFF_PEAK_JOB_FILE.read_text(encoding="utf-8") == "{not json"

    bt.TranscribeOffPeakSink().persist(provider="gemini", job_id="batches/x", status="running")
    kept = list(sandboxed_user_data.glob("off_peak_job.unreadable-*.json"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "{not json"
    assert app_state.read_off_peak_job_state()["job_id"] == "batches/x"


def test_test_mode_reused_run_id_keeps_both_records(sandboxed_user_data, tmp_path):
    first = bt.TestModeOffPeakSink("b1-a", "[a]", tmp_path / "a.md")
    second = bt.TestModeOffPeakSink("b1-a", "[a]", tmp_path / "b.md")
    first.persist(provider="gemini", job_id="batches/one", status="status_unknown")
    second.persist(provider="gemini", job_id="batches/two", status="running")
    second.clear_persisted()
    assert [j["job_id"] for j in app_state.read_test_off_peak_jobs().values()] == ["batches/one"]


def test_test_mode_unreadable_file_is_set_aside(sandboxed_user_data, tmp_path):
    app_state.TEST_OFF_PEAK_JOBS_FILE.write_text("[broken", encoding="utf-8")
    bt.TestModeOffPeakSink("b1-a", "[a]", tmp_path / "a.md").persist(job_id="batches/y", status="running")
    kept = list(sandboxed_user_data.glob("test_off_peak_jobs.unreadable-*.json"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "[broken"


# CODEX_REVIEW_2.md M-3: an entry this version can't interpret survives a
# later save and a single-job clear, and is reported at startup.

def test_malformed_entry_survives_save_and_clear(sandboxed_user_data):
    app_state.OFF_PEAK_JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    app_state.OFF_PEAK_JOB_FILE.write_text(json.dumps({
        "format": app_state.OFF_PEAK_JOBS_FORMAT,
        "jobs": {"good": {"job_id": "batches/good"}, "odd": "batches/plain-string"},
    }))
    assert app_state.write_off_peak_job_state(record_key="third", job_id="batches/third")
    stored = json.loads(app_state.OFF_PEAK_JOB_FILE.read_text())["jobs"]
    assert stored["odd"] == "batches/plain-string"
    assert set(stored) == {"good", "odd", "third"}
    app_state.clear_off_peak_job_state("good")
    stored = json.loads(app_state.OFF_PEAK_JOB_FILE.read_text())["jobs"]
    assert set(stored) == {"odd", "third"}
    assert set(app_state.read_off_peak_job_records()) == {"third"}
    with app_state.lock:
        app_state.state["log"].clear()
    app_state.surface_stale_off_peak_job()
    with app_state.lock:
        log = list(app_state.state["log"])
    assert any("could not be read and were kept" in line for line in log)
    assert any("batches/third" in line for line in log)
    with app_state.lock:
        app_state.state["log"].clear()
        app_state.state["summary"] = ""


def test_test_mode_malformed_entry_survives_save_and_clear(sandboxed_user_data):
    app_state.TEST_OFF_PEAK_JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    app_state.TEST_OFF_PEAK_JOBS_FILE.write_text(json.dumps({"a": {"job_id": "j-a"}, "b": "j-b-plain"}))
    assert app_state.write_test_off_peak_job_state("c", job_id="j-c")
    app_state.clear_test_off_peak_job_state("a")
    stored = json.loads(app_state.TEST_OFF_PEAK_JOBS_FILE.read_text())
    assert stored == {"b": "j-b-plain", "c": {"job_id": "j-c"}}


def test_set_aside_names_never_collide(sandboxed_user_data):
    path = app_state.OFF_PEAK_JOB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        path.write_text("{not json")
        app_state.write_off_peak_job_state(record_key="k", job_id="j")
        path.unlink()
    assert len(list(path.parent.glob(f"{path.stem}.unreadable-*"))) == 3
    with app_state.lock:
        app_state.state["log"].clear()
