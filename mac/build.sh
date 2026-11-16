#!/bin/bash
# Builds "Customizable Transcriber.app" and Customizable-Transcriber-Mac.dmg into the
# folder given as the only argument. Run on a Mac with the Xcode command line tools.
#
#   mac/build.sh build/mac
#
# The app carries the files of `git archive` of CT_SOURCE_REF (default HEAD), so the same
# export-ignore rules as the GitHub ZIP apply, and uncommitted changes are not included.
#
# Signing and notarization (all optional; without them the app is ad-hoc signed, for
# local testing only):
#   CT_SIGN_IDENTITY   e.g. "Developer ID Application: Name (TEAMID)", from the keychain
#   NOTARY_KEY_PATH    App Store Connect API key (.p8)
#   NOTARY_KEY_ID      its Key ID
#   NOTARY_ISSUER_ID   its Issuer ID
# With all four, the app is notarized and stapled, then the disk image is signed,
# notarized and stapled too, so both open without a warning, even offline.
set -euo pipefail

APP_NAME="Customizable Transcriber"
DMG_NAME="Customizable-Transcriber-Mac.dmg"

[ $# -eq 1 ] || { echo "usage: $0 OUTPUT_DIR" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
OUT="$(mkdir -p "$1" && cd "$1" && pwd -P)"
IDENTITY="${CT_SIGN_IDENTITY:--}"
NOTARIZE=""
if [ -n "${NOTARY_KEY_PATH:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER_ID:-}" ]; then
    [ "$IDENTITY" != "-" ] || { echo "Notarization needs CT_SIGN_IDENTITY." >&2; exit 2; }
    NOTARIZE=1
fi

APP="$OUT/$APP_NAME.app"
DMG="$OUT/$DMG_NAME"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

notarize() {
    local result status id
    result="$(xcrun notarytool submit "$1" --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" \
        --issuer "$NOTARY_ISSUER_ID" --wait --timeout 30m --output-format json)" || true
    echo "$result"
    status="$(plutil -extract status raw -o - - <<<"$result" 2>/dev/null || true)"
    id="$(plutil -extract id raw -o - - <<<"$result" 2>/dev/null || true)"
    if [ "$status" != "Accepted" ]; then
        echo "Notarization of $(basename "$1") failed (status: ${status:-unknown})." >&2
        [ -n "$id" ] && xcrun notarytool log "$id" --key "$NOTARY_KEY_PATH" \
            --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID" >&2 || true
        exit 1
    fi
}

sign() {
    if [ "$IDENTITY" = "-" ]; then
        codesign --force --sign - "$@"
    else
        codesign --force --options runtime --timestamp --sign "$IDENTITY" "$@"
    fi
}

echo "Building $APP_NAME.app from ${CT_SOURCE_REF:-HEAD}..."
rm -rf "$APP" "$DMG"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
git -C "$ROOT" archive --format=tar "${CT_SOURCE_REF:-HEAD}" | tar -x -C "$APP/Contents/Resources/app"
VERSION="$(tr -d '[:space:]' < "$APP/Contents/Resources/app/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "VERSION is not like 1.2.3: $VERSION" >&2; exit 1; }

clang -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 -O2 -Wall -Werror \
    -o "$APP/Contents/MacOS/$APP_NAME" "$HERE/launcher.c"
sed "s/__VERSION__/$VERSION/g" "$HERE/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$HERE/launcher.sh" "$APP/Contents/Resources/launcher.sh"
chmod 755 "$APP/Contents/Resources/launcher.sh"
cp "$ROOT/static/app-icon.icns" "$APP/Contents/Resources/app-icon.icns"
xattr -cr "$APP"

sign "$APP"
codesign --verify --strict --verbose=2 "$APP"

if [ -n "$NOTARIZE" ]; then
    echo "Notarizing the app..."
    ditto -c -k --keepParent "$APP" "$WORK/app.zip"
    notarize "$WORK/app.zip"
    xcrun stapler staple "$APP"
fi

echo "Building $DMG_NAME..."
mkdir "$WORK/dmg"
ditto "$APP" "$WORK/dmg/$APP_NAME.app"
ln -s /Applications "$WORK/dmg/Applications"
hdiutil create -quiet -volname "$APP_NAME" -srcfolder "$WORK/dmg" -fs HFS+ -format UDZO -ov "$DMG"

if [ -n "$NOTARIZE" ]; then
    sign "$DMG"
    echo "Notarizing the disk image..."
    notarize "$DMG"
    xcrun stapler staple "$DMG"
    spctl --assess --type execute --verbose=2 "$APP"
    spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
fi

echo "Version $VERSION:"
echo "  $APP"
echo "  $DMG"
