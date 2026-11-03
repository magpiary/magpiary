"""Transcripts on the Mac: whisper.cpp (`small` model) through pywhispercpp.

It runs in a child process (`python -m magpiary.transcribe <media> <out.json>`) so a crash or the
model's memory never touches the service. Whisper sometimes gets stuck repeating itself (S5); a
guard spots that and runs once more without carrying context between segments.
"""

import json
import re
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path

MODEL = "small"
TIMEOUT_SECONDS = 3 * 3600


class TranscribeFailed(Exception):
    pass


MUSIC_MARKS = re.compile(r"[\[(]\s*(music|applause|laughter|silence|instrumental|blank_audio)[^\])]*[\])]|[♪♫]", re.I)


def has_speech(segments: list[dict], duration: float | None) -> bool:
    """False for music-only videos: Whisper's "[Music]" and "♪" marks do not count as words."""
    words = sum(len(re.findall(r"\w+", MUSIC_MARKS.sub(" ", s["text"]))) for s in segments)
    minutes = max((duration or 60) / 60, 0.25)
    return words / minutes >= 15


def looks_stuck(segments: list[dict], duration: float | None) -> bool:
    """A phrase repeated over and over, or far more words than anyone can say."""
    words = re.findall(r"\w+", " ".join(s["text"] for s in segments).lower())
    if len(words) < 30:
        return False
    if duration and len(words) / max(duration, 1) > 6:
        return True
    grams = Counter(tuple(words[i:i + 5]) for i in range(len(words) - 4))
    top = grams.most_common(1)[0][1] if grams else 0
    return top >= 6 and top * 5 > len(words) * 0.25


def _whisper(media: Path, **params) -> list[dict]:
    from pywhispercpp.model import Model  # only in the child process

    def report(segment) -> None:  # the parent turns this into a percentage
        print(f"PROGRESS {segment.t1 / 100:.1f}", flush=True)

    model = Model(MODEL, redirect_whispercpp_logs_to=None, n_threads=6, **params)
    return [{"start": round(s.t0 / 100, 2), "end": round(s.t1 / 100, 2), "text": s.text.strip()}
            for s in model.transcribe(str(media), language="auto", new_segment_callback=report) if s.text.strip()]


def run_child(media: Path, out: Path, duration: float | None) -> None:
    segments = _whisper(media)
    guarded = False
    if looks_stuck(segments, duration):
        segments, guarded = _whisper(media, no_context=True, temperature=0.2), True
    out.write_text(json.dumps({"engine": f"whisper.cpp {MODEL}", "loop_guard_used": guarded,
                               "segments": segments}, ensure_ascii=False))


def _run_with_progress(command: list[str], duration: float | None, on_progress) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timer = threading.Timer(TIMEOUT_SECONDS, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            if line.startswith("PROGRESS") and duration and on_progress:
                try:
                    on_progress(float(line.split()[1]) / duration * 100)
                except (ValueError, IndexError):
                    pass
        stderr = proc.stderr.read()
        proc.wait()
    finally:
        timer.cancel()
    return subprocess.CompletedProcess(command, proc.returncode, "", stderr)


def has_audio(media: Path) -> bool:
    """Some posts (often on X) are silent videos with no sound track at all."""
    from magpiary.tools import find

    ffprobe = find("ffprobe")
    if not ffprobe:
        return True
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", str(media)], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return "audio" in out


def transcribe(media: Path, out: Path, duration: float | None = None, run=None, on_progress=None,
               audio_check=has_audio) -> dict:
    """Write `out` (transcript.json) and return it. Raises TranscribeFailed."""
    if not audio_check(media):  # nothing to hear: an empty transcript, and the frames carry the post
        data = {"engine": "none (the video has no sound)", "loop_guard_used": False, "segments": []}
        out.write_text(json.dumps(data))
        return data
    command = [sys.executable, "-m", "magpiary.transcribe", str(media), str(out), str(duration or 0)]
    try:
        if run is None:
            result = _run_with_progress(command, duration, on_progress)
        else:
            result = run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as err:
        raise TranscribeFailed(f"transcriber did not run: {type(err).__name__}") from err
    if result.returncode != 0 or not out.exists():
        last = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise TranscribeFailed(f"transcriber failed: {last[0][:160]}")
    return json.loads(out.read_text())


if __name__ == "__main__":
    run_child(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]) or None)
