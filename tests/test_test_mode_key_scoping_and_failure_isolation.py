"""Regression tests for CODEX_REVIEW.md finding M-5 / HUMAN_DECISIONS.md's
resolution:

1. Test Mode API keys are now scoped by provider (one Gemini field, one
   Claude field), not by A/B slot -- a queue that mixes providers across
   batches (or within one batch's own A/B pair) is satisfiable with just
   the two provider fields, and only the provider(s) actually in use need
   a key filled in at all.
2. run_test_job()'s per-run loop now isolates each run's own failure --
   one run's setup/validation/batch failure no longer aborts every run
   still queued after it, matching the function's own documented
   independence guarantee.
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from http.cookiejar import Cookie, CookieJar

import app as ctapp
import handlers.test_mode_run as test_mode_handlers
import run_support


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


def _get_status(host: str, port: int, jar: CookieJar) -> dict:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(
        "GET", "/test-mode/status", headers={"Host": f"{host}:{port}", "Cookie": _cookie_header(jar)}
    )
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return data


def test_mixed_provider_queue_requires_only_the_providers_in_use(
    live_server, sandboxed_user_data, tmp_path, monkeypatch
):
    host, port = live_server
    jar = _get_csrf_cookie(host, port)

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(test_mode_handlers, "load_source_folder", lambda: source_folder)

    captured_specs = []
    done_event = threading.Event()

    def fake_run_test_job(form, run_specs):
        captured_specs.append(run_specs)
        done_event.set()

    monkeypatch.setattr(test_mode_handlers, "run_test_job", fake_run_test_job)

    profile = ctapp.save_custom_profile("Mixed Queue Profile", "role", "reference", "format")

    # A queue with one all-Gemini batch and one all-Claude batch -- exactly
    # the scenario one shared A/B-slot key pair couldn't satisfy before.
    with ctapp.test_lock:
        ctapp.test_state["running"] = False
        ctapp.test_state["queue"] = [
            {
                "batch_id": "batch-gemini",
                "label": "Gemini Batch",
                "model_a": "gemini-3.1-pro-preview",
                "model_b": "gemini-2.5-pro",
            },
            {
                "batch_id": "batch-claude",
                "label": "Claude Batch",
                "model_a": "claude-opus-5",
                "model_b": "claude-sonnet-5",
            },
        ]

    base_fields = {
        "profile_id": profile["id"],
        "profile_action": "use",
        "order": "oldest",
        "file_type": "jpeg",
        "model_a": "gemini-3.1-pro-preview",
        "model_b": "gemini-3.1-pro-preview",
    }

    try:
        # Missing the Claude key entirely -- must fail with a clear,
        # provider-specific error naming Claude, not the old blanket
        # "paste an API key for both Model A and Model B".
        response = _post_no_redirect(
            host, port, jar, "/test-mode/run", {**base_fields, "api_key_gemini": "fake-gemini-key"}
        )
        assert response.status == 303
        status = _get_status(host, port, jar)
        assert "Claude" in status["summary"]
        assert not captured_specs

        # Both keys provided -- must succeed and route each run to the
        # right provider's key, regardless of which A/B slot it's in.
        response = _post_no_redirect(
            host,
            port,
            jar,
            "/test-mode/run",
            {**base_fields, "api_key_gemini": "fake-gemini-key", "api_key_claude": "sk-ant-fake-claude-key"},
        )
        assert response.status == 303
        assert done_event.wait(timeout=2)
        assert len(captured_specs) == 1
        keys_by_model = {model: key for (_run_id, _label, model, key, _md, _out) in captured_specs[0]}
        assert keys_by_model["gemini-3.1-pro-preview"] == "fake-gemini-key"
        assert keys_by_model["gemini-2.5-pro"] == "fake-gemini-key"
        assert keys_by_model["claude-opus-5"] == "sk-ant-fake-claude-key"
        assert keys_by_model["claude-sonnet-5"] == "sk-ant-fake-claude-key"
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
            ctapp.test_state["queue"] = []


def test_one_run_failure_does_not_abort_the_rest_of_the_queue(sandboxed_user_data, tmp_path, monkeypatch):
    profile = ctapp.save_custom_profile("Failure Isolation Profile", "role", "reference", "format")

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source_folder)

    call_count = {"n": 0}

    def flaky_validate(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("bad key")

    monkeypatch.setattr(run_support, "validate_api_key_with_retry", flaky_validate)

    def fake_run_batch(config, project_dir, progress=None, cancel_requested=None):
        config.output_file.parent.mkdir(parents=True, exist_ok=True)
        config.output_file.write_text("Some transcription text.", encoding="utf-8")
        return []

    monkeypatch.setattr(run_support, "run_batch", fake_run_batch)

    run_1_id, run_2_id = "run-1", "run-2"
    with ctapp.test_lock:
        ctapp.test_state["running"] = True
        ctapp.test_state["runs"] = {
            run_1_id: ctapp.new_test_run_state(),
            run_2_id: ctapp.new_test_run_state(),
        }

    run_specs = [
        (run_1_id, "Run 1", "gemini-2.5-pro", "fake-key", tmp_path / "run1.md", tmp_path / "run1.docx"),
        (run_2_id, "Run 2", "gemini-2.5-pro", "fake-key", tmp_path / "run2.md", tmp_path / "run2.docx"),
    ]

    form = ctapp.FormData(
        {
            "profile_id": [profile["id"]],
            "profile_action": ["use"],
            "order": ["oldest"],
            "file_type": ["jpeg"],
        }
    )

    try:
        ctapp.run_test_job(form, run_specs)

        run_1_state = ctapp.test_state["runs"][run_1_id]
        run_2_state = ctapp.test_state["runs"][run_2_id]

        # Run 1's own failure is recorded against run 1 only...
        assert "Failed" in run_1_state["summary"]
        assert run_1_state["download"] == ""

        # ...and run 2, queued after it, still completed normally instead of
        # being aborted by run 1's exception.
        assert run_2_state["download"] != ""
        assert "Processed" in run_2_state["summary"]

        # The whole job is not reported as one blanket fatal error.
        assert "Fatal error" not in ctapp.test_state["summary"]
        assert "1 failed" in ctapp.test_state["summary"]
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
