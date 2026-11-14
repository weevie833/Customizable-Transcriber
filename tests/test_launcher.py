"""The double-click installer can only really run on Windows (the CI windows-install
job does that). These catch what breaks it from any platform, plus the launcher's
own decisions."""
import os
import re
import subprocess
from pathlib import Path

import pytest

import launch

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "Start Customizable Transcriber (Windows).bat"
INSTRUCTIONS = ROOT / "Install Instructions.txt"
COMMAND = ROOT / "Start Customizable Transcriber (Mac).command"


def test_bat_keeps_windows_line_endings_and_plain_text():
    for path in (BAT, INSTRUCTIONS):
        raw = path.read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n") > 0, path.name
        assert raw.isascii(), path.name


def test_every_goto_has_a_label():
    text = BAT.read_text()
    labels = set(re.findall(r"^:(\w+)", text, re.MULTILINE))
    targets = set(re.findall(r"\bgoto (\w+)", text))
    assert targets and targets <= labels


def test_every_call_has_a_label():
    text = BAT.read_text()
    labels = set(re.findall(r"^:(\w+)", text, re.MULTILINE))
    targets = set(re.findall(r"\bcall :(\w+)", text))
    assert targets and targets <= labels


def test_bat_pins_python_by_hash():
    text = BAT.read_text()
    assert re.search(r'PYTHON_SHA256=[0-9a-f]{64}"', text)
    # %%2B: a single % before 2 would expand the batch file's second argument.
    assert re.search(
        r'PYTHON_URL=https://github\.com/astral-sh/python-build-standalone/releases/download/\d+/'
        r'cpython-3\.12\.\d+%%2B\d+-x86_64-pc-windows-msvc-install_only\.tar\.gz"', text)


def test_both_installers_pin_the_same_python_release():
    def release(text):
        return re.search(r"download/(\d+)/cpython-(3\.\d+\.\d+)", text).groups()
    assert release(BAT.read_text()) == release(COMMAND.read_text())


@pytest.mark.parametrize("path", [BAT, COMMAND], ids=["windows", "mac"])
def test_installed_python_build_is_checked_on_every_start(path):
    """An app update that pins a newer Python must replace the installed one, not just
    reinstall packages (reviews/CODEX_REVIEW.md H-1)."""
    text = path.read_text()
    assert "python-build.txt" in text
    assert "PYTHON_SHA256" in text.split("installed-requirements.txt", 1)[1]
    assert "python-old" in text and "restore_previous" in text


def test_lock_file_pins_every_direct_dependency_at_the_same_version():
    def pins(path):
        found = {}
        for line in path.read_text().splitlines():
            line = line.split("#")[0].strip()
            if "==" in line:
                name, version = line.split("==")
                found[re.sub(r"[-_.]+", "-", name).lower()] = version
        return found
    direct, locked = pins(ROOT / "requirements.txt"), pins(ROOT / "requirements.lock")
    assert direct
    for name, version in direct.items():
        assert locked.get(name) == version, name


def test_running_server_only_opens_the_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(launch, "server_is_up", lambda: True)
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    monkeypatch.setattr(launch.app, "main", lambda: pytest.fail("should not start a second server"))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py"])
    launch.main()
    assert opened == [launch.app_url()]


def test_server_is_the_apps_own_local_only_server(monkeypatch):
    started = []
    monkeypatch.setattr(launch, "server_is_up", lambda: False)
    monkeypatch.setattr(launch.app, "main", lambda: started.append(1))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "--no-browser"])
    launch.main()
    assert started == [1]
    assert launch.app.HOST == "127.0.0.1"
    assert launch.app_url() == f"http://127.0.0.1:{launch.app.PORT}/"


def test_ctrl_c_is_a_normal_stop(monkeypatch):
    def interrupted():
        raise KeyboardInterrupt
    monkeypatch.setattr(launch, "server_is_up", lambda: False)
    monkeypatch.setattr(launch.app, "main", interrupted)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "--no-browser"])
    launch.main()


def test_bat_asks_for_the_desktop_shortcut():
    assert b'"%APP_PYTHON%" launch.py --desktop-shortcut\r\n' in BAT.read_bytes()
    assert launch.ICON_PATH.is_file()
    assert launch.BAT_PATH == BAT


def test_shortcut_is_made_once_per_app_location(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(launch, "create_desktop_shortcut", lambda: made.append(1) or True)
    launch.ensure_desktop_shortcut(tmp_path)
    launch.ensure_desktop_shortcut(tmp_path)    # also the case of a deleted shortcut: not remade
    assert len(made) == 1
    monkeypatch.setattr(launch, "BAT_PATH", tmp_path / "moved" / "start.bat")
    launch.ensure_desktop_shortcut(tmp_path)
    assert len(made) == 2


def test_failed_shortcut_says_so_and_tries_again_next_start(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(launch, "create_desktop_shortcut", lambda: False)
    launch.ensure_desktop_shortcut(tmp_path)
    assert "couldn't be created" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_shortcut_failure_never_stops_the_app(monkeypatch):
    def refuse(*args, **kwargs):
        raise FileNotFoundError("no powershell")
    monkeypatch.setattr(launch.subprocess, "run", refuse)
    assert launch.create_desktop_shortcut() is False


def test_no_path_is_written_into_the_shortcut_script():
    assert '"' not in launch._SHORTCUT_SCRIPT
    assert "$env:CT_SHORTCUT_BAT" in launch._SHORTCUT_SCRIPT


@pytest.mark.skipif(os.name != "nt" or not os.environ.get("CI"), reason="makes a real shortcut; Windows CI only")
def test_real_shortcut_starts_the_bat():
    assert launch.create_desktop_shortcut()
    read = (
        "$p = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Customizable Transcriber.lnk';"
        "$l = (New-Object -ComObject WScript.Shell).CreateShortcut($p);"
        "$l.TargetPath; $l.Arguments; $l.IconLocation; Remove-Item $p"
    )
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", read],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    assert out[0].lower().endswith("cmd.exe")
    assert out[1] == f'/c ""{launch.BAT_PATH}""'
    assert out[2].startswith(str(launch.ICON_PATH))


# --- macOS ---------------------------------------------------------------

def test_command_is_an_executable_lf_bash_script():
    raw = COMMAND.read_bytes()
    assert raw.startswith(b"#!/bin/bash\n")
    assert b"\r" not in raw and raw.isascii()
    assert os.access(COMMAND, os.X_OK) or os.name == "nt"
    if os.name == "nt":
        # Windows runners' bash (WSL or Git Bash) can't open a D:\ path;
        # the syntax check runs on the Linux and macOS jobs.
        return
    subprocess.run(["bash", "-n", str(COMMAND)], check=True)


def test_command_pins_python_by_hash():
    text = COMMAND.read_text()
    assert re.search(r'PYTHON_SHA256="[0-9a-f]{64}"', text)
    assert re.search(
        r'PYTHON_URL="https://github\.com/astral-sh/python-build-standalone/releases/download/\d+/'
        r'cpython-3\.12\.\d+%2B\d+-aarch64-apple-darwin-install_only\.tar\.gz"', text)


def test_command_asks_for_the_mac_app():
    assert '"$APP_PYTHON" launch.py --mac-app' in COMMAND.read_text()
    assert launch.COMMAND_PATH == COMMAND
    assert launch.ICNS_PATH.is_file()


def test_mac_app_opens_the_start_file_in_terminal(monkeypatch, tmp_path):
    import plistlib
    monkeypatch.setattr(launch, "MAC_APPS_DIR", tmp_path)
    assert launch.create_mac_app()
    bundle = tmp_path / launch.MAC_APP_NAME
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == launch.MAC_BUNDLE_ID
    launcher = bundle / "Contents" / "MacOS" / info["CFBundleExecutable"]
    assert os.access(launcher, os.X_OK) or os.name == "nt"
    assert "open -a Terminal" in launcher.read_text()
    assert str(launch.COMMAND_PATH) not in launcher.read_text()    # path lives in a data file
    assert (bundle / "Contents" / "Resources" / "start-file.txt").read_text() == str(launch.COMMAND_PATH)
    assert (bundle / "Contents" / "Resources" / "app-icon.icns").is_file()
    assert launch.create_mac_app()    # replacing our own app is fine
    assert [p.name for p in tmp_path.iterdir()] == [launch.MAC_APP_NAME]


def test_mac_app_never_replaces_someone_elses_app(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "MAC_APPS_DIR", tmp_path)
    other = tmp_path / launch.MAC_APP_NAME / "Contents"
    other.mkdir(parents=True)
    (other / "keep.txt").write_text("not ours")
    assert launch.create_mac_app() is False
    assert (other / "keep.txt").read_text() == "not ours"


def test_mac_app_is_made_once_per_app_location(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(launch, "create_mac_app", lambda: made.append(1) or True)
    launch.ensure_mac_app(tmp_path)
    launch.ensure_mac_app(tmp_path)    # also the case of a deleted app: not remade
    assert len(made) == 1
    monkeypatch.setattr(launch, "COMMAND_PATH", tmp_path / "moved" / "start.command")
    launch.ensure_mac_app(tmp_path)
    assert len(made) == 2


def test_failed_mac_app_says_so_and_tries_again_next_start(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(launch, "create_mac_app", lambda: False)
    launch.ensure_mac_app(tmp_path)
    assert "couldn't be added" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
