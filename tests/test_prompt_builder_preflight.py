"""Regression test: Prompt Builder's Preflight Test (POST
/prompt-builder/preflight-test) runs a cheap (max_tokens=4) API-key check
before the real, much more expensive test call (a full image plus the
whole system prompt, at MEDIUM thinking) -- see app.py's
preflight_test_prompt_builder(). A bad/revoked key should fail in under a
second there instead of only surfacing after that costlier call already
ran. Exercises the real Handler on an ephemeral port (see tests/conftest.py's
live_server fixture), the same way tests/test_index_compare_http.py does,
so a future change that reorders these calls is actually caught here."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import anthropic

import app as ctapp

# Only needs to satisfy sniff_file_type()'s magic-byte check -- the real
# transcribe_image() call is never expected to run in these tests, so the
# rest of the bytes don't need to be a real, decodable image.
_FAKE_JPEG = b"\xff\xd8\xff" + b"\x00" * 32


def _get(host, port, path, cookiejar):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(f"http://{host}:{port}{path}", headers={"Host": f"{host}:{port}"})
    return opener.open(req, timeout=5)


def _multipart_body(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "----preflighttestboundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    for name, (filename, content) in files.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post_multipart(host, port, cookiejar, path, fields, files):
    body, content_type = _multipart_body(fields, files)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=body,
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": content_type},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def _preflight_fields() -> dict[str, str]:
    return {
        "example_entry": "Entry 1: a worked example.",
        "full_prompt": "Transcribe the attached image.",
        "record_type": "battesimi",
        "model": "claude-opus-5",
        "api_key": "sk-ant-not-a-real-key",
    }


def test_preflight_test_fails_fast_on_bad_key_without_the_expensive_call(live_server, monkeypatch):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    auth_error = anthropic.AuthenticationError(
        "invalid x-api-key",
        response=mock.Mock(status_code=401, headers={}),
        body={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
    )
    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(side_effect=auth_error))
    expensive_call = mock.Mock(side_effect=AssertionError("transcribe_image() should not run after a bad key"))
    monkeypatch.setattr(ctapp, "transcribe_image", expensive_call)

    response = _post_multipart(
        host,
        port,
        jar,
        "/prompt-builder/preflight-test",
        _preflight_fields(),
        {"image": ("page.jpg", _FAKE_JPEG)},
    )
    assert response.status == 400
    data = json.loads(response.read())
    assert "Anthropic rejected the API key" in data["error"]
    assert "claude-opus-5" in data["error"]
    expensive_call.assert_not_called()


def test_preflight_test_runs_the_real_call_when_the_key_check_passes(live_server, monkeypatch):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    monkeypatch.setattr(ctapp, "validate_api_key_with_retry", mock.Mock(return_value=None))
    monkeypatch.setattr(ctapp, "make_client", mock.Mock(return_value=object()))
    monkeypatch.setattr(ctapp, "transcribe_image", mock.Mock(return_value="raw transcription"))
    monkeypatch.setattr(ctapp, "critique_prompt_gap", mock.Mock(return_value=["looks good"]))

    response = _post_multipart(
        host,
        port,
        jar,
        "/prompt-builder/preflight-test",
        _preflight_fields(),
        {"image": ("page.jpg", _FAKE_JPEG)},
    )
    assert response.status == 200
    data = json.loads(response.read())
    assert data["raw_output"] == "raw transcription"
    assert data["suggestions"] == ["looks good"]
