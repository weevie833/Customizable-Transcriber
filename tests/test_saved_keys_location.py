"""reviews/CODEX_REVIEW_8.md L-4 (maintainer chose the user-data folder):
opted-in saved API keys live in the per-user data folder, which app updates
never replace. The app reads that file first and the app folder's second,
an exported variable still wins, the app copies an old app-folder file
across once (owner-only, never overwriting), and both Mac update scripts do
the same before replacing the installed copy."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import profiles_store
from customizable_transcriber import core

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    data, app = tmp_path / "data", tmp_path / "app"
    data.mkdir()
    app.mkdir()
    monkeypatch.setattr(profiles_store, "USER_DATA_DIR", data)
    monkeypatch.setattr(profiles_store, "PROJECT_DIR", app)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return data, app


def test_user_data_file_is_read_before_app_folder(dirs):
    data, app = dirs
    (data / ".env").write_text("GEMINI_API_KEY=from-user-data\n", encoding="utf-8")
    (app / ".env").write_text("GEMINI_API_KEY=from-app\nANTHROPIC_API_KEY=sk-ant-from-app\n", encoding="utf-8")
    assert core.api_key(app) == "from-user-data"
    assert core.claude_api_key(app) == "sk-ant-from-app"  # falls back per key


def test_exported_variable_still_wins(dirs, monkeypatch):
    data, app = dirs
    (data / ".env").write_text("GEMINI_API_KEY=from-user-data\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "exported")
    assert core.api_key(app) == "exported"


def test_startup_copies_app_folder_file_once_owner_only(dirs):
    data, app = dirs
    (app / ".env").write_text("GEMINI_API_KEY=k\n", encoding="utf-8")
    profiles_store.migrate_saved_keys_file()
    assert (data / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=k\n"
    assert (app / ".env").exists()  # original left alone
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(data / ".env").st_mode) == 0o600

    (app / ".env").write_text("GEMINI_API_KEY=changed\n", encoding="utf-8")
    profiles_store.migrate_saved_keys_file()
    assert (data / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=k\n"  # never overwritten


def _helpers(text: str) -> str:
    return "".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M).group(0)
        for name in ("saved_key_line", "keep_saved_keys")
    )


@pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")
@pytest.mark.parametrize("script", ["install-mac.sh", "mac/launcher.sh"])
def test_mac_update_scripts_carry_saved_keys_over(script, tmp_path):
    text = (ROOT / script).read_text(encoding="utf-8")
    helper = _helpers(text)
    app, data = tmp_path / "App", tmp_path / "data"
    app.mkdir()
    (app / ".env").write_text("GEMINI_API_KEY=k\n", encoding="utf-8")
    env = {**os.environ, "CT_DATA_DIR": str(data)}
    script_text = helper + 'keep_saved_keys "$1"\n'
    subprocess.run(["bash", "-c", script_text, "_", str(app)], check=True, env=env)
    assert (data / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=k\n"
    assert stat.S_IMODE(os.stat(data / ".env").st_mode) == 0o600

    (app / ".env").write_text("GEMINI_API_KEY=changed\n", encoding="utf-8")
    subprocess.run(["bash", "-c", script_text, "_", str(app)], check=True, env=env)
    assert (data / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=k\n"
    assert 'keep_saved_keys "$app_dir"' in text  # called before the copy is replaced


# CODEX_REVIEW_2.md L-4: keys split across the two files (Gemini in the
# user-data file, Claude only in the app folder) must survive replacement of
# the app folder, without changing anything already in the user-data file.

SPLIT_USER = "GEMINI_API_KEY=gem-user\n"
SPLIT_APP = "# saved keys\nGEMINI_API_KEY=gem-app\nANTHROPIC_API_KEY='sk-ant-app'\n"


def _effective_keys(data_dir: Path, app_dir: Path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr(profiles_store, "USER_DATA_DIR", data_dir)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return core.api_key(app_dir), core.claude_api_key(app_dir)


def test_startup_copier_merges_a_key_only_the_app_folder_had(dirs, monkeypatch):
    data, app = dirs
    (data / ".env").write_text(SPLIT_USER.rstrip("\n"), encoding="utf-8")  # no trailing newline
    (app / ".env").write_text(SPLIT_APP, encoding="utf-8")
    profiles_store.migrate_saved_keys_file()
    text = (data / ".env").read_text(encoding="utf-8")
    assert text == "GEMINI_API_KEY=gem-user\nANTHROPIC_API_KEY='sk-ant-app'\n"
    (app / ".env").unlink()  # the app folder is replaced
    assert _effective_keys(data, app, monkeypatch) == ("gem-user", "sk-ant-app")
    profiles_store.migrate_saved_keys_file()  # idempotent
    assert (data / ".env").read_text(encoding="utf-8") == text


@pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")
@pytest.mark.parametrize("script", ["install-mac.sh", "mac/launcher.sh"])
def test_mac_update_scripts_merge_split_keys(script, tmp_path, monkeypatch):
    helper = _helpers((ROOT / script).read_text(encoding="utf-8"))
    app, data = tmp_path / "App", tmp_path / "data"
    app.mkdir()
    data.mkdir()
    (app / ".env").write_text(SPLIT_APP, encoding="utf-8")
    (data / ".env").write_text(SPLIT_USER, encoding="utf-8")
    os.chmod(data / ".env", 0o600)
    env = {**os.environ, "CT_DATA_DIR": str(data)}
    run = helper + 'keep_saved_keys "$1"\n'
    subprocess.run(["bash", "-c", run, "_", str(app)], check=True, env=env, capture_output=True)
    subprocess.run(["bash", "-c", run, "_", str(app)], check=True, env=env, capture_output=True)  # twice: no duplicates
    assert (data / ".env").read_text(encoding="utf-8") == SPLIT_USER + "ANTHROPIC_API_KEY='sk-ant-app'\n"
    assert stat.S_IMODE(os.stat(data / ".env").st_mode) == 0o600
    (app / ".env").unlink()
    assert _effective_keys(data, app, monkeypatch) == ("gem-user", "sk-ant-app")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="bash scripts; root ignores permissions")
@pytest.mark.parametrize("script", ["install-mac.sh", "mac/launcher.sh"])
def test_failed_key_copy_keeps_the_installed_copy(script, tmp_path):
    """A copy error returns failure, and the script then keeps the old folder
    (the only copy) instead of replacing it."""
    text = (ROOT / script).read_text(encoding="utf-8")
    helper = _helpers(text)
    app, data = tmp_path / "App", tmp_path / "data"
    app.mkdir()
    data.mkdir()
    (app / ".env").write_text(SPLIT_APP, encoding="utf-8")
    (data / ".env").write_text(SPLIT_USER, encoding="utf-8")
    os.chmod(data / ".env", 0o400)  # read-only: the append fails
    env = {**os.environ, "CT_DATA_DIR": str(data)}
    try:
        result = subprocess.run(["bash", "-c", helper + 'keep_saved_keys "$1"\n', "_", str(app)],
                                env=env, capture_output=True, text=True)
    finally:
        os.chmod(data / ".env", 0o600)
    assert result.returncode != 0
    assert "sk-ant-app" not in result.stdout + result.stderr
    assert re.search(r'keep_saved_keys "\$app_dir" \|\| \{ rm -rf "\$new"; fail ', text)


@pytest.mark.skipif(sys.platform != "darwin" or os.geteuid() == 0, reason="runs the signed app's launcher")
def test_signed_app_keeps_old_copy_when_keys_cant_be_carried_over(tmp_path):
    """Through the real launcher.sh: an older installed copy holding the only
    saved Claude key is not replaced when that key can't be carried over."""
    bundle = tmp_path / "Customizable Transcriber.app"
    resources = bundle / "Contents" / "Resources"
    (resources / "app").mkdir(parents=True)
    (resources / "launcher.sh").write_bytes((ROOT / "mac" / "launcher.sh").read_bytes())
    (resources / "app" / "VERSION").write_text("0.9.0\n")
    start = "Start Customizable Transcriber (Mac).command"
    (resources / "app" / start).write_text("#!/bin/bash\n")
    app_dir, data = tmp_path / "support" / "App", tmp_path / "support"
    app_dir.mkdir(parents=True)
    (app_dir / "VERSION").write_text("0.5.0\n")
    (app_dir / start).write_text("#!/bin/bash\n")
    (app_dir / ".env").write_text(SPLIT_APP, encoding="utf-8")
    (data / ".env").write_text(SPLIT_USER, encoding="utf-8")
    os.chmod(data / ".env", 0o400)
    env = dict(os.environ, CT_APP_DIR=str(app_dir), CT_RUNTIME_DIR=str(data / "Runtime"),
               CT_DATA_DIR=str(data), CT_SERVER_URL="http://127.0.0.1:1/", CT_LAUNCH_DRY_RUN="1")
    try:
        result = subprocess.run(["bash", str(resources / "launcher.sh")], env=env,
                                capture_output=True, text=True, timeout=30)
    finally:
        os.chmod(data / ".env", 0o600)
    assert result.returncode == 1 and "saved API keys" in result.stdout
    assert (app_dir / "VERSION").read_text() == "0.5.0\n" and (app_dir / ".env").exists()
    assert not (tmp_path / "support" / "App-new").exists()
