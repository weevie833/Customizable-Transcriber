"""Regression test for CODEX_REVIEW.md finding L-4: load_custom_profiles()
caught unreadable/invalid JSON, but passed any *syntactically valid* JSON
value (a bare list, null, string, or number -- not necessarily a profile
object) straight into normalize_profile_sections()'s dict-only `.get()`
calls. A single such file used to raise AttributeError and take down every
profile-dependent page instead of being skipped like a genuinely unparseable
file already was."""

from __future__ import annotations

import json

import profiles_store


def test_non_object_json_profile_is_skipped_not_fatal(sandboxed_user_data):
    good = profiles_store.save_custom_profile("Good Profile", "role", "reference", "format")

    # A syntactically valid JSON file that is not a profile object at all --
    # e.g. `[]`, `null`, or a bare string, as might result from a partial
    # migration or an external sync tool.
    (profiles_store.USER_PROFILES_DIR / "not-an-object.json").write_text("[]", encoding="utf-8")
    (profiles_store.USER_PROFILES_DIR / "also-not-an-object.json").write_text("null", encoding="utf-8")
    (profiles_store.USER_PROFILES_DIR / "bare-string.json").write_text(
        json.dumps("just a string"), encoding="utf-8"
    )

    profiles = profiles_store.load_custom_profiles()

    ids = {profile["id"] for profile in profiles}
    assert good["id"] in ids
    assert "not-an-object" not in ids
