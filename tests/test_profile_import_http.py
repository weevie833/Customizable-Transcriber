"""An imported profile must be loadable into Prompt Builder without a page
reload. The page's loader reads answers only from window.PB_SAVED_PROFILES,
which the server fills at page load, so the import response has to send the
imported profile's pb_answers back for the page to add. Before this, choosing
a just-imported profile left most questionnaire fields blank."""

from __future__ import annotations

import json
from http.cookiejar import CookieJar

import pytest

from tests.test_prompt_builder_preflight import _get, _post_multipart

pytestmark = pytest.mark.usefixtures("sandboxed_user_data")

PB_ANSWERS = {
    "fields": {"recordType": "morti", "locality": "Rende", "nameLexiconSurnames": "Apa\nBova"},
    "checked": {"latinDeclension": ["on"]},
    "rows": {"pb-example-rows": [{"0": "Image 71", "1": "Anno Domini 1763 ..."}]},
}


def _export_file(pb_answers):
    return json.dumps({
        "format": "customizable-transcription-profile",  # an older app name's format id
        "format_version": 1,
        "profile": {
            "label": "Church Morti draft",
            "role_context": "role",
            "reference_context": "reference",
            "output_format": "format",
            "record_type": "morti",
            "pb_answers": pb_answers,
        },
    }).encode()


def _import(live_server, file_bytes):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _post_multipart(
        host, port, jar, "/prompt-builder/import-profile", {}, {"file": ("p.tbprofile.json", file_bytes)}
    )
    return response.status, json.loads(response.read())


def test_import_returns_the_answers_the_page_needs_to_load_it(live_server):
    status, data = _import(live_server, _export_file(PB_ANSWERS))
    assert status == 200
    assert data["has_pb_answers"] is True
    assert data["pb_answers"] == PB_ANSWERS


def test_import_without_answers_returns_none(live_server):
    status, data = _import(live_server, _export_file(None))
    assert status == 200
    assert data["has_pb_answers"] is False
    assert data["pb_answers"] is None
