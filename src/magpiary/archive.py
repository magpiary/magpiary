"""Archive one item: fetch it and write its folder in ~/Magpiary/library/<slug>/.

The folder is written under a temporary name and swapped in at the end, so a failed or
repeated fetch never leaves half a folder. Files: media-NN.* (video or images), thumbnail.jpg,
caption.txt, meta.json, and discussion.json where comments came with the post.
"""

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from magpiary.activity import NO_PROGRESS, Progress
from magpiary.sources import FetchFailed, Get, describe, http_get
from magpiary.tools import Run, YtDlp, YtDlpError, default_run, video_seconds

MAX_IMAGE_BYTES = 25_000_000
_MAGIC = [(b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif")]


def slug(url: str, source: str) -> str:
    """A readable folder name, disambiguated by the whole canonical URL."""
    parts = urlsplit(url)
    code = (parse_qs(parts.query).get("v") or [""])[0] or (parts.path.rstrip("/").split("/") or [""])[-1]
    code = re.sub(r"[^A-Za-z0-9_-]", "", code)
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    if source == "other" or not code:
        return f"{source}-{digest}"
    return f"{source}-{code[:40]}-{digest}"


def _archive_folder(item: dict, library: Path) -> Path:
    """Keep a recorded legacy path on refetch only if its metadata belongs to this URL."""
    if item.get("archive_dir"):
        old = Path(item["archive_dir"])
        if old.resolve().parent == library.resolve():
            try:
                if json.loads((old / "meta.json").read_text()).get("url") == item["canonical_url"]:
                    return old
            except (OSError, ValueError, AttributeError):
                pass
    return library / slug(item["canonical_url"], item["source"])


def _image_type(data: bytes) -> str | None:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _save_images(urls: list[str], folder: Path, get: Get, start: int) -> list[str]:
    saved = []
    for url in urls:
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        try:
            status, data = get(url)
        except OSError:
            continue  # a missing picture does not fail the whole item
        ext = _image_type(data) if status == 200 and len(data) <= MAX_IMAGE_BYTES else None
        if ext:
            name = f"media-{start + len(saved):02d}.{ext}"
            (folder / name).write_bytes(data)
            saved.append(name)
    return saved


def fetch_item(item: dict, library: Path, get: Get = http_get, ytdlp: YtDlp | None = None,
               run: Run = default_run, progress: Progress = NO_PROGRESS) -> Path:
    """Fetch and archive one item. Returns its folder. Raises FetchFailed."""
    ytdlp = ytdlp or YtDlp(run)
    url, source = item["canonical_url"], item["source"]
    progress.step("fetch")
    fetched = describe(source, url, get, ytdlp)
    progress.step("download")
    final = _archive_folder(item, library)
    work = library / f".tmp-{final.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        if fetched.video:
            try:
                ytdlp.download(url, work, on_progress=progress.percent if progress.activity else None)
            except YtDlpError as err:
                if not fetched.images:
                    raise FetchFailed(err.reason, err.detail) from err
        media = sorted(p.name for p in work.glob("media-*"))
        media += _save_images(fetched.images, work, lambda u: get_image(get, u), len(media) + 1)
        if not media and not fetched.meta.get("text"):
            raise FetchFailed("unknown", "nothing could be saved from this post")
        videos = [work / m for m in media if m.endswith((".mp4", ".webm", ".mov", ".mkv"))]
        if videos and not fetched.meta.get("duration"):
            fetched.meta["duration"] = video_seconds(videos[0], run)
        meta = {"url": url, "source": source, "kind": item.get("kind"), **fetched.meta,
                "media": media, "thumbnail": "thumbnail.jpg" if (work / "thumbnail.jpg").exists() else next(
                    (m for m in media if not m.endswith((".mp4", ".webm", ".mov", ".mkv"))), None),
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "stats_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "fetched_with": fetched.fetched_with + (f" (yt-dlp {ytdlp.version()})" if fetched.video else "")}
        (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        (work / "caption.txt").write_text(fetched.meta.get("text") or "")
        if fetched.discussion is not None:
            (work / "discussion.json").write_text(json.dumps(fetched.discussion, ensure_ascii=False, indent=2))
        old = library / f".old-{final.name}"
        shutil.rmtree(old, ignore_errors=True)
        if final.exists():
            final.rename(old)
        work.rename(final)
        shutil.rmtree(old, ignore_errors=True)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)


def get_image(get: Get, url: str) -> tuple[int, bytes]:
    """Images may be larger than pages; the default getter takes a size limit."""
    if get is http_get:
        return http_get(url, MAX_IMAGE_BYTES + 1)
    return get(url)
