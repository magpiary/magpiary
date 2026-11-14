"""Draws one category tab of a post view (owner decisions 14 Nov 2026: "structured + interactive").

`render_tab(tab, body, view, state, item)` turns a tab's items (views.ITEM_FIELDS, all strings) into HTML by the tab's
`render` kind (categories.RENDERS). Everything in a view came from a post or an AI reading it, so all of it is untrusted:
every string is escaped, links are only http(s), and a link is either built here from a search provider, written by
lookups.py, or a URL that appears in the post itself. No inline event handlers (the hub's CSP); views.js does the
clicking: ticks and servings are saved through POST /hub/pv/state, copy buttons, flashcards, "Add to calendar".

Ticks are keyed by a hash of the item's name and group, so a rebuilt view keeps the ticks of the items it kept.
"""

import hashlib
import math
import re
from datetime import datetime, timedelta
from fractions import Fraction
from urllib.parse import urlsplit

from magpiary import categories as cats
from magpiary import lookups
from magpiary.web import e

CODE_KINDS = {"code", "prompt", "command"}
COPY_TABS = {"snippets", "setup", "tickets", "copy", "quotes", "best"}  # tabs whose `value` is text to copy (palette: its hex)
AT = re.compile(r"\d{1,2}(?::\d{2}){1,2}")
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])")
WHEN = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
SERVES = re.compile(r"\b(?:serves|servings?:?|feeds|for)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:servings|portions|people)\b", re.I)
MAX_SERVINGS = 24
UNICODE_FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅛": "1/8", "⅜": "3/8",
                     "⅝": "5/8", "⅞": "7/8", "⅙": "1/6", "⅚": "5/6"}
QTY = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)(?:\s*([-–])\s*(\d+/\d+|\d+(?:[.,]\d+)?))?")
ICONS = {
    "copy": ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/>'
             '<path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>'),
    "play": ('<svg class="ico" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10-6.5z"/></svg>'),
    "cal": ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/>'
            '<path d="M3.5 10h17M8 3v4M16 3v4M12 13v4M10 15h4"/></svg>'),
    "pin": ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/>'
            '<circle cx="12" cy="10" r="2.3"/></svg>'),
}


# ---- small helpers ----------------------------------------------------------------------------------------------------


def item_key(it: dict) -> str:
    """A tick's key: stable across rebuilds for the same item (name + group), and inside /hub/pv/state's key rule."""
    raw = (it.get("group", "").strip().lower() + "|" + it.get("name", "").strip().lower()).encode()
    return "i." + hashlib.sha1(raw).hexdigest()[:12]


def http_url(url) -> str:
    """The URL when it is a plain http(s) link to a host, else ""."""
    if not isinstance(url, str) or not url or any(c.isspace() or c in "\"'<>`\\" for c in url) or len(url) > 2000:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return url if parts.scheme in ("http", "https") and parts.hostname else ""


def in_post(url: str, item: dict) -> bool:
    """A URL from a view's `value` becomes a link only when the post itself contains it (never one an AI made up)."""
    text = " ".join(str(item.get(k) or "") for k in ("canonical_url", "caption", "title", "summary"))
    return bool(url) and url in text


def _plain(text) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .,:;!?-–—\"'“”‘’")


def literal(it: dict) -> str:
    """The item's `value` when it adds something; "" when it only repeats the name or the detail (the real-post test
    found genres and sources there, shown as copy boxes)."""
    value = _plain(it.get("value"))
    if not value:
        return ""
    for field in ("name", "detail"):
        other = _plain(it.get(field))
        if other and (value == other or (len(value) >= 3 and value in other)):
            return ""
    return str(it["value"]).strip()


def copyable(tab: cats.Tab, it: dict) -> bool:
    """A copy button only where copying makes sense: prompts, code, commands, quotes, ticket codes (and palette hexes)."""
    return tab.id in COPY_TABS or it.get("kind", "").strip().lower() in CODE_KINDS


def _value_block(tab: cats.Tab, it: dict, what: str) -> str:
    """A literal to copy (code box + Copy), else the value as one more plain line, else nothing."""
    value = literal(it)
    if not value or http_url(value):
        return ""
    if copyable(tab, it):
        return f'<div class="pvcode"><pre><code>{e(value)}</code></pre>{_copy_button(value, what)}</div>'
    return f'<small class="pvdetail pvval">{e(value)}</small>'


def _at(it: dict) -> str:
    """The "jump to this moment" button (hub.js seeks the video for every [data-t] in a post), or "" when not a time."""
    at = it.get("at", "").strip()
    if not AT.fullmatch(at):
        return ""
    return (f'<button type="button" class="pvjump" data-t="{e(at)}" aria-label="Play from {e(at)}">'
            f'{ICONS["play"]}<span>{e(at)}</span></button>')


def _copy_button(text: str, what: str, label: str = "Copy") -> str:
    return (f'<button type="button" class="pvcopy" data-pvcopy="{e(text)}" data-pvwhat="{e(what)}">'
            f'{ICONS["copy"]}<span>{e(label)}</span></button>')


def _chip(text: str, cls: str = "") -> str:
    return f'<span class="pvchip{" " + cls if cls else ""}">{e(text)}</span>' if text else ""


def _groups(items: list[dict]) -> list[tuple[str, list[tuple[int, dict]]]]:
    """Items gathered under their `group`, groups in the order they first appear; the item's index rides along."""
    out: dict[str, list] = {}
    for i, it in enumerate(items):
        out.setdefault(it.get("group", "").strip(), []).append((i, it))
    return list(out.items())


def _heading(group: str) -> str:
    return f'<h5 class="pvgh">{e(group)}</h5>' if group else ""


# ---- quantities (the servings scaler) -----------------------------------------------------------------------------------


def _number(text: str) -> Fraction:
    text = text.replace(",", ".").strip()
    if " " in text:
        whole, frac = text.split(None, 1)
        return Fraction(whole) + Fraction(frac)
    return Fraction(text)


def _show(value: Fraction, decimal: bool = False) -> str:
    """A scaled quantity, written the way a cook reads it: 1 1/2, 3/4, 13; an amount written with a decimal stays one."""
    if value.denominator == 1:
        return str(value.numerator)
    nice = Fraction(round(value * 8), 8) if value < 10 and not decimal else None
    if nice is not None and nice > 0 and abs(nice - value) < Fraction(1, 50):
        whole, part = divmod(nice, 1)
        if not part:
            return str(whole)
        frac = f"{part.numerator}/{part.denominator}"
        return f"{whole} {frac}" if whole else frac
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def scale_amount(amount: str, factor: Fraction) -> str:
    """Scales the leading quantity of an amount ("200 g", "1 1/2 cups", "2-3 cloves", "½ tsp"); anything else as it is."""
    if factor == 1 or not amount:
        return amount
    text = amount
    for sym, frac in UNICODE_FRACTIONS.items():  # "1½" → "1 1/2", "½" → "1/2"
        text = re.sub(rf"(\d)\s*{sym}", rf"\1 {frac}", text).replace(sym, frac)
    m = QTY.match(text)
    if not m:
        return amount
    try:
        decimal = bool(re.search(r"[.,]", m.group(0)))
        first = _show(_number(m.group(1)) * factor, decimal)
        second = f"{m.group(2)}{_show(_number(m.group(3)) * factor, decimal)}" if m.group(3) else ""
    except (ValueError, ZeroDivisionError):
        return amount
    lead = text[:len(text) - len(text.lstrip())]
    return lead + first + second + text[m.end():]


def base_servings(body: dict, item: dict) -> int:
    """How many the recipe makes, when the tab's text or the post says so ("Serves 4"); 0 when unknown."""
    for text in (body.get("text", ""), str(item.get("caption") or ""), str(item.get("summary") or "")):
        m = SERVES.search(text or "")
        if m:
            n = int(m.group(1) or m.group(2))
            if 1 <= n <= MAX_SERVINGS:
                return n
    return 0


def _servings(body: dict, state: dict, item: dict) -> tuple[int, int]:
    """(base, chosen): base 0 means unknown, then `chosen` is a multiplier (×1, ×2…)."""
    base = base_servings(body, item)
    try:
        chosen = int(state.get("servings", "") or 0)
    except ValueError:
        chosen = 0
    if not 1 <= chosen <= MAX_SERVINGS:
        chosen = base or 1
    return base, chosen


# ---- links for cards -----------------------------------------------------------------------------------------------------


API_LABELS = {"musicbrainz": "MusicBrainz", "nominatim": "OpenStreetMap", "openlibrary": "Open Library",
              "tvmaze": "TVmaze", "wikidata": "Wikidata", "wikipedia": "Wikipedia"}
API_REPLACES = {"nominatim": "osm", "openlibrary": "openlibrary", "wikipedia": "wikipedia"}  # exact page beats that search


def lookup_for(view: dict, tab_id: str, it: dict) -> dict:
    """What lookups.py found for this item: {api: {status, url, title, year, lat, lon, thumb}}, only entries whose status
    is "ok". Thumbnails are remote images and are never shown (opening a post must not contact other sites)."""
    found = (view.get("lookups") or {}) if isinstance(view.get("lookups"), dict) else {}
    found = found.get(tab_id) if isinstance(found.get(tab_id), dict) else {}
    hit = found.get(lookups.item_key(it, tab_id))  # name plus artist/author/city: the key lookups.py saved under
    if not isinstance(hit, dict):
        return {}
    return {k: v for k, v in hit.items() if isinstance(v, dict) and v.get("status", "ok") == "ok"}


def links_for(tab: cats.Tab, it: dict, view: dict, post: dict | None = None) -> list[dict]:
    """The buttons on a card: lookups' exact pages first (MusicBrainz, Open Library, TVmaze…), then a search link for each
    of the tab's providers (lookups.search_links). An exact page replaces the same site's search. A URL in `value` makes
    an "Official site" button only when the post itself contains it (`post`), never one the AI made up."""
    value = http_url(it.get("value", "").strip())
    if value and not in_post(value, post or {}):
        it = {k: v for k, v in it.items() if k != "value"}
    try:
        found = lookups.search_links(tab.providers or ("google",), it, tab, (post or {}).get("link_rows") or ())
    except Exception:  # a lookups bug must not break the post view
        found = []
    out, seen = [], set()
    for pid, data in lookup_for(view, tab.id, it).items():
        url = http_url(data.get("url"))
        if url:
            out.append({"provider": pid, "label": API_LABELS.get(pid) or "Page", "url": url, "exact": True})
            seen.update((pid, API_REPLACES.get(pid, pid)))
    out += [row for row in found if row["provider"] not in seen and http_url(row.get("url"))]
    return out[:7]


def _link_buttons(links: list[dict], name: str) -> str:
    return "".join(
        f'<a class="pvprov{" exact" if row.get("exact") else ""}" href="{e(row["url"])}" target="_blank" '
        f'rel="noopener noreferrer" aria-label="{e(row["label"])}: {e(name)}">{e(row["label"])}<span aria-hidden="true">↗</span></a>'
        for row in links)


def _year(exact: dict) -> str:
    for data in exact.values():
        year = str(data.get("year") or "").strip()
        if re.fullmatch(r"\d{4}", year):
            return year
    return ""


def _point(exact: dict) -> tuple[float, float] | None:
    for data in exact.values():
        try:
            lat, lon = float(data.get("lat")), float(data.get("lon"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


# ---- one renderer per kind -------------------------------------------------------------------------------------------------


def _row_text(it: dict) -> str:
    detail = f'<small class="pvdetail">{e(it["detail"])}</small>' if it.get("detail") else ""
    return f'<span class="pvtxt"><span class="pvname">{e(it["name"])}</span>{detail}</span>'


def _checklist(tab, body, view, state, item) -> str:
    items = body.get("items") or []
    scaler, factor = "", Fraction(1)
    if tab.id == "ingredients":
        base, chosen = _servings(body, state, item)
        factor = Fraction(chosen, base) if base else Fraction(chosen)
        label = "Serves" if base else "Batch"
        shown = str(chosen) if base else f"×{chosen}"
        scaler = (f'<div class="pvserv" data-pvserv data-base="{base}" data-chosen="{chosen}" data-max="{MAX_SERVINGS}">'
                  f'<span class="pvservl">{label}</span>'
                  f'<button type="button" class="pvstep-btn" data-pvservby="-1" aria-label="Fewer"{" disabled" if chosen <= 1 else ""}>−</button>'
                  f'<output class="pvservn" aria-live="polite">{shown}</output>'
                  f'<button type="button" class="pvstep-btn" data-pvservby="1" aria-label="More"'
                  f'{" disabled" if chosen >= MAX_SERVINGS else ""}>+</button>'
                  f'<button type="button" class="pvreset" data-pvservby="0"{"" if chosen != (base or 1) else " hidden"}>Reset</button></div>')
    done = sum(1 for it in items if state.get(item_key(it)) == "1")
    parts = []
    for group, rows in _groups(items):
        lis = []
        for _, it in rows:
            key, on = item_key(it), state.get(item_key(it)) == "1"
            amount = it.get("amount", "")
            amt = (f'<span class="pvamt" data-amt="{e(amount)}">{e(scale_amount(amount, factor))}</span>' if amount else "")
            lis.append(f'<li class="pvrow{" on" if on else ""}"><label><input type="checkbox" data-pvkey="{key}"'
                       f'{" checked" if on else ""}><span class="pvbox" aria-hidden="true"></span>{_row_text(it)}{amt}</label>'
                       f'{_at(it)}</li>')
        parts.append(_heading(group) + f'<ul class="pvrows" data-group="{e(group)}">{"".join(lis)}</ul>')
    bar = (f'<div class="pvbar2">{scaler}<p class="pvprog" data-pvprog data-total="{len(items)}">'
           f'<span data-pvdone>{done}</span> of {len(items)} ticked</p>'
           f'<button type="button" class="pvcopy" data-pvcopylist data-pvwhat="List">{ICONS["copy"]}<span>Copy list</span></button></div>')
    return bar + "".join(parts)


def _steps(tab, body, view, state, item) -> str:
    items = body.get("items") or []
    done = sum(1 for it in items if state.get(item_key(it)) == "1")
    lis = []
    for n, it in enumerate(items, 1):
        key, on = item_key(it), state.get(item_key(it)) == "1"
        amount = _chip(it.get("amount", ""), "pvtime")
        value = _value_block(tab, it, "Command")
        plain, value = (value, "") if value.startswith("<small") else ("", value)  # a plain value reads as a detail line
        group = f'<small class="pvstepg">{e(it["group"])}</small>' if it.get("group") else ""
        lis.append(f'<li class="pvstep{" on" if on else ""}"><label><input type="checkbox" data-pvkey="{key}"'
                   f'{" checked" if on else ""}><span class="pvnum" aria-hidden="true">{n}</span>'
                   f'<span class="pvtxt">{group}<span class="pvname">{e(it["name"])}</span>'
                   + (f'<small class="pvdetail">{e(it["detail"])}</small>' if it.get("detail") else "") + plain
                   + f'</span></label><span class="pvside">{amount}{_at(it)}</span>{value}</li>')
    bar = (f'<div class="pvbar2"><p class="pvprog" data-pvprog data-total="{len(items)}"><span data-pvdone>{done}</span> of '
           f'{len(items)} done</p></div>')
    return bar + f'<ol class="pvsteps">{"".join(lis)}</ol>'


def _card(tab, it: dict, view: dict, item: dict, index: int, number: str = "") -> str:
    exact = lookup_for(view, tab.id, it)
    year = _year(exact)
    amount = it.get("amount", "")
    chips = _chip(it.get("kind", ""), "pvkind") + _chip(year if year and year != amount else "", "pvyear") + _chip(amount)
    url = http_url(literal(it))
    extra = _value_block(tab, it, "Code")
    if url and in_post(url, item):
        extra = (f'<a class="pvprov pvown" href="{e(url)}" target="_blank" rel="noopener noreferrer">'
                 f'{e(urlsplit(url).hostname or "Link")}<span aria-hidden="true">↗</span></a>')
    links = _link_buttons(links_for(tab, it, view, item), it["name"])
    num = f'<span class="pvpin" aria-hidden="true">{e(number)}</span>' if number else ""
    group = f'<small class="pvcardg">{e(it["group"])}</small>' if it.get("group") and tab.render in ("cards", "places") else ""
    return (f'<li class="pvcard" id="pvc-{e(tab.id)}-{index}" tabindex="-1"><div class="pvch">{num}<span class="pvname">'
            f'{e(it["name"])}</span>{_at(it)}</div>{group}'
            + (f'<div class="pvchips">{chips}</div>' if chips else "")
            + (f'<p class="pvdetail">{e(it["detail"])}</p>' if it.get("detail") else "")
            + extra + (f'<div class="pvprovs">{links}</div>' if links else "") + "</li>")


def _cards(tab, body, view, state, item) -> str:
    items = body.get("items") or []
    return f'<ul class="pvcards">{"".join(_card(tab, it, view, item, i) for i, it in enumerate(items))}</ul>'


def map_svg(points: list[tuple[int, str, float, float]], tab_id: str) -> str:
    """A small plot of the places that have coordinates: no map tiles (nothing is fetched), just where they sit relative
    to each other, numbered like the cards below. points = [(index, name, lat, lon)]."""
    w, h, pad = 640, 300, 34
    lats, lons = [p[2] for p in points], [p[3] for p in points]
    mid = math.radians(sum(lats) / len(lats))
    xs = [lon * max(math.cos(mid), 0.2) for lon in lons]
    span_x, span_y = max(xs) - min(xs), max(lats) - min(lats)
    span = max(span_x / (w - 2 * pad), span_y / (h - 2 * pad), 1e-4)
    cx, cy = (max(xs) + min(xs)) / 2, (max(lats) + min(lats)) / 2
    dots = []
    for n, (index, name, lat, _), x in zip(range(1, len(points) + 1), points, xs):
        px, py = w / 2 + (x - cx) / span, h / 2 - (lat - cy) / span
        dots.append(f'<a href="#pvc-{e(tab_id)}-{index}" class="pvdot" data-pvjumpto="pvc-{e(tab_id)}-{index}" '
                    f'aria-label="{n}. {e(name)}"><circle cx="{px:.1f}" cy="{py:.1f}" r="17"/>'
                    f'<text x="{px:.1f}" y="{py + 5:.1f}" text-anchor="middle">{n}</text>'
                    f'<title>{e(name)}</title></a>')
    grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}"/>' for x in range(0, w + 1, 80)) + \
        "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>' for y in range(0, h + 1, 60))
    return (f'<figure class="pvmap"><svg viewBox="0 0 {w} {h}" role="group" aria-label="Where the places are" '
            f'preserveAspectRatio="xMidYMid meet"><g class="pvgrid" aria-hidden="true">{grid}</g>{"".join(dots)}</svg>'
            f'<figcaption>Where they sit relative to each other (no map is downloaded). Open one in Maps from its card.'
            f'</figcaption></figure>')


def _places(tab, body, view, state, item) -> str:
    items = body.get("items") or []
    points, numbers = [], {}
    for i, it in enumerate(items):
        pt = _point(lookup_for(view, tab.id, it))
        if pt:
            points.append((i, it["name"], *pt))
            numbers[i] = str(len(points))
    tab_maps = tab if any(p in tab.providers for p in ("google_maps", "apple_maps", "osm")) else cats.Tab(
        tab.id, tab.label, tab.render, tab.ai, providers=("google_maps", "apple_maps") + tuple(tab.providers))
    # one grid, each card naming its area: a heading per area left a column of lone half-width cards when most areas
    # hold one place (polish round 1, 14 Nov)
    cards = "".join(_card(tab_maps, it, view, item, i, numbers.get(i, "")) for i, it in enumerate(items))
    return (map_svg(points, tab.id) if points else "") + f'<ul class="pvcards pvplaces">{cards}</ul>'



def _ink(hex_: str) -> str:
    """Dark or light text for a swatch, by its brightness."""
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#111" if lum > 0.55 else "#fff"


def _palette(tab, body, view, state, item) -> str:
    lis = []
    for it in body.get("items") or []:
        hex_ = next((c.strip() for c in (it.get("value", ""), it.get("name", ""), it.get("detail", ""))
                     if HEX.fullmatch(c.strip())), "")
        if not hex_:
            m = HEX.search(it.get("value", "") + " " + it.get("detail", ""))
            hex_ = m.group(0) if m and HEX.fullmatch(m.group(0)) else ""
        hex_ = hex_.lower()
        detail = f'<small>{e(it["detail"])}</small>' if it.get("detail") else ""
        if hex_:
            lis.append(f'<li><button type="button" class="pvsw" data-pvcopy="{e(hex_)}" data-pvwhat="{e(hex_)}" '
                       f'style="--sw:{hex_};--ink:{_ink(hex_)}" aria-label="Copy {e(hex_)} ({e(it["name"])})">'
                       f'<span class="pvswc" aria-hidden="true"><span class="pvcopied">Copied</span></span>'
                       f'<span class="pvswt"><b>{e(it["name"])}</b><code>{e(hex_)}</code>{detail}</span></button></li>')
        else:
            lis.append(f'<li><div class="pvsw nohex"><span class="pvswc" aria-hidden="true"></span>'
                       f'<span class="pvswt"><b>{e(it["name"])}</b><code>no hex</code>{detail}</span></div></li>')
    return f'<ul class="pvswatches">{"".join(lis)}</ul>'


def _specs(tab, body, view, state, item) -> str:
    rows = []
    for group, its in _groups(body.get("items") or []):
        if group:
            rows.append(f'<tr class="pvsg"><th colspan="2" scope="colgroup">{e(group)}</th></tr>')
        for _, it in its:
            value = " · ".join(e(it[k]) for k in ("detail", "amount") if it.get(k)) or "—"
            rows.append(f'<tr><th scope="row">{e(it["name"])}</th><td>{value}{_at(it)}</td></tr>')
    return f'<table class="pvspecs"><tbody>{"".join(rows)}</tbody></table>'


def _proscons(tab, body, view, state, item) -> str:
    sides = {"pro": [], "con": [], "": []}
    for it in body.get("items") or []:
        kind = it.get("kind", "").strip().lower()
        side = "pro" if kind.startswith(("pro", "+", "plus", "good")) else "con" if kind.startswith(("con", "-", "minus", "bad")) else ""
        sides[side].append(it)

    def column(side: str, title: str) -> str:
        lis = "".join(f'<li>{_row_text(it)}{_at(it)}</li>' for it in sides[side])
        return (f'<div class="pvside-{side}"><h5 class="pvgh">{title} <small>{len(sides[side])}</small></h5>'
                f'<ul>{lis or "<li class=muted>None named</li>"}</ul></div>')

    rest = ("<h5 class=\"pvgh\">Also said</h5><ul class=\"pvnotes\">"
            + "".join(f'<li>{_row_text(it)}</li>' for it in sides[""]) + "</ul>") if sides[""] else ""
    return f'<div class="pvpc">{column("pro", "Pros")}{column("con", "Cons")}</div>{rest}'


def _quotes(tab, body, view, state, item) -> str:
    out = []
    for it in body.get("items") or []:
        kind = it.get("kind", "").strip().lower()
        value = literal(it)
        text = value or it.get("detail") or it.get("name")
        who = it["name"] if text != it["name"] else ""
        what = {"prompt": "Prompt", "code": "Code", "command": "Command"}.get(kind, "Quote")
        inner = (f'<pre><code>{e(text)}</code></pre>' if kind in CODE_KINDS
                 else f'<blockquote>{e(text)}</blockquote>')
        note = f'<small class="pvdetail">{e(it["detail"])}</small>' if value and it.get("detail") else ""
        out.append(f'<figure class="pvquote{" code" if kind in CODE_KINDS else ""}">{inner}<figcaption>'
                   f'{_chip(kind, "pvkind") if kind and kind != "quote" else ""}<span class="pvwho">{e(who)}</span>{note}'
                   f'<span class="pvqa">{_at(it)}{_copy_button(text, what)}</span></figcaption></figure>')
    return "".join(out)


def _notes(tab, body, view, state, item) -> str:
    parts = []
    for group, rows in _groups(body.get("items") or []):
        lis = []
        for _, it in rows:
            detail = f' <span class="pvdetail">{e(it["detail"])}</span>' if it.get("detail") else ""
            extra = _chip(it.get("kind", ""), "pvkind") + _chip(it.get("amount", ""))
            value = _value_block(tab, it, "Code")
            lis.append(f'<li><span class="pvname">{e(it["name"])}</span>{detail}{extra}{_at(it)}{value}</li>')
        parts.append(_heading(group) + f'<ul class="pvnotes">{"".join(lis)}</ul>')
    return "".join(parts)


def _flashcards(tab, body, view, state, item) -> str:
    cards = []
    for n, it in enumerate(body.get("items") or [], 1):
        answer = it.get("detail") or it.get("value") or "No answer in the post."
        cards.append(f'<li><button type="button" class="pvfc" aria-expanded="false"><span class="pvfci"><span class="pvfcf"><small>Q{n}</small>{e(it["name"])}</span>'
                     f'<span class="pvfcb" aria-hidden="true"><small>A{n}</small>{e(answer)}</span></span></button></li>')
    bar = ('<div class="pvbar2"><p class="pvprog">Click a card, or press Enter, to turn it over.</p>'
           '<button type="button" class="btn sm pvflipall" data-pvflipall aria-pressed="false">Show all answers</button></div>')
    return bar + f'<ul class="pvflash">{"".join(cards)}</ul>'


def _timeline(tab, body, view, state, item) -> str:
    groups = []
    for group, rows in _groups(body.get("items") or []):
        lis = "".join(f'<li class="pvti"><span class="pvtdot" aria-hidden="true"></span>{_row_text(it)}'
                      f'{_chip(it.get("amount", ""))}{_at(it)}</li>' for _, it in rows)
        groups.append(f'<li class="pvtg">{_heading(group)}<ol>{lis}</ol></li>')
    return f'<ol class="pvtimeline">{"".join(groups)}</ol>'


def when_of(value: str) -> tuple[datetime, bool] | None:
    """(start, has_time) from an ISO date or date-time, else None."""
    m = WHEN.fullmatch((value or "").strip())
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0)), hh is not None
    except ValueError:
        return None


def _end(start: datetime, timed: bool) -> datetime | None:
    """2 hours later, or the next day; None at the end of the calendar (9999-12-31: no Add to calendar)."""
    try:
        return start + (timedelta(hours=2) if timed else timedelta(days=1))
    except OverflowError:
        return None


def _event(tab, body, view, state, item) -> str:
    out = []
    for it in body.get("items") or []:
        when = when_of(it.get("value", ""))
        if when:
            start, timed = when
            day = f"{start:%a} {start.day} {start:%b %Y}"
            shown = day + (f", {start:%H:%M}" if timed else "")
            end = _end(start, timed)
            stamp = "%Y%m%dT%H%M%S" if timed else "%Y%m%d"
            cal = (f'<button type="button" class="btn sm dark pvical" data-pvical data-title="{e(it["name"])}" '
                   f'data-start="{start.strftime(stamp)}" data-end="{end.strftime(stamp)}" data-allday="{"0" if timed else "1"}" '
                   f'data-place="{e(it.get("group", ""))}" data-note="{e(it.get("detail", ""))}">{ICONS["cal"]}'
                   f'<span>Add to calendar</span></button>') if end else ""
            date = (f'<div class="pvdate" aria-hidden="true"><small>{start:%b}</small><b>{start.day}</b>'
                    f'<small>{start:%a}</small></div>')
        else:
            value = literal(it)
            shown, cal = (value if value and not http_url(value) else ""), ""
            date = '<div class="pvdate none" aria-hidden="true"><b>?</b><small>date</small></div>'
        lines = "".join(f'<li>{icon}<span>{text}</span></li>' for icon, text in (
            (ICONS["cal"], e(shown) if shown else "Date not given in the post"),
            (ICONS["pin"], e(it.get("group", ""))),
        ) if text)
        extra = _chip(it.get("amount", "")) + (f'<small class="pvdetail">{e(it["detail"])}</small>' if it.get("detail") else "")
        out.append(f'<article class="pvevent">{date}<div class="pvevb"><h5 class="pvname">{e(it["name"])}</h5>'
                   f'<ul class="pvevl">{lines}</ul>{extra}<div class="pvevact">{cal}{_at(it)}</div></div></article>')
    return "".join(out)


RENDERERS = {"checklist": _checklist, "steps": _steps, "cards": _cards, "places": _places, "palette": _palette,
             "specs": _specs, "proscons": _proscons, "quotes": _quotes, "notes": _notes, "flashcards": _flashcards,
             "timeline": _timeline, "event": _event}


def render_tab(tab: cats.Tab, body: dict, view: dict, state: dict, item: dict, links=()) -> str:
    """One category tab's pane. `body` = {"text", "items"}; `state` = this tab's saved ticks/servings ({key: value});
    `links` = the post's Links rows (store.links_for): an "Official site" button comes from these or from a URL the
    post itself contains, never from one the AI wrote."""
    item = {**item, "link_rows": list(links)} if links else item
    body = body if isinstance(body, dict) else {}
    items = [it for it in (body.get("items") or []) if isinstance(it, dict) and str(it.get("name") or "").strip()]
    items = [{k: str(v) for k, v in it.items() if isinstance(v, (str, int, float))} for it in items]
    body = {"text": str(body.get("text") or ""), "items": items}
    state = state if isinstance(state, dict) else {}
    view = view if isinstance(view, dict) else {}
    text = f'<p class="it-sum sm pvtext">{e(body["text"])}</p>' if body["text"].strip() else ""
    if not items:
        return (f'<div class="pvv pv-{e(tab.render)} pvv-empty" data-pvtab="{e(tab.id)}">'
                + (text or f'<p class="muted pvempty">{e(tab.empty_text)}</p>') + "</div>")
    draw = RENDERERS.get(tab.render, _notes)
    return (f'<div class="pvv pv-{e(tab.render)}" data-pvtab="{e(tab.id)}" data-pvid="{int(item.get("id") or 0)}">'
            f'{text}{draw(tab, body, view, state, item)}<p class="sr" data-pvlive aria-live="polite"></p></div>')
