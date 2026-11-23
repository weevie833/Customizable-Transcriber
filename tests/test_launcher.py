"""The double-click installer can only really run on Windows (the CI windows-install
job does that). These catch what breaks it from any platform, plus the launcher's
own decisions."""
import os
import re
import subprocess
import sys
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
    monkeypatch.setattr(launch, "probe_server", lambda: "ours")
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    monkeypatch.setattr(launch.app, "main", lambda: pytest.fail("should not start a second server"))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py"])
    launch.main()
    assert opened == [launch.app_url()]


def test_server_is_the_apps_own_local_only_server(monkeypatch):
    started = []
    monkeypatch.setattr(launch, "probe_server", lambda: "none")
    monkeypatch.setattr(launch.app, "main", lambda: started.append(1))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "--no-browser"])
    launch.main()
    assert started == [1]
    assert launch.app.HOST == "127.0.0.1"
    assert launch.app_url() == f"http://127.0.0.1:{launch.app.PORT}/"


def test_ctrl_c_is_a_normal_stop(monkeypatch):
    def interrupted():
        raise KeyboardInterrupt
    monkeypatch.setattr(launch, "probe_server", lambda: "none")
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


# --- macOS one-line installer (install-mac.sh) -----------------------------

INSTALLER = ROOT / "install-mac.sh"


def test_installer_is_an_executable_lf_bash_script():
    raw = INSTALLER.read_bytes()
    assert raw.startswith(b"#!/bin/bash\n")
    assert b"\r" not in raw and raw.isascii()
    assert os.access(INSTALLER, os.X_OK) or os.name == "nt"
    if os.name != "nt":
        subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_installer_runs_only_once_fully_downloaded():
    """`curl | bash` runs a script as it arrives: everything must sit in functions, with
    the one call to main on the last line."""
    lines = [l for l in INSTALLER.read_text().splitlines() if l.strip()]
    assert lines[-1] == 'main "$@"'
    top_level = [l for l in lines if not l.startswith((" ", "\t", "#", "}"))]
    assert all(re.match(r'(\w+=|\w+\(\) \{$|main "\$@"$)', l) for l in top_level), top_level


def test_installer_names_this_repo_and_the_start_file():
    text = INSTALLER.read_text()
    readme = (ROOT / "README.md").read_text()
    url = re.search(r"https://raw\.githubusercontent\.com/\S+/install-mac\.sh", text).group(0)
    assert url in readme
    repo = re.search(r'REPO="([^"]+)"', text).group(1)
    assert f"raw.githubusercontent.com/{repo}/main/" in url
    assert f'START_FILE="{COMMAND.name}"' in text


def test_installer_is_left_out_of_the_zip():
    attrs = (ROOT / ".gitattributes").read_text().splitlines()
    assert "install-mac.sh export-ignore" in attrs
    assert "*.sh text eol=lf" in attrs


# --- macOS signed app (mac/: the disk image's app, built and notarized by CI) ---

MAC_DIR = ROOT / "mac"
APP_LAUNCHER = MAC_DIR / "launcher.sh"


def write_signed_app_marker(runtime_dir, bundle):
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_text("<plist/>")
    (runtime_dir / "signed-app.txt").write_text(str(bundle))


def test_no_own_mac_app_when_the_signed_app_is_installed(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(launch, "create_mac_app", lambda: made.append(1) or True)
    write_signed_app_marker(tmp_path, tmp_path / "Applications" / "Customizable Transcriber.app")
    launch.ensure_mac_app(tmp_path)
    assert made == []


def test_signed_app_that_was_deleted_no_longer_counts(tmp_path):
    bundle = tmp_path / "Customizable Transcriber.app"
    write_signed_app_marker(tmp_path, bundle)
    assert launch.signed_app_installed(tmp_path)
    import shutil
    shutil.rmtree(bundle)
    assert not launch.signed_app_installed(tmp_path)


@pytest.mark.parametrize("points_here", [True, False])
def test_own_mac_app_is_removed_only_when_it_opens_this_copy(monkeypatch, tmp_path, points_here):
    apps = tmp_path / "apps"
    monkeypatch.setattr(launch, "MAC_APPS_DIR", apps)
    apps.mkdir()
    assert launch.create_mac_app()
    if not points_here:
        (apps / launch.MAC_APP_NAME / "Contents" / "Resources" / "start-file.txt").write_text("/elsewhere")
    write_signed_app_marker(tmp_path, tmp_path / "signed" / "Customizable Transcriber.app")
    launch.ensure_mac_app(tmp_path)
    assert (apps / launch.MAC_APP_NAME).exists() is not points_here


@pytest.mark.parametrize("path", ["launcher.sh", "build.sh"])
def test_mac_scripts_are_executable_lf_bash(path):
    script = MAC_DIR / path
    raw = script.read_bytes()
    assert raw.startswith(b"#!/bin/bash\n") and b"\r" not in raw
    assert os.access(script, os.X_OK) or os.name == "nt"
    if os.name != "nt":
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_signed_app_identity_and_start_file():
    import plistlib
    info = plistlib.loads((MAC_DIR / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "io.github.weevie833.customizable-transcriber"
    assert info["CFBundleShortVersionString"] == "__VERSION__"
    assert f'START_FILE="{COMMAND.name}"' in APP_LAUNCHER.read_text()
    assert "signed-app.txt" in APP_LAUNCHER.read_text()


def test_mac_build_files_are_left_out_of_the_zip():
    assert "mac/ export-ignore" in (ROOT / ".gitattributes").read_text().splitlines()


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="uses ditto and xattr")
def test_signed_app_installs_only_a_newer_copy(tmp_path):
    bundle = tmp_path / "Customizable Transcriber.app"
    resources = bundle / "Contents" / "Resources"
    (resources / "app").mkdir(parents=True)
    (resources / "launcher.sh").write_bytes(APP_LAUNCHER.read_bytes())
    (resources / "app" / "VERSION").write_text("0.6.0\n")
    (resources / "app" / COMMAND.name).write_text("#!/bin/bash\n")
    app_dir = tmp_path / "support" / "App"
    env = dict(os.environ, CT_APP_DIR=str(app_dir), CT_RUNTIME_DIR=str(tmp_path / "support" / "Runtime"),
               CT_SERVER_URL="http://127.0.0.1:1/", CT_LAUNCH_DRY_RUN="1")

    def run():
        out = subprocess.run(["bash", str(resources / "launcher.sh")], env=env,
                             capture_output=True, text=True, check=True).stdout
        return out, (app_dir / "VERSION").read_text().strip()

    out, version = run()
    assert version == "0.6.0" and out.startswith("open -a Terminal ") and COMMAND.name in out
    assert os.access(app_dir / COMMAND.name, os.X_OK)
    assert (tmp_path / "support" / "Runtime" / "signed-app.txt").read_text() == str(bundle.resolve())
    (app_dir / "VERSION").write_text("0.10.0\n")    # newer, e.g. from the one-line installer
    assert run()[1] == "0.10.0"
    (app_dir / "VERSION").write_text("0.5.9\n")
    assert run()[1] == "0.6.0"
    assert sorted(p.name for p in app_dir.parent.iterdir()) == ["App", "Runtime"]    # no -new or -old left


# reviews/CODEX_REVIEW_8.md L-1: only this app's health answer counts as
# "already running"; an unrelated 200, a redirect or a 404 is a port conflict.
import http.server as _http_server
import threading as _threading


def _serve(handler_body):
    class Handler(_http_server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            handler_body(self)

        def log_message(self, *args):
            pass

    server = _http_server.HTTPServer(("127.0.0.1", 0), Handler)
    _threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _reply(status, body=b"", headers=None):
    def handler(request):
        request.send_response(status)
        for key, value in (headers or {}).items():
            request.send_header(key, value)
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)
    return handler


@pytest.mark.parametrize("handler, expected", [
    (_reply(200, b'{"app": "customizable-transcriber", "version": "1"}'), "ours"),
    (_reply(200, b"<html>some other app</html>"), "other"),
    (_reply(302, headers={"Location": "http://example.invalid/"}), "other"),
    (_reply(404), "other"),
])
def test_probe_distinguishes_this_app_from_other_services(monkeypatch, handler, expected):
    server = _serve(handler)
    try:
        monkeypatch.setattr(launch.app, "PORT", server.server_address[1])
        assert launch.probe_server() == expected
    finally:
        server.shutdown()


def test_probe_reports_nothing_listening(monkeypatch):
    monkeypatch.setattr(launch.app, "PORT", 1)
    assert launch.probe_server() == "none"


def test_port_conflict_does_not_open_browser_or_start(monkeypatch):
    monkeypatch.setattr(launch, "probe_server", lambda: "other")
    monkeypatch.setattr(launch.webbrowser, "open", lambda url: pytest.fail("opened the wrong app"))
    monkeypatch.setattr(launch.app, "main", lambda: pytest.fail("started over another service"))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py"])
    with pytest.raises(SystemExit):
        launch.main()


def test_setup_instructions_install_the_tested_lock():
    """CODEX_REVIEW_2.md M-14: the manual setup installs requirements.lock,
    the same set the installers install, and CI's dev install pulls in that
    same lock, so the instructions and their tested inputs stay aligned."""
    import re

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installs = {name.rstrip("`)") for name in re.findall(r"pip install -r\s+(\S+)", readme)}
    # requirements-dev.txt (developer tooling) itself pulls in the lock, below.
    assert installs - {"requirements-dev.txt"} == {"requirements.lock"}
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "-r requirements.lock" in dev and "-r requirements.txt" not in dev


# CODEX_REVIEW_2.md L-1: the signed app's shell launcher applies the same
# rule as launch.py -- HTTP 200 and a JSON object whose top-level "app" is
# this app's id. Runs the real launcher.sh against a local stub server.

@pytest.mark.skipif(sys.platform != "darwin", reason="launcher.sh uses macOS tools")
@pytest.mark.parametrize("handler, expected", [
    (_reply(200, b'{"app": "customizable-transcriber", "version": "1"}'), "ours"),
    (_reply(200, b'{\n  "app"\t:\n "customizable-transcriber"\n}'), "ours"),  # valid JSON whitespace
    (_reply(200, b'{"note": "\\"app\\": \\"customizable-transcriber\\""}'), "conflict"),  # substring only
    (_reply(200, b'{"nested": {"app": "customizable-transcriber"}}'), "conflict"),
    (_reply(200, b'["app", "customizable-transcriber"]'), "conflict"),
    (_reply(200, b'{"app": "customizable-transcriber"'), "conflict"),  # malformed
    (_reply(200, b"<html>some other app</html>"), "conflict"),
    (_reply(302, b'{"app": "customizable-transcriber"}', {"Location": "http://example.invalid/"}), "conflict"),
    (_reply(404, b'{"app": "customizable-transcriber"}'), "conflict"),
    (_reply(200, b'{"app": "customizable-transcriber", "pad": "' + b"x" * 5000 + b'"}'), "conflict"),  # oversized
])
def test_signed_app_launcher_identity_check(tmp_path, handler, expected):
    server = _serve(handler)
    try:
        resources = tmp_path / "Customizable Transcriber.app" / "Contents" / "Resources"
        resources.mkdir(parents=True)
        (resources / "launcher.sh").write_bytes(APP_LAUNCHER.read_bytes())
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        env = dict(os.environ, CT_SERVER_URL=url, CT_LAUNCH_DRY_RUN="1",
                   CT_APP_DIR=str(tmp_path / "App"), CT_RUNTIME_DIR=str(tmp_path / "Runtime"))
        result = subprocess.run(["bash", str(resources / "launcher.sh")], env=env,
                                capture_output=True, text=True, timeout=30)
    finally:
        server.shutdown()
    if expected == "ours":
        assert result.returncode == 0 and result.stdout.strip() == f"open {url}"
    else:
        assert result.returncode == 1
        assert "Another program is already using port 8765" in result.stdout
        assert not (tmp_path / "App").exists()
