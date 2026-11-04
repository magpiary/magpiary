#!/bin/sh
# Magpiary Mac app, installed from Terminal. Paste into Terminal:
#   curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install-app.sh | sh
#
# Why this exists: the app is not signed with a paid Apple account, so a disk image downloaded in a browser makes macOS ask for
# "Open Anyway". A file fetched by curl is not marked as downloaded from the internet, so macOS has nothing to block: the app
# opens like any other. The script downloads the latest disk image from GitHub, checks it against the published checksum,
# copies Magpiary into Applications and opens it. Nothing else is changed. Safe to run again: it replaces the app.
#
# Options (environment variables): MAGPIARY_DMG_URL and MAGPIARY_SUMS_URL (where to download from; used by the install test),
# MAGPIARY_APP_DIR (where to put the app, default /Applications) and MAGPIARY_NO_OPEN=1 (do not open the app afterwards).
set -eu

BASE="https://github.com/magpiary/magpiary/releases/latest/download"
DMG_URL="${MAGPIARY_DMG_URL:-$BASE/Magpiary.dmg}"
SUMS_URL="${MAGPIARY_SUMS_URL:-$BASE/SHA256SUMS}"
APP_DIR="${MAGPIARY_APP_DIR:-/Applications}"
APP="$APP_DIR/Magpiary.app"

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "Magpiary runs on macOS only."
[ "$(uname -m)" = "arm64" ] || { printf '\nMagpiary needs a Mac with Apple Silicon (M1 or newer).\n' >&2; exit 1; }

WORK="$(mktemp -d)"
MOUNT=""
cleanup() { [ -z "$MOUNT" ] || hdiutil detach "$MOUNT" -quiet -force >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

step "1/4  Downloading Magpiary (about 110 MB)"
curl -fL --progress-bar -o "$WORK/Magpiary.dmg" "$DMG_URL" || fail "The download did not work. Check your internet connection and try again."

step "2/4  Checking the download"
curl -fsSL -o "$WORK/SHA256SUMS" "$SUMS_URL" || fail "Could not get the checksum list."
WANT="$(awk '$2 ~ /^Magpiary(-[0-9.]+)?\.dmg$/ { print $1; exit }' "$WORK/SHA256SUMS")"
HAVE="$(shasum -a 256 "$WORK/Magpiary.dmg" | awk '{print $1}')"
[ -n "$WANT" ] || fail "The checksum list has no entry for the disk image."
[ "$WANT" = "$HAVE" ] || fail "The download did not match its published checksum, so it was not installed."
echo "Checksum matches."

step "3/4  Putting Magpiary in Applications"
MOUNT="$(hdiutil attach "$WORK/Magpiary.dmg" -nobrowse -readonly -noautoopen 2>/dev/null | awk -F'\t' '/\/Volumes\// { print $NF; exit }')"
[ -d "$MOUNT/Magpiary.app" ] || fail "The disk image did not contain Magpiary.app."
osascript -e 'tell application "Magpiary" to quit' >/dev/null 2>&1 || true
rm -rf "$APP"
mkdir -p "$APP_DIR"
ditto "$MOUNT/Magpiary.app" "$APP" || fail "Could not copy into $APP_DIR. If you are not an administrator, ask one to run this."
echo "Installed $APP"

step "4/4  Opening Magpiary"
if [ "${MAGPIARY_NO_OPEN:-}" = "1" ]; then
  echo "Done. Open Magpiary from Applications."
else
  open "$APP"
  echo "Magpiary is opening. A window shows the setup (about 720 MB of downloads, a few minutes). Nothing else is needed."
fi
