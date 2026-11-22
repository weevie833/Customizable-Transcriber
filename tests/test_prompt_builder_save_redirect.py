"""Saving from Prompt Builder (POST /prompt-builder/save-profile) answers with a
redirect to a plain GET page, so reloading the page after a save never sends
the save again (which made a duplicate profile, or failed the request-token
check once the app had restarted)."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import profiles_store
from tests.test_prompt_builder_preflight import _get


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _save(host, port, jar, name):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)
    body = urllib.parse.urlencode(
        {
            "new_profile_name": name,
            "role_context": "role",
            "reference_context": "reference",
            "output_format": "format",
            "save_mode": "new",
        }
    ).encode()
    req = urllib.request.Request(
        f"http://{host}:{port}/prompt-builder/save-profile",
        data=body,
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def test_save_redirects_and_reload_does_not_save_again(live_server, sandboxed_user_data):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _save(host, port, jar, "Redirect Test")
    assert response.status == 303
    location = response.headers["Location"]
    assert location.startswith("/prompt-builder?saved=")
    saved = [p for p in profiles_store.load_custom_profiles() if p["label"] == "Redirect Test"]
    assert len(saved) == 1

    for _ in range(2):  # the page after the save, then a reload of it
        page = _get(host, port, location, jar).read().decode()
        assert 'Saved profile &quot;Redirect Test&quot;' in page
    assert len([p for p in profiles_store.load_custom_profiles() if p["label"] == "Redirect Test"]) == 1


def test_unknown_id_shows_no_banner(live_server, sandboxed_user_data):
    host, port = live_server
    page = _get(host, port, "/prompt-builder?saved=nope", CookieJar()).read().decode()
    assert "pb-banner-success" not in page
