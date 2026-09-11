"""HTTP handlers for the small folder-picker/settings endpoints: browsing
for a source folder, typing one in manually, and opening the outputs folder
in the native file manager. Also owns the per-OS subprocess-dispatch
helpers those three endpoints call (pick_source_folder_dialog()/
open_folder_in_file_manager()), since nothing else in the app needs them.

`platform`/`subprocess` are imported as modules (not `from X import Y`) and
called as `platform.system()`/`subprocess.run(...)` throughout this file --
tests/test_open_outputs_folder.py depends on this exact shape, since it
monkeypatches `handlers.settings.platform`/`handlers.settings.subprocess`
to stub out real OS dispatch. See docs/DESIGN.md's "Codebase structure"
section on why a moved function's dependencies must be patched on the
module that now owns them, not on app.py's copy of the same name.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from app_state import USER_OUTPUTS_DIR, save_source_folder
from http_utils import parse_json_body


def _pick_source_folder_macos() -> str | None:
    """Native Finder "choose folder" dialog via AppleScript. Runs as an
    independent OS process (not bound to the calling Python thread's GUI
    affinity), which matters because ThreadingHTTPServer handles each request
    on its own thread — a GUI toolkit living inside this process (e.g.
    tkinter) would need to run on the main thread on macOS; shelling out
    sidesteps that entirely, and the same reasoning applies to the Windows
    and Linux variants below."""
    script = 'POSIX path of (choose folder with prompt "Select the source folder for transcription images")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "User canceled" in stderr or "-128" in stderr:
            return None
        raise RuntimeError(stderr or "Couldn't open the folder picker.")
    chosen = result.stdout.strip()
    return chosen or None


def _pick_source_folder_windows() -> str | None:
    """Native folder-browse dialog via .NET's FolderBrowserDialog, run
    through PowerShell as a separate process. `-STA` (single-threaded
    apartment) is required for WinForms dialogs to display correctly."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$dialog.Description = 'Select the source folder for transcription images';"
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or "Couldn't open the folder picker.")
    # Empty stdout means the user closed the dialog without clicking OK — not an error.
    chosen = result.stdout.strip()
    return chosen or None


def _pick_source_folder_linux() -> str | None:
    """Native folder dialog via zenity (GNOME/GTK) if it's installed; there is
    no single cross-desktop-environment API to fall back to on Linux the way
    osascript/PowerShell provide one on Mac/Windows, so an unavailable zenity
    surfaces as a clear error pointing at the manual-path fallback rather than
    a silent failure."""
    try:
        result = subprocess.run(
            [
                "zenity",
                "--file-selection",
                "--directory",
                "--title=Select the source folder for transcription images",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No folder-picker dialog is available (zenity is not installed). "
            "Type the folder path directly in the field below instead."
        ) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        return None  # zenity exits 1 on Cancel/Escape
    chosen = result.stdout.strip()
    return chosen or None


def pick_source_folder_dialog() -> str | None:
    """Show the platform's native folder-choose dialog and return the chosen
    absolute path, or None if the user canceled. Raises RuntimeError on any
    other failure. Dispatches by platform.system() so this works the same way
    (a real native dialog, not a browser file input — a browser can't hand
    back an absolute filesystem path for the backend to read from disk) on
    macOS, Windows, and Linux."""
    system = platform.system()
    if system == "Darwin":
        return _pick_source_folder_macos()
    if system == "Windows":
        return _pick_source_folder_windows()
    if system == "Linux":
        return _pick_source_folder_linux()
    raise RuntimeError(
        f"No folder-picker dialog is available on this platform ({system}). "
        "Type the folder path directly in the field below instead."
    )


def open_folder_in_file_manager(path: Path) -> None:
    """Reveals `path` in the native file manager (Finder/Explorer/whatever
    the Linux desktop's default is) via the same per-OS subprocess dispatch
    pattern as pick_source_folder_dialog() above, and for the same reason:
    generated outputs now live in a per-user data directory outside the app
    folder (see USER_OUTPUTS_DIR) rather than somewhere a user would already
    have open, and on macOS that directory sits under the normally-hidden
    ~/Library -- printing the raw path in the UI (which this app also still
    does) isn't enough for a non-technical user to actually get there."""
    system = platform.system()
    path.mkdir(parents=True, exist_ok=True)
    try:
        if system == "Darwin":
            result = subprocess.run(["open", str(path)], capture_output=True, text=True, timeout=15)
        elif system == "Windows":
            # explorer.exe routinely exits 1 even when it opens the window
            # successfully -- a documented quirk, not a failure signal -- so
            # a non-zero returncode is not treated as an error below, unlike
            # the other two branches.
            result = subprocess.run(["explorer", str(path)], capture_output=True, text=True, timeout=15)
            return
        elif system == "Linux":
            result = subprocess.run(["xdg-open", str(path)], capture_output=True, text=True, timeout=15)
        else:
            raise RuntimeError(f"Can't open a file manager window on this platform ({system}).")
    except FileNotFoundError as exc:
        raise RuntimeError(f"No file manager command was found to open {path}.") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the outputs folder: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or f"Couldn't open {path}.")


class SettingsHandlerMixin:
    def pick_source_folder(self) -> None:
        try:
            chosen = pick_source_folder_dialog()
            if chosen is None:
                self.respond_json({"canceled": True})
                return
            path = Path(chosen)
            if not path.is_dir():
                raise RuntimeError(f"{path} is not a folder.")
            save_source_folder(path)
            self.respond_json({"source_folder": str(path)})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def set_source_folder(self) -> None:
        """Manual-entry fallback for platforms/setups where the native folder
        dialog isn't available (e.g. Linux without zenity), or for a user who
        just wants to type/paste a path directly."""
        try:
            payload = parse_json_body(self)
            raw = str(payload.get("path") or "").strip()
            if not raw:
                raise RuntimeError("Enter a folder path.")
            path = Path(raw).expanduser()
            if not path.is_dir():
                raise RuntimeError(f"{path} is not a folder, or doesn't exist on this machine.")
            save_source_folder(path)
            self.respond_json({"source_folder": str(path)})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def open_outputs_folder(self) -> None:
        try:
            open_folder_in_file_manager(USER_OUTPUTS_DIR)
            self.respond_json({"ok": True})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)
