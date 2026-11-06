"""Make a saved video playable on an iPhone, the first time a phone asks for it, and keep only that copy.

iPhones often cannot play VP9 or AV1 inside an .mp4. When an iPhone asks for such a video the Mac re-encodes it to
H.264 (720p at most, AAC sound), checks the result, and then REPLACES the original: the new file takes the old file's
name in one step, so there is never a second copy of the video on disk (owner's rule, 6 Nov 2026). If anything about
the new file looks wrong the original is kept untouched. Short videos are converted while the phone waits; long ones
convert in the background and the phone is told to try again."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from pathlib import Path

from magpiary.tools import find

log = logging.getLogger("magpiary.phone_video")

WAIT_UP_TO_SECONDS = 600  # videos longer than this convert in the background
IPHONE = re.compile(r"iPhone|iPad|iPod")

_guard = threading.Lock()
_locks: dict[Path, threading.Lock] = {}
_background: dict[Path, threading.Thread] = {}
_failed: set[Path] = set()


def is_iphone(user_agent: str) -> bool:
    return bool(IPHONE.search(user_agent or ""))


def probe(path: Path) -> dict | None:
    """{'codec', 'duration', 'audio'} of a video file, or None if it cannot be read."""
    ffprobe = find("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not video:
            return None
        return {"codec": video.get("codec_name", ""), "duration": float(data.get("format", {}).get("duration") or 0),
                "audio": any(s.get("codec_type") == "audio" for s in streams)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _convert(path: Path, before: dict) -> bool:
    """Re-encode `path` and replace it with the H.264 version. True when replaced."""
    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return False
    tmp = path.with_name(f".{path.stem}.h264.tmp.mp4")
    tmp.unlink(missing_ok=True)
    try:
        command = [ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-y", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                   "-vf", "scale=-2:'min(720,ih)'", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)]
        done = subprocess.run(command, capture_output=True, timeout=3 * 3600)
        after = probe(tmp) if done.returncode == 0 else None
        slack = max(1.0, before["duration"] * 0.02)
        if (not after or after["codec"] != "h264" or abs(after["duration"] - before["duration"]) > slack
                or (before["audio"] and not after["audio"])):
            log.warning("phone video: result of %s did not check out, original kept", path.name)
            return False
        tmp.replace(path)  # one step: the original is gone, the H.264 file is now the only copy
        return True
    except (OSError, subprocess.SubprocessError):
        log.warning("phone video: converting %s failed, original kept", path.name, exc_info=True)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def ensure(path: Path) -> str:
    """'ready' (play it now), 'converting' (ask again soon) or 'failed' (serve the original as it is)."""
    if path in _failed:
        return "failed"
    with _guard:
        if path in _background:
            return "converting"
        lock = _locks.setdefault(path, threading.Lock())
    with lock:
        before = probe(path)
        if before is None:
            _failed.add(path)
            return "failed"
        if before["codec"] == "h264":
            return "ready"
        if before["duration"] > WAIT_UP_TO_SECONDS:
            def work() -> None:
                with lock:
                    if not _convert(path, before):
                        _failed.add(path)
                with _guard:
                    _background.pop(path, None)
            thread = threading.Thread(target=work, daemon=True)
            with _guard:
                _background[path] = thread
            thread.start()
            return "converting"
        if _convert(path, before):
            return "ready"
        _failed.add(path)
        return "failed"
