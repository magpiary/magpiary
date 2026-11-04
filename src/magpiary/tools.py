"""The outside programs M2 relies on: yt-dlp (downloads), uv (updates yt-dlp) and ffprobe (video length).

yt-dlp ships inside Magpiary's own environment and updates itself daily (uv or pip); an older separate install is still found. The Mac app never changes its
own folder, so there the updates go to `ytdlp_updates_dir()`, which the app's yt-dlp launcher prefers. It gets the owner's Instagram login (a cookies file) only for an item they asked to try with it.
Every call goes through an injected `run`, so tests replay recorded output.
"""

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from magpiary.config import data_dir

Run = Callable[[list[str], int], subprocess.CompletedProcess]

VIDEO_FORMAT = "res:720,ext:mp4:m4a"  # up to 720p, mp4 where offered (owner's choice)
UPDATE_SETTING = "ytdlp_updated_on"


def default_run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def tools_dir() -> Path:
    """Standalone copies of ffmpeg, ffprobe and Deno, for Macs without Homebrew."""
    return data_dir() / "tools"


def in_mac_app() -> bool:
    """Running from Magpiary.app, whose launcher names itself here; there is no `magpiary` command in Terminal then."""
    return ".app/Contents/" in os.environ.get("MAGPIARY_PROGRAM", "")


def ytdlp_updates_dir() -> Path:
    """The Mac app's newer yt-dlp. packaging/app/build-app.sh's launcher looks here too; keep the two in step."""
    return tools_dir() / "yt-dlp-updates"


def find(name: str) -> str | None:
    """Look beside Magpiary first (a Homebrew install keeps the yt-dlp it updates there), then the PATH, then where
    uv, Homebrew and Magpiary's own tools folder put programs; the service's PATH is short."""
    extra = [str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin", str(tools_dir())]
    return shutil.which(name, path=os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", ""), *extra]))


class ToolMissing(Exception):
    pass


class YtDlpError(Exception):
    """yt-dlp gave up. `reason` is one of the needs-attention reasons."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason, self.detail = reason, detail


# (text in yt-dlp's error, reason); first match wins
_ERRORS = [
    ("unsupported url", "unsupported"),
    ("no video could be found", "no_video"),
    ("there is no video in this", "no_video"),
    ("no video formats found", "no_video"),
    ("private", "private"),
    ("rate-limit", "rate_limited"),
    ("rate limit", "rate_limited"),
    ("too many requests", "rate_limited"),
    ("http error 429", "rate_limited"),
    ("empty media response", "rate_limited"),  # Instagram's transient refusal (S1)
    ("login required", "login_wall"),
    ("log in", "login_wall"),
    ("cookies", "login_wall"),
    ("authentication", "login_wall"),
    ("removed", "deleted"),
    ("deleted", "deleted"),
    ("not available", "deleted"),
    ("does not exist", "deleted"),
    ("http error 404", "deleted"),
]


def classify(stderr: str) -> tuple[str, str]:
    lines = [ln for ln in stderr.splitlines() if ln.startswith("ERROR")] or stderr.strip().splitlines() or [""]
    message = lines[-1].removeprefix("ERROR:").strip()
    low = message.lower()
    for needle, reason in _ERRORS:
        if needle in low:
            return reason, message[:200]
    return "unknown", message[:200]


class YtDlp:
    def __init__(self, run: Run = default_run, binary: str | None = None, cookies: Path | None = None, proxy: str = ""):
        self.run = run
        self.proxy = proxy
        self.binary = binary or find("yt-dlp")
        self.cookies = cookies

    def _base(self, progress: bool = False) -> list[str]:
        if not self.binary:
            raise ToolMissing("yt-dlp is not installed. Reinstall Magpiary, or run: uv tool install yt-dlp")
        command = [self.binary, "--no-warnings", "--ignore-config", "--no-cache-dir"]
        command += ["--newline", "--progress-template", "download:MAGPIARY_PCT %(progress._percent_str)s"] if progress \
            else ["--no-progress"]
        runtime = next(((name, path) for name in ("deno", "node") if (path := find(name))), None)
        if runtime:
            command += ["--js-runtimes", f"{runtime[0]}:{runtime[1]}"]  # YouTube needs a JavaScript runtime (S1)
        ffmpeg = find("ffmpeg")
        if ffmpeg:
            command += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
        if self.cookies:
            command += ["--cookies", str(self.cookies)]
        if self.proxy:
            command += ["--proxy", self.proxy]
        return command

    def info(self, url: str) -> dict:
        """The post's details. Slides yt-dlp cannot read (photos in a carousel) come back as None."""
        result = self.run([*self._base(), "--ignore-errors", "-J", url], 120)
        out = result.stdout.strip()
        if not out or out == "null":
            raise YtDlpError(*classify(result.stderr))
        return json.loads(out)

    def download(self, url: str, folder: Path, on_progress: Callable[[float], None] | None = None) -> None:
        """Media (and a thumbnail) into `folder` as media-01.mp4, media-02.jpg, ..."""
        run = self.run if on_progress is None else lambda cmd, timeout: stream(cmd, timeout, on_progress)
        result = run([*self._base(on_progress is not None), "--ignore-errors", "-S", VIDEO_FORMAT, "--merge-output-format", "mp4",
                           "--write-thumbnail", "--convert-thumbnails", "jpg",
                           "-o", str(folder / "media-%(autonumber)02d.%(ext)s"),
                           "-o", "thumbnail:" + str(folder / "thumbnail.%(ext)s"), url], 3600)
        for leftover in folder.glob("media-*"):
            if leftover.suffix in UNFINISHED or ".part-Frag" in leftover.name:
                leftover.unlink(missing_ok=True)  # a download cut short: never mistaken for the post's media
        if result.returncode != 0 and not media_files(folder):
            raise YtDlpError(*classify(result.stderr))

    def version(self) -> str:
        try:
            return self.run([*self._base(), "--version"], 30).stdout.strip()
        except (ToolMissing, OSError, subprocess.SubprocessError):
            return ""


UNFINISHED = {".part", ".ytdl", ".temp", ".tmp"}


def media_files(folder: Path) -> list[Path]:
    """The finished media in a download folder (media-01.mp4, ...), never a part file yt-dlp left behind."""
    return sorted(p for p in folder.glob("media-*") if p.is_file() and p.suffix not in UNFINISHED and ".part-Frag" not in p.name)


def stream(command: list[str], timeout: int, on_progress: Callable[[float], None]) -> subprocess.CompletedProcess:
    """Run yt-dlp, reporting its download percentage as it goes."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    out = []
    try:
        for line in proc.stdout:
            if line.startswith("MAGPIARY_PCT"):
                try:
                    on_progress(float(line.split()[-1].rstrip("%")))
                except ValueError:
                    pass
            else:
                out.append(line)
        stderr = proc.stderr.read()
        proc.wait()
    finally:
        timer.cancel()
    return subprocess.CompletedProcess(command, proc.returncode, "".join(out), stderr)


def _update_ytdlp_outside_app(run: Run) -> bool:
    """Fetch the newest yt-dlp beside the app, not into it (that would break the app's seal). The copy in use is swapped
    only once the new one has started, so a bad or partial download changes nothing."""
    target = ytdlp_updates_dir()
    new, old = target.with_name(target.name + ".new"), target.with_name(target.name + ".old")
    shutil.rmtree(new, ignore_errors=True)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fetched = run([sys.executable, "-B", "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check", "--no-deps",
                       "--target", str(new), "yt-dlp"], 300)
        works = run(["/usr/bin/env", f"PYTHONPATH={new}", sys.executable, "-B", "-m", "yt_dlp", "--version"], 30)
        if fetched.returncode != 0 or works.returncode != 0 or not works.stdout.strip():
            raise OSError("the new yt-dlp did not start")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        new.rename(target)
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(new, ignore_errors=True)
        return False
    shutil.rmtree(old, ignore_errors=True)
    return True


def update_ytdlp(store, run: Run = default_run, today: str | None = None, force: bool = False) -> bool:
    """Upgrade yt-dlp at most once a day. Returns True if an upgrade was run."""
    today = today or datetime.now().date().isoformat()
    if not force and store.get_setting(UPDATE_SETTING) == today:
        return False
    if in_mac_app():
        store.set_setting(UPDATE_SETTING, today)
        return _update_ytdlp_outside_app(run)
    uv = find("uv")
    ytdlp = find("yt-dlp") or ""
    beside = Path(ytdlp).parent == Path(sys.executable).parent  # yt-dlp lives in Magpiary's own environment (the app, Homebrew)
    if uv:
        command = [uv, "pip", "install", "--upgrade", "--python", sys.executable, "yt-dlp"] if beside else [uv, "tool", "upgrade", "yt-dlp"]
    elif beside:
        command = [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp"]
    else:
        return False
    store.set_setting(UPDATE_SETTING, today)
    try:
        run(command, 300)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def video_seconds(path: Path, run: Run = default_run) -> float | None:
    """Length of a downloaded video, by ffprobe (Instagram does not report it)."""
    ffprobe = find("ffprobe")
    if not ffprobe:
        return None
    try:
        out = run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], 60)
        return round(float(out.stdout.strip()), 1)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


# ---- standalone tools, for Macs without Homebrew (M5) ---------------------------------------
# Pinned builds, each checked against its published SHA-256 before it is used.
# ffmpeg and ffprobe: Martin Riedl's static macOS builds (GPL), 9.0.2. Deno: the official release, 2.9.8.
STANDALONE = {
    ("ffmpeg", "arm64"): ("https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip",
                          "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924"),
    ("ffprobe", "arm64"): ("https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip",
                           "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"),
    ("ffmpeg", "x86_64"): ("https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffmpeg.zip",
                           "7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4"),
    ("ffprobe", "x86_64"): ("https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffprobe.zip",
                            "2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd"),
    ("deno", "arm64"): ("https://github.com/denoland/deno/releases/download/v2.9.8/deno-aarch64-apple-darwin.zip",
                        "9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e"),
    ("deno", "x86_64"): ("https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-apple-darwin.zip",
                         "4b2f5edd2639b7470f034238b321d7002d8dfb4726d8558f52c17afac370eb2c"),
}


def missing_tools() -> list[str]:
    """What Magpiary still needs: ffmpeg, ffprobe, and a JavaScript runtime (Deno or Node) for YouTube."""
    missing = [name for name in ("ffmpeg", "ffprobe") if not find(name)]
    if not find("deno") and not find("node"):
        missing.append("deno")
    return missing


def install_tools(names: list[str], opener=urllib.request.urlopen,
                  report: Callable[[str], None] = lambda m: None) -> list[str]:
    """Download the named tools into tools_dir(). Returns problems (empty when all went well)."""
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    problems = []
    tools_dir().mkdir(parents=True, exist_ok=True)
    for name in names:
        url, sha = STANDALONE[(name, arch)]
        report(f"Downloading {name}…")
        try:
            # some download sites refuse Python's default user agent (found in the M5 sandbox test)
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) Magpiary"})
            with opener(request, timeout=120) as response:
                data = response.read()
        except OSError as err:
            problems.append(f"{name}: could not download ({type(err).__name__}).")
            continue
        if hashlib.sha256(data).hexdigest() != sha:
            problems.append(f"{name}: the download did not match its checksum, so it was not used.")
            continue
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            inside = next((n for n in archive.namelist() if Path(n).name == name), None)
            if inside is None:
                problems.append(f"{name}: the download did not contain {name}.")
                continue
            target = tools_dir() / name
            part = target.with_suffix(".part")
            part.write_bytes(archive.read(inside))
            part.chmod(0o755)
            part.rename(target)
        report(f"Installed {name} in {tools_dir()}.")
    return problems

