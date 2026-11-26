"""Off-peak translation (translation_offpeak.py). No real provider: fake
Gemini/Claude batch clients answer each request from its own JSON, so these
check request shape, result matching, the real-time re-send of failed
requests, Stop, the job record, and the HTTP route."""

from __future__ import annotations

import json
import types as pytypes
from pathlib import Path

from google.genai import types as genai_types

import app_state
import transcript_translation as tt
import translation_offpeak as top
from http_utils import extract_docx_text
from run_support import write_docx
from tests.test_transcript_translation import NATI, _multipart, _profile, _use_profiles

GEMINI = "gemini-3.1-pro-preview"
CLAUDE = "claude-sonnet-5"


def _answer(message: str, prefix: str = "B") -> str:
    entries = json.loads(message)["entries"]
    return json.dumps({"entries": [{"id": e["id"], "translations": {"English": f"{prefix} {e['id']}"}} for e in entries]})


class _FakeGeminiBatches:
    def __init__(self, finish_reasons=None):
        self.created = None
        self.cancelled = []
        self.finish_reasons = finish_reasons or {}

    def create(self, model, src, config=None):
        self.created = (model, src, config)
        return pytypes.SimpleNamespace(name="batches/translate1")

    def get(self, name):
        responses = []
        for request in self.created[1]:
            index = int(request.metadata["index"])
            reason = self.finish_reasons.get(index, genai_types.FinishReason.STOP)
            responses.append(
                pytypes.SimpleNamespace(
                    metadata=request.metadata,
                    error=None,
                    response=pytypes.SimpleNamespace(
                        text=_answer(request.contents),
                        candidates=[pytypes.SimpleNamespace(finish_reason=reason)],
                        usage_metadata=None,
                    ),
                )
            )
        return pytypes.SimpleNamespace(
            state=genai_types.JobState.JOB_STATE_SUCCEEDED,
            completion_stats=pytypes.SimpleNamespace(successful_count=len(responses), failed_count=0, incomplete_count=0),
            dest=pytypes.SimpleNamespace(inlined_responses=responses),
        )

    def cancel(self, name):
        self.cancelled.append(name)


def _setup(monkeypatch, batches):
    _use_profiles(monkeypatch, _profile())
    monkeypatch.setattr(top, "validate_api_key_with_retry", lambda *a, **k: None)
    client = pytypes.SimpleNamespace(batches=batches)
    monkeypatch.setattr(top, "_gemini_client", lambda key, timeout: client)
    with app_state.lock:
        app_state.state["running"] = True
        app_state.state["off_peak"] = True
        app_state.state["log"] = []
    app_state.stop_event.clear()


def _log() -> str:
    with app_state.lock:
        return "\n".join(app_state.state["log"])


def test_batch_translates_every_entry_and_clears_the_record(monkeypatch, sandboxed_user_data):
    batches = _FakeGeminiBatches()
    _setup(monkeypatch, batches)
    monkeypatch.setattr(tt, "call_ai_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no real-time call")))

    top.run_off_peak_translation_job(NATI, "Napoli corrected.docx", "napoli-nati", ["English"], GEMINI, "key")

    model, src, config = batches.created
    assert model == GEMINI
    # One request per image (never across images), tagged by position.
    assert [r.metadata["index"] for r in src] == ["0", "1"]
    assert src[0].config.system_instruction and src[0].config.response_mime_type == "application/json"
    assert config.display_name.startswith("customizable-transcriber-translate-")
    with app_state.lock:
        assert app_state.state["running"] is False and app_state.state["off_peak"] is False
        assert app_state.state["summary"].startswith("Off-peak: Translated 3 of 3 entries")
        download = app_state.state["download"]
    text = extract_docx_text(Path(download).read_bytes())
    assert "English Translation: B 2/Nati_003.jpg#2" in text
    assert not app_state.OFF_PEAK_JOB_FILE.exists()


def test_cut_off_request_is_resent_in_real_time(monkeypatch, sandboxed_user_data):
    batches = _FakeGeminiBatches(finish_reasons={1: genai_types.FinishReason.MAX_TOKENS})
    _setup(monkeypatch, batches)
    sent = []

    def real_time(api_key, model, system_prompt, message, cached, use_cache):
        sent.append(json.loads(message)["entries"])
        return json.loads(_answer(message, prefix="R"))

    monkeypatch.setattr(tt, "call_ai_json", real_time)
    top.run_off_peak_translation_job(NATI, "Napoli corrected.docx", "napoli-nati", ["English"], GEMINI, "key")

    assert [[e["id"] for e in chunk] for chunk in sent] == [["2/Nati_003.jpg#1", "2/Nati_003.jpg#2"]]
    assert "Re-sending 2 entries the batch could not translate" in _log()
    with app_state.lock:
        assert app_state.state["summary"].startswith("Off-peak: Translated 3 of 3 entries")
        download = app_state.state["download"]
    text = extract_docx_text(Path(download).read_bytes())
    assert "English Translation: B 1/Nati_002.jpg#1" in text
    assert "English Translation: R 2/Nati_003.jpg#2" in text


def test_stop_before_submission_sends_nothing(monkeypatch, sandboxed_user_data):
    batches = _FakeGeminiBatches()
    _setup(monkeypatch, batches)
    app_state.stop_event.set()
    try:
        top.run_off_peak_translation_job(NATI, "Napoli corrected.docx", "napoli-nati", ["English"], GEMINI, "key")
    finally:
        app_state.stop_event.clear()
    assert batches.created is None
    with app_state.lock:
        assert app_state.state["summary"] == "Stopped before the off-peak translation batch was submitted."
        assert app_state.state["running"] is False


def test_lost_job_is_recorded_for_the_next_start(monkeypatch, sandboxed_user_data):
    batches = _FakeGeminiBatches()
    batches.get = lambda name: (_ for _ in ()).throw(ValueError("unexpected provider reply"))
    _setup(monkeypatch, batches)
    top.run_off_peak_translation_job(NATI, "Napoli corrected.docx", "napoli-nati", ["English"], GEMINI, "key")
    record = json.loads(app_state.OFF_PEAK_JOB_FILE.read_text())
    (job,) = record["jobs"].values()
    assert job["kind"] == "translation" and job["job_id"] == "batches/translate1" and job["status"] == "status_unknown"
    with app_state.lock:
        assert app_state.state["summary"].startswith("Fatal error")
        assert app_state.state["running"] is False


def test_claude_requests_match_the_real_time_settings():
    plan_messages = ['{"entries": []}', '{"entries": [1]}']
    created = {}

    class _Batches:
        def create(self, requests):
            created["requests"] = requests
            return pytypes.SimpleNamespace(id="msgbatch_1")

    client = pytypes.SimpleNamespace(with_options=lambda **k: pytypes.SimpleNamespace(messages=pytypes.SimpleNamespace(batches=_Batches())))
    assert top.submit_claude_text_batch(client, CLAUDE, "prompt", plan_messages) == "msgbatch_1"
    first = created["requests"][0]
    assert first["custom_id"] == "0" and first["params"]["system"] == "prompt"
    assert first["params"]["max_tokens"] == top.CLAUDE_JSON_MAX_TOKENS
    assert first["params"]["messages"] == [{"role": "user", "content": '{"entries": []}'}]


def test_run_offpeak_route_starts_the_batch_job(live_server, sandboxed_user_data, monkeypatch, tmp_path):
    import urllib.request
    from http.cookiejar import CookieJar

    import handlers.transcribe_translate as handlers

    started = {}
    monkeypatch.setattr(handlers, "start_off_peak_translation_job", lambda *args: started.setdefault("args", args))
    _use_profiles(monkeypatch, _profile())
    source = tmp_path / "corrected.docx"
    write_docx(source, NATI, native_language="Italian", profile_label="Napoli Nati")
    host, port = live_server
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    opener.open(urllib.request.Request(f"http://{host}:{port}/", headers={"Host": f"{host}:{port}"}), timeout=5)
    body, content_type = _multipart(
        {"languages": "English", "profile_id": "", "model": GEMINI, "api_key": "key", "honorifics": "Don"},
        source.read_bytes(),
    )
    response = opener.open(
        urllib.request.Request(
            f"http://{host}:{port}/api/translate-transcript/run-offpeak", data=body, method="POST",
            headers={"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Content-Type": content_type},
        ),
        timeout=5,
    )
    assert response.status == 200 and json.loads(response.read())["ok"]
    assert started["args"][1] == "corrected.docx" and started["args"][4] == GEMINI
    with app_state.lock:
        assert app_state.state["off_peak"] is True
        assert app_state.state["summary"].startswith("Submitting off-peak translation")
        app_state.state["running"] = False
        app_state.state["off_peak"] = False
