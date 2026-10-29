"""Tests for the Transcribe page's "Translate completed transcript" feature
(transcript_translation.py, handlers/transcribe_translate.py). No real AI
call: the model is replaced by a stub, so these check parsing, insertion,
label rules, the preflight, failure handling, and the HTTP endpoints."""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path

import app_state
import handlers.transcribe_translate as translate_handlers
import transcript_translation as tt
from http_utils import extract_docx_text
from run_support import write_docx

NATI = """# Transcription Output

Source folder: /tmp/source


--- START OF RECORD: Nati_002.jpg ---

Date: 19 Luglio 1834 [19 July 1834]

Italian Transcription: Num. d'ordine. Quattrocentocinquantuno L'anno mille ottocento trentaquattro.

Baptism Record: L'anno mille ottocentotrentaquattro il dì venti.

Notes: ENTRY CONTINUES ON THE NEXT IMAGE -- the rest of this entry is in the record for Nati_003.jpg.


--- START OF RECORD: Nati_003.jpg ---

Notes: ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- the beginning of this entry is in the record for Nati_002.jpg.

Italian Transcription: La presentazione, e dichiarazione anzidetta.

Date: dicianove Luglio 1834 [19 July 1834]

Italian Transcription: Num. d'ordine. quattrocentocinquanta due.
"""

# Label on its own line, then the text -- the other layout real transcripts use.
MATRIMONI = """--- START OF RECORD: Matrimoni_002.jpg ---

Date: due Gennaro milleottocentoventitre [2 January 1823]

Italian Transcription:

Numero d'Ordine Uno. L'anno milleottocentoventitre.

Church Wedding Record:

L'anno mille ottocentoventitre il dì due del mese di Gennaro.
"""

MORTI_WITH_ENGLISH = """--- START OF RECORD: Morti_01.jpg ---

Page 12:

Date: Anno Dni 1702 die 22 Maii [22 May 1702]

Latin Transcription: Anno Dni 1702 die 22 Maii Angela Di Lio.

English Translation: On the 22nd day of May 1702. Angela Di Lio.
"""


def _profile(**overrides):
    profile = {
        "id": "napoli-nati",
        "label": "Napoli Nati",
        "role_context": "You are an expert paleographer.",
        "reference_context": "Surnames: Ferrajolo",
        "output_format": "",
        "native_language": "Italian",
        "record_type": "civil_birth",
        "pb_answers": {
            "fields": {"language": "Italian"},
            "checked": {"translateExpandAbbreviations": ["expand"], "translateConvertNames": [], "honorifics": ["Don"]},
            "rows": {},
        },
    }
    profile.update(overrides)
    return profile


def _use_profiles(monkeypatch, *profiles):
    monkeypatch.setattr(tt, "load_custom_profiles", lambda: [dict(p) for p in profiles])


def _fake_translations(plan):
    return {e.entry_id: {lang: f"[{lang} {e.entry_id}]" for lang in plan.work[e.entry_id]} for e in plan.entries_to_translate if e.entry_id in plan.work}


def _without_added(output: str, added: list[str]) -> list[str]:
    lines = output.split("\n")
    return [line for line in lines if not any(a in line for a in added)]


def test_parses_entries_fragments_and_side_blocks(monkeypatch):
    _use_profiles(monkeypatch, _profile())
    plan = tt.build_plan(NATI, "napoli-nati", ["English"])
    assert plan.errors == []
    entries = plan.parsed.entries
    assert [e.entry_id for e in entries] == ["Nati_002.jpg#1", "Nati_003.jpg#1", "Nati_003.jpg#2"]
    assert [e.is_fragment for e in entries] == [False, True, False]
    assert entries[0].first("baptism") is not None
    # The end-of-record continuation note is not an entry.
    assert len(plan.parsed.records[0].entries) == 1


def test_assembly_inserts_after_transcription_and_keeps_every_original_line(monkeypatch):
    _use_profiles(monkeypatch, _profile())
    plan = tt.build_plan(NATI, "napoli-nati", ["English"])
    output = tt.assemble(plan, _fake_translations(plan), {})
    lines = output.split("\n")
    # Translation sits between the transcription and the Baptism Record.
    transcription_at = lines.index("Italian Transcription: Num. d'ordine. Quattrocentocinquantuno L'anno mille ottocento trentaquattro.")
    assert lines[transcription_at + 2] == "English Translation: [English Nati_002.jpg#1]"
    assert lines[transcription_at + 4].startswith("Baptism Record:")
    # Removing each inserted "blank line + translation" pair gives back the original exactly.
    restored = output
    for translations in _fake_translations(plan).values():
        restored = restored.replace(f"\n\nEnglish Translation: {translations['English']}", "")
    assert restored == NATI


def test_separate_line_layout_and_church_wedding_record(monkeypatch):
    _use_profiles(monkeypatch, _profile(record_type="civil_marriage"))
    plan = tt.build_plan(MATRIMONI, "napoli-nati", ["English"])
    entry = plan.parsed.entries[0]
    assert plan.cwr_work == {entry.entry_id: ["English"]}
    output = tt.assemble(
        plan,
        {entry.entry_id: {"English": "On the 2nd day of January 1823. Order Number One."}},
        {entry.entry_id: {"English": "The year 1823 the second day of January."}},
    )
    assert (
        "Numero d'Ordine Uno. L'anno milleottocentoventitre.\n\nEnglish Translation:\n\n"
        "On the 2nd day of January 1823. Order Number One.\n\nChurch Wedding Record:"
    ) in output
    assert output.rstrip().endswith(
        "Gennaro.\n\nChurch Wedding Record (English translation):\n\nThe year 1823 the second day of January."
    )


def test_italian_translation_switches_labels_to_italian(monkeypatch):
    _use_profiles(monkeypatch, _profile(native_language="Latin", id="morti", label="Morti"))
    plan = tt.build_plan(MORTI_WITH_ENGLISH, "morti", ["English", "Italian"])
    entry = plan.parsed.entries[0]
    # English is already there, so only Italian is requested.
    assert plan.work == {entry.entry_id: ["Italian"]}
    output = tt.assemble(plan, {entry.entry_id: {"Italian": "Il giorno 22 di maggio 1702. Angela Di Lio."}}, {})
    assert "Trascrizione in Latino: Anno Dni 1702 die 22 Maii Angela Di Lio." in output
    assert "Traduzione in Inglese: On the 22nd day of May 1702. Angela Di Lio." in output
    assert output.index("Traduzione in Inglese:") < output.index("Traduzione in Italiano: Il giorno 22")
    assert "Latin Transcription:" not in output


def test_preflight_errors(monkeypatch):
    _use_profiles(monkeypatch, _profile(id="morti", label="Morti", native_language="Latin"))
    already = tt.build_plan(MORTI_WITH_ENGLISH, "morti", ["English"])
    assert any("nothing to translate" in error for error in already.errors)
    assert tt.build_plan(MORTI_WITH_ENGLISH, "missing", ["Italian"]).errors == ["The selected prompt profile was not found."]
    assert any("START OF RECORD" in e for e in tt.build_plan("just some text", "morti", ["English"]).errors)
    assert tt.build_plan(MORTI_WITH_ENGLISH, "morti", []).errors[0] == "Choose English, Italian, or both."
    _use_profiles(monkeypatch, _profile())
    native = tt.build_plan(NATI, "napoli-nati", ["Italian"])
    assert any("already in Italian" in error for error in native.errors)


def test_user_joined_entry_is_accepted_and_noted(monkeypatch):
    _use_profiles(monkeypatch, _profile())
    # The user moved image 003's fragment into 002's entry and deleted it.
    joined = NATI.replace(
        "Notes: ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- the beginning of this entry is in the record for Nati_002.jpg.\n\n"
        "Italian Transcription: La presentazione, e dichiarazione anzidetta.\n\n",
        "",
    )
    plan = tt.build_plan(joined, "napoli-nati", ["English"])
    assert plan.errors == []
    assert len(plan.accepted_edits) == 1
    assert "Treated as joined by you" in plan.accepted_edits[0]


def test_profile_detected_from_docx_header_and_header_updated(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, _profile())
    source = tmp_path / "source.docx"
    write_docx(source, NATI, native_language="Italian", translation_languages=[], record_type="civil_birth",
               model="gemini-3.1-pro-preview", profile_label="Napoli Nati")
    text = tt.docx_text(source.read_bytes())
    plan = tt.build_plan(text, "", ["English"])
    assert plan.errors == []
    assert plan.profile_detected and plan.profile["id"] == "napoli-nati"
    assert plan.parsed.header["Translations produced"] == "None"
    body = tt.assemble(plan, _fake_translations(plan), {})
    # The old header box is not carried into the body.
    assert "DO NOT EDIT" not in body and body.startswith("# Transcription Output")
    out = tmp_path / "out.docx"
    write_docx(out, body, native_language="Italian", translation_languages=plan.final_languages(_fake_translations(plan)))
    assert "Translations produced: English" in extract_docx_text(out.read_bytes())


def test_prompt_follows_the_users_choices_not_the_profiles_hidden_answers(monkeypatch):
    # The profile's saved (hidden, never chosen) answers say expand + Don only;
    # the user's choices in the Translate section are what count.
    options = tt.TranslationOptions(expand_abbreviations=False, convert_names=True, honorifics=["Don", "Signor"])
    prompt = tt.build_translation_prompt(_profile(), "Italian", ["English"], options)
    assert "Carry abbreviations over as written" in prompt
    assert "Give personal names in their standard English form" in prompt
    assert "keep only Don or Signor with the name" in prompt
    assert "On the Nth day of <Month> <year>." in prompt
    assert "Il giorno" not in prompt
    assert "Surnames: Ferrajolo" in prompt  # background still comes from the profile
    defaults = tt.build_translation_prompt(None, "Latin", ["Italian"], tt.TranslationOptions())
    assert "Carry abbreviations over as written" in defaults
    assert "Keep personal names in the form the transcription uses" in defaults
    assert "keep only Don or Master" in defaults
    assert "BACKGROUND ON THIS REGISTER" not in defaults
    none_kept = tt.build_translation_prompt(None, "Latin", ["English"], tt.TranslationOptions(honorifics=[]))
    assert "keep only" not in none_kept


def test_missing_profile_is_a_warning_and_runs_without_background(monkeypatch, tmp_path):
    _use_profiles(monkeypatch)  # nothing saved on this computer
    source = tmp_path / "source.docx"
    write_docx(source, NATI, native_language="Italian", record_type="civil_birth", profile_label="Someone Else's Profile")
    plan = tt.build_plan(tt.docx_text(source.read_bytes()), "", ["English"])
    assert plan.errors == [] and plan.profile is None
    assert "Someone Else's Profile" in plan.warnings[0] and "without its background" in plan.warnings[0]
    assert tt.record_type_for(plan.parsed, None) == "civil_birth"
    summary = tt.preflight_summary(plan)
    assert summary["ok"] and summary["profile_label"] == ""
    no_header = tt.build_plan(NATI, "", ["English"])
    assert no_header.errors == [] and "does not name its prompt profile" in no_header.warnings[0]


def test_chunk_failures_are_reported_and_truncation_splits(monkeypatch):
    _use_profiles(monkeypatch, _profile())
    plan = tt.build_plan(NATI, "napoli-nati", ["English"])
    chunk = [e for e in plan.parsed.entries if e.record == "Nati_003.jpg"]
    calls = []

    def fake_call(api_key, model, system_prompt, message, cached, use_cache):
        entries = json.loads(message)["entries"]
        calls.append([e["id"] for e in entries])
        if len(entries) > 1:
            raise tt.TruncatedResponseError("cut off")
        entry = entries[0]
        assert entry.get("fragment") is (True if entry["id"].endswith("#1") else None)
        if entry["id"].endswith("#2"):
            return {"entries": []}
        return {"entries": [{"id": entry["id"], "translations": {"English": "The presentation\nwas made."}}]}

    monkeypatch.setattr(tt, "call_ai_json", fake_call)
    done, _cwr_done, failed = tt._translate_chunk(chunk, plan, "key", "gemini-3.1-pro-preview", "prompt", None, False)
    assert calls == [["Nati_003.jpg#1", "Nati_003.jpg#2"], ["Nati_003.jpg#1"], ["Nati_003.jpg#2"]]
    assert done == {"Nati_003.jpg#1": {"English": "The presentation was made."}}
    assert failed == {"Nati_003.jpg#2": "The AI response left this entry out."}


def test_chunks_never_cross_images(monkeypatch):
    _use_profiles(monkeypatch, _profile())
    plan = tt.build_plan(NATI, "napoli-nati", ["English"])
    assert [[e.entry_id for e in c] for c in tt._chunks(plan.entries_to_translate, plan)] == [
        ["Nati_002.jpg#1"],
        ["Nati_003.jpg#1", "Nati_003.jpg#2"],
    ]


def test_job_writes_docx_md_and_report(monkeypatch, sandboxed_user_data):
    _use_profiles(monkeypatch, _profile())
    monkeypatch.setattr(tt, "validate_api_key_with_retry", lambda *a, **k: None)
    monkeypatch.setattr(tt, "create_gemini_prompt_cache", lambda *a, **k: None)

    def fake_call(api_key, model, system_prompt, message, cached, use_cache):
        return {"entries": [{"id": e["id"], "translations": {"English": "T " + e["id"]}} for e in json.loads(message)["entries"]]}

    monkeypatch.setattr(tt, "call_ai_json", fake_call)
    with app_state.lock:
        app_state.state["running"] = True
    tt.run_translation_job(NATI, "Napoli corrected.docx", "napoli-nati", ["English"], "gemini-3.1-pro-preview", "key")
    with app_state.lock:
        download, report = app_state.state["download"], app_state.state["report_download"]
        assert app_state.state["running"] is False
        assert app_state.state["summary"].startswith("Translated 3 of 3 entries")
    assert download.endswith(".docx") and "Napoli-corrected-translated" in download
    text = extract_docx_text(Path(download).read_bytes())
    assert "English Translation: T Nati_003.jpg#2" in text
    assert "Translations produced: English" in text
    with zipfile.ZipFile(io.BytesIO(Path(report).read_bytes())) as archive:
        report_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Translation Report" in report_xml and "continuation, no opening date" in report_xml


def _multipart(fields: dict[str, str], file_bytes: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="source_file"; filename="corrected.docx"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode() + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def test_http_preflight_and_run(live_server, sandboxed_user_data, monkeypatch, tmp_path):
    _use_profiles(monkeypatch, _profile())
    monkeypatch.setattr(tt, "validate_api_key_with_retry", lambda *a, **k: None)
    monkeypatch.setattr(tt, "create_gemini_prompt_cache", lambda *a, **k: None)
    key_checks = []

    def fake_key_check(project_dir, model, key, **kwargs):
        key_checks.append(key)
        if key == "revoked":
            raise RuntimeError("API key not valid. Please pass a valid API key.")

    monkeypatch.setattr(translate_handlers, "validate_api_key_with_retry", fake_key_check)
    prompts = []

    def fake_call(key, model, prompt, message, *rest):
        prompts.append(prompt)
        return {"entries": [{"id": e["id"], "translations": {"English": "T"}} for e in json.loads(message)["entries"]]}

    monkeypatch.setattr(tt, "call_ai_json", fake_call)
    source = tmp_path / "corrected.docx"
    write_docx(source, NATI, native_language="Italian", profile_label="Napoli Nati")
    host, port = live_server
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(urllib.request.Request(f"http://{host}:{port}/", headers={"Host": f"{host}:{port}"}), timeout=5)

    def post(path, fields):
        body, content_type = _multipart(fields, source.read_bytes())
        request = urllib.request.Request(
            f"http://{host}:{port}{path}", data=body, method="POST",
            headers={"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Content-Type": content_type},
        )
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        return response.status, json.loads(response.read())

    fields = {
        "languages": "English", "profile_id": "", "model": "gemini-3.1-pro-preview",
        "expand_abbreviations": "on", "convert_names": "", "honorifics": "Don,Master",
    }
    # No key: the document is still read, and the missing key is the one problem.
    status, data = post("/api/translate-transcript/preflight", fields)
    assert status == 200 and not data["ok"] and data["errors"] == ["Paste your API key in the API key field above."]
    assert key_checks == []
    # A Claude key with a Gemini model is caught by its shape, with no request.
    status, data = post("/api/translate-transcript/preflight", {**fields, "api_key": "sk-ant-abc"})
    assert not data["ok"] and "looks like a Claude key" in data["errors"][0] and key_checks == []
    # The provider rejects the key.
    status, data = post("/api/translate-transcript/preflight", {**fields, "api_key": "revoked"})
    assert not data["ok"] and data["api_key_valid"] is False and key_checks == ["revoked"]
    # A working key passes, and the document checks are reported as before.
    status, data = post("/api/translate-transcript/preflight", {**fields, "api_key": "key"})
    assert status == 200 and data["ok"] and data["api_key_valid"] and data["profile_detected"]
    assert data["to_translate"] == {"English": 3} and data["fragments"] == 1

    status, data = post("/api/translate-transcript/run", fields)
    assert status == 400 and "API key" in data["errors"][0]

    status, data = post("/api/translate-transcript/run", {**fields, "api_key": "key"})
    assert status == 200 and data["ok"]
    for _ in range(50):
        with app_state.lock:
            if not app_state.state["running"]:
                break
        time.sleep(0.1)
    report = opener.open(
        urllib.request.Request(f"http://{host}:{port}/download-translation-report", headers={"Host": f"{host}:{port}"}),
        timeout=5,
    )
    assert report.status == 200 and report.read()[:2] == b"PK"
    # The choices sent from the page reached the prompt.
    assert prompts and "Expand every abbreviation" in prompts[0] and "keep only Don or Master" in prompts[0]
