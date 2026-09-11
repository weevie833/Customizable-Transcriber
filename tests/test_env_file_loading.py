"""Regression tests for CODEX_REVIEW.md finding L-3: load_env_file() used to
copy every KEY=value line in .env into os.environ (not just the two
provider keys this app documents/uses) and always overwrote an
already-exported value. Both behaviors are fixed: only GEMINI_API_KEY/
ANTHROPIC_API_KEY are ever copied, and an existing environment value always
wins over the .env file, matching python-dotenv's own default."""

from __future__ import annotations

import pytest

import customizable_transcription.core as core


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SOME_UNRELATED_VAR", raising=False)
    monkeypatch.delenv("PATH_OVERRIDE_ATTEMPT", raising=False)


def test_only_documented_keys_are_copied(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=real-gemini-key\n"
        "SOME_UNRELATED_VAR=should-not-be-copied\n"
        "PATH_OVERRIDE_ATTEMPT=/malicious/bin\n",
        encoding="utf-8",
    )

    core.load_env_file(env_file)

    import os

    assert os.environ.get("GEMINI_API_KEY") == "real-gemini-key"
    assert "SOME_UNRELATED_VAR" not in os.environ
    assert "PATH_OVERRIDE_ATTEMPT" not in os.environ


def test_existing_environment_value_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "already-exported-key")
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=from-dotenv-file\n", encoding="utf-8")

    core.load_env_file(env_file)

    import os

    assert os.environ.get("GEMINI_API_KEY") == "already-exported-key"


def test_missing_env_file_is_a_no_op(tmp_path):
    core.load_env_file(tmp_path / "does-not-exist.env")
    import os

    assert "GEMINI_API_KEY" not in os.environ
