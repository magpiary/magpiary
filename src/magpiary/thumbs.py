"""Small copies of pictures for the lists. A wall of 60 posts should not load 60 full-size pictures (10 MB, and each one
decoded in the browser): a tile gets a 600 px copy, a slide strip a 160 px one. The copy is made once, on the Mac with
ffmpeg, and kept beside the original in `.thumbs/`. A video gets its first moment. If anything goes wrong the original
is served instead."""

import subprocess
import threading
from pathlib import Path

from magpiary.tools import find

WIDTHS = (160, 600)
TALL = {600: 800}  # a tile is portrait and its picture is cropped to fill it: a landscape picture (a website, a YouTube
# frame) needs this height too, or a Retina screen stretches 338 px to about 700 (blurry; item seen 4 Nov 2026)
_busy = threading.Semaphore(3)  # a wall seen for the first time asks for dozens at once: three at a time
VIDEO = (".mp4", ".webm", ".mov", ".mkv")


def small(path: Path, width: int, run=subprocess.run) -> Path | None:
    """The `width` px JPEG of `path`, made if it is not there yet (or the original changed). None when it can't be made."""
    if width not in WIDTHS:
        return None
    tall = TALL.get(width, 0)
    out = path.parent / ".thumbs" / (f"{path.stem}-{width}x{tall}.jpg" if tall else f"{path.stem}-{width}.jpg")
    try:
        if out.is_file() and out.stat().st_mtime >= path.stat().st_mtime:
            return out
        ffmpeg = find("ffmpeg")
        if not ffmpeg:
            return None
        out.parent.mkdir(exist_ok=True)
        tmp = out.with_suffix(f".{threading.get_ident()}.tmp.jpg")
        seek = ["-ss", "0.1"] if path.suffix.lower() in VIDEO else []
        with _busy:
            done = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(path), "-frames:v", "1",
                        "-vf", _scale(width, tall), "-q:v", "3", str(tmp)], capture_output=True, timeout=30)
        if done.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(out)
        return out
    except (OSError, subprocess.SubprocessError):
        return None


def _scale(width: int, tall: int) -> str:
    """At least `width` wide and, when `tall` is given, at least `tall` high (the tile is cropped to fill), never larger
    than the original."""
    if not tall:
        return f"scale='min({width},iw)':-2"
    return f"scale='trunc(min(iw,iw*max({width}/iw,{tall}/ih))/2)*2':-2"
