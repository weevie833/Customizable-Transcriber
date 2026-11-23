"""reviews/CODEX_REVIEW_8.md L-5: a preflight approval covers the language
role too, and conversion refuses marker overrides preflight never saw."""

from __future__ import annotations

import pytest

import handlers.xls_conversion as xls

BASE = dict(record_type="battesimi", text="T", image_range="1", model="gemini-3.1-pro-preview",
            target_language="English", process_all=False)


def test_changing_role_invalidates_preflight():
    token = xls.save_xls_preflight({"ok": True}, *BASE.values(), "translation")
    xls.validate_xls_preflight(token=token, ignore_failure=False, target_role="Translation", **BASE)
    with pytest.raises(RuntimeError, match="changed"):
        xls.validate_xls_preflight(token=token, ignore_failure=False, target_role="transcription", **BASE)


def test_marker_overrides_are_refused(live_server):
    import json
    import urllib.request
    from http.cookiejar import CookieJar

    from tests.test_post_redirect_get import _get_csrf_cookie

    host, port = live_server
    jar: CookieJar = _get_csrf_cookie(host, port)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({**BASE, "gemini_api_key": "AIzaFake", "image_overrides": "X=1", "target_role": "translation"})
    request = urllib.request.Request(
        f"http://{host}:{port}/api/xls-conversion/parse", data=body.encode(), method="POST",
        headers={"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(request, timeout=5)
    assert "overrides" in json.loads(caught.value.read())["error"]


# CODEX_REVIEW_2.md L-5: one canonical role from the request boundary on, so
# an approval for "transcription" and a conversion sent as "Transcription"
# both extract with the transcription instruction; unknown roles are refused.

@pytest.mark.parametrize("raw, expected", [
    ("transcription", "transcription"), ("Transcription", "transcription"),
    (" TRANSLATION ", "translation"),
])
def test_role_is_canonicalized(raw, expected):
    from xls_conversion.ai_parser import canonical_target_role
    assert canonical_target_role(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "notes", "transcriptions"])
def test_unknown_role_is_refused(raw):
    from xls_conversion.ai_parser import canonical_target_role
    with pytest.raises(RuntimeError, match="language role"):
        canonical_target_role(raw)


def _post_json(live_server, path, payload):
    import json
    import urllib.error
    import urllib.request

    from tests.test_post_redirect_get import _get_csrf_cookie

    host, port = live_server
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_get_csrf_cookie(host, port)))
    request = urllib.request.Request(
        f"http://{host}:{port}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}", "Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_case_variant_role_converts_with_the_approved_instruction(live_server, monkeypatch):
    from xls_conversion import ai_parser

    text = "--- START OF RECORD: reg_001.jpg ---\n\nEntry text\n"
    prompts: list[str] = []
    monkeypatch.setattr(xls, "validate_api_key_with_retry", lambda *a, **k: None)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    monkeypatch.setattr(
        ai_parser, "call_ai_json",
        lambda api_key, model, system_prompt, message, *a, **k: prompts.append(system_prompt + "\n" + message) or {"records": []},
    )
    settings = dict(record_type="civil_death", text=text, image_range="1",
                    model="gemini-3.1-pro-preview", target_language="Italian", process_all=False)
    token = xls.save_xls_preflight({"ok": True}, *settings.values(), "transcription")
    status, _body = _post_json(live_server, "/api/xls-conversion/parse", {
        **settings, "gemini_api_key": "AIzaFake", "target_role": "Transcription", "preflight_token": token,
    })
    assert prompts, (status, _body)
    assert all("no separate translation" in prompt for prompt in prompts)
    assert not any("Extract facts from the Italian translation" in prompt for prompt in prompts)


def test_unknown_role_is_refused_before_any_provider_call(live_server, monkeypatch):
    from xls_conversion import ai_parser

    monkeypatch.setattr(xls, "validate_api_key_with_retry", lambda *a, **k: pytest.fail("checked key"))
    monkeypatch.setattr(ai_parser, "call_ai_json", lambda *a, **k: pytest.fail("called provider"))
    status, body = _post_json(live_server, "/api/xls-conversion/preflight", {
        **BASE, "gemini_api_key": "AIzaFake", "target_role": "notes",
    })
    assert status == 400 and "language role" in body["error"]
