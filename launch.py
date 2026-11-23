"""
What "Start Customizable Transcriber (Windows).bat" and "(Mac).command" run: starts the server, opens the
browser once it answers, and, if a server is already running (a second
double-click), just opens the browser. Same server as `python app.py`: this
computer only (127.0.0.1), port 8765. With --desktop-shortcut on Windows it
also puts a shortcut on the desktop; with --mac-app on macOS it adds a small
app to ~/Applications. Either way, later starts don't need the app folder.
"""
import os
import subprocess
import sys
import threading
import time
import json
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import app

BROWSER_WAIT_SECONDS = 120
APP_DIR = Path(__file__).resolve().parent
BAT_PATH = APP_DIR / "Start Customizable Transcriber (Windows).bat"
ICON_PATH = APP_DIR / "static" / "app-icon.ico"
SHORTCUT_NAME = "Customizable Transcriber.lnk"

# Windows finds the desktop itself, since OneDrive often moves it. The shortcut
# runs the .bat through cmd.exe because Windows offers Pin to taskbar only for a
# shortcut to a program, not to a .bat. Paths arrive by environment variable, so
# an apostrophe in one can't change the script, and the script has no double
# quotes, which would need escaping on the way to PowerShell.
_SHORTCUT_SCRIPT = (
    "$ErrorActionPreference = 'Stop';"
    "$desktop = [Environment]::GetFolderPath('Desktop');"
    "$link = (New-Object -ComObject WScript.Shell).CreateShortcut("
    "(Join-Path $desktop $env:CT_SHORTCUT_NAME));"
    "$q = [string][char]34;"
    "$link.TargetPath = $env:ComSpec;"
    "$link.Arguments = '/c ' + $q + $q + $env:CT_SHORTCUT_BAT + $q + $q;"
    "$link.WorkingDirectory = Split-Path $env:CT_SHORTCUT_BAT;"
    "$link.IconLocation = $env:CT_SHORTCUT_ICON;"
    "$link.Description = 'Start Customizable Transcriber';"
    "$link.Save()"
)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


# Never through a system proxy: this is a request to this computer. Redirects
# are not followed, so another service can't pass for this app by redirecting.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def app_url() -> str:
    return f"http://{app.HOST}:{app.PORT}/"


def probe_server() -> str:
    """"ours" when this app answers its health endpoint, "other" when
    something else is listening on the port, "none" when nothing answers
    (reviews/CODEX_REVIEW_8.md L-1)."""
    try:
        with _opener.open(app_url() + "api/health", timeout=1) as response:
            if response.status != 200:
                return "other"
            data = json.loads(response.read(4096).decode("utf-8"))
            return "ours" if isinstance(data, dict) and data.get("app") == app.HEALTH_APP_ID else "other"
    except urllib.error.HTTPError:
        return "other"  # answered, but not as this app (404, redirect, ...)
    except (ValueError, UnicodeDecodeError):
        return "other"
    except OSError:
        return "none"


def server_is_up() -> bool:
    return probe_server() == "ours"


def open_browser_when_ready() -> None:
    deadline = time.monotonic() + BROWSER_WAIT_SECONDS
    while time.monotonic() < deadline:
        if server_is_up():
            webbrowser.open(app_url())
            return
        time.sleep(0.5)


def keep_console_from_freezing() -> None:
    """A click inside a Windows console selects text and pauses the program
    writing to it, which here would stall the server until someone pressed a
    key. Turns that off."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            enable_extended_flags, enable_quick_edit = 0x0080, 0x0040
            kernel32.SetConsoleMode(handle, (mode.value | enable_extended_flags) & ~enable_quick_edit)
    except (AttributeError, OSError):
        pass    # a convenience only; never a reason not to start


def create_desktop_shortcut() -> bool:
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SHORTCUT_SCRIPT],
            env={
                **os.environ,
                "CT_SHORTCUT_BAT": str(BAT_PATH),
                "CT_SHORTCUT_ICON": str(ICON_PATH),
                "CT_SHORTCUT_NAME": SHORTCUT_NAME,
            },
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def ensure_desktop_shortcut(runtime_dir: Path) -> None:
    """Once per app location, so someone who deletes the shortcut keeps it
    deleted, and someone who moves or replaces the app folder gets a shortcut
    that points at the new place."""
    marker = runtime_dir / "desktop-shortcut-for.txt"
    try:
        if marker.read_text(encoding="utf-8") == str(BAT_PATH):
            return
    except OSError:
        pass    # not made yet
    if not create_desktop_shortcut():
        print("A desktop shortcut couldn't be created. You can keep starting the app from this folder.")
        return
    try:
        marker.write_text(str(BAT_PATH), encoding="utf-8")
    except OSError:
        pass    # a convenience only; the next start makes the shortcut again


# --- macOS: a small app in ~/Applications that opens the .command in Terminal ---
# Made on this Mac, so it carries no download quarantine and Gatekeeper doesn't
# ask about it. It can go in the Dock and is found by Spotlight. The .command's
# path is read from a file inside the bundle, never written into the script.
COMMAND_PATH = APP_DIR / "Start Customizable Transcriber (Mac).command"
ICNS_PATH = APP_DIR / "static" / "app-icon.icns"
MAC_APPS_DIR = Path.home() / "Applications"
MAC_APP_NAME = "Customizable Transcriber.app"
MAC_BUNDLE_ID = "local.customizable-transcriber.launcher"
_MAC_LAUNCHER_SCRIPT = (
    "#!/bin/sh\n"
    "# Opens the app's start file in Terminal. Made by launch.py; safe to delete.\n"
    'exec /usr/bin/open -a Terminal "$(/bin/cat "$(/usr/bin/dirname "$0")/../Resources/start-file.txt")"\n'
)


def _is_our_mac_app(bundle: Path) -> bool:
    import plistlib
    try:
        with open(bundle / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == MAC_BUNDLE_ID
    except (OSError, ValueError):
        return False


def create_mac_app() -> bool:
    """Writes the bundle beside its final place, then swaps it in. Never
    replaces an app of the same name that this launcher didn't make."""
    import plistlib
    import shutil
    target = MAC_APPS_DIR / MAC_APP_NAME
    if target.exists() and not _is_our_mac_app(target):
        return False
    staging = MAC_APPS_DIR / (MAC_APP_NAME + ".new")
    try:
        shutil.rmtree(staging, ignore_errors=True)
        (staging / "Contents" / "MacOS").mkdir(parents=True)
        (staging / "Contents" / "Resources").mkdir()
        with open(staging / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({
                "CFBundleExecutable": "launcher",
                "CFBundleIdentifier": MAC_BUNDLE_ID,
                "CFBundleName": "Customizable Transcriber",
                "CFBundleDisplayName": "Customizable Transcriber",
                "CFBundleIconFile": "app-icon",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.0",
                "LSMinimumSystemVersion": "11.0",
            }, f)
        launcher = staging / "Contents" / "MacOS" / "launcher"
        launcher.write_text(_MAC_LAUNCHER_SCRIPT, encoding="utf-8")
        launcher.chmod(0o755)
        (staging / "Contents" / "Resources" / "start-file.txt").write_text(str(COMMAND_PATH), encoding="utf-8")
        shutil.copyfile(ICNS_PATH, staging / "Contents" / "Resources" / "app-icon.icns")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return False
    return True


def signed_app_installed(runtime_dir: Path) -> bool:
    """The signed app from the disk image writes its own location here each
    time it starts this copy (mac/launcher.sh)."""
    try:
        bundle = Path((runtime_dir / "signed-app.txt").read_text(encoding="utf-8").strip())
    except OSError:
        return False
    return bundle.name.endswith(".app") and (bundle / "Contents" / "Info.plist").is_file()


def remove_own_mac_app() -> None:
    """With the signed app installed, the small app made here would be a second
    "Customizable Transcriber" in Spotlight and Launchpad. Removed only when it
    is ours and opens this same copy."""
    import shutil
    target = MAC_APPS_DIR / MAC_APP_NAME
    try:
        points_here = (target / "Contents" / "Resources" / "start-file.txt").read_text(
            encoding="utf-8") == str(COMMAND_PATH)
    except OSError:
        return
    if points_here and _is_our_mac_app(target):
        shutil.rmtree(target, ignore_errors=True)


def ensure_mac_app(runtime_dir: Path) -> None:
    """Once per app location, like the Windows shortcut: a deleted app stays
    deleted, and a moved or replaced app folder gets an app that points at it.
    Not made at all when the signed app is installed."""
    if signed_app_installed(runtime_dir):
        remove_own_mac_app()
        return
    marker = runtime_dir / "mac-app-for.txt"
    try:
        if marker.read_text(encoding="utf-8") == str(COMMAND_PATH):
            return
    except OSError:
        pass    # not made yet
    if not create_mac_app():
        print("The Customizable Transcriber app couldn't be added to your Applications folder.")
        print("You can keep starting the app from this folder.\n")
        return
    print(f"Added \"Customizable Transcriber\" to {MAC_APPS_DIR}.")
    print("Next time, start the app from there, Spotlight or Launchpad. Drag it to the Dock for one-click starts.\n")
    try:
        marker.write_text(str(COMMAND_PATH), encoding="utf-8")
    except OSError:
        pass    # a convenience only; the next start makes the app again


def main() -> None:
    use_browser = "--no-browser" not in sys.argv[1:]
    # Both beside the venv, which a package update clears.
    if "--desktop-shortcut" in sys.argv[1:] and os.name == "nt":
        ensure_desktop_shortcut(Path(sys.prefix).parent)
    if "--mac-app" in sys.argv[1:] and sys.platform == "darwin":
        ensure_mac_app(Path(sys.prefix).parent)
    probe = probe_server()
    if probe == "ours":
        print(f"Customizable Transcriber is already running at {app_url()}")
        if use_browser:
            webbrowser.open(app_url())
        return
    if probe == "other":
        print(
            f"Another program is already using port {app.PORT} on this computer, so Customizable "
            "Transcriber can't start. Close that program (or restart the computer) and try again."
        )
        sys.exit(1)

    keep_console_from_freezing()
    print("Keep this window open while you use the app. Closing it stops the app.\n")
    if use_browser:
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    try:
        app.main()
    except KeyboardInterrupt:
        pass    # Ctrl+C in the window: a normal stop, not a problem to report


if __name__ == "__main__":
    main()
