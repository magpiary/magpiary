"""Lookups for the contextual post tabs (owner decision 5, 14 Nov 2026): deep search links for every card, and a few
free, keyless public APIs that check what a card names and add a year, a link and map coordinates.

- `search_links`: pure, no network. A search address per provider (Spotify, Apple Music, Maps, stores...) built from the
  item's name plus the one detail that narrows it (artist, author, city). Patterns come from the research note of
  14 Nov ("URL pattern table"); `verified` is False for addresses that block scripts (they work in a browser, untested)
  or that were not fetched.
- `enrich` / `lookups_due`: for posts whose view is built, MusicBrainz (songs, albums, artists), Nominatim (places,
  with lat/lon for the map), Open Library (books), TVmaze (shows) and Wikidata (films), Wikipedia (people, sources to
  go deeper). Results go into the view's `lookups`:

      {tab_id: {key(name): {api: {"status": "ok"|"none"|"failed", "at": "YYYY-MM-DD",
                                  "url", "title", "year", "lat", "lon", "thumb"}}}}

  "ok" carries the fields that were found (lat/lon are numbers, the rest strings); "none" means the API answered and
  nothing matched (done, not asked again); "failed" means the request failed and is tried again the next day, with
  whatever an earlier answer had found kept. Brave and Tavily are never used here (only through the Links engine).

Every request goes through `Run.fetch`, which checks the owner's settings right before it (Private mode or paused link
finding stop everything at once), keeps each API's rate limit (MusicBrainz and Nominatim ask for one request a second)
and sends one generic User-Agent with no personal detail. Network access is injected (`get`) so tests never go out.
Everything fetched is untrusted data: only short strings, https links and numbers are kept.
"""

import json
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

from magpiary import __version__
from magpiary import views

USER_AGENT = f"Magpiary/{__version__} (+https://magpiary.com)"  # generic: never a name, email or device

# One GET: (url, headers) -> (status, final url, body). Raises OSError on network failure (links.Get).
Get = Callable[[str, dict], tuple[int, str, bytes]]

# ---- search links (no network) -------------------------------------------------------------------------------------

# id -> (label, pattern with {q}, verified). verified=False: blocks scripts (works in a browser, not tested) or not fetched.
PROVIDERS: dict[str, tuple[str, str, bool]] = {
    # music
    "spotify": ("Spotify", "https://open.spotify.com/search/{q}", True),
    "apple_music": ("Apple Music", "https://music.apple.com/search?term={q}", True),
    "youtube_music": ("YouTube Music", "https://music.youtube.com/search?q={q}", True),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}", True),
    "bandcamp": ("Bandcamp", "https://bandcamp.com/search?q={q}", True),
    # maps and places
    "google_maps": ("Google Maps", "https://www.google.com/maps/search/?api=1&query={q}", True),
    "apple_maps": ("Apple Maps", "https://maps.apple.com/?q={q}", False),          # Apple's documented form, not fetched
    "osm": ("OpenStreetMap", "https://www.openstreetmap.org/search?query={q}", False),  # not fetched
    "maps_reviews": ("Reviews", "https://www.google.com/search?q={q}%20reviews", True),
    "opentable": ("OpenTable", "https://www.opentable.com/s?term={q}", False),     # browser only
    # shopping
    "google_shopping": ("Google Shopping", "https://www.google.com/search?tbm=shop&q={q}", True),
    "amazon": ("Amazon", "https://www.amazon.com/s?k={q}", True),
    "pinterest": ("Pinterest", "https://www.pinterest.com/search/pins/?q={q}", True),
    "rtings": ("RTINGS", "https://www.rtings.com/search?q={q}", True),
    # software and code
    "alternativeto": ("AlternativeTo", "https://alternativeto.net/browse/search/?q={q}", False),  # browser only
    "producthunt": ("Product Hunt", "https://www.producthunt.com/search?q={q}", False),          # browser only
    "github": ("GitHub", "https://github.com/search?q={q}", True),
    "npm": ("npm", "https://www.npmjs.com/search?q={q}", False),                                  # browser only
    "pypi": ("PyPI", "https://pypi.org/search/?q={q}", True),
    "huggingface": ("Hugging Face", "https://huggingface.co/models?search={q}", True),
    # film and TV
    "justwatch": ("JustWatch", "https://www.justwatch.com/us/search?q={q}", True),  # US catalogue
    "letterboxd": ("Letterboxd", "https://letterboxd.com/search/{q}/", True),
    "imdb": ("IMDb", "https://www.imdb.com/find/?q={q}", True),
    "youtube_trailer": ("Trailer", "https://www.youtube.com/results?search_query={q}%20trailer", True),
    # books
    "goodreads": ("Goodreads", "https://www.goodreads.com/search?q={q}", True),
    "storygraph": ("StoryGraph", "https://app.thestorygraph.com/browse?search_term={q}", False),  # browser only
    "openlibrary": ("Open Library", "https://openlibrary.org/search?q={q}", True),
    "bookshop": ("Bookshop.org", "https://bookshop.org/search?keywords={q}", False),             # browser only
    # the web
    "official": ("Official site", "", True),  # the item's own site, only when the post or Links found it
    "google": ("Google", "https://www.google.com/search?q={q}", True),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search={q}", True),
    "google_scholar": ("Google Scholar", "https://scholar.google.com/scholar?q={q}", True),
    "google_news": ("Google News", "https://news.google.com/search?q={q}", False),               # browser only
}

# The one item field that narrows a search, per tab (the rest search by name alone).
QUERY_DETAIL = {"tracks": "detail", "similar_music": "detail", "books": "detail", "places": "group", "spots": "group"}
# Sites that are directories, not an item's own site.
NOT_OFFICIAL = ("wikipedia.org", "wikidata.org", "openstreetmap.org", "doi.org", "archive.org", "google.com",
                "youtube.com", "youtu.be", "instagram.com", "threads.net", "x.com", "twitter.com", "reddit.com")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_text(text) -> str:
    """NFC, no control characters, one space between words. Every script is kept (review lesson 7)."""
    text = unicodedata.normalize("NFC", str(text or ""))
    return " ".join(_CONTROL.sub(" ", text).split())


def key(name) -> str:
    """A name tidied and lower-cased: the base of an item's lookups key."""
    return clean_text(name).lower()


def item_key(item: dict, tab) -> str:
    """The lookups key of an item on a tab: its name plus the field that narrows its query (artist, author, city), so
    two "Central Cafe"s in two cities, or one song by two artists, never share an answer, and an answer stops matching
    when that field changes (review 14 Nov 2026). The renderer reads lookups with the same key."""
    tab_id = getattr(tab, "id", tab)
    name = key(item.get("name"))
    extra = key(item.get(QUERY_DETAIL[tab_id])) if tab_id in QUERY_DETAIL else ""
    return f"{name} | {extra}" if name and extra else name


def query_for(item: dict, tab) -> str:
    tab_id = getattr(tab, "id", tab)
    name = clean_text(item.get("name"))
    extra = clean_text(item.get(QUERY_DETAIL.get(tab_id, ""), "")) if tab_id in QUERY_DETAIL else ""
    if extra and extra.lower() not in name.lower():
        name = f"{name} {extra}"
    return name[:150].strip()


def _host(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return (parts.hostname or "").lower() if parts.scheme in ("http", "https") else ""


def _official_host(host: str) -> bool:
    return bool(host) and not any(host == d or host.endswith("." + d) for d in NOT_OFFICIAL)


def official_url(item: dict, links=()) -> str:
    """The item's own site: a web address the post itself gave (in `value`; its bare site, no path or tracking), else a
    link the Links engine or the owner found for this name. "" when neither has one: never a guess."""
    value = clean_text(item.get("value"))
    if value.startswith(("http://", "https://")) and _official_host(_host(value)):
        return f"https://{_host(value)}/"
    wanted = key(item.get("name"))
    for link in links or ():
        url = str(link.get("url") or "")
        if wanted and key(link.get("name")) == wanted and not link.get("removed") and _official_host(_host(url)):
            return url
    return ""


def search_links(provider_ids, item: dict, tab, links=()) -> list[dict]:
    """[{provider, label, url}] for one card, in the tab's provider order. Unknown ids and an `official` with no known
    site are skipped. `links`: the post's link rows (`store.links_for`), used only by `official`."""
    query = query_for(item, tab)
    if not query:
        return []
    q = quote(query, safe="")
    out = []
    for pid in provider_ids or ():
        if pid not in PROVIDERS:
            continue
        label, pattern, _ = PROVIDERS[pid]
        url = official_url(item, links) if pid == "official" else pattern.replace("{q}", q)
        if url:
            out.append({"provider": pid, "label": label, "url": url})
    return out


# ---- free APIs -----------------------------------------------------------------------------------------------------

API_GAP = {"musicbrainz": 1.1, "nominatim": 1.1, "openlibrary": 1.0, "tvmaze": 0.6, "wikidata": 0.5, "wikipedia": 0.3}
API_TABS = {"tracks": "music", "similar_music": "music", "artists": "musicbrainz_artist", "places": "nominatim",
            "spots": "nominatim", "books": "openlibrary", "titles": "screen", "similar_watch": "screen",
            "people": "wikipedia", "deeper": "wikipedia"}
POSTS_PER_RUN = 5
REQUESTS_PER_RUN = 20
RETRY_FAILED_DAYS = 1
_FIELDS = {"url": 300, "title": 200, "year": 10, "thumb": 300}
_THUMB_HOSTS = ("covers.openlibrary.org", "static.tvmaze.com", "upload.wikimedia.org", "thumb.wikimedia.org")


class Stop(Exception):
    """No more requests this run: the budget is used, or the owner's settings refuse them now."""


class Pacer:
    """At least API_GAP seconds between two requests to the same API, across runs (one per process)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.clock, self.sleep, self.last, self._lock = clock, sleep, {}, threading.Lock()

    def wait(self, api: str) -> None:
        with self._lock:
            if api in self.last:
                gap = API_GAP.get(api, 1.0) - (self.clock() - self.last[api])
                if gap > 0:
                    self.sleep(gap)
            self.last[api] = self.clock()


PACER = Pacer()
FAILED = object()  # a request that failed (network, refused, rate limited, not JSON)


def default_get(url: str, headers: dict) -> tuple[int, str, bytes]:
    from magpiary.links import http_get  # public addresses only (network.public_urlopen), every redirect checked

    return http_get(url, headers, limit=300_000)


class Run:
    """One worker pass: a request budget, the owner's permission asked right before each request, the rate limits."""

    def __init__(self, get: Get | None = None, allow: Callable[[], bool] = lambda: True, requests: int = REQUESTS_PER_RUN,
                 pacer: Pacer | None = None):
        self.get, self.allow, self.left, self.pacer = get or default_get, allow, requests, pacer or PACER
        self.refused = False
        self.blocked: set[str] = set()  # APIs that said "slow down" or are down: not asked again this run

    def fetch(self, api: str, url: str):
        if api in self.blocked:
            return FAILED
        if self.left <= 0:
            raise Stop("budget")
        self.pacer.wait(api)
        if not self.allow():  # checked at the moment of use, after any wait (review lesson 2)
            self.refused = True
            raise Stop("refused")
        self.left -= 1
        try:
            status, _, body = self.get(url, {"User-Agent": USER_AGENT, "Accept": "application/json"})
        except OSError:
            self.blocked.add(api)
            return FAILED
        if status != 200:
            if status in (403, 429) or status >= 500:
                self.blocked.add(api)
            return FAILED
        try:
            return json.loads(body)
        except ValueError:
            return FAILED


def _fold(text) -> str:
    """For comparing names: NFKC, case-folded, punctuation gone, every script kept."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _bare_title(text) -> str:
    """A title without its (Remastered 2011) / [Live] / - Single Version tail."""
    text = re.sub(r"\s*[(\[].*?[)\]]", "", str(text or ""))
    return _fold(re.split(r"\s+-\s+", text)[0])


def same_name(a, b) -> bool:
    fa, fb = _fold(a), _fold(b)
    return bool(fa) and (fa == fb or _bare_title(a) == _bare_title(b) != "")


def _has(credit: str, artist: str) -> bool:
    """The artist the post named is among the credited ones (either may list several)."""
    if not artist:
        return True
    fc, fa = _fold(credit), _fold(artist)
    return bool(fc) and (fa in fc or fc in fa)


def _year(text) -> str:
    found = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(text or ""))
    return found.group(1) if found else ""


def _lucene(text: str) -> str:
    return '"' + clean_text(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _q(text: str) -> str:
    return quote(clean_text(text)[:200], safe="")


def _credit(hit: dict) -> str:
    return " ".join(str(a.get("name") or "") for a in hit.get("artist-credit") or [] if isinstance(a, dict))


def musicbrainz(run: Run, item: dict, artist_only: bool = False):
    """A song, an album or an artist on MusicBrainz, kept only when the title (and the artist, when the post named
    one) match. None: nothing matched."""
    name, artist = clean_text(item.get("name")), clean_text(item.get("detail"))
    kind = _fold(item.get("kind"))
    base = "https://musicbrainz.org/ws/2/"
    if artist_only or kind == "artist":
        data = run.fetch("musicbrainz", f"{base}artist/?query={_q('artist:' + _lucene(name))}&fmt=json&limit=3")
        if data is FAILED:
            return FAILED
        for hit in (data or {}).get("artists") or [] if isinstance(data, dict) else []:
            if isinstance(hit, dict) and same_name(hit.get("name"), name) and int(hit.get("score") or 0) >= 90:
                return {"url": f"https://musicbrainz.org/artist/{hit.get('id', '')}", "title": hit.get("name"),
                        "year": _year((hit.get("life-span") or {}).get("begin"))}
        return None
    album = kind in ("album", "ep", "record")
    entity, field, plural = ("release-group", "releasegroup", "release-groups") if album else ("recording", "recording", "recordings")
    query = f"{field}:{_lucene(name)}" + (f" AND artist:{_lucene(artist)}" if artist else "")
    data = run.fetch("musicbrainz", f"{base}{entity}/?query={_q(query)}&fmt=json&limit=5")
    if data is FAILED:
        return FAILED
    for hit in (data or {}).get(plural) or [] if isinstance(data, dict) else []:
        if not isinstance(hit, dict) or int(hit.get("score") or 0) < 80:
            continue
        credit = _credit(hit)
        if same_name(hit.get("title"), name) and _has(credit, artist):
            title = f"{hit.get('title')} · {credit}" if credit else hit.get("title")
            return {"url": f"https://musicbrainz.org/{entity}/{hit.get('id', '')}", "title": title,
                    "year": _year(hit.get("first-release-date"))}
    return None


def nominatim(run: Run, item: dict):
    """A place's coordinates on OpenStreetMap. Names differ by language (Eiffel Tower is "Tour Eiffel"), so the top hit
    is taken, but when the post gave a city it must be in the address."""
    city = clean_text(item.get("group"))
    query = query_for(item, "places")
    data = run.fetch("nominatim", f"https://nominatim.openstreetmap.org/search?q={_q(query)}&format=jsonv2&limit=1")
    if data is FAILED:
        return FAILED
    for hit in data if isinstance(data, list) else []:
        if not isinstance(hit, dict):
            continue
        if city and _fold(city) not in _fold(hit.get("display_name")):
            return None
        try:
            lat, lon = round(float(hit["lat"]), 6), round(float(hit["lon"]), 6)
        except (KeyError, TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        osm = f"https://www.openstreetmap.org/{hit.get('osm_type', 'node')}/{int(hit.get('osm_id') or 0)}"
        return {"url": osm, "title": str(hit.get("display_name") or "")[:200], "lat": lat, "lon": lon}
    return None


def openlibrary(run: Run, item: dict):
    name, author = clean_text(item.get("name")), clean_text(item.get("detail"))
    url = (f"https://openlibrary.org/search.json?title={_q(name)}" + (f"&author={_q(author)}" if author else "")
           + "&limit=3&fields=key,title,author_name,first_publish_year,cover_i")
    data = run.fetch("openlibrary", url)
    if data is FAILED:
        return FAILED
    for doc in (data or {}).get("docs") or [] if isinstance(data, dict) else []:
        if isinstance(doc, dict) and same_name(doc.get("title"), name) and _has(" ".join(doc.get("author_name") or []), author):
            cover = doc.get("cover_i")
            return {"url": "https://openlibrary.org" + str(doc.get("key") or ""), "title": doc.get("title"),
                    "year": str(doc.get("first_publish_year") or ""),
                    "thumb": f"https://covers.openlibrary.org/b/id/{int(cover)}-M.jpg" if isinstance(cover, int) else ""}
    return None


def tvmaze(run: Run, item: dict):
    name = clean_text(item.get("name"))
    data = run.fetch("tvmaze", f"https://api.tvmaze.com/search/shows?q={_q(name)}")
    if data is FAILED:
        return FAILED
    for hit in data if isinstance(data, list) else []:
        show = hit.get("show") if isinstance(hit, dict) else None
        if isinstance(show, dict) and same_name(show.get("name"), name):
            return {"url": show.get("url"), "title": show.get("name"), "year": _year(show.get("premiered")),
                    "thumb": (show.get("image") or {}).get("medium") or ""}
    return None


def wikidata_film(run: Run, item: dict):
    name = clean_text(item.get("name"))
    data = run.fetch("wikidata", "https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&language=en"
                                 f"&uselang=en&format=json&limit=5&search={_q(name)}")
    if data is FAILED:
        return FAILED
    for hit in (data or {}).get("search") or [] if isinstance(data, dict) else []:
        about = _fold(hit.get("description")) if isinstance(hit, dict) else ""
        if re.search(r"\b(film|movie|documentary)\b", about) and same_name(hit.get("label"), name):
            qid = str(hit.get("id") or "")
            if re.fullmatch(r"Q\d+", qid):
                return {"url": f"https://www.wikidata.org/wiki/{qid}", "title": hit.get("label"),
                        "year": _year(hit.get("description"))}
    return None


def wikipedia(run: Run, item: dict):
    name = clean_text(item.get("name"))
    data = run.fetch("wikipedia", f"https://en.wikipedia.org/w/rest.php/v1/search/page?q={_q(name)}&limit=1")
    if data is FAILED:
        return FAILED
    for page in (data or {}).get("pages") or [] if isinstance(data, dict) else []:
        if isinstance(page, dict) and same_name(page.get("title"), name):
            thumb = str((page.get("thumbnail") or {}).get("url") or "")
            thumb = ("https:" + thumb if thumb.startswith("//") else thumb).split("?")[0]
            return {"url": "https://en.wikipedia.org/wiki/" + quote(str(page.get("key") or ""), safe="_()',-"),
                    "title": page.get("title"), "year": "", "thumb": thumb}
    return None


def api_for(tab_id: str, item: dict) -> str:
    """Which API checks this item ("" for none)."""
    kind = API_TABS.get(tab_id, "")
    if kind == "music":
        return "musicbrainz" if _fold(item.get("kind")) != "playlist" else ""
    if kind == "musicbrainz_artist":
        return "musicbrainz"
    if kind == "screen":
        return "tvmaze" if re.search(r"show|series|tv", _fold(item.get("kind"))) else "wikidata"
    return kind


def _ask(run: Run, api: str, tab_id: str, item: dict):
    if api == "musicbrainz":
        return musicbrainz(run, item, artist_only=tab_id == "artists")
    return {"nominatim": nominatim, "openlibrary": openlibrary, "tvmaze": tvmaze, "wikidata": wikidata_film,
            "wikipedia": wikipedia}[api](run, item)


def _safe(found: dict) -> dict:
    """Only short strings, https links (thumbnails from known image hosts) and real numbers are kept."""
    out = {}
    for field, cap in _FIELDS.items():
        value = clean_text(found.get(field))[:cap]
        if field in ("url", "thumb") and value:
            host = _host(value)
            if not value.startswith("https://") or (field == "thumb" and host not in _THUMB_HOSTS):
                continue
        if value:
            out[field] = value
    for field in ("lat", "lon"):
        if isinstance(found.get(field), float):
            out[field] = found[field]
    return out


def _due(entry, today: str) -> bool:
    if not isinstance(entry, dict) or entry.get("status") not in ("ok", "none", "failed"):
        return True
    if entry["status"] != "failed":
        return False
    try:
        return (date.fromisoformat(today) - date.fromisoformat(str(entry.get("at")))).days >= RETRY_FAILED_DAYS
    except ValueError:
        return True


def wanted(view: dict, today: str) -> list[tuple[str, dict, str]]:
    """(tab id, item, api) still to look up in this view."""
    out, done = [], view.get("lookups") if isinstance(view.get("lookups"), dict) else {}
    for tab_id, body in (view.get("tabs") or {}).items():
        for item in body.get("items") or []:
            api = api_for(tab_id, item)
            k = item_key(item, tab_id)
            found = done.get(tab_id) if isinstance(done.get(tab_id), dict) else {}
            entries = found.get(k) if isinstance(found.get(k), dict) else {}
            if api and k and _due(entries.get(api), today):
                out.append((tab_id, item, api))
    return out


def enrich(view: dict, tab_id: str, items: list[dict], get: Get | None = None, run: Run | None = None,
           today: str | None = None) -> dict:
    """This tab's lookups after checking `items` with the free APIs: the view's old entries plus the new ones
    ({key: {api: entry}}). Stops quietly when the run's budget is used or the owner's settings refuse (what was
    found so far is returned). A failed request keeps the old fields and is marked failed, never done."""
    run = run or Run(get)
    today = today or date.today().isoformat()
    old = (view.get("lookups") or {}).get(tab_id) or {}
    out = {k: dict(v) for k, v in old.items() if isinstance(v, dict)}
    for item in items:
        api, k = api_for(tab_id, item), item_key(item, tab_id)
        if not api or not k or not _due((out.get(k) or {}).get(api), today):
            continue
        try:
            found = _ask(run, api, tab_id, item)
        except Stop:
            break
        before = (out.get(k) or {}).get(api) or {}
        if found is FAILED:
            entry = {**{f: v for f, v in before.items() if f not in ("status", "at")}, "status": "failed", "at": today}
        elif found:
            entry = {**_safe(found), "status": "ok", "at": today}
        else:
            entry = {"status": "none", "at": today}
        out.setdefault(k, {})[api] = entry
    return out


# ---- the worker step ---------------------------------------------------------------------------------------------

def allowed(store) -> bool:
    """May this Mac ask the free directories now? Not in Private mode (nothing about a save leaves the Mac for it; the
    search links still show, they need no request), and not while the owner has paused finding links (the same
    switch that stops the Links engine's Wikidata, OpenStreetMap and GitHub requests)."""
    from magpiary import modes

    return modes.current(store) != "private" and not store.paused("links")


_quiet: dict[str, tuple] = {}  # url -> (view.json mtime, day, note) when nothing was due: not read again that day
PAGE = 400  # candidates read at a time, newest first; later pages are read when the newer ones have nothing due


def _built(store, before: int | None = None, limit: int = PAGE) -> list[dict]:
    """Saved posts whose view the AI built, newest first, older than rowid `before`. Read-only."""
    with store._lock:
        rows = store._db.execute(
            "SELECT rowid AS id, canonical_url, archive_dir, note, screen_text FROM items WHERE view_status='done' "
            "AND shelf != 'trash' AND archive_dir IS NOT NULL" + (" AND rowid < ?" if before else "")
            + " ORDER BY rowid DESC LIMIT ?", ((before, limit) if before else (limit,))).fetchall()
    return [dict(r) for r in rows]


def _candidates(store):
    """Every built post, a page at a time (the newest 400 used to be the only ones ever looked at)."""
    before = None
    while True:
        rows = _built(store, before)
        yield from rows
        if len(rows) < PAGE:
            return
        before = rows[-1]["id"]


def post_text(folder: Path, row: dict) -> str:
    """What the post itself says, folded for matching: its title and caption, the transcript and the text read off the
    screen. Nothing an AI wrote (the summary's names could repeat the owner's note, even after he deletes it) and never
    the note itself: a lookup must not carry his own words to another service (reviews 14 Nov 2026)."""
    from magpiary.config import load_json

    meta = load_json(folder / "meta.json") or {}
    parts = [meta.get(k) for k in ("title", "text", "description", "author")] if isinstance(meta, dict) else []
    transcript = load_json(folder / "transcript.json") or {}
    if isinstance(transcript, dict):
        parts += [s.get("text") for s in transcript.get("segments") or [] if isinstance(s, dict)]
    screen = load_json(folder / "ocr.json") or []
    parts += [line.get("text") for line in screen if isinstance(line, dict)] if isinstance(screen, list) else []
    parts.append(row.get("screen_text"))
    return " " + _fold(" ".join(str(p) for p in parts if isinstance(p, (str, int, float)))) + " "


def grounded(item: dict, tab_id: str, text: str) -> bool:
    """The item's name, and the detail its query adds (artist, author, city), appear in the post's own words. Only
    those are looked up by themselves; anything else (an AI's guess, or words planted to make it send something) waits
    for the owner's click on a search link."""
    words = [item.get("name")] + ([item.get(QUERY_DETAIL[tab_id])] if tab_id in QUERY_DETAIL else [])
    folded = [_fold(w) for w in words if clean_text(w)]
    return bool(folded) and all(f and f" {f} " in text for f in folded)


def current_only(view: dict, lookups: dict) -> dict:
    """The lookups of the cards the view still has, under their current keys: answers for a card that is gone, or
    kept under an older key (name only, before the city or artist joined it), are dropped."""
    out = {}
    for tab_id, body in (view.get("tabs") or {}).items():
        keys = {item_key(i, tab_id) for i in body.get("items") or []}
        found = {k: v for k, v in (lookups.get(tab_id) or {}).items() if k in keys}
        if found:
            out[tab_id] = found
    return out


def lookups_due(store, get: Get | None = None, log: Callable[[str], None] = lambda m: None, pacer: Pacer | None = None,
                posts: int = POSTS_PER_RUN, requests: int = REQUESTS_PER_RUN, today: str | None = None) -> int:
    """Check the cards of up to `posts` built views with the free APIs (at most `requests` requests), saving each
    view's `lookups`. Only names grounded in the post are checked. Returns how many views were updated."""
    today = today or date.today().isoformat()
    if not allowed(store):
        return 0
    run = Run(get, allow=lambda: allowed(store), requests=requests, pacer=pacer)
    saved = touched = 0
    for row in _candidates(store):
        if touched >= posts or run.left <= 0 or run.refused:
            break
        folder = Path(row["archive_dir"])
        try:
            stamp = (folder / views.FILE).stat().st_mtime_ns
        except OSError:
            continue
        quiet = (stamp, today, str(row.get("note") or ""))
        if _quiet.get(row["canonical_url"]) == quiet:
            continue
        try:  # one odd file must not stop the worker: everything about this post is contained here
            view = views.load(folder)
            todo = wanted(view, today) if view else []
            if todo:
                text = post_text(folder, row)
                todo = [t for t in todo if grounded(t[1], t[0], text)]
        except Exception as err:
            log(f"lookups skipped a post: {type(err).__name__}")
            continue
        if not todo:
            _quiet[row["canonical_url"]] = quiet
            continue
        touched += 1
        lookups = dict(view.get("lookups") or {})
        try:
            for tab_id in dict.fromkeys(t for t, _, _ in todo):
                lookups[tab_id] = enrich(view, tab_id, [i for t, i, _ in todo if t == tab_id], run=run, today=today)
                if run.left <= 0 or run.refused:
                    break
        except Exception as err:  # one odd answer must not stop the worker; nothing is saved for this post
            log(f"lookups failed: {type(err).__name__}")
            continue
        if lookups == (view.get("lookups") or {}):
            continue
        fresh = views.load(folder)  # rebuilt meanwhile (Change category)? Its new cards are looked up next pass
        if not fresh or fresh.get("made_at") != view.get("made_at") or fresh.get("tabs") != view.get("tabs"):
            continue
        fresh["lookups"] = current_only(fresh, lookups)
        try:
            views.save(folder, fresh)
            saved += 1
        except OSError as err:
            log(f"lookups not saved: {type(err).__name__}")
            continue
        store.view_changed(row["id"])
    if run.refused:
        log("lookups stopped: Private mode or link finding paused")
    return saved
