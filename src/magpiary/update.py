"""Updating and removing Magpiary.

Once a day the service asks GitHub for the latest release's version number (no details about the owner are
sent; GitHub sees an ordinary request). If it is newer, the hub shows a banner. Updating reinstalls Magpiary
with uv from that release; the service then exits and launchd starts the new copy (KeepAlive).
The Mac app cannot replace itself (it is unsigned, and it never writes into its own folder): the banner sends the owner to
the release page for the new `.dmg`, and the app restarts the service when it first opens at a new version.
`MAGPIARY_SOURCE` points the update at another source (a local folder in tests and before the first release).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date

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
        return f"The Mac app updates by replacing it. Quit Magpiary, download the new version from {RELEASES_PAGE} and drag it to Applications."
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

