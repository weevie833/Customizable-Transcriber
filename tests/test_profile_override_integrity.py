"""CODEX_REVIEW_2.md M-13: a damaged user copy of a shipped profile must be
reported, never silently replaced by the shipped instructions, and a profile
file with invalid UTF-8 must not break the profile list."""

from __future__ import annotations

import json

import pytest

import profiles_store


@pytest.fixture
def stores(tmp_path, monkeypatch):
    shipped, user = tmp_path / "shipped", tmp_path / "user"
    shipped.mkdir()
    user.mkdir()
    monkeypatch.setattr(profiles_store, "PROFILES_DIR", shipped)
    monkeypatch.setattr(profiles_store, "USER_PROFILES_DIR", user)
    monkeypatch.setattr(profiles_store, "ensure_profiles_dir", lambda: None)
    (shipped / "demo-v1.json").write_text(json.dumps(
        {"id": "demo-v1", "label": "Demo", "role_context": "SHIPPED INSTRUCTIONS"}
    ))
    return shipped, user


@pytest.mark.parametrize("damage", [b"{not json", b"[]", b"\xff\xfe\x00bad-utf8"])
def test_damaged_override_is_reported_not_replaced(stores, damage):
    _shipped, user = stores
    (user / "demo-v1.json").write_bytes(damage)
    with pytest.raises(RuntimeError, match="your saved copy is damaged"):
        profiles_store.load_profile_exact("demo-v1")
    ids = [profile["id"] for profile in profiles_store.load_custom_profiles()]
    assert "demo-v1" not in ids  # the shipped copy isn't offered under the overridden id


def test_valid_override_wins(stores):
    _shipped, user = stores
    (user / "demo-v1.json").write_text(json.dumps({"id": "demo-v1", "label": "Mine", "role_context": "MINE"}))
    assert profiles_store.load_profile_exact("demo-v1")["role_context"] == "MINE"


def test_shipped_profile_without_override_loads(stores):
    assert profiles_store.load_profile_exact("demo-v1")["role_context"] == "SHIPPED INSTRUCTIONS"


def test_invalid_utf8_profile_does_not_break_listing(stores):
    _shipped, user = stores
    (user / "other.json").write_bytes(b"\xff\xfe broken")
    (user / "fine.json").write_text(json.dumps({"id": "fine", "label": "Fine"}))
    ids = [profile["id"] for profile in profiles_store.load_custom_profiles()]
    assert ids == ["demo-v1", "fine"]
    assert [p["id"] for p in profiles_store.profiles_with_display_labels()] == ["demo-v1", "fine"]
