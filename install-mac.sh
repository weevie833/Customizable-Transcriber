#!/bin/bash
# One-line Mac installer and updater for Customizable Transcriber. Paste into Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/weevie833/Customizable-Transcriber/main/install-mac.sh | bash
#
# Files that curl downloads carry no quarantine flag, so Gatekeeper doesn't block the start
# file the way it does after a browser download of the ZIP. This script downloads the latest
# release into ~/Library/Application Support/Customizable Transcriber/App, then runs that
# copy's "Start Customizable Transcriber (Mac).command", which installs Python and starts
# the app (and adds the app to ~/Applications). Run the same line again to update.
#
# Everything runs inside main(), called on the last line: bash reads a piped script as it
# goes, so this way nothing runs until the whole script has arrived, and nothing run from
# here can read the rest of the script from stdin.
#
# For tests: CT_APP_DIR (install folder), CT_ARCHIVE_URL (a .tar.gz of the app, skips the
# release lookup), CT_INSTALL_ONLY and CT_RUNTIME_DIR (passed to the start file).

REPO="weevie833/Customizable-Transcriber"
START_FILE="Start Customizable Transcriber (Mac).command"

fail() {
    echo
    for line in "$@"; do echo "$line"; done
    echo
    exit 1
}

# An opted-in saved-keys .env in the installed copy is carried over to the user-data folder
# (owner-readable only) before that copy is replaced, so an update can't delete a saved key
# the app still uses (reviews/CODEX_REVIEW_8.md L-4, CODEX_REVIEW_2.md L-4). The app reads
# the user-data file first and the app folder's second, per key; so a key the user-data
# file doesn't set yet is appended from the old file, line as written. Nothing already in
# the user-data file is changed. Returns 1 on any write error, and the caller then keeps
# the installed copy instead of replacing it. Never prints a key.
saved_key_line() {
    # The first line in $1 that sets key $2, as the app reads it ("KEY=value", # = comment).
    awk -v k="$2" '{ l = $0; sub(/^[ \t]+/, "", l) }
        l !~ /^#/ && index(l, "=") { n = substr(l, 1, index(l, "=") - 1); gsub(/[ \t]+$/, "", n)
        if (n == k) { print $0; exit } }' "$1" 2>/dev/null
}

keep_saved_keys() {
    local data_dir="${CT_DATA_DIR:-$HOME/Library/Application Support/Customizable Transcriber}"
    local source="$1/.env" target key line
    target="$data_dir/.env"
    [ -f "$source" ] || return 0
    mkdir -p "$data_dir" || return 1
    if [ ! -e "$target" ]; then
        (umask 077 && cp "$source" "$target") || return 1
        return 0
    fi
    for key in GEMINI_API_KEY ANTHROPIC_API_KEY; do
        line="$(saved_key_line "$source" "$key")"
        [ -n "$line" ] || continue
        [ -n "$(saved_key_line "$target" "$key")" ] && continue
        {
            [ -z "$(tail -c 1 "$target")" ] || echo
            printf '%s\n' "$line"
        } >> "$target" || return 1
    done
}

main() {
    local app_dir="${CT_APP_DIR:-$HOME/Library/Application Support/Customizable Transcriber/App}"
    local archive_url="$CT_ARCHIVE_URL" version=""

    echo
    echo "Customizable Transcriber installer"
    echo

    [ "$(uname -s)" = "Darwin" ] || fail "This installer is for a Mac."
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
        fail "This installer needs a Mac with Apple silicon (M1 or later)." \
            "On an Intel Mac, follow the manual setup in README.md:" \
            "https://github.com/$REPO#setup"
    fi

    if [ -z "$archive_url" ]; then
        # /releases/latest redirects to /releases/tag/<tag>.
        local latest
        latest="$(curl --fail --location --silent --show-error --retry 3 --output /dev/null \
            --write-out '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
            || fail "The latest version couldn't be found. Check your internet connection and try again."
        local tag="${latest##*/tag/}"
        case "$tag" in
            v[0-9]*) ;;
            *) fail "The latest version couldn't be found (GitHub answered $latest). Try again later." ;;
        esac
        version="${tag#v}"
        archive_url="https://github.com/$REPO/archive/refs/tags/$tag.tar.gz"

        if [ -f "$app_dir/$START_FILE" ] && [ "$(cat "$app_dir/VERSION" 2>/dev/null)" = "$version" ]; then
            echo "Version $version is already installed."
            start_app "$app_dir"
            return
        fi
    fi

    # Replacing the files of a running copy would leave it half old, half new.
    if [ -d "$app_dir" ] && curl --silent --output /dev/null --max-time 2 http://127.0.0.1:8765/; then
        fail "Customizable Transcriber seems to be running. Close its Terminal window" \
            "(click Terminate if asked), then paste the install line again."
    fi

    echo "Downloading Customizable Transcriber${version:+ $version}..."
    local parent new old download
    parent="$(dirname "$app_dir")"
    new="$app_dir-new"
    old="$app_dir-old"
    download="$parent/app-download.tar.gz"
    mkdir -p "$parent" || fail "The folder $parent couldn't be created."
    curl --fail --location --silent --show-error --retry 3 --output "$download" "$archive_url" \
        || fail "The app couldn't be downloaded. Check your internet connection and try again." \
            "If it keeps failing, your network may be blocking github.com."
    rm -rf "$new"
    mkdir "$new" && tar -xzf "$download" -C "$new" --strip-components 1 \
        && [ -f "$new/app.py" ] && [ -f "$new/$START_FILE" ] \
        || { rm -rf "$new" "$download"; fail "The download wasn't a complete copy of the app. Try again."; }
    rm -f "$download"
    chmod +x "$new/$START_FILE"

    # Keep the installed copy until the new one is set up, so a failed update goes back to it.
    rm -rf "$old"
    if [ -d "$app_dir" ]; then
        keep_saved_keys "$app_dir" || { rm -rf "$new"; fail "Your saved API keys (.env) couldn't be copied to the Application Support folder, so the installed copy was left as it is. Check that your disk isn't full, then try again."; }
        mv "$app_dir" "$old" || { rm -rf "$new"; fail "The installed copy couldn't be replaced."; }
    fi
    mv "$new" "$app_dir" || { [ -d "$old" ] && mv "$old" "$app_dir"; fail "The app couldn't be installed."; }

    # Python and the app's packages, without starting the app yet.
    if ! (cd "$app_dir" && CT_INSTALL_ONLY=1 "./$START_FILE" </dev/null); then
        if [ -d "$old" ]; then
            rm -rf "$app_dir"
            mv "$old" "$app_dir"
            fail "The update didn't finish, so the version you had is still installed." \
                "Check your internet connection and paste the install line again."
        fi
        fail "Setup didn't finish. Check your internet connection and paste the install line again."
    fi
    rm -rf "$old"
    echo "Installed in $app_dir"

    start_app "$app_dir"
}

start_app() {
    [ -n "$CT_INSTALL_ONLY" ] && return 0
    echo
    echo "Starting the app. Your browser opens when it is ready."
    echo "Leave this window open while you use the app; closing it stops the app."
    echo "Next time, start it from \"Customizable Transcriber\" in your Applications folder."
    echo
    cd "$1" || fail "The app's folder is missing: $1"
    # The start file waits for Return after an error, so give it the keyboard, not this pipe.
    if [ -r /dev/tty ]; then
        exec "./$START_FILE" </dev/tty
    fi
    exec "./$START_FILE" </dev/null
}

main "$@"
