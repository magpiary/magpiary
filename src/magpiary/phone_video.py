"""Make a saved video playable on an iPhone, the first time a phone asks for it, and keep only that copy.

iPhones often cannot play VP9 or AV1 inside an .mp4. When an iPhone asks for such a video the Mac re-encodes it to
H.264 (720p at most, AAC sound), checks the result, and then REPLACES the original: the new file takes the old file's
name in one step, so there is never a second copy of the video on disk (owner's rule, 6 Nov 2026). If anything about
the new file looks wrong the original is kept untouched. Conversions run in two background workers, never in the
thread answering the phone: a request waits a few seconds for the result and, if the video is not ready yet, is told
to try again (503 with Retry-After)."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

from magpiary.tools import find

log = logging.getLogger("magpiary.phone_video")

WAIT_FOR_RESULT_SECONDS = 20  # a request waits this long for a conversion, then the phone is told to ask again
MAX_CONVERSIONS = 2  # ffmpeg processes at the same time, however many videos are asked for
VIDEO_TOLERANCE = 0.1  # seconds the new video stream may differ from the old one (about two frames)
AUDIO_TOLERANCE = 0.3  # seconds the new audio stream may differ from the old one
RETRY_FIRST_SECONDS = 60  # wait before the first retry of a failed conversion; doubles each time
RETRY_LONGEST_SECONDS = 3600
IPHONE = re.compile(r"iPhone|iPad|iPod")

_lock = threading.Lock()  # guards the four collections below: one decision at a time
_jobs: dict[Path, "_Job"] = {}  # queued or running, at most one per file
_failed: dict[Path, tuple[float, tuple | None, int]] = {}  # when it failed, which file it was, failures in a row
_ready: dict[Path, tuple] = {}  # files known to be H.264, by file identity
_workers: list[threading.Thread] = []
_queue: "queue.Queue[_Job]" = queue.Queue()
_now = time.monotonic  # replaced by tests


class _Job:
    """One file waiting for, or going through, conversion."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.done = threading.Event()
        self.result = "failed"


def is_iphone(user_agent: str) -> bool:
    return bool(IPHONE.search(user_agent or ""))


def _identity(path: Path) -> tuple | None:
    """Size and modification time: changes when the file is replaced or edited."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


def _seconds(stream: dict | None) -> float | None:
    """A stream's own duration in seconds, or None when the file does not say."""
    if not stream:
        return None
    value = stream.get("duration") or (stream.get("tags") or {}).get("DURATION")
    try:
        if isinstance(value, str) and ":" in value:
            h, m, sec = value.split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
        return float(value) if value is not None else None
    except ValueError:
        return None


def probe(path: Path) -> dict | None:
    """{'codec', 'duration', 'video_duration', 'audio_duration', 'audio'} of a video file, or None if unreadable.
    The two stream durations are None when the file does not state them; 'duration' is the container's."""
    ffprobe = find("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,duration:stream_tags=DURATION:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not video:
            return None
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        return {"codec": video.get("codec_name", ""), "duration": float(data.get("format", {}).get("duration") or 0),
                "video_duration": _seconds(video), "audio_duration": _seconds(audio), "audio": audio is not None}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _checks_out(before: dict, after: dict | None) -> bool:
    """True only when the new file is H.264, keeps its sound, and has the same video and audio length as the old one.
    A missing length counts as a failure."""
    if not after or after["codec"] != "h264" or before["audio"] != after["audio"]:
        return False
    pairs = [(before["video_duration"], after["video_duration"], VIDEO_TOLERANCE)]
    if before["audio"]:
        pairs.append((before["audio_duration"], after["audio_duration"], AUDIO_TOLERANCE))
    return all(a is not None and b is not None and abs(a - b) <= tol for a, b, tol in pairs)


def _timeout(duration: float) -> float:
    """Seconds ffmpeg may run: ten minutes at least, three times the video's length, two hours at most."""
    return min(7200.0, max(600.0, 3 * duration))


def _command(ffmpeg: str, source: Path, target: Path) -> list[str]:
    """The ffmpeg command: H.264, 720p at most, AAC sound. -xerror stops at the first decoding error."""
    return [ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-v", "error", "-xerror", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-vf", "scale=-2:'min(720,ih)'", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(target)]


def _run_ffmpeg(command: list[str], timeout: float) -> tuple[int, bytes]:
    """Run ffmpeg to the end and return (exit code, its error text). On timeout the whole process group is killed."""
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.communicate()
        raise
    return proc.returncode, err or b""


def _convert(path: Path, before: dict) -> bool:
    """Re-encode `path` and replace it with the H.264 version. True when replaced."""
    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return False
    tmp = path.with_name(f".{path.stem}.h264.tmp.mp4")
    tmp.unlink(missing_ok=True)
    try:
        code, err = _run_ffmpeg(_command(ffmpeg, path, tmp), _timeout(before["video_duration"] or before["duration"]))
        if code != 0 or err.strip() or not _checks_out(before, probe(tmp)):
            log.warning("phone video: result of %s did not check out, original kept", path.name)
            return False
        tmp.replace(path)  # one step: the original is gone, the H.264 file is now the only copy
        return True
    except (OSError, subprocess.SubprocessError):
        log.warning("phone video: converting %s failed, original kept", path.name, exc_info=True)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _process(path: Path) -> str:
    """Look at the file as it is now (not as it was when queued) and convert it if needed. 'ready' or 'failed'."""
    before = probe(path)
    if before is None:
        return "failed"
    if before["codec"] == "h264":
        return "ready"
    if before["video_duration"] is None or (before["audio"] and before["audio_duration"] is None):
        log.warning("phone video: %s does not state its stream lengths, a copy cannot be checked, original kept", path.name)
        return "failed"
    return "ready" if _convert(path, before) else "failed"


def _finish(job: _Job, result: str) -> None:
    """Record the outcome, then release everyone waiting on the job."""
    identity = _identity(job.path)
    with _lock:
        _jobs.pop(job.path, None)
        if result == "ready" and identity:
            _ready[job.path] = identity
            _failed.pop(job.path, None)
        else:
            _, old_identity, count = _failed.get(job.path, (0.0, None, 0))
            _failed[job.path] = (_now(), identity, count + 1 if old_identity == identity else 1)
    job.result = result
    job.done.set()


def _worker() -> None:
    while True:
        job = _queue.get()
        try:
            result = _process(job.path)
        except Exception:  # a worker must survive anything; the job simply fails
            log.warning("phone video: unexpected error for %s", job.path.name, exc_info=True)
            result = "failed"
        _finish(job, result)


def _start_workers() -> None:
    """Start the worker threads on first use (call with the lock held)."""
    while len(_workers) < MAX_CONVERSIONS:
        thread = threading.Thread(target=_worker, name="phone-video", daemon=True)
        _workers.append(thread)
        thread.start()


def _may_retry(path: Path, identity: tuple | None) -> bool:
    """A failed file is tried again when it changed, or after a wait that doubles from a minute up to an hour."""
    when, failed_identity, count = _failed[path]
    wait = min(RETRY_LONGEST_SECONDS, RETRY_FIRST_SECONDS * 2 ** (count - 1))
    return identity != failed_identity or _now() - when >= wait


def _schedule(path: Path) -> "_Job | str":
    """The job to wait for, or 'ready'/'failed' when none is needed. One lock holds the whole decision."""
    identity = _identity(path)
    with _lock:
        if identity is None:
            return "failed"
        if (job := _jobs.get(path)) is not None:
            return job
        if _ready.get(path) == identity:
            return "ready"
        if path in _failed and not _may_retry(path, identity):
            return "failed"
        job = _jobs[path] = _Job(path)
        _queue.put(job)
        _start_workers()
        return job


def ensure(path: Path) -> str:
    """'ready' (play it now), 'converting' (ask again soon) or 'failed' (serve the original as it is)."""
    job = _schedule(path)
    if isinstance(job, str):
        return job
    return job.result if job.done.wait(WAIT_FOR_RESULT_SECONDS) else "converting"


def _reset() -> None:
    """Forget everything (for tests)."""
    with _lock:
        _jobs.clear()
        _failed.clear()
        _ready.clear()
