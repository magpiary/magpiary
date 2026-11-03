"""Preview cards for the web links an answer cites: the site, a title and a picture.

This Mac fetches them after the answer is written, logged out and with no cookies. The AI never sees them, so they cost no
tokens, and a page that cannot be reached simply gets no card."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from magpiary import icons
from magpiary.config import data_dir

log = logging.getLogger(__name__)
PageGet = Callable[[str, dict, int], tuple[int, str, bytes]]
PublicHost = Callable[[str], bool]

LINK = re.compile(r"\[[^\]]+\]\((https?://[^\s)\"']+)\)")
MAX_CARDS, MAX_IMAGE, MAX_PAGE, TOTAL_SECONDS = 4, 700_000, 250_000, 12
MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif"), (b"RIFF", "webp"))


def folder() -> Path:
    path = data_dir() / "ask-cards"
    path.mkdir(parents=True, exist_ok=True)
    return path


def links_in(text: str) -> list[str]:
    """The web links of an answer, once each (a site's own pages count once), at most four."""
    seen, out = set(), []
    for url in LINK.findall(text or ""):
        parts = urlsplit(url)
        key = (parts.hostname or "").removeprefix("www.") + parts.path.rstrip("/")
        if parts.hostname and key not in seen:
            seen.add(key)
            out.append(url)
    return out[:MAX_CARDS]


def _meta(html: str, *names: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        name = re.search(r'(?:property|name)=["\']([^"\']+)', tag, flags=re.I)
        if name and name.group(1).lower() in names:
            content = re.search(r'content=["\']([^"\']*)', tag, flags=re.I)
            if content and content.group(1).strip():
                return unescape(content.group(1)).strip()
    return ""


def _kind(data: bytes) -> str:
    for magic, ext in MAGIC:
        if data.startswith(magic) and (ext != "webp" or data[8:12] == b"WEBP"):
            return ext
    return ""


def card(
    url: str, get: PageGet | None = None, public: PublicHost = icons.public_host
) -> dict | None:
    """{"url", "title", "site", "host", "img"} for one link ("img" is a file key, or ""). None when the address is not a public site."""
    from magpiary.links import http_get

    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cached = folder() / f"{key}.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text())
        except (OSError, ValueError):
            pass
    host = (urlsplit(url).hostname or "").lower()
    if not host or not public(host):
        return None
    get = get or http_get
    out = {"url": url, "title": "", "site": host.removeprefix("www."), "host": host.removeprefix("www."), "img": ""}
    try:
        status, final, body = get(url, {}, MAX_PAGE)
        if status == 200:
            html = body.decode("utf-8", "ignore")
            title = _meta(html, "og:title", "twitter:title") or (unescape(m.group(1)).strip() if (m := re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)) else "")
            out["title"] = re.sub(r"\s+", " ", title)[:140]
            out["site"] = (_meta(html, "og:site_name") or out["site"])[:60]
            image = _meta(html, "og:image", "twitter:image", "og:image:url")
            image = urljoin(final or url, image) if image else ""
            if image and urlsplit(image).scheme == "https" and public(urlsplit(image).hostname or ""):
                status, _, data = get(image, {}, MAX_IMAGE + 1)
                kind = _kind(data) if status == 200 and len(data) <= MAX_IMAGE else ""
                if kind:
                    (folder() / f"{key}.{kind}").write_bytes(data)
                    out["img"] = key
    except Exception as err:  # a preview must never prevent the answer from being shown
        log.debug("Preview page or image unavailable (%s)", type(err).__name__)
    try:
        icons.fetch(out["host"], get)  # the site's small icon, once, for the link in the text
    except Exception as err:
        log.debug("Preview icon unavailable (%s)", type(err).__name__)
    if out["title"] or out["img"]:
        cached.write_text(json.dumps(out))
        return out
    return None


def cards_for(
    text: str, get: PageGet | None = None, public: PublicHost = icons.public_host
) -> list[dict]:
    """Cards for the links of an answer, fetched side by side, giving up on slow sites after a few seconds."""
    urls = links_in(text)
    if not urls:
        return []
    pool = ThreadPoolExecutor(max_workers=len(urls))
    try:
        futures = [pool.submit(card, u, get, public) for u in urls]
        wait(futures, timeout=TOTAL_SECONDS)
        return [r for f in futures if f.done() and not f.exception() and (r := f.result())]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def image_path(key: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{16}", key or ""):
        return None
    return next((p for p in folder().glob(f"{key}.*") if p.suffix != ".json"), None)


def content_type(path: Path) -> str:
    return {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(path.suffix[1:], "application/octet-stream")
