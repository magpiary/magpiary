"""Link cleaner: turns whatever the phone sent into a canonical URL.

A pure function, no network. Rules per source are the table in docs/specs.md
("Link-cleaning rules"). The same rules run on the phone; this is the second check.
Short links (Threads /share/, Reddit /s/ and redd.it, Instagram /share/, X t.co, LinkedIn lnkd.in)
cannot be cleaned without a network call: they come back with needs_expansion=True
and are expanded in a later step, then cleaned again.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

_CODE = r"[A-Za-z0-9_-]+"
_FIRST_LINK = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}>'\""

# Generic rule: parameters that only track the sharer or the click.
_TRACKING_PARAMS = {"igsh", "igshid", "xmt", "si", "s", "t", "fbclid", "gclid", "share_id",
                    "ref", "ref_src", "ref_url", "referrer", "referer", "mc_cid", "mc_eid", "_ga", "_gl", "gbraid", "wbraid", "msclkid", "yclid", "dclid", "twclid", "li_fat_id", "spm", "mkt_tok", "trk", "trkid", "trkinfo", "vero_id", "oly_enc_id", "oly_anon_id", "rb_clickid", "cmpid"}


class UnsupportedLink(ValueError):
    """The input is empty, not a link, or not a link to a post."""


@dataclass(frozen=True)
class CleanLink:
    url: str
    source: str  # instagram, threads, x, reddit, youtube, linkedin, other
    kind: str | None = None  # reel, post, video, ... where known
    needs_expansion: bool = False  # True: url is a short link to expand, then clean again


def extract_link(text: str) -> str:
    """First http(s) link in the text, without trailing punctuation."""
    match = _FIRST_LINK.search(text or "")
    if not match:
        raise UnsupportedLink("no link found")
    return match.group(0).rstrip(_TRAILING_PUNCT)


def clean(text: str) -> CleanLink:
    """Clean a shared link (or text containing one). Raises UnsupportedLink."""
    parts = urlsplit(extract_link(text))
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    query = dict(parse_qsl(parts.query))

    for domains, handler in _HANDLERS:
        if host in domains or any(host.endswith("." + d) for d in domains):
            return handler(host, segments, query)
    return _clean_other(parts)


def _instagram(host: str, segments: list[str], query: dict) -> CleanLink:
    if segments and segments[0] == "share":
        # /share/<code>/ and /share/reel/<code>/ and /share/p/<code>/
        if len(segments) >= 2 and re.fullmatch(_CODE, segments[-1]):
            return CleanLink("https://www.instagram.com/" + "/".join(segments) + "/",
                             "instagram", needs_expansion=True)
        raise UnsupportedLink("instagram share link without a code")
    # also handles /<user>/reel/<code>/
    for i, seg in enumerate(segments[:-1]):
        if seg in ("reel", "reels", "p", "tv") and re.fullmatch(_CODE, segments[i + 1]):
            kind = {"reel": "reel", "reels": "reel", "p": "post", "tv": "tv"}[seg]
            path = {"reel": "reel", "post": "p", "tv": "tv"}[kind]
            return CleanLink(f"https://www.instagram.com/{path}/{segments[i + 1]}/",
                             "instagram", kind)
    raise UnsupportedLink("not an instagram post, reel or tv link")


def _threads(host: str, segments: list[str], query: dict) -> CleanLink:
    if segments and segments[0] == "share" or (segments and segments[0] == "t"):
        if len(segments) >= 2 and re.fullmatch(_CODE, segments[1]):
            return CleanLink(f"https://www.threads.com/{segments[0]}/{segments[1]}/",
                             "threads", needs_expansion=True)
        raise UnsupportedLink("threads short link without a code")
    if len(segments) >= 3 and segments[0].startswith("@") and segments[1] == "post" \
            and re.fullmatch(_CODE, segments[2]):
        return CleanLink(f"https://www.threads.com/{segments[0]}/post/{segments[2]}/",
                         "threads", "post")
    raise UnsupportedLink("not a threads post link")


def _x(host: str, segments: list[str], query: dict) -> CleanLink:
    if host == "t.co":
        if len(segments) == 1 and re.fullmatch(_CODE, segments[0]):
            return CleanLink(f"https://t.co/{segments[0]}", "x", needs_expansion=True)
        raise UnsupportedLink("t.co link without a code")
    if len(segments) >= 3 and segments[1] in ("status", "statuses") and segments[2].isdigit():
        return CleanLink(f"https://x.com/{segments[0]}/status/{segments[2]}", "x", "post")
    raise UnsupportedLink("not an x post link")


def _reddit(host: str, segments: list[str], query: dict) -> CleanLink:
    if host == "redd.it":
        if len(segments) == 1 and re.fullmatch(_CODE, segments[0]):
            return CleanLink(f"https://redd.it/{segments[0]}", "reddit", needs_expansion=True)
        raise UnsupportedLink("redd.it link without a code")
    if len(segments) >= 4 and segments[0] == "r" and segments[2] == "s" \
            and re.fullmatch(_CODE, segments[3]):
        return CleanLink(f"https://www.reddit.com/r/{segments[1]}/s/{segments[3]}",
                         "reddit", needs_expansion=True)
    if len(segments) >= 4 and segments[0] == "r" and segments[2] == "comments" \
            and re.fullmatch(r"[a-z0-9]+", segments[3].lower()):
        return CleanLink(
            f"https://www.reddit.com/r/{segments[1].lower()}/comments/{segments[3].lower()}/",
            "reddit", "post")
    raise UnsupportedLink("not a reddit post link")


def _linkedin(host: str, segments: list[str], query: dict) -> CleanLink:
    if host == "lnkd.in":
        if len(segments) == 2 and segments[0] == "p" and re.fullmatch(_CODE, segments[1]):
            return CleanLink(f"https://lnkd.in/p/{segments[1]}", "linkedin", needs_expansion=True)
        raise UnsupportedLink("lnkd.in link without a code")
    # /posts/<slug>-<id>, /feed/update/urn:li:activity:<id>, /pulse/<slug>: the path is the identity
    if segments and segments[0] in ("posts", "feed", "pulse", "events"):
        return CleanLink("https://www.linkedin.com/" + "/".join(segments) + "/", "linkedin", "post")
    raise UnsupportedLink("not a linkedin post link")


def _youtube(host: str, segments: list[str], query: dict) -> CleanLink:
    video_id = None
    if host == "youtu.be":
        video_id = segments[0] if segments else None
    elif segments and segments[0] == "watch":
        video_id = query.get("v")
    elif len(segments) >= 2 and segments[0] in ("shorts", "live", "embed", "v"):
        video_id = segments[1]
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        kind = "short" if segments and segments[0] == "shorts" else "video"
        return CleanLink(f"https://www.youtube.com/watch?v={video_id}", "youtube", kind)
    raise UnsupportedLink("not a youtube video link")


def _clean_other(parts) -> CleanLink:
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise UnsupportedLink("not a web link")
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    netloc = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
    url = f"{parts.scheme.lower()}://{netloc}{parts.path}"
    if kept:
        url += "?" + urlencode(kept)
    return CleanLink(url, "other")


_HANDLERS = [
    (("instagram.com",), _instagram),
    (("threads.net", "threads.com"), _threads),
    (("x.com", "twitter.com", "t.co"), _x),
    (("reddit.com", "redd.it"), _reddit),
    (("youtube.com", "youtu.be"), _youtube),
    (("linkedin.com", "lnkd.in"), _linkedin),
]
