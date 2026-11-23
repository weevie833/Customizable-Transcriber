"""reviews/CODEX_REVIEW_8.md M-13: a saved profile can't vanish from the list
(the reserved settings.json name), and running never falls back to a
different profile."""

from __future__ import annotations

import json

import pytest

import profiles_store
import run_support
from http_utils import FormData


def test_profile_named_settings_is_listed_and_loadable(sandboxed_user_data):
    saved = profiles_store.save_custom_profile("Settings", "role", "ref", "fmt")
    profiles_store.save_custom_profile("Demo", "role", "ref", "fmt")
    assert saved["id"] != "settings"
    ids = [p["id"] for p in profiles_store.load_custom_profiles()]
    assert saved["id"] in ids
    assert profiles_store.load_profile_exact(saved["id"])["label"] == "Settings"


def test_existing_genuine_settings_profile_is_recovered(sandboxed_user_data):
    profiles_store.ensure_profiles_dir()
    path = profiles_store.USER_PROFILES_DIR / "settings.json"
    path.write_text(json.dumps({"id": "settings", "label": "Settings", "role_context": "r"}))
    assert "settings" in [p["id"] for p in profiles_store.load_custom_profiles()]


def test_legacy_settings_file_is_still_skipped(sandboxed_user_data):
    profiles_store.ensure_profiles_dir()
    (profiles_store.USER_PROFILES_DIR / "settings.json").write_text(json.dumps({"selected_profile_id": "x"}))
    assert "settings" not in [p["id"] for p in profiles_store.load_custom_profiles()]


def test_corrupt_selected_profile_is_rejected_not_substituted(sandboxed_user_data):
    profiles_store.save_custom_profile("Demo", "role", "ref", "fmt")
    profiles_store.ensure_profiles_dir()
    (profiles_store.USER_PROFILES_DIR / "broken.json").write_text("{not json")
    form = FormData({"profile_id": ["broken"]})
    with pytest.raises(RuntimeError, match="valid prompt profile"):
        run_support.selected_profile_id(form)
    with pytest.raises(RuntimeError, match="damaged"):
        profiles_store.load_profile_exact("broken")
