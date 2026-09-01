"""Regression test for the /run and /test-mode/run TOCTOU race -- see
CLAUDE.md's review notes on "concurrent run requests can start duplicate
jobs and overwrite output." Reproduces the actual race at the HTTP layer
(two real concurrent POST requests against the real Handler) rather than
unit-testing the reservation logic in isolation, since the bug was
specifically that code moved outside the lock -- a refactor that
reintroduces that would only be caught by exercising the real endpoint."""

from __future__ import annotations

import threading
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import app as ctapp


def _get(host, port, path, cookiejar, timeout=5):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(f"http://{host}:{port}{path}", headers={"Host": f"{host}:{port}"})
    return opener.open(req, timeout=timeout)


def _post(host, port, cookiejar, path, form_fields, timeout=5):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    body = urllib.parse.urlencode(form_fields).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=body,
        method="POST",
        headers={
            "Host": f"{host}:{port}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    return opener.open(req, timeout=timeout)


def _post_run(host, port, cookiejar, form_fields):
    return _post(host, port, cookiejar, "/run", form_fields)


def test_two_concurrent_run_requests_only_start_one_job(live_server, sandboxed_user_data, tmp_path, monkeypatch):
    host, port = live_server

    # A real source folder with one real jpeg in it, so
    # preflight_source_file_type() passes without needing to be mocked.
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(ctapp, "load_source_folder", lambda: source_folder)

    profile = ctapp.save_custom_profile("Race Test Profile", "role", "reference", "format")

    # run_job() is what actually calls the AI provider -- stubbed out here so
    # this test exercises only the reservation race, not a real network call.
    # It holds state["running"] True for a short, controlled window so a
    # second concurrent request has something to race against.
    run_job_calls = []
    run_job_started = threading.Event()

    def fake_run_job(form, output_file):
        run_job_calls.append(output_file)
        run_job_started.set()
        time.sleep(0.4)
        with ctapp.lock:
            ctapp.state["running"] = False

    monkeypatch.setattr(ctapp, "run_job", fake_run_job)

    with ctapp.lock:
        ctapp.state["running"] = False

    jar = CookieJar()
    _get(host, port, "/", jar)  # obtain the CSRF cookie, as a real browser would

    form_fields = {
        "gemini_api_key": "fake-key-for-test",
        "profile_id": profile["id"],
        "profile_action": "use",
        "order": "oldest",
        "file_type": "jpeg",
    }

    results = []

    def fire():
        try:
            response = _post_run(host, port, jar, form_fields)
            results.append(response.status)
        except Exception as exc:  # noqa: BLE001 -- capture for assertion below
            results.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert run_job_started.wait(timeout=2)
    # The whole point of the fix: no matter how the two requests interleaved,
    # exactly one of them must have actually reserved the run slot and
    # started a job -- never zero, never two.
    assert len(run_job_calls) == 1

    # Let the stubbed job finish and clear "running" before the fixture tears
    # the server down, so this test doesn't leak state into a later one.
    time.sleep(0.5)
    with ctapp.lock:
        ctapp.state["running"] = False


def test_busy_endpoints_respond_promptly_instead_of_deadlocking(live_server, sandboxed_user_data):
    """Distinct bug from the race above, found while writing that test: six
    handlers (/run, /delete-profile, /test-mode/run, /test-mode/queue/add,
    /test-mode/queue/remove, /test-mode/delete-profile) used to call
    page()/test_mode_page() -- which each acquire `lock`/`test_lock`
    themselves -- from *inside* the same `with lock:`/`with test_lock:`
    block already held for the "is a job already running" check. Since
    threading.Lock is not reentrant, hitting any of these while a job was
    running deadlocked that request's handler thread forever (reproduced:
    it never returned even after a 5s client-side timeout). Exercises
    /delete-profile as the representative case."""
    host, port = live_server
    # page() (called by the "still running" response path) looks up the
    # currently-selected profile unconditionally -- needs at least one to
    # exist, independent of what this test is actually exercising.
    ctapp.save_custom_profile("Deadlock Test Profile", "role", "reference", "format")
    with ctapp.lock:
        ctapp.state["running"] = True
    try:
        jar = CookieJar()
        _get(host, port, "/", jar)
        # A short client timeout: if the deadlock regresses, this raises
        # TimeoutError instead of returning -- that failure mode is exactly
        # what this test exists to catch.
        response = _post(host, port, jar, "/delete-profile", {"profile_id": "does-not-matter"}, timeout=3)
        assert response.status == 200
    finally:
        with ctapp.lock:
            ctapp.state["running"] = False
