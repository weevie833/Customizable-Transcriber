"""Regression test for CODEX_REVIEW.md finding M-4: two near-simultaneous
save_custom_profile() calls for the same name could both see the same
available auto-suffixed id as free (each checking find_profile_path()
independently) and race to write it -- one profile's content silently lost
even though the caller believed both saves succeeded. profiles_store.py now
serializes id allocation and every profile mutation through one
process-local lock, closing the check-then-write window this test widens
with an artificial delay: on the fixed code the delay only adds latency
(the lock keeps the two calls fully serialized), but the same delay would
reliably reproduce the collision if the lock were ever removed, since both
threads would then be free to run their own "is this id free?" check before
either had written its file."""

from __future__ import annotations

import threading
import time

import profiles_store


def test_concurrent_creates_with_same_name_never_collide_on_one_id(
    sandboxed_user_data, monkeypatch
):
    real_find_profile_path = profiles_store.find_profile_path

    def slow_find_profile_path(profile_id):
        result = real_find_profile_path(profile_id)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(profiles_store, "find_profile_path", slow_find_profile_path)

    results = []

    def create():
        try:
            results.append(profiles_store.save_custom_profile("Race Profile", "role", "ref", "fmt"))
        except Exception as exc:  # noqa: BLE001 -- captured for the assertion below
            results.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 2
    assert all(isinstance(result, dict) for result in results), results

    ids = {result["id"] for result in results}
    # The whole point of the fix: two distinct ids, two distinct files on
    # disk -- never both threads landing on "race-profile" and one save
    # silently overwriting the other's file.
    assert len(ids) == 2
    for profile_id, result in zip((r["id"] for r in results), results):
        path = profiles_store.find_profile_path(profile_id)
        assert path is not None
        saved = profiles_store.load_profile(profile_id)
        assert saved["label"] == result["label"] == "Race Profile"
