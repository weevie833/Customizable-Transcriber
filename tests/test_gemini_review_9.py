"""Regression tests for reviews/GEMINI_REVIEW_9.md, through the real entry
points (live server, real handlers) with synthetic data and temp dirs. No
provider is ever called."""

from __future__ import annotations

import http.client
import io
import json
import os
import struct
import urllib.parse
import zipfile

import pytest

import app as ctapp
import app_state
import profiles_store
import update_check
from http_utils import extract_docx_text
from index_compare import reader
from tests.test_post_redirect_get import _get_csrf_cookie, _post_no_redirect


@pytest.fixture(autouse=True)
def _restore_run_state():
    """The handlers under test write the shared run state (selected profile,
    summary, log); put it back so later test files start clean."""
    import copy

    with ctapp.lock:
        saved = copy.deepcopy(ctapp.state)
    yield
    with ctapp.lock:
        ctapp.state.clear()
        ctapp.state.update(saved)


def _raw(host, port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def _cookie_header(jar) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in jar)


# --- M-1: a ZIP that understates its size is cut off, never expanded -------

def _understated_zip(name: str, real_bytes: int, declared: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, b"A" * real_bytes)
    raw = bytearray(buf.getvalue())
    struct.pack_into("<I", raw, 22, declared)               # local header
    central = raw.rfind(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 24, declared)     # central directory
    return bytes(raw)


def test_docx_with_understated_size_is_rejected_not_expanded():
    payload = _understated_zip("word/document.xml", 20_000_000, 1000)
    with pytest.raises(RuntimeError):
        extract_docx_text(payload)


def test_xlsx_with_understated_size_is_rejected_not_expanded():
    payload = _understated_zip("xl/worksheets/sheet1.xml", 20_000_000, 1000)
    with pytest.raises(RuntimeError):
        reader.list_worksheets(payload)


def test_zipfile_never_reads_past_the_declared_size():
    """What M-1 rests on: Python's zipfile stops at the declared size."""
    payload = _understated_zip("word/document.xml", 5_000_000, 1000)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive, archive.open("word/document.xml") as handle:
        data = b""
        try:
            while chunk := handle.read(65536):
                data += chunk
        except zipfile.BadZipFile:
            pass
    assert len(data) <= 1000


# --- M-2: saving a profile during a run keeps the run's progress -----------

def test_profile_save_during_a_run_keeps_summary_log_and_download(live_server, sandboxed_user_data):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    profile = ctapp.save_custom_profile("Mid Run Profile", "role", "reference", "format")
    with ctapp.lock:
        saved = {k: ctapp.state[k] for k in ("running", "summary", "log", "download")}
        ctapp.state.update(running=True, summary="Translating image 3 of 9", log=["line 1", "line 2"],
                           download="/outputs/run.docx")
    try:
        _post_no_redirect(host, port, jar, "/save-profile", {
            "profile_id": profile["id"], "role_context": "new role",
            "reference_context": "new reference", "output_format": "new format",
        })
        with ctapp.lock:
            summary, log, download = ctapp.state["summary"], list(ctapp.state["log"]), ctapp.state["download"]
    finally:
        with ctapp.lock:
            ctapp.state.update(saved)
    assert summary == "Translating image 3 of 9"
    assert download == "/outputs/run.docx"
    assert log[:2] == ["line 1", "line 2"] and log[-1].startswith("Updated profile:")
    assert profiles_store.load_profile_exact(profile["id"])["role_context"] == "new role"


# --- M-3: rejected requests get no token cookie ----------------------------

def test_rejected_requests_carry_no_token_cookie(live_server):
    host, port = live_server
    resp, _ = _raw(host, port, "GET", "/", headers={"Host": "evil.example"})
    assert resp.status == 400 and resp.getheader("Set-Cookie") is None
    resp, _ = _raw(host, port, "POST", "/stop", headers={
        "Host": f"{host}:{port}", "Origin": "http://evil.example", "Content-Length": "0"})
    assert resp.status == 403 and resp.getheader("Set-Cookie") is None
    resp, _ = _raw(host, port, "POST", "/stop", headers={
        "Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Content-Length": "0"})
    assert resp.status == 403 and resp.getheader("Set-Cookie") is None
    resp, _ = _raw(host, port, "GET", "/", headers={"Host": f"{host}:{port}"})
    assert resp.status == 200 and "ct_token=" in (resp.getheader("Set-Cookie") or "")


def test_cookie_comes_back_after_a_rejection_on_the_same_connection(live_server):
    """The suppress flag is per request, not per (keep-alive) connection."""
    host, port = live_server
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("POST", "/stop", headers={"Host": f"{host}:{port}", "Origin": "http://evil.example",
                                           "Content-Length": "0"})
    first = conn.getresponse()
    first.read()
    conn.request("GET", "/", headers={"Host": f"{host}:{port}"})
    second = conn.getresponse()
    second.read()
    conn.close()
    assert first.getheader("Set-Cookie") is None
    assert "ct_token=" in (second.getheader("Set-Cookie") or "")


# --- L-1: token compare and owner-only files -------------------------------

def test_non_ascii_token_is_refused_not_a_server_error(live_server):
    host, port = live_server
    resp, _ = _raw(host, port, "POST", "/stop", headers={
        "Host": f"{host}:{port}", "Origin": f"http://{host}:{port}",
        "Cookie": "ct_token=\u00e9\u00e9\u00e9".encode().decode("latin-1"), "Content-Length": "0"})
    assert resp.status == 403


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_existing_request_token_file_is_made_owner_only(tmp_path):
    path = tmp_path / ctapp.REQUEST_TOKEN_FILE_NAME
    path.write_text("A" * 40, encoding="utf-8")
    os.chmod(path, 0o644)
    assert ctapp.load_request_token(tmp_path) == "A" * 40
    assert (path.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_existing_saved_keys_file_is_made_owner_only(tmp_path, monkeypatch):
    project, data = tmp_path / "app", tmp_path / "data"
    project.mkdir()
    data.mkdir()
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    target = data / ".env"
    target.write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    os.chmod(target, 0o644)
    monkeypatch.setattr(profiles_store, "PROJECT_DIR", project)
    monkeypatch.setattr(profiles_store, "USER_DATA_DIR", data)
    profiles_store.migrate_saved_keys_file()
    assert (target.stat().st_mode & 0o777) == 0o600
    assert "ANTHROPIC_API_KEY=sk-ant-test" in target.read_text(encoding="utf-8")


# --- L-2: a profile id with header characters is not a profile ------------

def test_profile_file_with_unsafe_id_is_not_loaded(sandboxed_user_data):
    bad = profiles_store.USER_PROFILES_DIR / "bad.json"
    profiles_store.USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    bad.write_text(json.dumps({"id": 'x"\r\nSet-Cookie: a=b', "label": "Bad", "role_context": "r",
                               "reference_context": "", "output_format": ""}), encoding="utf-8")
    ids = [p["id"] for p in profiles_store.load_custom_profiles()]
    assert not any("\n" in i or '"' in i for i in ids)


def test_export_filename_is_the_safe_profile_id(sandboxed_user_data):
    profile = ctapp.save_custom_profile("Export Me", "role", "reference", "format")
    filename, _body = profiles_store.export_profile_payload(profile["id"])
    assert filename == f"{profile['id']}.tbprofile.json"


# --- L-3: downloads only come from the outputs folder ---------------------

@pytest.mark.parametrize("path, set_state", [
    ("/download", lambda p: ctapp.state.__setitem__("download", p)),
    ("/download-translation-report",
     lambda p: ctapp.state.__setitem__("report_download", p)),
])
def test_download_outside_outputs_is_not_served(live_server, sandboxed_user_data, tmp_path, path, set_state):
    host, port = live_server
    outside = tmp_path / "secret.docx"
    outside.write_bytes(b"not an output")
    with ctapp.lock:
        saved = (ctapp.state.get("download", ""), ctapp.state.get("report_download", ""))
        set_state(str(outside))
    try:
        resp, data = _raw(host, port, "GET", path, headers={"Host": f"{host}:{port}"})
    finally:
        with ctapp.lock:
            ctapp.state["download"], ctapp.state["report_download"] = saved
    assert resp.status == 404 and b"not an output" not in data


def test_test_mode_download_outside_outputs_is_not_served(live_server, sandboxed_user_data, tmp_path):
    host, port = live_server
    outside = tmp_path / "secret.docx"
    outside.write_bytes(b"not an output")
    with ctapp.test_lock:
        ctapp.test_state.setdefault("runs", {})["r1"] = {"download": str(outside)}
    try:
        resp, data = _raw(host, port, "GET", "/test-mode/download/r1", headers={"Host": f"{host}:{port}"})
    finally:
        with ctapp.test_lock:
            ctapp.test_state["runs"].pop("r1", None)
    assert resp.status == 404 and b"not an output" not in data


def test_output_file_accepts_only_files_in_the_outputs_folder(sandboxed_user_data, tmp_path):
    app_state.USER_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    inside = app_state.USER_OUTPUTS_DIR / "run.docx"
    inside.write_bytes(b"x")
    assert app_state.output_file(str(inside)) == inside.resolve()
    assert app_state.output_file(str(app_state.USER_OUTPUTS_DIR / ".." / "run.docx")) is None
    assert app_state.output_file(str(tmp_path / "elsewhere.docx")) is None
    assert app_state.output_file("") is None


# --- L-5: an unknown profile id never borrows another profile's layout ----

def test_page_zoom_check_ignores_an_unknown_profile(live_server, sandboxed_user_data, monkeypatch):
    host, port = live_server
    # The only other profile has a two-page layout; the old fallback lookup
    # would have reported it for the unknown id.
    profiles_store.USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    (profiles_store.USER_PROFILES_DIR / "two-pages.json").write_text(json.dumps({
        "id": "two-pages", "label": "Two Pages", "role_context": "r", "reference_context": "",
        "output_format": "", "pb_answers": {"fields": {"pageLayout": "two_facing"}},
    }), encoding="utf-8")
    seen = []

    def fake_advice(folder, file_type, model, zoom_on, page_layout):
        seen.append(page_layout)
        return {"suggest": False}

    monkeypatch.setattr(ctapp, "page_zoom_advice", fake_advice)
    query = urllib.parse.urlencode({"model": "gemini-3.1-pro-preview", "file_type": "jpeg",
                                    "profile_id": "no-such-profile"})
    resp, _ = _raw(host, port, "GET", f"/api/page-zoom-check?{query}", headers={"Host": f"{host}:{port}"})
    assert resp.status == 200 and seen == [""]


# --- L-6: bad form text and oversized profile imports ---------------------

def test_form_with_invalid_utf8_gets_a_clear_message(live_server, sandboxed_user_data):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    body = b"profile_id=\xff\xfe"
    resp, _ = _raw(host, port, "POST", "/save-profile", body=body, headers={
        "Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Cookie": _cookie_header(jar),
        "Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))})
    with ctapp.lock:
        summary = ctapp.state["summary"]
    assert resp.status in (302, 303)
    assert "isn't valid UTF-8" in summary


def test_oversized_profile_import_is_refused(live_server, sandboxed_user_data):
    """Refused from Content-Length alone, before the body is read."""
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.putrequest("POST", "/prompt-builder/import-profile", skip_host=True)
    for name, value in {
        "Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Cookie": _cookie_header(jar),
        "Content-Type": "multipart/form-data; boundary=ctboundary", "Content-Length": "2100000",
    }.items():
        conn.putheader(name, value)
    conn.endheaders()
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 400
    assert "smaller than 2 MB" in data


# --- I-1: install line pinned to the release; redirect host checked -------

def test_install_line_is_pinned_to_the_release_tag(monkeypatch):
    monkeypatch.delenv("CT_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update_check, "latest_tag", lambda: "v9.0.0")
    status = update_check.update_status("0.5.6")
    assert f"/{update_check.REPO}/v9.0.0/install-mac.sh | bash" in status["install_line"]
    assert update_check.install_line_for("main; rm -rf ~") == update_check.INSTALL_LINE


@pytest.mark.parametrize("location", [
    "https://evil.example/x/y/releases/tag/v9.0.0",
    "http://github.com/x/y/releases/tag/v9.0.0",
])
def test_redirect_off_github_is_ignored(monkeypatch, location):
    import urllib.error

    class Opener:
        def open(self, request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 302, "Found", {"Location": location}, None)

    monkeypatch.setattr(update_check.urllib.request, "build_opener", lambda *a: Opener())
    assert update_check.fetch_latest_tag() is None


# --- I-2: provider-neutral wording, key checked before a run starts --------

@pytest.mark.parametrize("path", ["/run", "/run-offpeak"])
def test_wrong_provider_key_is_refused_before_the_run_starts(live_server, sandboxed_user_data, tmp_path,
                                                             monkeypatch, path):
    import run_support

    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: folder)
    profile = ctapp.save_custom_profile("Key Check", "role", "reference", "format")
    with ctapp.lock:
        ctapp.state["running"] = False
    _post_no_redirect(host, port, jar, path, {
        "source_folder": str(folder), "gemini_api_key": "AIza-looks-like-gemini",
        "model": "claude-opus-5-5", "profile_id": profile["id"], "profile_action": "use",
        "order": "oldest", "file_type": "jpeg",
    })
    with ctapp.lock:
        running, summary = ctapp.state["running"], ctapp.state["summary"]
        ctapp.state["running"] = False
    assert not running
    assert "doesn't look like a Claude key" in summary


def test_missing_key_message_does_not_name_a_provider(live_server, sandboxed_user_data):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)
    with ctapp.lock:
        ctapp.state["running"] = False
    _post_no_redirect(host, port, jar, "/run", {"gemini_api_key": "", "model": "claude-opus-5-5"})
    with ctapp.lock:
        summary = ctapp.state["summary"]
        ctapp.state["running"] = False
    assert "Paste an API key before running transcription." in summary

