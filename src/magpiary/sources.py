"""Source adapters: what a post says and which media it has, fetched logged out.

Each adapter takes the canonical URL and returns a `Fetched`, or raises `FetchFailed` with a
needs-attention reason. Network access is injected (`get` for pages, a `YtDlp` for video sites)
so tests replay recorded responses. Everything fetched is untrusted data: it is stored, never obeyed.
"""

import html
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from magpiary import __version__
from magpiary.network import public_urlopen
from magpiary.tools import YtDlp, YtDlpError

USER_AGENT = f"Mozilla/5.0 (Macintosh) Magpiary/{__version__}"  # honest; Threads serves full text to it
MAX_PAGE_BYTES = 3_000_000

# One GET: returns (status, body). Raises OSError on network failure.
Get = Callable[[str], tuple[int, bytes]]


class FetchFailed(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason, self.detail = reason, detail[:200]


@dataclass
class Fetched:
    meta: dict
    video: bool = False  # True: yt-dlp downloads the post's media
    images: list[str] = field(default_factory=list)  # image URLs to download ourselves
    videos: list[str] = field(default_factory=list)  # video file URLs to download ourselves (no yt-dlp)
    poster: str = ""  # a video's cover picture, saved as thumbnail.jpg rather than as a media still
    discussion: list[dict] | None = None
    fetched_with: str = ""


def http_get(url: str, limit: int = MAX_PAGE_BYTES, cookie: str = "") -> tuple[int, bytes]:
    """One page, logged out. `cookie` is only ever the owner's own login for that site, for a post they pressed Retry with my login on."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en", **({"Cookie": cookie} if cookie else {})})
    try:
        with public_urlopen(request, timeout=20) as response:  # no cookie handler: logged out
            return response.status, response.read(limit + 1)[:limit]
    except urllib.error.HTTPError as err:
        return err.code, b""


def _page(get: Get, url: str) -> bytes:
    try:
        status, body = get(url)
    except OSError as err:
        raise FetchFailed("unknown", f"network error: {type(err).__name__}") from err
    if status in (404, 410):
        raise FetchFailed("deleted", f"HTTP {status}")
    if status == 429:
        raise FetchFailed("rate_limited", "HTTP 429")
    if status in (401, 403):
        raise FetchFailed("login_wall", f"HTTP {status}")
    if status != 200:
        raise FetchFailed("unknown", f"HTTP {status}")
    return body


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: dict[str, str] = {}
        self._in_title, self.title = False, ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content") is not None:
                self.tags.setdefault(key.lower(), a["content"])
        self._in_title = tag == "title"

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        self._in_title = False


def page_tags(body: bytes) -> dict[str, str]:
    parser = _Meta()
    parser.feed(body.decode("utf-8", "replace"))
    tags = dict(parser.tags)
    tags.setdefault("title", parser.title.strip())
    return tags


def _from_tags(tags: dict[str, str]) -> dict:
    return {"title": tags.get("og:title") or tags.get("title") or "",
            "text": tags.get("og:description") or tags.get("description") or "",
            "published_at": tags.get("article:published_time") or "",
            "author": tags.get("article:author") or ""}


def html_to_text(fragment: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", fragment)
    text = re.sub(r"<!--.*?-->|<[^>]+>", "", text, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


# ---- video sites through yt-dlp -----------------------------------------------------------

def _from_info(info: dict) -> dict:
    first = next((e for e in info.get("entries") or [] if e), {})
    pick = lambda key: info.get(key) if info.get(key) not in (None, "") else first.get(key)  # noqa: E731
    published = pick("timestamp")
    return {"title": pick("title") or "", "text": pick("description") or "",
            "author": pick("uploader") or pick("channel") or "",
            "author_handle": _handle(pick("uploader_id"), pick("channel")),
            "published_at": _iso(published) if published else (pick("upload_date") or ""),
            "duration": pick("duration"), "like_count": pick("like_count"),
            "comment_count": pick("comment_count"), "view_count": pick("view_count"),
            "parts": len(info.get("entries") or []) or 1}


def _handle(uploader_id, channel) -> str:
    """Instagram's uploader_id is a number; its `channel` is the @name people know."""
    uid = str(uploader_id or "")
    return str(channel or "") if (not uid or uid.isdigit()) else uid


def _iso(timestamp) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(int(timestamp), UTC).isoformat()


def instagram_photos(url: str, get: Get) -> list[str]:
    """Every photo of a post, from Instagram's own embed page (logged out). yt-dlp skips photos."""
    try:
        body = _page(get, url.rstrip("/") + "/embed/captioned/").decode("utf-8", "replace")
    except FetchFailed:
        return []
    found = []
    for raw in re.findall(r'display_url\\*":\\*"(https:.*?)\\*"', body):
        clean = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)
        clean = html.unescape(clean.replace("\\", ""))
        if urlsplit(clean).path not in {urlsplit(f).path for f in found}:
            found.append(clean)
    return found[:20]


def photo_slides(entries: list, pictures: list[str]) -> list[str]:
    """The embed page lists one picture per slide, a video's cover included. Keep the ones for the photo slides
    (the slides yt-dlp returned nothing for), so a video is not also saved as a still."""
    if len(pictures) == len(entries):
        return [pic for entry, pic in zip(entries, pictures, strict=True) if entry is None]
    return pictures


def video_site(url: str, get: Get, ytdlp: YtDlp) -> Fetched:
    """Instagram and YouTube: yt-dlp reads the post. Instagram photos come from the embed page."""
    try:
        info = ytdlp.info(url)
    except YtDlpError as err:
        if err.reason != "no_video":
            raise FetchFailed(err.reason, err.detail) from err
        tags = page_tags(_page(get, url))
        photos = instagram_photos(url, get) if "instagram.com" in url else []
        return Fetched(_from_tags(tags), images=photos or ([tags["og:image"]] if tags.get("og:image") else []),
                       fetched_with="page")
    entries = info.get("entries")
    if entries is not None and None in entries:  # a carousel with photos yt-dlp could not read
        return Fetched(_from_info(info), video=any(entries), images=photo_slides(entries, instagram_photos(url, get)),
                       fetched_with="yt-dlp + embed page")
    return Fetched(_from_info(info), video=True, fetched_with="yt-dlp")


# ---- Threads: one page request ------------------------------------------------------------

def threads(url: str, get: Get, ytdlp: YtDlp) -> Fetched:
    tags = page_tags(_page(get, url))
    if not tags.get("og:description") and not tags.get("og:title"):
        raise FetchFailed("unknown", "the page had no post text (Threads may have changed)")
    meta = _from_tags(tags)
    match = re.match(r"(.*?)\s*\(@([\w.]+)\)", meta["title"])
    if match:
        meta["author"], meta["author_handle"] = match.group(1), match.group(2)
    image = [tags["og:image"]] if tags.get("og:image") else []
    videos = threads_videos(url, get)
    if videos:  # the page's picture is then the video's cover
        return Fetched(meta, videos=videos, poster=image[0] if image else "", fetched_with="page + embed page")
    return Fetched(meta, images=image, fetched_with="page")


def threads_videos(url: str, get: Get) -> list[str]:
    """A post's video files, from Threads' own embed page (logged out). The post page itself only has the cover."""
    try:
        body = _page(get, url.rstrip("/") + "/embed").decode("utf-8", "replace")
    except FetchFailed:
        return []
    found = [html.unescape(src) for src in re.findall(r'<video[^>]*>\s*<source[^>]*\bsrc="(https://[^"]+)"', body)]
    return list(dict.fromkeys(found))[:20]


# ---- Reddit: the post's RSS feed (post first, then comments) -----------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"


def reddit(url: str, get: Get, ytdlp: YtDlp) -> Fetched:
    body = _page(get, url.rstrip("/") + "/.rss")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        root = None
    if root is None or root.tag != f"{_ATOM}feed":
        raise FetchFailed("unknown", "Reddit did not send a feed (probably a bot check)")
    entries = root.findall(f"{_ATOM}entry")
    if not entries:
        raise FetchFailed("deleted", "the feed has no post")

    def read(entry) -> dict:
        content = entry.findtext(f"{_ATOM}content") or ""
        return {"author": (entry.findtext(f"{_ATOM}author/{_ATOM}name") or "").removeprefix("/u/"),
                "published_at": entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated") or "",
                "html": content, "text": html_to_text(content)}

    post = read(entries[0])
    images = re.findall(r'https://(?:i\.redd\.it|preview\.redd\.it)/[^"\'\s<>&]+', html.unescape(post["html"]))
    meta = {"title": entries[0].findtext(f"{_ATOM}title") or "", "text": post["text"],
            "author": post["author"], "author_handle": post["author"], "published_at": post["published_at"],
            "community": (root.find(f"{_ATOM}category").get("label", "") if root.find(f"{_ATOM}category") is not None else "")}
    if "v.redd.it" in post["html"]:
        meta["video_not_archived"] = "Reddit video needs a login; postponed"
    comments = [{k: c[k] for k in ("author", "published_at", "text")} for c in map(read, entries[1:])]
    return Fetched(meta, images=list(dict.fromkeys(images))[:20], discussion=comments, fetched_with="rss")


# ---- X: X's own embed feed ----------------------------------------------------------------

def _x_token(tweet_id: str) -> str:
    """The token X's embed widget sends with the id ((id / 1e15) * pi in base 36, no 0s or dot)."""
    n = (int(tweet_id) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole, frac = int(n), n - int(n)
    out = ""
    while whole:
        out, whole = digits[whole % 36] + out, whole // 36
    out += "."
    for _ in range(12):
        frac *= 36
        out += digits[int(frac)]
        frac -= int(frac)
    return out.replace("0", "").replace(".", "")


def x(url: str, get: Get, ytdlp: YtDlp) -> Fetched:
    tweet_id = urlsplit(url).path.rstrip("/").split("/")[-1]
    body = _page(get, f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token={_x_token(tweet_id)}")
    try:
        data = json.loads(body)
    except ValueError as err:
        raise FetchFailed("unknown", "X sent something that is not a post") from err
    if not data or data.get("__typename") == "TweetTombstone" or "text" not in data:
        raise FetchFailed("deleted", "X has no public post with this id")
    user = data.get("user") or {}
    text = (data.get("note_tweet") or {}).get("note_tweet_results", {}).get("result", {}).get("text") or data["text"]
    meta = {"title": "", "text": text, "author": user.get("name", ""), "author_handle": user.get("screen_name", ""),
            "published_at": data.get("created_at", ""), "like_count": data.get("favorite_count"),
            "comment_count": data.get("conversation_count")}
    media = data.get("mediaDetails") or []
    images = [m["media_url_https"] for m in media if m.get("type") == "photo" and m.get("media_url_https")]
    video = any(m.get("type") in ("video", "animated_gif") for m in media)
    return Fetched(meta, video=video, images=images, fetched_with="x-embed")


# ---- LinkedIn and any other site: the page's details --------------------------------------

def linkedin(url: str, get: Get, ytdlp: YtDlp) -> Fetched:
    tags = page_tags(_page(get, url))
    fetched = Fetched(_from_tags(tags), images=[tags["og:image"]] if tags.get("og:image") else [],
                      fetched_with="page")
    try:
        info = ytdlp.info(url)
        if info.get("formats"):
            fetched.video, fetched.images = True, []
            fetched.meta["duration"] = info.get("duration")
    except YtDlpError:
        pass  # a text or image post: the page is enough
    return fetched


THIN_PAGE = 400  # characters of readable text below which a page is probably drawn by scripts
MAX_PAGE_TEXT = 20_000
MAX_PAGE_IMAGES = 10
SKIP_IMAGE = re.compile(r"(?i)\.svg(\?|$)|^data:|avatar|icon|logo|sprite|emoji|badge|pixel|tracking|1x1|placeholder")
SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "template"}
TEXT_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "figcaption", "pre", "td"}


class _Readable(HTMLParser):
    """The words and pictures of a page's body, leaving out menus, footers and scripts. Text inside <article> or
    <main> is kept apart: when a page has one, that is the reading part."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.skip, self.inside, self.block = base, 0, 0, None
        self.parts: dict[bool, list[str]] = {True: [], False: []}
        self.images: dict[bool, list[str]] = {True: [], False: []}

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in ("article", "main"):
            self.inside += 1
        elif tag in TEXT_TAGS and not self.skip:
            self.block = []
        elif tag == "img" and not self.skip:
            a = dict(attrs)
            src = a.get("data-src") or a.get("src") or ""
            srcset = a.get("srcset") or a.get("data-srcset") or ""
            if srcset:  # the largest picture of a srcset
                src = srcset.split(",")[-1].strip().split(" ")[0] or src
            width = a.get("width") or ""
            small = width.isdigit() and int(width) < 80  # icons and avatars
            if src and not SKIP_IMAGE.search(src) and not small:
                full = urljoin(self.base, src)
                if full.startswith("https://") and full not in self.images[self.inside > 0]:
                    self.images[self.inside > 0].append(full)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in ("article", "main"):
            self.inside = max(0, self.inside - 1)
        elif tag in TEXT_TAGS and self.block is not None:
            line = re.sub(r"\s+", " ", "".join(self.block)).strip()
            if len(line) > 1:
                self.parts[self.inside > 0].append(line)
            self.block = None

    def handle_data(self, data):
        if self.block is not None and not self.skip:
            self.block.append(data)


def readable(body: bytes, url: str) -> tuple[str, list[str]]:
    """A page's reading text and its content pictures (the article or main part when there is one)."""
    parser = _Readable(url)
    try:
        parser.feed(body.decode("utf-8", "replace"))
    except (AssertionError, ValueError):  # broken markup: keep what was read
        pass
    main = bool(parser.parts[True])
    lines = parser.parts[main]
    text = "\n".join(dict.fromkeys(lines))[:MAX_PAGE_TEXT]
    images = (parser.images[True] if main else []) or parser.images[False]
    return text, images[:MAX_PAGE_IMAGES]


# A browser render: url -> the page's HTML after its scripts ran, or b"" when no browser is there or it failed.
Render = Callable[[str], bytes]
BROWSERS = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")


def chrome_render(url: str) -> bytes:
    """The page as a browser draws it, for pages made by scripts. Headless Chrome (or Chromium, Edge, Brave) with a fresh
    empty profile, so logged out, and its own honest headless identity. Only used on a page that already loaded (never on
    one that refused Magpiary), and nothing it runs is kept."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    binary = next((b for b in BROWSERS if Path(b).exists()), None)
    if not binary:
        return b""
    profile = tempfile.mkdtemp(prefix="magpiary-render-")
    try:
        result = subprocess.run([binary, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                 "--disable-extensions", "--mute-audio", f"--user-data-dir={profile}",
                                 "--virtual-time-budget=10000", "--dump-dom", url],
                                capture_output=True, timeout=60)
        return result.stdout[:MAX_PAGE_BYTES] if result.returncode == 0 else b""
    except (OSError, subprocess.SubprocessError):
        return b""
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def other(url: str, get: Get, ytdlp: YtDlp, render: Render | None = None) -> Fetched:
    """Any other page: its preview tags, then its reading text and pictures. A page that loads but is nearly empty is
    drawn by scripts: a browser on the Mac draws it once (when one is installed). A page that refuses Magpiary
    (401/403/429) is not retried another way here: the owner's own browser (the Chrome extension) can send it."""
    body = _page(get, url)
    tags = page_tags(body)
    text, pictures = readable(body, url)
    how = "page"
    if len(text) < THIN_PAGE and render:
        drawn = render(url)
        if drawn:
            drawn_text, drawn_pictures = readable(drawn, url)
            if len(drawn_text) > len(text) or len(drawn_pictures) > len(pictures):
                text, pictures, how = drawn_text, drawn_pictures, "page (drawn by a browser on this Mac)"
                tags = {**page_tags(drawn), **{k: v for k, v in tags.items() if v}}
    meta = _from_tags(tags)
    if len(text) > len(meta["text"]):
        meta["text"] = (meta["text"] + "\n\n" + text).strip() if meta["text"] and meta["text"] not in text else text
    images = list(dict.fromkeys(([tags["og:image"]] if tags.get("og:image") else []) + pictures))[:MAX_PAGE_IMAGES]
    return Fetched(meta, images=images, fetched_with=how)


ADAPTERS = {"instagram": video_site, "youtube": video_site, "threads": threads, "reddit": reddit,
            "x": x, "linkedin": linkedin, "other": other}


def describe(source: str, url: str, get: Get = http_get, ytdlp: YtDlp | None = None, render: Render | None = None) -> Fetched:
    adapter = ADAPTERS.get(source, other)
    if adapter is other:
        return other(url, get, ytdlp or YtDlp(), render)
    return adapter(url, get, ytdlp or YtDlp())
