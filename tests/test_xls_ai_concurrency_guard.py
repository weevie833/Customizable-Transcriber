"""Regression test for CODEX_REVIEW.md finding M-2 / HUMAN_DECISIONS.md's
resolution: XLS Conversion's AI-backed endpoints (Parse, Preflight, Detect
Languages) previously had no concurrency guard at all -- two requests could
run real, expensive AI batches at the same time with no server-side limit.
xls_ai_lock now rejects a second such request with a clear 409 while one is
still in flight, and this is a single shared lock across all three
endpoints (not one per endpoint), so a slow request to one of them blocks a
concurrent request to any of the others too."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.cookiejar import CookieJar


def _request(host, port, method, path, headers=None, body=None, cookiejar=None):
    jar = cookiejar if cookiejar is not None else CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def _post_json(host, port, jar, path, payload):
    body = json.dumps(payload).encode("utf-8")
    return _request(
        host,
        port,
        "POST",
        path,
        headers={
            "Host": f"{host}:{port}",
            "Content-Type": "application/json",
            "Origin": f"http://{host}:{port}",
        },
        body=body,
        cookiejar=jar,
    )


def test_concurrent_xls_ai_requests_across_different_endpoints_are_rejected(live_server, monkeypatch):
    import app as ctapp

    host, port = live_server
    jar = CookieJar()
    _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"}, cookiejar=jar)

    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", lambda *args, **kwargs: None)

    slow_call_started = threading.Event()
    release_slow_call = threading.Event()

    def slow_detect_languages(**kwargs):
        slow_call_started.set()
        release_slow_call.wait(timeout=5)
        return {"languages": []}

    monkeypatch.setattr(ctapp, "detect_languages", slow_detect_languages)
    monkeypatch.setattr(
        ctapp,
        "preflight_records_with_ai",
        lambda **kwargs: {"ok": True, "entries": [], "issues": [], "reviewed_images": []},
    )

    results = []

    def fire_slow_request():
        results.append(
            _post_json(
                host,
                port,
                jar,
                "/api/xls-conversion/detect-languages",
                {"model": "gemini-2.5-pro", "gemini_api_key": "fake-key", "text": "some text", "image_range": ""},
            )
        )

    thread = threading.Thread(target=fire_slow_request)
    thread.start()
    assert slow_call_started.wait(timeout=2)

    try:
        # A *different* endpoint, while the slow one is still in flight --
        # the lock is shared across all three, not per-endpoint.
        blocked_response = _post_json(
            host,
            port,
            jar,
            "/api/xls-conversion/preflight",
            {
                "model": "gemini-2.5-pro",
                "gemini_api_key": "fake-key",
                "record_type": "battesimi",
                "text": "some text",
                "image_range": "1",
                "target_language": "English",
                "target_role": "translation",
            },
        )
        assert blocked_response.status == 409
        blocked_payload = json.loads(blocked_response.read())
        assert "already running" in blocked_payload["error"]
    finally:
        release_slow_call.set()
        thread.join(timeout=5)

    # Once the slow request finishes and releases the lock, a new request
    # succeeds normally.
    followup_response = _post_json(
        host,
        port,
        jar,
        "/api/xls-conversion/preflight",
        {
            "model": "gemini-2.5-pro",
            "gemini_api_key": "fake-key",
            "record_type": "battesimi",
            "text": "some text",
            "image_range": "1",
            "target_language": "English",
            "target_role": "translation",
        },
    )
    assert followup_response.status == 200

    assert len(results) == 1
    assert results[0].status == 200
