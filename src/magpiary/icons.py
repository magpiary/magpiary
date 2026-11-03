"""Little site icons for links. Built-in marks for well-known sites; otherwise the site's own favicon, fetched ONCE by this Mac
(never by the browser on each view, never through an icon service) and kept in the library's config folder; otherwise a globe."""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from magpiary.config import config_dir

BUILTIN = {"github.com": "github", "gist.github.com": "github", "x.com": "x", "twitter.com": "x", "instagram.com": "instagram",
           "youtube.com": "youtube", "youtu.be": "youtube", "linkedin.com": "linkedin"}
EXTRA_MARKS = {  # simple one-colour marks that follow the text colour
    "youtube": '<path d="M21.6 7.2a2.5 2.5 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.5 2.5 0 0 0 2.4 7.2C2 8.8 2 12 2 12s0 3.2.4 4.8a2.5 2.5 0 0 0 1.8 1.8C5.8 19 12 19 12 19s6.2 0 7.8-.4a2.5 2.5 0 0 0 1.8-1.8c.4-1.6.4-4.8.4-4.8s0-3.2-.4-4.8ZM10 15V9l5.2 3Z"/>',
    "linkedin": '<path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5ZM3 9.75h4V21H3V9.75Zm6.5 0h3.8v1.6h.1c.5-1 1.8-1.9 3.7-1.9 4 0 4.6 2.6 4.6 6V21h-4v-4.9c0-1.2 0-2.7-1.7-2.7s-1.9 1.3-1.9 2.6V21h-4V9.75Z"/>',
}
MAX_BYTES = 64_000
MAGIC = ((b"\x89PNG", "png"), (b"\x00\x00\x01\x00", "ico"), (b"GIF8", "gif"), (b"\xff\xd8\xff", "jpg"))
MIME = {"png": "image/png", "ico": "image/x-icon", "gif": "image/gif", "jpg": "image/jpeg"}
HOST = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def folder() -> Path:
    return config_dir() / "icons"


def builtin(host: str) -> str | None:
    host = host.lower()
    return BUILTIN.get(host) or BUILTIN.get(".".join(host.split(".")[-2:]))


def cached(host: str) -> Path | None:
    if not HOST.fullmatch(host):
        return None
    return next((p for p in folder().glob(f"{host}.*") if p.suffix in (".png", ".ico", ".gif", ".jpg")), None)


def content_type(path: Path) -> str:
    return MIME.get(path.suffix.lstrip("."), "application/octet-stream")


def public_host(host: str) -> bool:
    """Only real public sites: never an address inside this Mac or the home network."""
    if not HOST.fullmatch(host) or host in ("localhost",) or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        return all(ipaddress.ip_address(info[4][0]).is_global for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    except (OSError, ValueError):
        return False


def _page_icon(html: str, base: str) -> str:
    """The icon address a home page names (<link rel="icon" href="...">), preferring a larger PNG; "" when none or not https."""
    found = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        if not re.search(r'rel=["\'][^"\']*icon', tag, flags=re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)', tag, flags=re.I)
        if not href:
            continue
        url = urljoin(base, href.group(1).strip())
        if urlsplit(url).scheme == "https" and not url.lower().split("?")[0].endswith(".svg"):
            size = re.search(r'sizes=["\'](\d+)x', tag, flags=re.I)
            found.append((int(size.group(1)) if size else 16, url))
    return max(found)[1] if found else ""


def _keep(host: str, body: bytes, status: int) -> bool:
    kind = next((ext for magic, ext in MAGIC if body.startswith(magic)), None)
    if status != 200 or not kind or not 60 <= len(body) <= MAX_BYTES:
        return False
    (folder() / f"{host}.{kind}").write_bytes(body)
    return True


def fetch(host: str, get=None, public=public_host) -> bool:
    """Ask the site once for its icon: /favicon.ico, and if that is not an image, the icon its home page names. Keep it, or note
    that it has none. True when an icon was kept."""
    from magpiary.links import http_get

    folder().mkdir(parents=True, exist_ok=True)
    if cached(host) or (folder() / f"{host}.none").exists():
        return bool(cached(host))
    marker = folder() / f"{host}.none"
    if not public(host):
        marker.write_text("")
        return False
    get = get or http_get
    try:
        status, _, body = get(f"https://{host}/favicon.ico", {}, MAX_BYTES + 1)
        if _keep(host, body, status):
            return True
        status, final, page = get(f"https://{host}/", {}, 200_000)
        url = _page_icon(page.decode("utf-8", "ignore"), final or f"https://{host}/") if status == 200 else ""
        if url and public(urlsplit(url).hostname or ""):
            status, _, body = get(url, {}, MAX_BYTES + 1)
            if _keep(host, body, status):
                return True
    except Exception:
        pass
    marker.write_text("")
    return False


def due(urls: list[str], limit: int = 8) -> list[str]:
    hosts, seen = [], set()
    for u in urls:
        h = host_of(u)
        if h and h not in seen and not builtin(h) and not cached(h) and not (folder() / f"{h}.none").exists() and HOST.fullmatch(h):
            seen.add(h)
            hosts.append(h)
    return hosts[:limit]
