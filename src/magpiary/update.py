"""Updating and removing Magpiary.

Once a day the service asks GitHub for the latest release's version number (no details about the owner are
sent; GitHub sees an ordinary request). If it is newer, the hub shows a banner. Updating reinstalls Magpiary
with uv from that release; the service then exits and launchd starts the new copy (KeepAlive).
The Mac app cannot replace itself while it runs, so "Update now" downloads the offered version's `.dmg` (fetched by Python,
so macOS does not mark it as downloaded from the internet), checks it against that release's SHA256SUMS, and starts a small
helper that outlives the app: it checks the bundle and version, quits Magpiary, swaps the copy in Applications, opens it,
and puts the old copy back if the new one does not start. The checksum comes from the same GitHub release as the image:
it catches a broken download, not a compromised release account (the Homebrew and uv routes trust GitHub the same way). The app restarts the service when it first
opens at a new version. If the app's folder is not writable, the banner falls back to the release page.
`MAGPIARY_SOURCE` points the update at another source (a local folder in tests and before the first release).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import hashlib
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from magpiary import __version__
from magpiary.config import config_dir, data_dir
from magpiary.tools import find, in_mac_app

REPO = "magpiary/magpiary"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
LATEST_SETTING, CHECKED_SETTING = "latest_version", "version_checked_on"
CHECK_SETTING = "version_check"  # "0" when the owner turned the daily check off (Settings → Library & this Mac)

Get = Callable[[str], tuple[int, bytes]]
Run = Callable[[list[str], int], subprocess.CompletedProcess]


def _get(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"Magpiary/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read(200_000)
    except urllib.error.HTTPError as err:
        return err.code, b""


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


DMG_NAME = "Magpiary.dmg"
RELEASE_BASE = f"https://github.com/{REPO}/releases/download"  # + /v<version>/<file>: the version the banner offered
BUNDLE_ID = "org.magpiary.app"
MAX_DMG, MAX_SUMS, DOWNLOAD_DEADLINE = 800_000_000, 64_000, 900  # bytes, bytes, seconds (review 15 Nov 2026)
# Runs after the hub has answered, detached from it. Arguments: disk image, app path, work folder, version, result file.
# One helper at a time (a lock folder beside the app); checks the image holds Magpiary at the expected version before
# quitting anything; replaces the app through unique sibling copies; keeps the old app until the new one is running and
# puts it back if the new one does not start. The result goes to a file outside the work folder for the hub to show.
HELPER = r"""#!/bin/bash
DMG="$1"; APP="$2"; WORK="$3"; WANT="$4"; RESULT="$5"
LOG="$WORK/update.log"; LOCK="$APP.updating"
exec >"$LOG" 2>&1
finish() { mkdir -p "$(dirname "$RESULT")"; printf '%s\t%s\t%s\n' "$1" "$WANT" "$2" > "$RESULT"; cp "$LOG" "$RESULT.log" 2>/dev/null; }
mkdir "$LOCK" 2>/dev/null || { echo "another update is running"; exit 1; }
MOUNT=""
cleanup() { [ -z "$MOUNT" ] || hdiutil detach "$MOUNT" -quiet -force >/dev/null 2>&1; rmdir "$LOCK" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT
sleep 3
MOUNT="$(hdiutil attach "$DMG" -nobrowse -readonly -noautoopen | awk -F'\t' '/\/Volumes\// { print $NF; exit }')"
SRC="$MOUNT/Magpiary.app"
plist() { /usr/libexec/PlistBuddy -c "Print $1" "$SRC/Contents/Info.plist" 2>/dev/null; }
[ -n "$MOUNT" ] && [ -x "$SRC/Contents/MacOS/Magpiary" ] || { finish failed "The download did not contain Magpiary."; exit 1; }
[ "$(plist CFBundleIdentifier)" = "org.magpiary.app" ] && [ "$(plist CFBundleShortVersionString)" = "$WANT" ] \
  || { finish failed "The download was not Magpiary $WANT."; exit 1; }
EXE="$APP/Contents/MacOS/Magpiary"
pids() { ps -axo pid=,comm= | awk -v exe="$EXE" '{ p=$1; sub(/^ *[0-9]+ /, ""); if ($0 == exe) print p }'; }
osascript -e "tell application (POSIX file \"$APP\" as text) to quit" >/dev/null 2>&1
for _ in $(seq 1 30); do [ -z "$(pids)" ] && break; sleep 1; done
for p in $(pids); do kill "$p" 2>/dev/null; done
sleep 1
[ -z "$(pids)" ] || { finish failed "Magpiary did not quit, so nothing was changed."; open "$APP"; exit 1; }
STAMP="$(date +%s).$$"; NEW="$APP.new-$STAMP"; OLD="$APP.old-$STAMP"
if ! ditto "$SRC" "$NEW"; then rm -rf "$NEW"; finish failed "The new version could not be copied; the old one is kept."; open "$APP"; exit 1; fi
if ! mv "$APP" "$OLD"; then rm -rf "$NEW"; finish failed "The old version could not be moved aside; it is kept."; open "$APP"; exit 1; fi
if ! mv "$NEW" "$APP"; then mv "$OLD" "$APP"; rm -rf "$NEW"; finish failed "The new version could not be put in place; the old one is back."; open "$APP"; exit 1; fi
open "$APP"
for _ in $(seq 1 20); do [ -n "$(pids)" ] && break; sleep 1; done
if [ -n "$(pids)" ]; then rm -rf "$OLD"; finish ok "Updated to Magpiary $WANT."
else rm -rf "$APP"; mv "$OLD" "$APP"; finish failed "Magpiary $WANT did not start, so the old version is back."; open "$APP"; fi
"""
RESULT_NAME = "update-result.txt"


def result_path() -> Path:
    """Where the helper leaves how the last Mac-app update went (status, version, message), for the hub to show."""
    return data_dir() / RESULT_NAME


def last_result() -> tuple[str, str, str] | None:
    """(status "ok" or "failed", version, message) of the last Mac-app update, or None."""
    try:
        status, version, message = result_path().read_text(errors="ignore").rstrip("\n").split("\t", 2)
    except (OSError, ValueError):
        return None
    return (status, version, message[:300]) if status in ("ok", "failed") else None


def app_path() -> Path | None:
    """The Magpiary.app this program runs from (the nearest enclosing bundle), or None outside the Mac app."""
    program = os.environ.get("MAGPIARY_PROGRAM", "")
    head, marker, _ = program.rpartition(".app/Contents/")
    if not marker:
        return None
    app = Path(head + ".app")
    return app if app.name == "Magpiary.app" else None


def _download(url: str, to: Path, limit: int = MAX_DMG, deadline: float = DOWNLOAD_DEADLINE) -> bool:
    """Save `url` to `to`; False past `limit` bytes or `deadline` seconds, or on any error (the partial file is removed)."""
    import time

    request = urllib.request.Request(url, headers={"User-Agent": f"Magpiary/{__version__}"})
    stop = time.monotonic() + deadline
    try:
        with urllib.request.urlopen(request, timeout=60) as response, to.open("wb") as out:
            got = 0
            while chunk := response.read(1 << 20):
                got += len(chunk)
                if got > limit or time.monotonic() > stop:
                    raise OSError("too large or too slow")
                out.write(chunk)
        return True
    except (OSError, urllib.error.URLError, ValueError):
        to.unlink(missing_ok=True)
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def install_app(version: str, download: Callable[..., bool] = _download,
                spawn: Callable[[list[str]], object] | None = None) -> str | None:
    """Download and check that version's disk image, then start the helper that swaps the app in. Returns an error to
    show, or None. The helper quits the app itself, a few seconds after this returns."""
    app = app_path()
    if app is None or not app.is_dir():
        return "Magpiary is not running from the Mac app."
    if not parse(version) or not newer(version):
        return "There is no newer version."
    if not os.access(app.parent, os.W_OK):
        return f"Magpiary cannot replace itself in {app.parent}. Download the new version from {RELEASES_PAGE} and drag it to Applications."
    if Path(f"{app}.updating").exists():
        return "An update is already running. Magpiary will close and open again by itself."
    base = f'{os.environ.get("MAGPIARY_RELEASE_BASE", RELEASE_BASE)}/v{version}'
    name = f"Magpiary-{version}.dmg"
    work = Path(tempfile.mkdtemp(prefix="magpiary-update-"))
    dmg, sums = work / DMG_NAME, work / "SHA256SUMS"
    fail = f"The update could not be downloaded or checked, so nothing changed. You can download it from {RELEASES_PAGE}."
    if not download(f"{base}/{name}", dmg, MAX_DMG) or not download(f"{base}/SHA256SUMS", sums, MAX_SUMS):
        shutil.rmtree(work, ignore_errors=True)
        return fail
    want = next((line.split()[0].lower() for line in sums.read_text(errors="ignore").splitlines()
                 if len(line.split()) == 2 and line.split()[1].lstrip("*") == name), "")
    if not want or want != _sha256(dmg):
        shutil.rmtree(work, ignore_errors=True)
        return "The download did not match its published checksum, so it was not installed."
    script = work / "helper.sh"
    script.write_text(HELPER)
    script.chmod(0o700)
    result_path().unlink(missing_ok=True)
    command = ["/bin/bash", str(script), str(dmg), str(app), str(work), version, str(result_path())]
    (spawn or (lambda c: subprocess.Popen(c, start_new_session=True, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))(command)
    return None


def parse(version: str) -> tuple[int, ...]:
    if not isinstance(version, str) or not re.fullmatch(r"v?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        return ()
    return tuple(int(p) for p in version.removeprefix("v").split("."))


def newer(candidate: str, current: str = __version__) -> bool:
    return parse(candidate) > parse(current) if parse(candidate) and parse(current) else False


def latest(get: Get = _get) -> str:
    """The newest release's version, or "" if GitHub cannot say (no release yet, offline, private)."""
    try:
        status, body = get(f"https://api.github.com/repos/{REPO}/releases/latest")
        tag = json.loads(body).get("tag_name", "") if status == 200 else ""
        return tag.removeprefix("v") if parse(tag) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def check_daily(store, get: Get = _get, today: str | None = None) -> str:
    """Ask at most once a day, unless turned off. Returns the newer version waiting, or ""."""
    today = today or date.today().isoformat()
    if store.get_setting(CHECK_SETTING, "1") != "0" and store.get_setting(CHECKED_SETTING) != today:
        store.set_setting(CHECKED_SETTING, today)
        found = latest(get)
        if found:
            store.set_setting(LATEST_SETTING, found)
    waiting = store.get_setting(LATEST_SETTING, "")
    return waiting if newer(waiting) else ""


def from_homebrew() -> bool:
    """Installed with `brew install`: Homebrew updates it, not Magpiary."""
    return "/Cellar/" in sys.executable or "/opt/homebrew/opt/" in sys.executable


def source(version: str) -> str:
    return os.environ.get("MAGPIARY_SOURCE") or \
        f"magpiary @ https://github.com/{REPO}/archive/refs/tags/v{version}.tar.gz"


def install(version: str, run: Run = _run) -> str | None:
    """Install that version with uv. Returns an error to show, or None."""
    if not parse(version):
        return "The release version is invalid. Check for a new version again."
    if in_mac_app():
        return install_app(version)
    if from_homebrew():
        return "Magpiary was installed with Homebrew. Update it in Terminal: brew upgrade magpiary"
    uv = find("uv")
    if not uv:
        return "uv is missing. Run the installer again."
    result = run([uv, "tool", "install", "--force", "--python", "3.12", source(version)], 900)
    if result.returncode != 0:
        return "The update did not install. Try again in Terminal with a reviewed release source."
    run([uv, "tool", "upgrade", "yt-dlp"], 300)
    return None


def remove(delete_library: bool, run: Run = _run) -> list[str]:
    """Take Magpiary off this Mac. The library and settings stay unless `delete_library`. Returns what was done."""
    from magpiary import service

    done = [service.uninstall()]
    for folder in (data_dir() / "tools", data_dir() / "models"):
        if folder.exists():
            shutil.rmtree(folder)
            done.append(f"Removed {folder}.")
    if delete_library:
        for folder in (data_dir(), config_dir(), service.log_path().parent):
            if folder.exists():
                shutil.rmtree(folder)
                done.append(f"Deleted {folder}.")
    else:
        done.append(f"Kept your library in {data_dir()} and settings in {config_dir()}.")
    uv = find("uv")
    if uv:
        run([uv, "tool", "uninstall", "magpiary"], 120)
        done.append("Removed the magpiary command.")
    done.append("Kept yt-dlp and uv (other programs may use them): uv tool uninstall yt-dlp removes yt-dlp.")
    return done

