#!/bin/bash
# Double-click to install Customizable Transcriber (first run only) and start it.
# Python and the app's packages go in a private folder under ~/Library/Application Support,
# not the app folder: no admin rights, nothing on PATH, no Homebrew or python.org installer.
# Python is python-build-standalone (Astral), pinned by SHA-256. Apple Silicon only: the
# cryptography release the app pins for security fixes has no Intel Mac build.

cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
PYTHON_SHA256="fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e"
RUNTIME="${CT_RUNTIME_DIR:-$HOME/Library/Application Support/Customizable Transcriber/Runtime}"
BASE_PYTHON="$RUNTIME/python/bin/python3"
APP_PYTHON="$RUNTIME/venv/bin/python"
INSTALLED_LOCK="$RUNTIME/venv/installed-requirements.txt"
# Which Python build is installed (its archive SHA-256). When a newer app version pins a
# different build, the next start replaces Python instead of keeping the old one forever.
BUILD_MARKER="$RUNTIME/python-build.txt"
# Written before an update moves anything aside and removed only after every marker is
# written: if it is still there at the next start, that update failed or was interrupted,
# and the last working runtime is put back before anything else (CODEX_REVIEW_2.md M-11).
# Holds "python" (Python and packages being replaced) or "venv" (packages only).
PENDING="$RUNTIME/update-pending.txt"
# Imported after installing, before the markers are written: a broken install is rolled back.
SMOKE_IMPORTS="import google.genai, anthropic, openpyxl, rapidfuzz, PIL, cryptography, certifi"

fail() {
    echo
    for line in "$@"; do echo "$line"; done
    echo
    if [ -z "$CT_INSTALL_ONLY" ]; then read -r -p "Press Return to close this window. "; fi
    exit 1
}

installed_build() { cat "$BUILD_MARKER" 2>/dev/null; }

# An update failed or was interrupted: put the last working runtime back. The backup goes
# back to the exact path it came from, so the absolute paths inside the virtual environment
# stay valid. Safe to run at any point of an update, and again after being interrupted.
restore_previous() {
    case "$(cat "$PENDING" 2>/dev/null)" in
        python)
            if [ -d "$RUNTIME/python-old" ]; then
                rm -rf "$RUNTIME/python"
                mv "$RUNTIME/python-old" "$RUNTIME/python" || return 1
            fi
            if [ -d "$RUNTIME/venv-old" ]; then
                rm -rf "$RUNTIME/venv"
                mv "$RUNTIME/venv-old" "$RUNTIME/venv" || return 1
            fi
            if [ -f "$BUILD_MARKER.old" ]; then
                mv -f "$BUILD_MARKER.old" "$BUILD_MARKER" || return 1
            else
                rm -f "$BUILD_MARKER"
            fi
            ;;
        venv)
            if [ -d "$RUNTIME/venv-old" ]; then
                rm -rf "$RUNTIME/venv"
                mv "$RUNTIME/venv-old" "$RUNTIME/venv" || return 1
            fi
            ;;
    esac
    rm -f "$PENDING"
}

# Starts an update of the given kind: only now may an older backup be discarded, because
# no update is outstanding (restore_previous ran first if one was).
begin_update() {
    rm -rf "$RUNTIME/python-old" "$RUNTIME/venv-old" "$BUILD_MARKER.old"
    if [ "$1" = python ] && [ -f "$BUILD_MARKER" ]; then
        cp "$BUILD_MARKER" "$BUILD_MARKER.old" || return 1
    fi
    echo "$1" > "$PENDING"
}

printf '\033]0;Customizable Transcriber\007'

[ -f "app.py" ] || fail "This file has to stay in the app's folder, next to app.py." \
    "Open the folder you downloaded and double-click it there."

if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
    fail "This installer needs a Mac with Apple silicon (M1 or later)." \
        "On an Intel Mac, follow the manual setup in README.md instead."
fi

if [ -f "$PENDING" ]; then
    echo
    echo "The last update didn't finish. Putting the previous working setup back first..."
    restore_previous || fail "The previous setup couldn't be put back. Close every Customizable Transcriber window, then try again." \
        "If it keeps failing, send this window's text to whoever gave you the app."
fi

if [ -x "$APP_PYTHON" ] && [ "$(installed_build)" = "$PYTHON_SHA256" ] \
    && [ -f "$INSTALLED_LOCK" ] && cmp -s "requirements.lock" "$INSTALLED_LOCK"; then
    :    # already installed with this Python and these exact package versions: just start
else
    echo
    echo "Setting up Customizable Transcriber. This happens once and takes a few minutes."
    echo "Please leave this window open, and stay connected to the internet."
    echo
    mkdir -p "$RUNTIME" || fail "The folder $RUNTIME couldn't be created."

    if [ ! -x "$BASE_PYTHON" ] || [ "$(installed_build)" != "$PYTHON_SHA256" ]; then
        echo "Step 1 of 2: downloading Python..."
        DOWNLOAD="$RUNTIME/python-download.tar.gz"
        curl --fail --location --silent --show-error --retry 3 --output "$DOWNLOAD" "$PYTHON_URL" \
            || fail "Python couldn't be downloaded. Check your internet connection and try again." \
                "If it keeps failing, your network may be blocking github.com. Send this message to whoever gave you the app."
        if [ "$(shasum -a 256 "$DOWNLOAD" | awk '{print $1}')" != "$PYTHON_SHA256" ]; then
            rm -f "$DOWNLOAD"
            fail "The downloaded copy of Python didn't match the expected file, so it wasn't used. Try again." \
                "If it keeps failing, send this message to whoever gave you the app."
        fi
        rm -rf "$RUNTIME/python-new"
        mkdir "$RUNTIME/python-new" && tar -xzf "$DOWNLOAD" -C "$RUNTIME/python-new" \
            || fail "Python couldn't be unpacked. Try again. If it keeps failing, send this message to whoever gave you the app."
        # Keep the current runtime until the new one is fully set up, so a failed or
        # interrupted update can go back to it.
        begin_update python || fail "The update couldn't start. Close every Customizable Transcriber window, then try again."
        if [ -d "$RUNTIME/python" ]; then
            mv "$RUNTIME/python" "$RUNTIME/python-old" || { restore_previous; fail "Python couldn't be updated because it's in use. Close every Customizable Transcriber window, then try again."; }
        fi
        if [ -d "$RUNTIME/venv" ]; then
            mv "$RUNTIME/venv" "$RUNTIME/venv-old" || { restore_previous; fail "Python couldn't be updated because it's in use. Close every Customizable Transcriber window, then try again."; }
        fi
        mv "$RUNTIME/python-new/python" "$RUNTIME/python" \
            || { restore_previous; fail "Python couldn't be unpacked. Try again. If it keeps failing, send this message to whoever gave you the app."; }
        rm -rf "$RUNTIME/python-new" "$DOWNLOAD"
    fi

    # Same Python, new package list: keep the working environment until the new one is
    # installed and imports cleanly (reviews/CODEX_REVIEW_8.md M-11).
    if [ ! -f "$PENDING" ] && [ -d "$RUNTIME/venv" ]; then
        begin_update venv || fail "The update couldn't start. Close every Customizable Transcriber window, then try again."
        mv "$RUNTIME/venv" "$RUNTIME/venv-old" || { restore_previous; fail "The app's components couldn't be updated. Close every Customizable Transcriber window, then try again."; }
    fi

    echo "Step 2 of 2: installing the app's components..."
    "$BASE_PYTHON" -m venv --clear "$RUNTIME/venv" \
        && "$APP_PYTHON" -m pip install --quiet --disable-pip-version-check --no-input --only-binary=:all: -r requirements.lock \
        && "$APP_PYTHON" -c "$SMOKE_IMPORTS" \
        || { restore_previous; fail "The app's components couldn't be installed. Check your internet connection and try again." \
            "If it keeps failing, your network may be blocking pypi.org. Send this window's text to whoever gave you the app."; }
    # The previous runtime is discarded only after both markers are written.
    { cp "requirements.lock" "$INSTALLED_LOCK" && echo "$PYTHON_SHA256" > "$BUILD_MARKER"; } \
        || { restore_previous; fail "Setup couldn't finish writing its files. Check that your disk isn't full, then try again."; }
    rm -f "$PENDING"
    rm -rf "$RUNTIME/python-old" "$RUNTIME/venv-old" "$BUILD_MARKER.old"
    echo "Setup is complete."
    echo
fi

[ -n "$CT_INSTALL_ONLY" ] && exit 0

"$APP_PYTHON" launch.py --mac-app \
    || fail "Customizable Transcriber stopped because of a problem. Send this window's text to whoever gave you the app." \
        "If the text says the address is already in use, another copy of the app, or another program, is using port 8765."
