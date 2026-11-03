"""The hub's look (M7a, the C1+ design): static files, the page shell (top bar, the strip, update banner), the
viewer's appearance settings, and the small pieces every page shares (tiles, colours, titles, times).

Static files live in `static/` next to this module and are served only from a fixed list. Every value shown is
escaped; pages run no inline script except the one carrying the nonce, so the page policy stays strict.
"""

import hashlib
import json
import re
from functools import lru_cache
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from magpiary.brain import TYPE_NAMES
from magpiary.queuepage import SOURCE_NAMES
from magpiary.web import Response, e

STATIC = Path(__file__).with_name("static")
STATIC_FILES = {"hub.css": "text/css; charset=utf-8", "hub.js": "text/javascript; charset=utf-8",
                "fonts/bricolage-grotesque.woff2": "font/woff2", "fonts/dm-sans.woff2": "font/woff2",
                "fonts/quicksand.woff2": "font/woff2", "indigo.css": "text/css; charset=utf-8",
                "indigo.js": "text/javascript; charset=utf-8", "digest.js": "text/javascript; charset=utf-8", "vendor/lenis.min.js": "text/javascript; charset=utf-8",
                **{f"art/{n}.webp": "image/webp" for n in ("fly-a", "fly-b", "fly-c", "fly-d", "land-a", "land-b",
                                                           "land-c", "stack", "post", "digest-gift-1x", "digest-gift-2x")},
                "vendor/gsap.min.js": "text/javascript; charset=utf-8",
                "vendor/Flip.min.js": "text/javascript; charset=utf-8", "icon.svg": "image/svg+xml",
                "emoji.json": "application/json",
                "lock.js": "text/javascript; charset=utf-8", "settings.js": "text/javascript; charset=utf-8",
                "map.js": "text/javascript; charset=utf-8", "map.css": "text/css; charset=utf-8"}  # every emoji (Unicode names and keywords, MIT: emoji.LICENSE.txt)

SIZES = {"s": "Small tiles", "m": "Medium tiles", "l": "Large tiles"}
# Looks the owner kept as choices in Settings → Appearance (24 Oct); the first of each is the default.
# Search is always the Spotlight and posts always open as a page (owner, 1 Nov): those two are no longer choices, only fixed
# attributes (FIXED) that hub.js reads.
CHOICES = {"piles": {"stack": "Stacks", "folder": "Folders"},
           "labels": {"black": "Black overlay", "colour": "Coloured", "soft": "Soft caption"},
           "glass": {"on": "On", "off": "Off"},
           "world": {"full": "Moving", "frame": "Dark content", "still": "Still"},
           # how big the whole hub is; Automatic shrinks it on a laptop-sized window (hub.css: html[data-scale])
           "scale": {"auto": "Automatic", "85": "85%", "90": "90%", "100": "100%", "110": "110%"}}  # first choice is the default
THEMES = {"indigo": "Indigo", "dark": "Dark"}  # a light theme may come later
DEFAULT_THEME = "dark"  # what a new install opens in (owner, 1 Nov); Settings → Appearance can switch to Indigo
FIXED = ' data-search="spot" data-open="page"'
LAYOUTS = {"boxed": "Boxed", "full": "Full width"}
BOX_MIN, BOX_MAX, BOX_DEFAULT = 960, 2400, 1600  # the page is capped at 1,600 px by default
GLASS_STOPS = (25, 50, 75, 100)  # Settings → Appearance → Glass strength: four steps, 25 is the default


def glass_stop(value) -> int:
    """The nearest of the four stops (an old or odd saved number lands on one)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return GLASS_STOPS[0]
    return min(GLASS_STOPS, key=lambda s: abs(s - v))


def glass_gs(level: int) -> float:
    """The number every glass value in hub.css scales by: the first stop is the look the owner approved on 29 Oct
    (0.3 of the full effect), the last is the full effect."""
    return 0.3 + (glass_stop(level) - GLASS_STOPS[0]) * 0.7 / (GLASS_STOPS[-1] - GLASS_STOPS[0])
BOX_PRESETS = (1600, 1920, 2200, 2400)  # Settings → Appearance offers these (a slider was too jumpy)

# The wall's heading changes once a day (no counts: they stop meaning much at 400 saves).
HEADS = [("Shiny things,", "safely <em>kept.</em>"), ("Everything that", "caught your <em>eye.</em>"),
         ("Your little", "<em>hoard.</em>"), ("Saved for", "a <em>reason.</em>"), ("Worth a", "second <em>look.</em>"),
         ("The good bits,", "all in <em>one place.</em>"), ("Collected,", "not <em>forgotten.</em>")]


def fingerprint() -> str:
    """In every static URL, so a changed file is never served from an old cache (sizes and change times only)."""
    digest = hashlib.sha256()
    for name in STATIC_FILES:
        try:
            st = (STATIC / name).stat()
            digest.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            pass
    return digest.hexdigest()[:10]


def static(path: str) -> Response:
    name = path.removeprefix("/static/")
    if name not in STATIC_FILES:
        return Response(404, b"not found", "text/plain")
    try:
        data = (STATIC / name).read_bytes()
    except OSError:
        return Response(404, b"not found", "text/plain")
    return Response(200, data, STATIC_FILES[name], {"Cache-Control": "public, max-age=31536000, immutable",
                                                    "X-Content-Type-Options": "nosniff"})


def csp(nonce: str) -> str:
    return (f"default-src 'none'; img-src 'self' data:; media-src 'self'; connect-src 'self'; font-src 'self'; "
            f"style-src 'self' 'unsafe-inline'; script-src 'nonce-{nonce}' 'self'; form-action 'self'; "
            f"base-uri 'none'; frame-ancestors 'none'")


def appearance(store) -> dict:
    size = store.get_setting("ui_size", "m")
    theme = store.get_setting("ui_theme", DEFAULT_THEME)
    layout = store.get_setting("ui_layout", "boxed")
    try:
        box = min(max(int(store.get_setting("ui_box", str(BOX_DEFAULT))), BOX_MIN), BOX_MAX)
    except ValueError:
        box = BOX_DEFAULT
    glass_level = glass_stop(store.get_setting("ui_glass_level", str(GLASS_STOPS[0])))
    look = {"size": size if size in SIZES else "m", "theme": theme if theme in THEMES else DEFAULT_THEME,
            "layout": layout if layout in LAYOUTS else "boxed", "box": box, "glass_level": glass_level}
    for name, choices in CHOICES.items():
        value = store.get_setting(f"ui_{name}", "")
        look[name] = value if value in choices else next(iter(choices))
    return look


def document(title: str, body: str, look: dict, csrf: str, page: str, status: int = 200, script: str = "",
             body_class: str = "") -> Response:
    """A whole page. `script` is page data (JSON) for hub.js, carried by the one nonce'd script tag."""
    nonce = secrets.token_urlsafe(12)
    v = fingerprint()
    theme = f' data-theme="{look["theme"]}"'
    picks = "".join(f' data-{name}="{look[name]}"' for name in CHOICES) + FIXED
    doc = (f'<!doctype html><html lang="en" data-size="{look["size"]}" data-layout="{look["layout"]}"{theme}{picks} '
           f'style="--box:{look["box"]}px;--gs:{glass_gs(look["glass_level"]):.3g}"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
           f'<meta name="csrf" content="{e(csrf)}">'
           f'<script nonce="{nonce}">try{{if(sessionStorage.getItem("mag-enter"))document.documentElement.classList.add("entering");'
           f'if(sessionStorage.getItem("mag-slide"))document.documentElement.classList.add("slide-in","slidefx");'
           f'if((!sessionStorage.getItem("mag-opened")||/[?&]opening=1/.test(location.search))&&!matchMedia("(prefers-reduced-motion: reduce)").matches)document.documentElement.classList.add("opening")}}catch(e){{}}</script>'
           f'<title>{e(title)} · Magpiary</title>'
           f'<link rel="icon" type="image/svg+xml" href="/static/icon.svg?v={v}">'
           f'<link rel="stylesheet" href="/static/hub.css?v={v}">'
           f'<link rel="stylesheet" href="/static/indigo.css?v={v}"><link rel="stylesheet" href="/static/map.css?v={v}">'
           f'<link rel="preload" href="/static/fonts/quicksand.woff2" as="font" type="font/woff2" crossorigin>'
           f'<link rel="preload" href="/static/fonts/dm-sans.woff2" as="font" type="font/woff2" crossorigin>'
           f'<script defer src="/static/vendor/gsap.min.js?v={v}"></script>'
           f'<script defer src="/static/vendor/Flip.min.js?v={v}"></script>'
           f'<script defer src="/static/vendor/lenis.min.js?v={v}"></script>'
           f'<script defer src="/static/digest.js?v={v}"></script><script defer src="/static/map.js?v={v}"></script>'
           f'<script defer src="/static/hub.js?v={v}"></script>'
           f'<script defer src="/static/indigo.js?v={v}"></script>'
           f'<script defer src="/static/lock.js?v={v}"></script><script defer src="/static/settings.js?v={v}"></script></head>'
           f'<body data-page="{e(page)}"{f" class={chr(34)}{body_class}{chr(34)}" if body_class else ""}>{body}'
           + (f'<script nonce="{nonce}" type="application/json" id="page-data">{script}</script>' if script else "")
           + "</body></html>")
    return Response(status, doc.encode(), headers={"Cache-Control": "no-store", "Content-Security-Policy": csp(nonce),
                                                   "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"})


@lru_cache(maxsize=1)
def logo_mark() -> str:
    """The Pair (owner's pick, 24 Oct): the back bird pink, the front bird in ink so it follows the theme."""
    svg = re.sub(r"<style>.*?</style>", "", (STATIC / "icon.svg").read_text().strip())
    return svg.replace('class="k"', 'fill="currentColor"').replace("<svg ", '<svg class="mark" aria-hidden="true" ', 1)


def art(name: str) -> str:
    """A picture of the bird or its things, cached like every other static file."""
    return f"/static/art/{name}.webp?v={fingerprint()}"


def hidden(csrf: str, **fields) -> str:
    return "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in {"csrf": csrf, **fields}.items())


def button_form(csrf: str, action: str, fields: dict, label: str, cls: str = "btn sm", confirm: str = "",
                title: str = "", busy: str = "") -> str:
    """A button that posts. `busy` is what its label says while the page answers ("Syncing…")."""
    data = f' data-confirm="{e(confirm)}"' if confirm else ""
    data += f' data-busy-label="{e(busy)}"' if busy else ""
    tip = f' title="{e(title)}" aria-label="{e(title)}"' if title else ""
    return (f'<form method="post" action="{e(action)}"{data}>{hidden(csrf, **fields)}'
            f'<button class="{cls}" type="submit"{tip}>{label}</button></form>')


def sticker(sid: str, cls: str = "") -> str:
    """A board's sticker: its emoji with a white die-cut edge, tilted a little (the same way every time)."""
    from magpiary import stickers

    tilt = (sum(map(ord, sid or "")) % 13) - 6
    return (f'<span class="stk{" " + cls if cls else ""}" style="--tilt:{tilt}deg" aria-hidden="true">'
            f'{e(stickers.emoji(sid))}</span>')


SOCIAL_ICONS = {  # the logos of the link slots, one colour (the text colour); the website gets a globe
    "instagram": '<rect x="3.2" y="3.2" width="17.6" height="17.6" rx="5.2" fill="none" stroke="currentColor" stroke-width="2"/>'
                 '<circle cx="12" cy="12" r="4.1" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.3" cy="6.7" r="1.2"/>',
    "x": '<path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 '
         '6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/>',
    "github": '<path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04'
              '-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 '
              '1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 '
              '1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 '
              '3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.925.435.375.81 1.095.81 '
              '2.22 0 1.605-.015 2.895-.015 3.285 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>',
    "website": '<g fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/>'
               '<path d="M3 12h18M12 3c2.6 2.6 3.9 5.6 3.9 9s-1.3 6.4-3.9 9c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3Z"/></g>',
}


def social_icon(slot: str) -> str:
    return (f'<svg class="soc" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{SOCIAL_ICONS[slot]}</svg>'
            if slot in SOCIAL_ICONS else "")


def avatar(name: str, colour: str, photo_url: str = "", cls: str = "") -> str:
    """A member's round picture: their photo, or their initials on their colour."""
    from magpiary.identity import initials

    inner = (f'<img src="{e(photo_url)}" alt="">' if photo_url else f"<span>{e(initials(name))}</span>")
    return f'<span class="avatar{" " + cls if cls else ""}" style="--c:{e(colour)};--ink:{ink(colour)}" aria-hidden="true">{inner}</span>'


# ---- what a save looks like --------------------------------------------------------------------------

SOURCE_LOGOS = {
    "threads": '<path d="M17.7 11.1a7 7 0 0 0-.3-.1c-.2-3-1.8-4.7-4.6-4.7-1.7 0-3 .7-3.9 2l1.6 1.1c.6-1 1.5-1.2 2.3-1.2 1 0 1.7.3 2.2.8.3.4.5.9.6 1.5-.8-.1-1.7-.2-2.6-.1-2.6.2-4.3 1.7-4.2 3.9.1 1.1.6 2 1.5 2.6.8.5 1.8.8 2.8.7 1.4-.1 2.5-.6 3.2-1.6.6-.7.9-1.7 1-2.9.7.4 1.2 1 1.5 1.6.5 1.1.5 3-1 4.5-1.3 1.3-2.9 1.9-5.3 1.9-2.7 0-4.7-.9-6-2.6-1.2-1.6-1.9-3.8-1.9-6.5s.7-4.9 1.9-6.5c1.3-1.7 3.3-2.6 6-2.6s4.8.9 6.2 2.6c.7.8 1.2 1.9 1.5 3.1l1.9-.5c-.4-1.5-1-2.8-1.9-3.8C18.4 1.1 15.8 0 12.3 0 8.9 0 6.3 1.1 4.6 3.3 3.1 5.3 2.3 8 2.3 11.5v.1c0 3.4.8 6.2 2.3 8.2 1.7 2.2 4.3 3.3 7.7 3.3 3 0 5.2-.8 6.9-2.5 2.3-2.3 2.2-5.1 1.5-6.9-.5-1.2-1.6-2.2-3-2.7zm-5 4.8c-1.2.1-2.4-.5-2.5-1.5 0-.8.6-1.7 2.4-1.8h.8c.6 0 1.3.1 1.8.2-.2 2.4-1.4 3-2.5 3.1z"/>',
    "youtube": '<path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8zM9.6 15.6V8.4l6.2 3.6-6.2 3.6z"/>',
    "reddit": '<path d="M24 12.1a2.6 2.6 0 0 0-4.4-1.9 12.8 12.8 0 0 0-6.9-2.2l1.2-5.5 3.8.8a1.9 1.9 0 1 0 .2-1l-4.3-.9a.5.5 0 0 0-.6.4l-1.3 6.2a12.9 12.9 0 0 0-7 2.2 2.6 2.6 0 1 0-2.9 4.3 5 5 0 0 0 0 .8c0 3.9 4.6 7.1 10.2 7.1s10.2-3.2 10.2-7.1a5 5 0 0 0 0-.8 2.6 2.6 0 0 0 1.8-2.4zM6.7 13.9a1.9 1.9 0 1 1 3.8 0 1.9 1.9 0 0 1-3.8 0zm10.3 4.8c-1.3 1.3-3.8 1.4-5 1.4s-3.7-.1-5-1.4a.5.5 0 0 1 .7-.7c.8.8 2.6 1.1 4.3 1.1s3.5-.3 4.3-1.1a.5.5 0 0 1 .7.7zm-.4-2.9a1.9 1.9 0 1 1 0-3.8 1.9 1.9 0 0 1 0 3.8z"/>',
    "linkedin": '<path d="M20.4 20.4h-3.5v-5.6c0-1.3 0-3-1.9-3s-2.1 1.4-2.1 2.9v5.7H9.3V9h3.4v1.6c.5-.9 1.6-1.9 3.4-1.9 3.6 0 4.3 2.4 4.3 5.5v6.2zM5.3 7.4a2.1 2.1 0 1 1 0-4.1 2.1 2.1 0 0 1 0 4.1zm1.8 13H3.6V9h3.5v11.4z"/>',
}


SOURCE_DOMAINS = {"x": "x.com", "instagram": "instagram.com", "threads": "threads.com", "youtube": "youtube.com",
                  "reddit": "reddit.com", "linkedin": "linkedin.com"}


def source_logo(source: str, cls: str = "slogo") -> str:
    """The platform's mark alone, one flat colour (the text colour), for a place where a picture should be."""
    paths = SOURCE_LOGOS.get(source) or SOCIAL_ICONS.get(source) or SOCIAL_ICONS["website"]
    return f'<svg class="{cls}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{paths}</svg>'


def source_badge(source: str) -> str:
    """Where a post came from: its logo and its name, plainly (owner, 1 Nov). A source with no logo gets the globe."""
    paths = SOURCE_LOGOS.get(source) or SOCIAL_ICONS.get(source) or SOCIAL_ICONS["website"]
    return (f'<span class="pvsrc"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{paths}</svg>'
            f'{SOURCE_DOMAINS.get(source) or source_name(source)}</span>')


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source.title() if source else "Web")


def source_colour(source: str) -> str:
    known = ("instagram", "threads", "youtube", "reddit", "x", "linkedin")
    return f"var(--s-{source if source in known else 'other'})"


def type_colour(kind: str | None) -> str:
    return f"var(--t-{kind if kind in TYPE_NAMES else 'other'})"


# Piles and board folders use their own deep palette, so a bright colour on a tile always means a kind of post
PILE_COLOURS = ("sky", "coral", "lilac", "rose", "mint", "butter", "peach", "aqua")
# a board's stored colour (also the creator's colour, synced to friends) shown in the folder palette
FOLDER_COLOURS = {"#ff2e93": "rose", "#2f6bff": "sky", "#8a3ffc": "lilac", "#00a37a": "mint",
                  "#f5a300": "butter", "#e04b00": "peach", "#0091b3": "aqua", "#ff4f2b": "coral",
                  "#8ab32d": "moss", "#c026d3": "plum", "#4f46e5": "indigo", "#64748b": "slate",
                  "#22a14b": "forest", "#e11d48": "berry", "#0284c7": "ocean", "#c8a26b": "clay"}


def pile_colour(pile: dict) -> str:
    """Each pile keeps its own colour, picked once from its id, so the Piles view is always colourful."""
    return f"var(--f-{PILE_COLOURS[pile['id'] % len(PILE_COLOURS)]})"


def folder_colour(stored: str) -> str:
    return f"var(--f-{FOLDER_COLOURS.get((stored or '').lower(), 'rose')})"


# text on a person's colour (initials on an avatar); checked like the tokens in scripts/contrast_check.py
PERSON_INK = {"#ff2e93": "#111", "#2f6bff": "#fff", "#8a3ffc": "#fff", "#00a37a": "#111",
              "#f5a300": "#111", "#e04b00": "#111", "#0091b3": "#111", "#ff4f2b": "#111",
              "#8ab32d": "#111", "#c026d3": "#fff", "#4f46e5": "#fff", "#64748b": "#fff",
              "#22a14b": "#111", "#e11d48": "#fff", "#0284c7": "#111", "#c8a26b": "#111"}


def deep(colour: str) -> str:
    """The deeper shade of a category or source colour, for white text on it: `var(--t-tool)` → `var(--t-tool-deep)`."""
    return f"{colour[:-1]}-deep)" if colour.startswith(("var(--t-", "var(--s-")) else colour


def ink(colour: str) -> str:
    """The text colour that reads on a person's colour (initials on an avatar)."""
    return PERSON_INK.get(colour.lower(), "#fff")


def type_name(kind: str | None) -> str:
    return TYPE_NAMES.get(kind or "", "Other")


def caption_title(item: dict) -> str:
    """Without an AI title: the caption's first sentence, else the post's own title, else 'Post by …'."""
    if item["source"] in ("reddit", "youtube") and item.get("title"):
        return item["title"]
    caption = (item.get("caption") or "").strip()
    if caption:
        first = re.split(r"(?<=[.!?])\s|\n", caption, maxsplit=1)[0].strip()
        return first[:160] or caption[:160]
    who = item.get("author") or source_name(item["source"])
    return item.get("title") or f"Post by {who}"


def title_of(item: dict) -> str:
    return item.get("ai_title") or caption_title(item)


def hue(item: dict) -> int:
    return int(hashlib.sha256(item["canonical_url"].encode()).hexdigest()[:4], 16) % 360


def gradient(item: dict) -> str:
    h = hue(item)
    return f"linear-gradient(160deg,hsl({h} 70% 58%),hsl({(h + 45) % 360} 65% 32%))"


def duration(seconds) -> str:
    try:
        secs = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}"


def secs(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{int(value // 60)}m {int(value % 60)}s" if value >= 60 else f"{value:.1f}s" if value < 10 else f"{int(value)}s"


def local(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone() if when.tzinfo else when


def day(stamp: str | None) -> str:
    when = local(stamp)
    if not when:
        return ""
    now = datetime.now(when.tzinfo)
    if when.date() == now.date():
        return f"today {when:%H:%M}"
    if when.date() == (now - timedelta(days=1)).date():
        return f"yesterday {when:%H:%M}"
    return f"{when.day} {when:%b}" + (f" {when.year}" if when.year != now.year else "")


def section_of(item: dict, today=None) -> str:
    """Today, This week, then the month (with the year when it is not this year), by when it was last shared."""
    when = local(item.get("last_shared_at") or item.get("created_at"))
    if not when:
        return "Earlier"
    today = today or datetime.now(when.tzinfo).date()
    if when.date() == today:
        return "Today"
    if (today - when.date()).days < 7:
        return "This week"
    return f"{when:%B}" + (f" {when.year}" if when.year != today.year else "")


def mark(text: str, words: list[str]) -> str:
    """Escaped text with the search words highlighted (word starts, any case)."""
    if not words:
        return e(text)
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")", re.IGNORECASE)
    out, last = [], 0
    for m in pattern.finditer(text):
        out.append(e(text[last:m.start()]))
        out.append(f"<mark>{e(m.group(0))}</mark>")
        last = m.end()
    out.append(e(text[last:]))
    return "".join(out)


HIT_FIELDS = (("Said", "transcript_text"), ("Caption", "caption"), ("On screen", "screen_text"), ("Summary", "summary"),
              ("Your note", "note"), ("Mentioned", "entities_text"))


def hit(item: dict, words: list[str]) -> tuple[str, str] | None:
    """Where a search matched, as (label, the matching line), skipping the title (it is on the tile already)."""
    if not words:
        return None
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")", re.IGNORECASE)
    for label, field in HIT_FIELDS:
        text = item.get(field) or ""
        m = pattern.search(text)
        if m:
            start = max(0, m.start() - 30)
            snippet = text[start:start + 100].replace("\n", " ").strip()
            return label, ("…" if start else "") + snippet + ("…" if start + 100 < len(text) else "")
    title = item.get("title") or ""
    if pattern.search(title) or pattern.search(item.get("ai_title") or ""):
        return "Title", "The words are in the title"
    return None


def why(item: dict, words: list[str]) -> tuple[str, str]:
    """Why a save is in the results: where the words matched, or "Topic" when it was found by meaning alone."""
    return hit(item, words) or ("Topic", "Close in meaning to what you typed")


# ---- what is in an item's folder (read once per change) ------------------------------------------------

@lru_cache(maxsize=4096)
def _read(path: str, stamp: int):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def read_json(path: Path):
    """A JSON file from an item's folder, cached until the file changes. Treat the result as read-only."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    return _read(str(path), stamp)


def folder_of(item: dict) -> Path | None:
    return Path(item["archive_dir"]) if item.get("archive_dir") else None


def media_of(item: dict) -> dict:
    """For a tile: the first video, the photos, the length, and where the first key moment is (seconds)."""
    folder = folder_of(item)
    meta = (read_json(folder / "meta.json") if folder else None) or {}
    record = (read_json(folder / "record.json") if folder else None) or {}
    media = meta.get("media") or []
    videos = [m for m in media if m.endswith((".mp4", ".webm", ".mov"))]
    photos = [m for m in media if not m.endswith((".mp4", ".webm", ".mov"))]
    start = 0
    for point in record.get("key_points") or []:
        at = (point.get("at") or "").split(":")
        if all(x.isdigit() for x in at) and at != [""]:
            start = sum(int(x) * 60 ** n for n, x in enumerate(reversed(at)))
            break
    return {"video": videos[0] if videos else "", "photos": photos, "duration": meta.get("duration"), "start": start,
            "entities": record.get("entities") or {}}


# ---- small line icons (currentColor), for the Nest and Settings ------------------------------------------------

_ICON_PATHS = {
    "terminal": '<path d="m5 8 4 4-4 4"/><path d="M12 17h7"/>',
    "fetch": '<path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19h14"/>',
    "download": '<path d="M7 17h10M12 4v9m0 0 3.5-3.5M12 13 8.5 9.5"/><rect x="4" y="15" width="16" height="5" rx="2"/>',
    "transcribe": '<path d="M4 12h2m3-5v10m3-13v16m3-11v6m3-8v10m3-5h0"/>',
    "frames": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "summary": '<path d="M4 20l4-1 11-11-3-3L5 16l-1 4z"/><path d="M14 6l3 3"/>',
    "links": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "alert": '<path d="M12 4 2.8 19.5h18.4L12 4z"/><path d="M12 10v4.5m0 2.5v.01"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "up": '<path d="M7 11v9H4.5a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1zM7 11l4-7.5a2 2 0 0 1 3.4 1.8L13.6 9H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7"/>',
    "grip": '<circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/>',
    "sparkle": '<path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6z"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "library": '<rect x="3.5" y="4" width="7" height="7" rx="1.5"/><rect x="13.5" y="4" width="7" height="7" rx="1.5"/><rect x="3.5" y="13" width="7" height="7" rx="1.5"/><rect x="13.5" y="13" width="7" height="7" rx="1.5"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.4 0 2-1 1.4-2.2-.7-1.4.3-2.8 1.8-2.8H17a3.5 3.5 0 0 0 3.5-3.5C20.5 7 16.7 3.5 12 3.5z"/><circle cx="8" cy="11" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16" cy="10" r="1"/>',
    "moon": '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "chev": '<path d="M9 5l7 7-7 7"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "chevup": '<path d="M5.5 15l6.5-6.5 6.5 6.5"/>',
    "openpage": '<path d="M13 4h7v7M20 4l-9 9M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "expand": '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
    "minimize": '<path d="M6 12h12"/>',
    "chats": '<rect x="3.5" y="4.5" width="17" height="15" rx="3.5"/><path d="M9.5 4.5v15"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "grid2": '<rect x="4.00" y="4.00" width="6.80" height="6.80" rx="1.60"/><rect x="12.00" y="4.00" width="6.80" height="6.80" rx="1.60"/><rect x="4.00" y="12.00" width="6.80" height="6.80" rx="1.60"/><rect x="12.00" y="12.00" width="6.80" height="6.80" rx="1.60"/>',
    "grid3": '<rect x="4.00" y="4.00" width="4.13" height="4.13" rx="1.38"/><rect x="9.33" y="4.00" width="4.13" height="4.13" rx="1.38"/><rect x="14.67" y="4.00" width="4.13" height="4.13" rx="1.38"/><rect x="4.00" y="9.33" width="4.13" height="4.13" rx="1.38"/><rect x="9.33" y="9.33" width="4.13" height="4.13" rx="1.38"/><rect x="14.67" y="9.33" width="4.13" height="4.13" rx="1.38"/><rect x="4.00" y="14.67" width="4.13" height="4.13" rx="1.38"/><rect x="9.33" y="14.67" width="4.13" height="4.13" rx="1.38"/><rect x="14.67" y="14.67" width="4.13" height="4.13" rx="1.38"/>',
    "grid4": '<rect x="4.00" y="4.00" width="2.80" height="2.80" rx="0.93"/><rect x="8.00" y="4.00" width="2.80" height="2.80" rx="0.93"/><rect x="12.00" y="4.00" width="2.80" height="2.80" rx="0.93"/><rect x="16.00" y="4.00" width="2.80" height="2.80" rx="0.93"/><rect x="4.00" y="8.00" width="2.80" height="2.80" rx="0.93"/><rect x="8.00" y="8.00" width="2.80" height="2.80" rx="0.93"/><rect x="12.00" y="8.00" width="2.80" height="2.80" rx="0.93"/><rect x="16.00" y="8.00" width="2.80" height="2.80" rx="0.93"/><rect x="4.00" y="12.00" width="2.80" height="2.80" rx="0.93"/><rect x="8.00" y="12.00" width="2.80" height="2.80" rx="0.93"/><rect x="12.00" y="12.00" width="2.80" height="2.80" rx="0.93"/><rect x="16.00" y="12.00" width="2.80" height="2.80" rx="0.93"/><rect x="4.00" y="16.00" width="2.80" height="2.80" rx="0.93"/><rect x="8.00" y="16.00" width="2.80" height="2.80" rx="0.93"/><rect x="12.00" y="16.00" width="2.80" height="2.80" rx="0.93"/><rect x="16.00" y="16.00" width="2.80" height="2.80" rx="0.93"/>',
    "select": '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "fingerprint": '<path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4"/><path d="M14 13.12c0 2.38 0 6.38-1 8.88"/>'
                   '<path d="M17.29 21.02c.12-.6.43-2.3.5-3.02"/><path d="M2 12a10 10 0 0 1 18-6"/><path d="M2 16h.01"/>'
                   '<path d="M21.8 16c.2-2 .131-5.354 0-6"/><path d="M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .34-2"/>'
                   '<path d="M8.65 22c.21-.66.45-1.32.57-2"/><path d="M9 6.8a6 6 0 0 1 9 5.2v2"/>',
    "more": '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5m0-8.5v.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "wifi": '<path d="M3.5 9.5a12 12 0 0 1 17 0M6.5 12.8a7.8 7.8 0 0 1 11 0M9.6 16a3.4 3.4 0 0 1 4.8 0"/><circle cx="12" cy="19" r=".8" fill="currentColor"/>',
    "play": '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M10.5 9.5l4 2.5-4 2.5z"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "stop": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 8.5l7 7"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V5h5v2M6.5 7l1 12.5h9l1-12.5"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/>',
    "digest": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 8.5h8M8 12h8M8 15.5h5"/>',
    "share": '<path d="M12 3.5v11M8 7.5l4-4 4 4"/><path d="M7 11H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-1"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "paste": '<rect x="5.5" y="5" width="13" height="16" rx="2.5"/><path d="M9 5v-.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V5"/><path d="M9 12h6M9 16h4"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "ext": '<path d="M7 17 17 7M9 7h8v8"/>',
    "health": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/><path d="M8 11h2l1-2 2 4 1-2h2"/>',
    "chart": '<path d="M5 20V11M12 20V5M19 20v-6"/>',
    "stats": '<path d="M4 19h16M7 16v-5M12 16V6M17 16v-8"/>',
    "trend": '<path d="M4 16l5-5 3.5 3.5L20 7"/><path d="M14.5 7H20v5.5"/>',
    "heart": '<path d="M12 19.5s-7-4.3-7-9.6A3.9 3.9 0 0 1 12 7.6a3.9 3.9 0 0 1 7 2.3c0 5.3-7 9.6-7 9.6z"/>',
    "comment": '<path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V16h-.5A2.5 2.5 0 0 1 5 13.5z"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    "send": '<path d="M20.5 3.5 10 14"/><path d="M20.5 3.5 14 20.5l-4-6.5-6.5-4z"/>',
    "people": '<circle cx="9" cy="8.5" r="3.2"/><path d="M3 19c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><circle cx="17" cy="9.5" r="2.5"/><path d="M15.8 14.2c2.6-.3 4.6 1.1 5.2 4.3"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1.2"/><path d="M5 9v9.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V9M10 13h4"/>',
    # Lucide "activity" (ISC licence): the Nest, what the Mac is working on (owner, 29 Oct: a known icon, not our nest)
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "book": '<path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5c-3.5-.5-6.5 0-8.5 1.5z"/><path d="M12 6.5v13"/>',
}


def icon(name: str, cls: str = "ico") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICON_PATHS.get(name, "")}</svg>')
