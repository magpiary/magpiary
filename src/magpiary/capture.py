"""Pages the Chrome extension captured as the owner saw them ("Save what I see").

The extension reads the open page only when the owner ticks the box and saves: the article or gallery as blocks
(headings, paragraphs, pictures, videos) in reading order, one screenshot of the visible part, and the browser's own
copy of the page (MHTML). It sends them to this Mac only. A capture waits in

    ~/Magpiary/captures/<url hash>/<capture id>/  page.json, screen.jpg, page.mhtml

(folders 0700, files 0600 from the first byte) until the fetch step has archived the post from it. The browser's copy
is used only as the backup for pictures the Mac could not download itself, and is deleted with the capture.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from email import message_from_bytes, policy
from pathlib import Path

from magpiary.config import data_dir
from magpiary.sources import Fetched

MAX_BYTES = 48_000_000  # one capture request: screenshot and page copy included (base64)
MAX_BLOCKS = 5000
MAX_TEXT = 2_000_000  # characters of text in all blocks
MAX_PICTURES = 40  # pictures downloaded from one capture (owner, 4 Nov 2026)
MAX_VIDEOS = 5
ID = re.compile(r"[A-Za-z0-9-]{1,64}")
BLOCK_TEXT = {"h", "p", "li", "quote", "code", "caption"}
BLOCK_MEDIA = {"img", "video"}


class BadCapture(ValueError):
    """The capture did not have the expected shape; only that capture is refused."""


def root() -> Path:
    return data_dir() / "captures"


def _folder(url: str) -> Path:
    return root() / hashlib.sha256(url.encode()).hexdigest()[:24]


def _text(value, limit: int = 20_000) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _http(value) -> str:
    return value if isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 4000 else ""


def clean_page(page) -> dict:
    """Keep only the fields and block kinds Magpiary knows; anything else from the page is dropped."""
    if not isinstance(page, dict) or not isinstance(page.get("blocks"), list):
        raise BadCapture("page")
    if len(page["blocks"]) > MAX_BLOCKS:
        raise BadCapture("too many blocks")
    blocks, total = [], 0
    for raw in page["blocks"]:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("t")
        if kind in BLOCK_TEXT:
            text = _text(raw.get("text")).strip()
            if not text:
                continue
            total += len(text)
            block = {"t": kind, "text": text}
            if kind == "h":
                block["level"] = raw.get("level") if raw.get("level") in (1, 2, 3, 4, 5, 6) else 2
            if kind == "li":
                block["ordered"] = raw.get("ordered") is True
            blocks.append(block)
        elif kind == "img" and _http(raw.get("src")):
            blocks.append({"t": "img", "src": raw["src"], "also": [u for u in map(_http, raw["also"][:8]) if u] if isinstance(raw.get("also"), list) else [],
                           "alt": _text(raw.get("alt"), 500), "caption": _text(raw.get("caption"), 2000)})
        elif kind == "video" and (_http(raw.get("src")) or _http(raw.get("poster"))):
            blocks.append({"t": "video", "src": _http(raw.get("src")), "poster": _http(raw.get("poster"))})
        elif kind == "embed" and _http(raw.get("src")):
            blocks.append({"t": "embed", "src": raw["src"]})
    if total > MAX_TEXT:
        raise BadCapture("too much text")
    return {"title": _text(page.get("title"), 500).strip(), "byline": _text(page.get("byline"), 300).strip(),
            "published": _text(page.get("published"), 40).strip(), "site": _text(page.get("site"), 200).strip(),
            "lang": _text(page.get("lang"), 20).strip(), "blocks": blocks}


def _b64(value, prefix: str = "") -> bytes:
    if not value:
        return b""
    if not isinstance(value, str):
        raise BadCapture("encoding")
    if prefix and value.startswith(prefix):
        value = value[len(prefix):]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise BadCapture("encoding") from err


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # private before the first byte (review lessons 4)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def save(url: str, capture_id: str, page, screen=None, mhtml=None) -> Path:
    """Write one capture for this canonical URL. Written under a temporary name and swapped in, so a half-written
    capture is never read. Raises BadCapture for a capture of the wrong shape."""
    if not isinstance(capture_id, str) or not ID.fullmatch(capture_id):
        raise BadCapture("id")
    cleaned = clean_page(page)
    shot = _b64(screen, "data:image/jpeg;base64,")
    if shot and not shot.startswith(b"\xff\xd8\xff"):
        raise BadCapture("screenshot")
    copy = _b64(mhtml)
    for path in (root(), _folder(url)):
        _private_dir(path)
    final = _folder(url) / capture_id
    if final.exists():
        return final  # the same capture sent twice (the reply was lost): already stored
    work = _folder(url) / f".tmp-{capture_id}"
    shutil.rmtree(work, ignore_errors=True)
    _private_dir(work)
    try:
        _write_private(work / "page.json", json.dumps({"url": url, **cleaned}, ensure_ascii=False).encode())
        if shot:
            _write_private(work / "screen.jpg", shot)
        if copy:
            _write_private(work / "page.mhtml", copy)
        work.rename(final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return final


@dataclass
class Capture:
    folder: Path
    page: dict

    @property
    def id(self) -> str:
        return self.folder.name

    @property
    def screen(self) -> Path | None:
        path = self.folder / "screen.jpg"
        return path if path.exists() else None

    def pictures(self) -> list[str]:
        return list(dict.fromkeys(b["src"] for b in self.page["blocks"] if b["t"] == "img"))[:MAX_PICTURES]

    def videos(self) -> list[str]:
        return list(dict.fromkeys(b["src"] for b in self.page["blocks"] if b["t"] == "video" and b["src"]))[:MAX_VIDEOS]

    def text(self) -> str:
        """The reading text, one block a paragraph, for the summary and search."""
        lines = []
        for b in self.page["blocks"]:
            if b["t"] == "h":
                lines.append(b["text"])
            elif b["t"] == "li":
                lines.append(f"- {b['text']}")
            elif b["t"] in BLOCK_TEXT:
                lines.append(b["text"])
            elif b["t"] == "img" and b.get("caption"):
                lines.append(b["caption"])
        return "\n\n".join(lines)

    def fetched(self) -> Fetched:
        p = self.page
        meta = {"title": p["title"], "text": self.text(), "published_at": p["published"], "author": p["byline"],
                "site_name": p["site"], "captured": True}
        posters = [b["poster"] for b in p["blocks"] if b["t"] == "video" and b["poster"] and not b["src"]]
        return Fetched(meta, images=list(dict.fromkeys(self.pictures() + posters))[:MAX_PICTURES],
                       videos=self.videos(), fetched_with="the page as you saw it (Chrome extension)")

    def backup(self) -> dict[str, bytes]:
        """Pictures from the browser's own copy of the page, by the address the Mac asks for: only the ones this capture
        lists. The browser's copy may hold another size of a picture (the one in its src, not the largest offered)."""
        path = self.folder / "page.mhtml"
        wanted = set(self.pictures())
        if not wanted or not path.exists():
            return {}
        names = {}  # any address a listed picture goes by -> the address the Mac asks for
        for b in self.page["blocks"]:
            if b["t"] == "img" and b["src"] in wanted:
                for where in [b["src"], *b.get("also", [])]:
                    names.setdefault(where, b["src"])
        try:
            message = message_from_bytes(path.read_bytes(), policy=policy.default)
        except Exception:  # a damaged copy only means no backup
            return {}
        found = {}
        for part in message.walk():
            src = names.get(part.get("Content-Location", ""))
            if src and part.get_content_maintype() == "image":
                try:
                    data = part.get_payload(decode=True)
                except Exception:
                    continue
                if data and (src not in found or part.get("Content-Location") == src):  # the size asked for wins
                    found[src] = data
        return found


def latest(url: str) -> Capture | None:
    """The newest complete capture of this page, if one is waiting."""
    folder = _folder(url)
    if not folder.is_dir():
        return None
    for path in sorted((p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            page = json.loads((path / "page.json").read_text())
            if page.get("url") == url:
                return Capture(path, clean_page(page))
        except (OSError, ValueError):
            continue
    return None


def done(capture: Capture) -> None:
    """The post was archived from this capture: remove it (and any older ones). A newer one stays for the next fetch."""
    folder = capture.folder.parent
    mtime = capture.folder.stat().st_mtime
    for path in list(folder.iterdir()):
        try:
            if not path.name.startswith(".") and path.stat().st_mtime <= mtime:  # .tmp-*: a capture being written now
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass
    try:
        folder.rmdir()  # only when nothing newer is left
    except OSError:
        pass
