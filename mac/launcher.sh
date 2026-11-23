#!/bin/bash
# Run by the signed "Customizable Transcriber.app" (Contents/MacOS/... execs this file).
#
# The app carries a copy of the app's files (Resources/app). On each open it:
#   1. just opens the browser if the app is already running;
#   2. copies its files to ~/Library/Application Support/Customizable Transcriber/App when
#      nothing is installed there yet or what is there is older (so a newer copy installed
#      with the one-line Terminal installer is never replaced by an older app);
#   3. opens that copy's start file in Terminal, which installs Python on first use and
#      starts the app, exactly as a double-click on the start file does.
# The copy is made without the download quarantine flag, so Gatekeeper doesn't ask about
# the start file: Apple has already checked the whole app (it is notarized).
#
# For tests: CT_APP_DIR, CT_RUNTIME_DIR, CT_SERVER_URL, and CT_LAUNCH_DRY_RUN=1 (print
# what would be opened instead of opening it).

START_FILE="Start Customizable Transcriber (Mac).command"
TITLE="Customizable Transcriber"

say() {
    # A dialog, since an app opened from Finder has no window to print to.
    if [ -n "$CT_LAUNCH_DRY_RUN" ]; then
        echo "dialog: $1"
        return
    fi
    /usr/bin/osascript -e 'on run argv' \
        -e 'display dialog (item 1 of argv) buttons {"OK"} default button 1 with title (item 2 of argv) with icon caution' \
        -e 'end run' "$1" "$TITLE" >/dev/null 2>&1
}

fail() {
    say "$1"
    exit 1
}

open_target() {
    if [ -n "$CT_LAUNCH_DRY_RUN" ]; then
        echo "open $*"
    else
        /usr/bin/open "$@"
    fi
}

# 0 when version $1 is older than version $2 (both like 0.5.4); anything unreadable is older.
older_than() {
    local IFS=.
    local -a a=($1) b=($2)
    local i
    for i in 0 1 2; do
        local x="${a[$i]:-0}" y="${b[$i]:-0}"
        [[ "$x" =~ ^[0-9]+$ ]] || return 0
        [[ "$y" =~ ^[0-9]+$ ]] || return 1
        if (( 10#$x < 10#$y )); then return 0; fi
        if (( 10#$x > 10#$y )); then return 1; fi
    done
    return 1
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

# 0 only when $1 answers HTTP 200 with a JSON object whose top-level "app" is this app's
# id -- the same rule as launch.py's probe_server() (CODEX_REVIEW_2.md L-1). The body is
# capped at 4 KB and parsed as JSON (plutil), not searched for a substring; redirects are
# not followed and don't count.
health_is_ours() {
    local response status body
    response="$(curl --silent --max-time 2 --max-redirs 0 --max-filesize 4096 \
        --write-out $'\n%{http_code}' "$1" 2>/dev/null)" || return 1
    status="${response##*$'\n'}"
    body="${response%$'\n'*}"
    [ "$status" = "200" ] || return 1
    [[ "$body" =~ ^[[:space:]]*\{ ]] || return 1
    [ "$(printf '%s' "$body" | /usr/bin/plutil -extract app raw -o - - 2>/dev/null)" = "customizable-transcriber" ]
}

main() {
    local resources bundle bundled app_dir runtime url
    resources="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
    bundle="$(cd "$resources/../.." && pwd -P)"
    bundled="$resources/app"
    app_dir="${CT_APP_DIR:-$HOME/Library/Application Support/Customizable Transcriber/App}"
    runtime="${CT_RUNTIME_DIR:-$HOME/Library/Application Support/Customizable Transcriber/Runtime}"
    url="${CT_SERVER_URL:-http://127.0.0.1:8765/}"

    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
        say "Customizable Transcriber needs a Mac with Apple silicon (M1 or later). On an Intel Mac, follow the manual setup in the README on GitHub."
        open_target "https://github.com/weevie833/Customizable-Transcriber#setup"
        exit 1
    fi

    # Opened straight from the disk image (or from Downloads, where macOS runs it from a
    # temporary read-only copy): it would work once, then be gone when the disk is ejected.
    case "$bundle" in
        /Volumes/*|*/AppTranslocation/*)
            fail "Drag Customizable Transcriber into your Applications folder first, then open it from there."
            ;;
    esac

    # Only this app's own health answer counts as "already running"; any other
    # listener on the port is a conflict, not something to open
    # (reviews/CODEX_REVIEW_8.md L-1).
    if health_is_ours "${url}api/health"; then
        open_target "$url"
        exit 0
    fi
    if curl --silent --output /dev/null --max-time 2 "$url"; then
        fail "Another program is already using port 8765 on this Mac, so Customizable Transcriber can't start. Quit that program (or restart the Mac) and try again."
    fi

    [ -f "$bundled/VERSION" ] && [ -f "$bundled/$START_FILE" ] \
        || fail "This copy of Customizable Transcriber is damaged. Download it again from GitHub."

    local installed=""
    [ -f "$app_dir/$START_FILE" ] && installed="$(cat "$app_dir/VERSION" 2>/dev/null)"
    if [ -z "$installed" ] || older_than "$installed" "$(cat "$bundled/VERSION")"; then
        local parent new old
        parent="$(dirname "$app_dir")"
        new="$app_dir-new"
        old="$app_dir-old"
        mkdir -p "$parent" || fail "The folder $parent couldn't be created."
        rm -rf "$new" "$old"
        /usr/bin/ditto --noqtn "$bundled" "$new" \
            || { rm -rf "$new"; fail "Customizable Transcriber couldn't be installed. Is your disk full?"; }
        /usr/bin/xattr -dr com.apple.quarantine "$new" 2>/dev/null
        chmod +x "$new/$START_FILE"
        if [ -d "$app_dir" ]; then
            keep_saved_keys "$app_dir" || { rm -rf "$new"; fail "Your saved API keys (.env) couldn't be copied to the Application Support folder, so the installed copy was left as it is. Check that your disk isn't full, then try again."; }
            mv "$app_dir" "$old" || { rm -rf "$new"; fail "The installed copy couldn't be replaced."; }
        fi
        mv "$new" "$app_dir" || { [ -d "$old" ] && mv "$old" "$app_dir"; fail "Customizable Transcriber couldn't be installed."; }
        rm -rf "$old"
    fi

    # Tells the start file that this app exists, so it doesn't add its own small
    # "Customizable Transcriber" to ~/Applications as well (launch.py reads this).
    mkdir -p "$runtime" && printf '%s' "$bundle" > "$runtime/signed-app.txt"

    open_target -a Terminal "$app_dir/$START_FILE"
}

main "$@"
