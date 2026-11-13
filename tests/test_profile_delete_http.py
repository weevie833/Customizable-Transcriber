"""Prompt Builder's "Delete a Profile" section (POST /prompt-builder/delete-profile).
This is the only place a profile can be deleted: the Transcribe and Test
Mode pages no longer have a Delete Profile button or route."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import app as ctapp
import profiles_store
from pages.prompt_builder import prompt_builder_page
from pages.test_mode import test_mode_page as render_test_mode_page
from pages.transcribe import page as transcribe_page
from tests.test_prompt_builder_preflight import _get


def _post_json(host, port, jar, path, payload):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": "application/json"},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def _delete(live_server, profile_id):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _post_json(host, port, jar, "/prompt-builder/delete-profile", {"profile_id": profile_id})
    return response.status, json.loads(response.read())


def test_deletes_a_saved_profile(live_server, sandboxed_user_data):
    profile = ctapp.save_custom_profile("Delete Me", "role", "reference", "format")
    status, data = _delete(live_server, profile["id"])
    assert status == 200
    assert data == {"id": profile["id"], "label": "Delete Me", "still_listed": False}
    assert not profiles_store.user_profile_path(profile["id"]).exists()


def test_unknown_profile_is_an_error(live_server, sandboxed_user_data):
    status, data = _delete(live_server, "does-not-exist")
    assert status == 400
    assert "valid prompt profile" in data["error"]


def test_refused_while_a_run_is_in_progress(live_server, sandboxed_user_data):
    profile = ctapp.save_custom_profile("Busy Profile", "role", "reference", "format")
    with ctapp.test_lock:
        ctapp.test_state["running"] = True
    try:
        status, data = _delete(live_server, profile["id"])
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
    assert status == 409
    assert "in progress" in data["error"]
    assert profiles_store.user_profile_path(profile["id"]).exists()


def test_deleting_a_users_copy_of_a_shipped_example_reports_the_original_is_back(
    live_server, sandboxed_user_data
):
    shipped = profiles_store.PROFILES_DIR / "example.json"
    shipped.write_text(json.dumps({"id": "example", "label": "Example", "role_context": "r"}))
    profiles_store.write_profile({"id": "example", "label": "My Example", "role_context": "mine"})
    status, data = _delete(live_server, "example")
    assert status == 200
    assert data["still_listed"] is True
    assert shipped.exists()


def test_only_user_profiles_are_offered_for_deletion(sandboxed_user_data):
    (profiles_store.PROFILES_DIR / "example.json").write_text(
        json.dumps({"id": "example", "label": "Example", "role_context": "r"})
    )
    mine = ctapp.save_custom_profile("Mine", "role", "reference", "format")
    html_text = prompt_builder_page()
    delete_select = html_text.split('id="pb-delete-select"')[1].split("</select>")[0]
    assert f'value="{mine["id"]}"' in delete_select
    assert 'value="example"' not in delete_select
    # The section sits above Import/Export.
    assert html_text.index('id="pb-delete-section"') < html_text.index('id="pb-import-export-section"')


def test_transcribe_and_test_mode_pages_have_no_delete_button(sandboxed_user_data):
    ctapp.save_custom_profile("Any", "role", "reference", "format")
    assert "profile-delete-button" not in transcribe_page()
    assert "profile-delete-button" not in render_test_mode_page()
