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

fail() {
    echo
    for line in "$@"; do echo "$line"; done
    echo
    if [ -z "$CT_INSTALL_ONLY" ]; then read -r -p "Press Return to close this window. "; fi
    exit 1
}

printf '\033]0;Customizable Transcriber\007'

[ -f "app.py" ] || fail "This file has to stay in the app's folder, next to app.py." \
    "Open the folder you downloaded and double-click it there."

if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
    fail "This installer needs a Mac with Apple silicon (M1 or later)." \
        "On an Intel Mac, follow the manual setup in README.md instead."
fi

if [ -x "$APP_PYTHON" ] && [ -f "$INSTALLED_LOCK" ] && cmp -s "requirements.lock" "$INSTALLED_LOCK"; then
    :    # already installed with these exact package versions: just start
else
    echo
    echo "Setting up Customizable Transcriber. This happens once and takes a few minutes."
    echo "Please leave this window open, and stay connected to the internet."
    echo
    mkdir -p "$RUNTIME" || fail "The folder $RUNTIME couldn't be created."

    if [ ! -x "$BASE_PYTHON" ]; then
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
        rm -rf "$RUNTIME/python-new" "$RUNTIME/python"
        mkdir "$RUNTIME/python-new" \
            && tar -xzf "$DOWNLOAD" -C "$RUNTIME/python-new" \
            && mv "$RUNTIME/python-new/python" "$RUNTIME/python" \
            || fail "Python couldn't be unpacked. Try again. If it keeps failing, send this message to whoever gave you the app."
        rm -rf "$RUNTIME/python-new" "$DOWNLOAD"
    fi

    echo "Step 2 of 2: installing the app's components..."
    "$BASE_PYTHON" -m venv --clear "$RUNTIME/venv" \
        && "$APP_PYTHON" -m pip install --quiet --disable-pip-version-check --no-input --only-binary=:all: -r requirements.lock \
        || fail "The app's components couldn't be installed. Check your internet connection and try again." \
            "If it keeps failing, your network may be blocking pypi.org. Send this window's text to whoever gave you the app."
    cp "requirements.lock" "$INSTALLED_LOCK"
    echo "Setup is complete."
    echo
fi

[ -n "$CT_INSTALL_ONLY" ] && exit 0

"$APP_PYTHON" launch.py --mac-app \
    || fail "Customizable Transcriber stopped because of a problem. Send this window's text to whoever gave you the app." \
        "If the text says the address is already in use, another copy of the app, or another program, is using port 8765."
