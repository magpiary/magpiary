#!/bin/sh
# Magpiary installer for macOS. Paste into Terminal:
#   curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install.sh | sh
#
# It installs, for your user only (no password, no Homebrew needed):
#   uv (runs Python programs), yt-dlp (downloads posts), Magpiary,
#   ffmpeg, ffprobe and Deno if this Mac does not have them (checked copies),
#   the transcript and meaning models (about 600 MB), and the background service.
# Then it runs a health check and opens the setup page. Safe to run again: it updates what is there.
#
# Options (environment variables): MAGPIARY_SOURCE (where Magpiary is installed from),
# MAGPIARY_PORT (default: 8765 for the first Mac account, the next one up for the next), MAGPIARY_NO_SERVICE=1 and MAGPIARY_NO_OPEN=1 (used by the install test).
set -eu

UV_VERSION="0.13.0"
# The reviewed release this script installs, by its exact commit (a commit cannot be changed later, a branch can).
# The release steps update both lines after tagging.
RELEASE="0.1.8"
RELEASE_COMMIT="28acaeb21d8682e0a4eec61d87df91d9bce19e90"
SOURCE="${MAGPIARY_SOURCE:-magpiary @ git+https://github.com/magpiary/magpiary@$RELEASE_COMMIT}"
PORT="${MAGPIARY_PORT:-$((8765 + ($(id -u) - 501) % 20))}"   # one port per Mac account
BIN="$HOME/.local/bin"

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "Magpiary runs on macOS only."
[ "$(uname -m)" = "arm64" ] || fail "Magpiary needs a Mac with Apple Silicon (M1 or newer); this Mac has $(uname -m)."
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 14 ] 2>/dev/null || fail "Magpiary needs macOS 14 or newer; this Mac has $(sw_vers -productVersion)."

export PATH="$BIN:$PATH"

step "1/7  uv"
if command -v uv >/dev/null 2>&1; then
  echo "Already here: $(uv --version)"
else
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh
  command -v uv >/dev/null 2>&1 || fail "uv did not install. See https://docs.astral.sh/uv/"
fi

step "2/7  yt-dlp"
uv tool install --upgrade --python 3.12 yt-dlp

step "3/7  Magpiary $RELEASE"
uv tool install --force --python 3.12 "$SOURCE"
command -v magpiary >/dev/null 2>&1 || fail "Magpiary did not install."
magpiary --version

step "4/7  ffmpeg, ffprobe and a JavaScript runtime"
magpiary tools install

step "5/7  Models (transcripts and meaning, about 600 MB the first time)"
magpiary models install

step "6/7  Background service"
if [ "${MAGPIARY_NO_SERVICE:-}" = "1" ]; then
  echo "Skipped (MAGPIARY_NO_SERVICE=1)."
else
  magpiary service install --port "$PORT"
fi

step "7/7  Health check"
magpiary doctor --offline --port "$PORT" || true

# Make the magpiary command available in new Terminal windows.
# (A fresh login shell, so the PATH set above does not count.)
case ":$(env -i HOME="$HOME" USER="${USER:-}" /bin/zsh -lic 'echo $PATH' 2>/dev/null):" in
  *":$BIN:"*) ;;
  *) printf '\n# Added by the Magpiary installer\nexport PATH="%s:$PATH"\n' "$BIN" >> "$HOME/.zprofile"
     echo "Added $BIN to your PATH in ~/.zprofile (new Terminal windows will find magpiary)." ;;
esac

step "Done."
echo "Magpiary's library: http://localhost:$PORT/  (the setup page walks you through pairing your iPhone)"
if [ "${MAGPIARY_NO_OPEN:-}" != "1" ] && [ "${MAGPIARY_NO_SERVICE:-}" != "1" ]; then
  sleep 2
  open "http://localhost:$PORT/" || true
fi
