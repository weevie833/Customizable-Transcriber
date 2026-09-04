"""Regression test for a real reported bug: after clicking Run, a hard
reload (Cmd+Shift+R/Ctrl+Shift+R) silently resubmitted the exact same POST
/run request -- with no confirmation prompt -- starting a second,
unintended transcription batch.

Root cause: every state-changing POST handler in app.py used to respond
with a direct 200 HTML render (self.respond(page())/self.respond(
test_mode_page())) instead of the standard POST/Redirect/GET pattern. That
makes the *POST request itself* the browser's history entry for that
navigation, and reloading a POST history entry either prompts to resubmit
(a plain reload) or -- confirmed live in a real browser during
investigation -- resubmits silently with no prompt at all on a hard
reload. Fixed by redirecting (303 See Other) to the corresponding GET page
after every state change, using the redirect_transcribe()/
redirect_test_mode() helpers that already existed for this exact purpose
(reset()/reset_test() already used them; this closes the same gap on
every other handler that didn't).

This test doesn't drive a real browser (no reload-resubmission behavior to
exercise at the HTTP layer) -- it instead asserts the actual fix directly:
every one of these endpoints must respond with a 303 and a same-origin
Location header, never a 200 HTML body, which is what makes the browser's
history entry a GET and a reload of it harmless regardless of how any
particular browser handles POST resubmission.
"""

from __future__ import annotations

import http.client
import urllib.parse
from http.cookiejar import Cookie, CookieJar

import app as ctapp


def _cookie_header(jar: CookieJar) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in jar)


def _get_csrf_cookie(host: str, port: int) -> CookieJar:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/", headers={"Host": f"{host}:{port}"})
    resp = conn.getresponse()
    resp.read()
    jar = CookieJar()
    for header in resp.msg.get_all("Set-Cookie", []):
        name_value = header.split(";", 1)[0]
        name, _, value = name_value.partition("=")
        jar.set_cookie(
            Cookie(0, name, value, None, False, host, False, False, "/", False, False, None, True, None, None, {})
        )
    conn.close()
    return jar


def _post_no_redirect(host: str, port: int, jar: CookieJar, path: str, fields: dict[str, str]):
    """POSTs without following any redirect, so the response actually
    returned by the handler under test can be inspected directly."""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(
        "POST",
        path,
        body=body,
        headers={
            "Host": f"{host}:{port}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": _cookie_header(jar),
            "Origin": f"http://{host}:{port}",
        },
    )
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp


def test_run_redirects_instead_of_rendering_html(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    """Covers both the success path and the validation-error path (no API
    key) against one shared live_server instance -- each live_server spins
    up a real ThreadingHTTPServer, and this whole file already adds several
    of those on top of the rest of the suite's; folding two closely related
    /run scenarios into one test keeps that count down rather than doubling
    it for no real gain in coverage."""
    host, port = live_server
    jar = _get_csrf_cookie(host, port)

    # Error path first (no API key) -- doesn't touch state["running"] at
    # all, so no cleanup needed before the success path below reuses the
    # same server/state.
    response = _post_no_redirect(host, port, jar, "/run", {"profile_id": "", "order": "oldest", "file_type": "jpeg"})
    assert response.status == 303
    assert response.getheader("Location") == "/transcribe"

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(ctapp, "load_source_folder", lambda: source_folder)
    monkeypatch.setattr(ctapp, "run_job", lambda form, output_file: None)

    profile = ctapp.save_custom_profile("Redirect Test Profile", "role", "reference", "format")
    try:
        response = _post_no_redirect(
            host,
            port,
            jar,
            "/run",
            {
                "gemini_api_key": "fake-key-for-test",
                "profile_id": profile["id"],
                "profile_action": "use",
                "order": "oldest",
                "file_type": "jpeg",
            },
        )
        assert response.status == 303
        assert response.getheader("Location") == "/transcribe"
    finally:
        with ctapp.lock:
            ctapp.state["running"] = False


def test_test_mode_run_redirects_instead_of_rendering_html(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(ctapp, "load_source_folder", lambda: source_folder)
    monkeypatch.setattr(ctapp, "run_test_job", lambda form, run_specs: None)

    profile = ctapp.save_custom_profile("Redirect Test Mode Profile", "role", "reference", "format")
    try:
        response = _post_no_redirect(
            host,
            port,
            jar,
            "/test-mode/run",
            {
                "api_key_a": "fake-key-a",
                "api_key_b": "fake-key-b",
                "profile_id": profile["id"],
                "profile_action": "use",
                "order": "oldest",
                "file_type": "jpeg",
                "model_a": "gemini-3.1-pro-preview",
                "model_b": "gemini-3.1-pro-preview",
            },
        )
        assert response.status == 303
        assert response.getheader("Location") == "/test-mode"
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False


def test_delete_profile_stop_and_queue_endpoints_redirect(live_server, sandboxed_user_data):
    """Every other state-changing POST handler that had the same
    respond(page())/respond(test_mode_page())-after-POST anti-pattern --
    lower-stakes than /run (no AI batch), but a resubmitted delete/stop/
    queue-edit on reload is still an unintended action a 303 prevents."""
    host, port = live_server
    jar = _get_csrf_cookie(host, port)

    profile = ctapp.save_custom_profile("Delete Redirect Test Profile", "role", "reference", "format")

    cases = [
        ("/delete-profile", {"profile_id": profile["id"]}, "/transcribe"),
        ("/stop", {}, "/transcribe"),
        ("/test-mode/queue/add", {"model_a": "gemini-3.1-pro-preview", "model_b": "gemini-3.1-pro-preview"}, "/test-mode"),
        ("/test-mode/queue/remove", {"batch_id": "does-not-exist"}, "/test-mode"),
        ("/test-mode/stop", {}, "/test-mode"),
        ("/test-mode/delete-profile", {"profile_id": "does-not-exist"}, "/test-mode"),
    ]
    for path, fields, expected_location in cases:
        response = _post_no_redirect(host, port, jar, path, fields)
        assert response.status == 303, f"{path} returned {response.status}, expected 303"
        assert response.getheader("Location") == expected_location, path
