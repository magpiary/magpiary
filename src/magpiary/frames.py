"""Frames on the Mac: scene changes picked by ffmpeg, near-repeats dropped, capped, 768 px wide.

A reel gets up to 8 frames, a long video up to 16. A video with no speech (music only) carries its
information in the visuals, so it gets up to 40 frames, taken more densely. If a video has few scene
changes, evenly spaced frames fill in so the summary still sees the whole thing.
"""

import re
from pathlib import Path

from magpiary.tools import Run, default_run, find

WIDTH = 768
SCENE = 0.3


MUSIC_ONLY_CAP = 40


def frame_cap(duration: float | None, speech: bool = True) -> int:
    if not speech:
        return MUSIC_ONLY_CAP
    return 8 if not duration or duration <= 180 else 16


def _pick(times: list[float], cap: int) -> list[float]:
    if len(times) <= cap:
        return times
    step = len(times) / cap
    return [times[int(i * step)] for i in range(cap)]


def scene_times(video: Path, run: Run = default_run, threshold: float = SCENE) -> list[float]:
    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return []
    result = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-vf",
                  f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"], 1800)
    return [float(t) for t in re.findall(r"pts_time:([0-9.]+)", result.stderr or "")]


def extract(video: Path, folder: Path, duration: float | None, run: Run = default_run,
            speech: bool = True, cap: int | None = None) -> list[dict]:
    """Save frames as frames/<seconds>.jpg; returns [{"at": seconds, "path": "frames/0012.jpg"}]."""
    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return []
    cap = min(cap, frame_cap(duration, speech)) if cap else frame_cap(duration, speech)
    gap = 1.5 if speech else 0.5  # without speech, text on screen can change every half second
    times = [t for t in scene_times(video, run, SCENE if speech else SCENE / 2) if not duration or t < duration - 0.5]
    times = sorted({round(t, 1) for t in [0.5, *times]})
    spaced = [t for t in times if all(abs(t - u) >= gap for u in times if u < t)]  # drop near-repeats
    if duration and len(spaced) < (min(cap, 4) if speech else cap // 2):
        even = [round(duration * (i + 0.5) / cap, 1) for i in range(cap)]
        spaced = sorted(set(spaced) | set(even))  # _pick below spreads them over the whole video
    out = folder / "frames"
    out.mkdir(exist_ok=True)
    frames = []
    for t in _pick(spaced, cap):
        name = f"frames/{int(t):04d}-{int(t * 10) % 10}.jpg"
        result = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video),
                      "-frames:v", "1", "-vf", f"scale='min({WIDTH},iw)':-2", "-q:v", "4", str(folder / name)], 120)
        if (folder / name).exists() and getattr(result, "returncode", 0) == 0:
            frames.append({"at": t, "path": name})
    return frames
