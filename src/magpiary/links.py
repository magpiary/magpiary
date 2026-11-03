"""Links for everything a post names (Links v2, 24 Oct): each thing gets its real home as the main link (the
product's own site, a skill's repository, a book's Wikipedia page, a cited paper's DOI), with GitHub, App Store and
Wikipedia as badges beside it.

Targets come from the AI record: `link_targets` (kind, central or passing, what it is, a likely website) on top of
`entities`, which stays the full list of names. Big platforms and big places mentioned in passing get no link.

Order for a product: an address the post itself gives (and the post's own page, read for links to the rest), then
Wikidata's official website, then the AI's suggested domain, then the owner's web search key (Tavily or Brave),
then an App Store listing or GitHub repository, then the maker's site. Code goes to GitHub. Books, people and places
go to Wikipedia and OpenStreetMap through Wikidata. Cited sources go to Crossref DOIs. No AI is asked here.
Every page is opened logged out and must load and fit the post. Network access is injected (`get`).
Everything fetched is untrusted data.
"""

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit

from magpiary.sources import USER_AGENT, page_tags
from magpiary.network import public_urlopen

# One GET: (url, headers) -> (status, final url, body). Raises OSError on network failure.
Get = Callable[[str, dict], tuple[int, str, bytes]]
# A web search: query -> [{"title", "url", "snippet"}]. Raises SearchLimit when the month's searches are used.
Search = Callable[[str], list[dict]]

KINDS = {"tools": "Tools and apps", "skills_code": "Skills and code", "products": "Products",
         "books_media": "Books, films and shows", "places": "Places", "people": "People", "sources": "Sources",
         "links": "Websites"}
TARGET_KIND = {"tool": "tools", "code": "skills_code", "product": "products", "book_media": "books_media",
               "place": "places", "person": "people", "source": "sources"}
ENTITY_KIND = {"tools": "tool", "skills_code": "code", "products": "product", "books_media": "book_media",
               "places": "place", "people": "person"}
CATALOGS = [("anthropics/skills", "skills")]  # official skill lists, checked first for skills
URL_IN_TEXT = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\b(?:[a-z0-9-]+\.)+(?:com|io|ai|app|dev|org|net|co|so|sh|xyz|me|gg|tv|"
                         r"in|us|uk|tools|tech|site|page|link|studio|design|style)(?:/[^\s<>\"')\]]*)?", re.I)
STOP = {"the", "and", "for", "with", "this", "that", "your", "you", "are", "from", "have", "will", "about", "into",
        "what", "when", "they", "them", "their", "just", "more", "most", "here", "there", "video", "reel", "post",
        "free", "best", "new", "how", "use", "using", "can", "get", "all", "one", "out", "not", "but", "its", "via"}
PLATFORM_HOSTS = ("instagram.com", "threads.com", "threads.net", "x.com", "twitter.com", "youtube.com", "youtu.be",
                  "tiktok.com", "reddit.com", "linkedin.com", "facebook.com", "lnkd.in", "t.co", "redd.it")
# Hosts that are never a product's own site, even when the AI suggests them.
GENERIC_HOSTS = ("github.com", "gitlab.com", "apps.apple.com", "play.google.com", "wikipedia.org", "wikidata.org",
                 "medium.com", "substack.com", "notion.site", "linktr.ee", "bit.ly", *PLATFORM_HOSTS)
# Named only in passing, these get no link (the owner's rule): they need no introduction.
BIG_NAMES = {"google", "google drive", "google colab", "google maps", "gmail", "apple", "microsoft", "amazon", "aws",
             "meta", "facebook", "openai", "anthropic", "cloudflare", "youtube", "instagram", "twitter", "x",
             "threads", "tiktok", "linkedin", "reddit", "github", "gitlab", "whatsapp", "telegram", "app store",
             "mac app store", "play store", "google play", "macos", "ios", "ipados", "windows", "android", "iphone",
             "mac", "chatgpt", "claude", "claude ai", "gemini", "wikipedia", "wikimedia common", "spotify", "netflix"}
BIG_PLACE_TYPES = {"country", "state", "city", "county", "region", "province", "continent", "municipality",
                   "state_district"}
KIND_WORDS = {
    "tool": {"software", "application", "app", "service", "platform", "website", "company", "tool", "framework",
             "library", "database", "system", "manager", "management", "editor", "engine", "suite", "api", "web",
             "online", "open", "source", "saas", "product", "browser", "client", "server", "agent", "model",
             "startup", "tech", "technology", "developer", "developed"},
    "book_media": {"book", "novel", "film", "movie", "series", "album", "song", "show", "television", "podcast",
                   "game", "nonfiction", "written"},
    "person": {"human"},
    "place": {"park", "national", "reserve", "museum", "restaurant", "cafe", "temple", "beach", "lake", "mountain",
              "island", "village", "town", "building", "monument", "garden", "street", "market", "tiger"}}
PARKED = re.compile(r"domain (?:name )?(?:is )?for sale|buy this domain|this domain is parked|parked free|"
                    r"hugedomains|sedo\.com|dan\.com|domain has expired", re.I)
COMMON = {"social", "media", "finance", "security", "marketing", "agent", "claude", "skill", "code", "open", "free",
          "best", "super", "data", "design", "video", "image", "audio", "voice", "file", "files", "web", "app"}
COPY_MARKS = re.compile(r"(^|[-_.])(zh|cn|zh-cn|jp|ko|ru|fork|clone|copy|mirror|lite|auto|best|awesome)($|[-_.])", re.I)
SOURCE_HEAD = re.compile(r"^\s*(sources?|references?|citations?|further reading|bibliography)\s*:?\s*$", re.I | re.M)
CREDITS_HEAD = re.compile(r"^\s*(credits?|image credits?|photo credits?|music)\s*:?", re.I | re.M)
DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>,;]+", re.I)
SIGN_IN = re.compile(r"(^|\.)(accounts|login|signin|auth|sso)\.|/(login|signin|sign-in|auth)\b", re.I)
ORG_SUFFIXES = ("", "s", "ai", "hq", "app", "api", "inc", "dev", "labs", "-ai", "-hq", "-com", "-dev", "-labs", "-inc", "io")


class SearchLimit(Exception):
    """The owner's monthly search limit or the provider's credit is used up."""


@dataclass
class Found:
    name: str
    kind: str
    url: str
    title: str = ""
    source: str = ""
    score: int = 0
    checked: str = "yes"  # yes, or "not checked" when the site refuses scripts
    role: str = "main"  # main, or badge (GitHub, App Store, Wikipedia beside the main link)
    central: bool = True  # False: shown behind "Show N more"
    section: str = "named"  # named in the post, or "alternative" (Also worth a look)
    possible: bool = False  # a likely match, not a sure one
    homepage: str = ""  # a repository's own website, as its owner set it (not stored)
    about: str = ""  # a repository's description and topics (not stored)


@dataclass
class Target:
    name: str
    kind: str  # tool, code, product, book_media, place, person, source
    role: str = "central"
    what: str = ""
    domain: str = ""
    open_source: bool = False
    maker: str = ""
    repo: str = ""  # owner/name when the post gives it
    section: str = "named"
    guessed: bool = False  # from the named things, not the AI's link tags: its role is a guess
    found: list[Found] = field(default_factory=list)

    @property
    def central(self) -> bool:
        return self.role == "central"


@dataclass
class Page:
    status: int
    url: str
    title: str = ""
    description: str = ""
    text: str = ""
    anchors: list[tuple[str, str]] = field(default_factory=list)  # (address, link text)


def norm(text: str) -> str:
    """Lower case, punctuation to spaces, and plural 's' dropped (skills = skill, anthropics = anthropic)."""
    tokens = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return " ".join(t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in tokens)


BIG = {norm(n) for n in BIG_NAMES}


def words(text: str) -> set[str]:
    return {w for w in norm(text).split() if len(w) > 2 and w not in STOP}


def name_score(name: str, title: str) -> int:
    """3: the same name; 2: every word of the name appears in the title; 0: no real match."""
    n, t = norm(name), norm(title)
    if not n or not t:
        return 0
    if n == t or n.replace(" ", "") == t.replace(" ", ""):
        return 3
    if set(n.split()) <= set(t.split()) or n.replace(" ", "") in t.replace(" ", ""):
        return 2
    return 0


def _names_page(name: str, url: str) -> bool:
    """A badge's address must carry the thing's own name: refuses Wikipedia's "Railroad" for Railway, and io.js's
    article and repository for Node.js (Wikidata entries can point at a predecessor or a broader topic)."""
    squashed = norm(name).replace(" ", "")
    tail = norm(unquote(urlsplit(url).path).replace("_", " ")).replace(" ", "")
    return any(len(n) >= 2 and n in tail for n in {squashed, squashed.removesuffix("js")})  # React.js is at React_(software)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def on_host(url: str, hosts) -> bool:
    host = host_of(url)
    return any(host == h or host.endswith("." + h) for h in hosts)


def host_names(name: str, url: str) -> bool:
    """The address carries the name: 'Pebble Desk' in pebbledesk.example.com, 'NocoDB' in nocodb.com."""
    squashed = norm(name).replace(" ", "")
    labels = host_of(url).split(".")
    return len(squashed) >= 3 and any(squashed == norm(label).replace(" ", "") for label in labels[:-1])


def http_get(url: str, headers: dict | None = None, limit: int = 500_000) -> tuple[int, str, bytes]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en", **(headers or {})})
    try:
        with public_urlopen(request, timeout=10) as response:
            return response.status, response.geturl(), response.read(limit)
    except urllib.error.HTTPError as err:
        return err.code, url, b""


def http_post_json(url: str, headers: dict, body: dict) -> tuple[int, dict]:
    """One JSON POST (Tavily's search). Raises OSError on network failure."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json", **headers})
    try:
        with public_urlopen(request, timeout=20, redirects=False) as response:
            return response.status, json.loads(response.read(500_000) or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, {}
    except ValueError:
        return 200, {}


def counted(search: Search, used: Callable[[], int], spend: Callable[[], None], limit: int) -> Search:
    """A search that stops at the owner's monthly limit, whatever the provider would allow."""
    def run(query: str) -> list[dict]:
        if used() >= limit:
            raise SearchLimit(f"this month's {limit} searches are used")
        spend()
        return search(query)
    return run


def _json(get: Get, url: str, headers: dict | None = None):
    try:
        status, _, body = get(url, headers or {})
    except OSError:
        return None
    if status != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def read_page(get: Get, url: str) -> Page | None:
    """Open a page logged out: title, description, first text and its links. None when it does not load."""
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    try:
        status, final, body = get(url, {})
    except OSError:
        return None
    if status >= 400 and status not in (401, 403, 429):
        return None
    if host_of(final) != host_of(url) and SIGN_IN.search(host_of(final) + urlsplit(final).path):
        final = url  # a sign-in wall (drive.google.com -> accounts.google.com): the address asked for is the link
    page = Page(status, final)
    if body:
        tags = page_tags(body)
        page.title = html.unescape(tags.get("og:title") or tags.get("title") or "")[:200]
        page.description = html.unescape(tags.get("og:description") or tags.get("description") or "")[:400]
        raw = body.decode("utf-8", "replace")
        page.anchors = [(urljoin(final, html.unescape(a)), html.unescape(re.sub(r"<[^>]+>", " ", t)).strip())
                        for a, t in re.findall(r'<a\b[^>]*\bhref="([^"#]+)"[^>]*>(.*?)</a>', raw, re.S | re.I)][:400]
        stripped = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", raw, flags=re.S | re.I)
        page.text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", stripped)))[:20000]
    return page


def fits(page: Page, target: Target, context: set[str]) -> bool:
    """Its words overlap what the post says the thing is (so a different NocoDB, or a parked domain, fails)."""
    about = words(f"{page.title} {page.description} {page.text[:3000]}") - words(target.name)
    return bool(about & (words(target.what) | context))


def parked(page: Page) -> bool:
    return bool(PARKED.search(f"{page.title} {page.text[:3000]}"))


def check_site(target: Target, url: str, get: Get, context: set[str], source: str, score: int,
               trusted: bool | str = False) -> Found | None:
    """Open a candidate site. A trusted source (Wikidata says it is the official site) need only load; anything
    else must also carry the name and fit the post."""
    page = read_page(get, url)
    if page is None:
        return None
    found = Found(target.name, TARGET_KIND.get(target.kind, "tools"), page.url, page.title[:120], source, score,
                  central=target.central, section=target.section)
    if page.status in (401, 403, 429):  # the site refuses scripts; it may well be fine
        found.checked, found.url = "not checked", url
        return found if trusted or host_names(target.name, url) else None
    if parked(page):
        return None
    named = name_score(target.name, page.title) or host_names(target.name, page.url) or \
        host_names(target.name, url) or name_score(target.name, page.description)
    if trusted == "maker":  # the post's own maker: their site need only load
        return found
    if trusted:  # Wikidata or the maker says so: it need only carry the name (Wikidata has typos)
        return found if named or name_score(norm(target.name).split()[0], page.title) else None
    return found if named and fits(page, target, context) else None


def check(found: Found, get: Get) -> Found | None:
    """A link written in the post: kept if it loads and is not parked."""
    page = read_page(get, found.url)
    if page is None:
        return None
    if page.status in (401, 403, 429):
        found.checked = "not checked"
        return found
    if parked(page):
        return None
    found.title, found.url = found.title or page.title[:120], page.url
    return found


# ---- targets ------------------------------------------------------------------------------

def urls_in(text: str) -> list[str]:
    found = []
    for raw in URL_IN_TEXT.findall(text or ""):
        url = raw.rstrip(".,;:!?")
        if not url.lower().startswith("http"):
            url = "https://" + url
        host = (urlsplit(url).hostname or "").lower()
        if host and "." in host and url not in found:
            found.append(url)
    return found


def _before_credits(caption: str) -> str:
    match = CREDITS_HEAD.search(caption or "")
    return caption[:match.start()] if match else caption or ""


def guess_kind(name: str, kind: str) -> str:
    if kind == "tool" and (re.fullmatch(r"[\w.-]+/[\w.-]+", name) or re.search(r"\b(mcp|skills?|plugin|sdk|cli)\b|-skill",
                                                                            name, re.I)):
        return "code"
    return kind


def targets_for(record: dict, caption: str, transcript: str, comments: list[dict] | None,
                author: str = "") -> tuple[list[Target], list[str]]:
    """The things to link (AI tags first, then the rest of the named things) and the URLs written, said or shown
    anywhere in the post."""
    targets: list[Target] = []
    seen: dict[str, Target] = {}
    framing = " ".join([record.get("title") or "", record.get("summary") or "",
                        " ".join(p.get("text", "") for p in record.get("key_points") or [] if isinstance(p, dict)),
                        (record.get("extras") or {}).get("tool_name") or ""])
    clean_caption = _before_credits(caption)
    skip = {norm(author)} if author else set()

    def add(t: Target) -> None:
        key = norm(t.name)
        if not key or len(key) > 120 or key in skip:
            return
        if key in seen:
            return
        repo = re.fullmatch(r"([\w.-]+)/([\w.-]+)", t.name.strip())
        if repo:  # "example-maker/workshop-notes": the repo of a name already listed
            twin = next((o for o in seen.values() if name_score(o.name, repo.group(2)) >= 2), None)
            if twin:
                twin.repo, twin.kind = twin.repo or t.name.strip(), "code"
                return
            t.repo, t.kind = t.name.strip(), "code"
        else:
            for other in list(seen.values()):  # "workshop-notes" after "example-maker/workshop-notes"
                if other.repo and name_score(key, other.repo.split("/")[1]) >= 2:
                    return
        if t.domain and on_host(_http(t.domain), ("github.com",)):
            path = urlsplit(_http(t.domain)).path.strip("/").split("/")
            t.kind, t.domain = "code", ""
            if len(path) == 2 and not t.repo:
                t.repo = "/".join(path)
        seen[key] = t
        targets.append(t)

    for t in record.get("link_targets") or []:
        if isinstance(t, dict) and t.get("name"):
            add(Target(t["name"].strip(), guess_kind(t["name"], t.get("kind") or "tool"),
                       "passing" if t.get("role") == "passing" else "central", t.get("what") or "",
                       t.get("domain") or "", bool(t.get("open_source")), t.get("maker") or ""))
    for kind, names in (record.get("entities") or {}).items():
        if kind not in ENTITY_KIND:
            continue
        for name in names:
            name = name.strip()
            tkind = guess_kind(name, ENTITY_KIND[kind])
            if tkind == "person" and (len(name.split()) < 2 or name not in f"{framing} {clean_caption} {transcript}"):
                continue  # a surname alone, or someone named only in the credits: who they are is not clear
            central = tkind == "code" or bool(name_score(name, framing)) or norm(name) in norm(framing)
            add(Target(name, tkind, "central" if central else "passing", guessed=True))
    for citation in citations(caption):
        add(Target(citation, "source", "passing"))
    urls = []
    sources = [caption, transcript, " ".join((record.get("entities") or {}).get("links") or []),
               (record.get("extras") or {}).get("tool_url") or ""]
    sources += [c.get("text", "") for c in comments or []]
    for text in sources:
        for url in urls_in(text):
            if url not in urls:
                urls.append(url)
    return targets, urls[:30]


def citations(caption: str) -> list[str]:
    """Lines under a 'Sources:' heading, split where one line cites two works."""
    match = SOURCE_HEAD.search(caption or "")
    if not match:
        return []
    out = []
    for line in caption[match.end():].splitlines():
        line = line.strip()
        if not line:
            if out:
                break
            continue
        if CREDITS_HEAD.match(line) or SOURCE_HEAD.match(line) or line.startswith("#"):
            break
        for part in re.split(r";\s+(?=[A-Z])", line.lstrip("-•*· ").strip()):
            if len(part) > 8:
                out.append(part[:200])
    return out[:12]


def skipped(target: Target) -> bool:
    """A big platform gets a link only when the AI says the post is about it."""
    return norm(target.name) in BIG and (not target.central or target.guessed)


# ---- directories --------------------------------------------------------------------------

def wikidata(target: Target, get: Get, context: set[str], pause) -> dict | None:
    """The Wikidata entry for this thing: {id, label, description, site, repo, app, article, kinds}."""
    pause("wikidata")
    data = _json(get, "https://www.wikidata.org/w/api.php?action=wbsearchentities&language=en&uselang=en&type=item"
                      f"&limit=7&format=json&search={quote(target.name)}")
    best, best_score = None, 0.0
    own = words(target.name)
    hits = (data or {}).get("search", [])
    same = sum(name_score(target.name, h.get("label") or "") == 3 for h in hits)
    for rank, hit in enumerate(hits):
        description = hit.get("description") or ""
        if "disambiguation" in description or "Wikimedia" in description:
            continue
        label = hit.get("label") or ""
        score = max(name_score(target.name, label), name_score(target.name, (hit.get("match") or {}).get("text", "")))
        if score < 2 or (score == 2 and (len(norm(target.name).split()) < 2 or
                                         len(norm(label).split()) > len(norm(target.name).split()) + 1)):
            continue
        strong = (words(description) - own) & (words(target.what) | context)
        weak = (words(description) - own) & KIND_WORDS.get(target.kind, set())
        if not strong and (score < 3 or not weak) and target.kind != "person":
            continue
        if same > 1 and len(strong) < 2 and target.kind != "person":
            continue  # several things share this name: only a clear fit with the post will do
        total = score + 2 * len(strong) + 0.5 * bool(weak) - 0.05 * rank
        if total > best_score:
            best, best_score = hit, total
    if not best:
        return None
    pause("wikidata")
    query = ("SELECT ?site ?repo ?app ?article ?kind WHERE { BIND(wd:%s AS ?i) "
             "OPTIONAL { ?i wdt:P856 ?site } OPTIONAL { ?i wdt:P1324 ?repo } OPTIONAL { ?i wdt:P3861 ?app } "
             "OPTIONAL { ?article schema:about ?i; schema:isPartOf <https://en.wikipedia.org/> } "
             "OPTIONAL { ?i wdt:P31 ?kind } } LIMIT 40") % best["id"]
    answer = _json(get, "https://query.wikidata.org/sparql?format=json&query=" + quote(query),
                   {"Accept": "application/sparql-results+json"})
    entry = {"id": best["id"], "label": best.get("label", ""), "description": best.get("description", ""),
             "site": "", "repo": "", "app": "", "article": "", "kinds": set()}
    for row in ((answer or {}).get("results") or {}).get("bindings", []):
        for k in ("site", "repo", "app", "article"):
            if k in row and not entry[k]:
                entry[k] = row[k]["value"]
        if "kind" in row:
            entry["kinds"].add(row["kind"]["value"].rsplit("/", 1)[-1])
    if target.kind == "person" and "Q5" not in entry["kinds"]:
        return None
    return entry


def github_repo(full_name: str, get: Get) -> dict | None:
    data = _json(get, f"https://api.github.com/repos/{full_name}")
    return data if data and data.get("html_url") else None


def catalog_skill(target: Target, get: Get) -> Found | None:
    for repo, folder in CATALOGS:
        listing = _json(get, f"https://api.github.com/repos/{repo}/contents/{folder}")
        for entry in listing if isinstance(listing, list) else []:
            if name_score(target.name, entry.get("name", "")) == 3:
                return Found(target.name, "skills_code", entry["html_url"], f"{repo}: {entry['name']}",
                             "official skill list", 6, central=target.central, section=target.section)
    return None


def github_guess(target: Target, get: Get) -> Found | None:
    """'Alex Example Skills' -> github.com/alexexample/skills; 'Anthropic Skills' -> github.com/anthropics/skills.
    Tries the address directly (search often misses originals); at most 4 requests per name."""
    tokens = re.sub(r"[^a-z0-9]+", " ", target.name.lower()).split()
    if not 2 <= len(tokens) <= 5:
        return None
    tries = []
    for cut in range(1, len(tokens)):
        owner, rest = "".join(tokens[:cut]), "-".join(tokens[cut:])
        tries += [(owner, rest), (owner + "s", rest)] if not owner.endswith("s") else [(owner, rest)]
    for owner, repo in tries[:4]:
        data = github_repo(f"{owner}/{repo}", get)
        if data:
            return Found(target.name, "skills_code", data["html_url"], data.get("full_name", ""), "GitHub", 6,
                         central=target.central, section=target.section, homepage=data.get("homepage") or "")
    return None


SKILL_REPO = re.compile(r"\b(skills?|plugins?|mcp|agents?|claude|extensions?|prompts?)\b", re.I)


def skills_post(context: set[str]) -> bool:
    return bool(context & {"skill", "plugin", "mcp", "extension"})


def repo_about(found: Found) -> str:
    return found.about


def brand(target: Target) -> str:
    """The maker's name: 'Stripe' in 'Stripe MCP', or the maker the AI gave. Empty for generic names."""
    if target.maker:
        return norm(target.maker).replace(" ", "")
    tokens = norm(target.name).split()
    if len(tokens) >= 2 and len(tokens[0]) >= 4 and tokens[0] not in COMMON:
        return tokens[0]
    return ""


def is_official(target: Target, owner: str) -> bool:
    """The repository belongs to the maker's own account: stripe, XeroAPI, perplexityai, remotion-dev, heygen-com."""
    b, login = brand(target), owner.lower()
    return bool(b) and any(login == prefix + b + suffix for prefix in ("", "make", "get", "use", "try")
                           for suffix in ORG_SUFFIXES)


def github_official(target: Target, get: Get, context: set[str], pause) -> Found | None:
    """'Remotion skills' -> the remotion-dev account -> its 'skills' repository, when search missed it."""
    b = brand(target)
    if not b:
        return None
    pause("github")
    orgs = _json(get, f"https://api.github.com/search/users?q={quote(b)}&per_page=8")
    rest = " ".join(norm(target.name).split()[1:]) or target.name
    for login in [u.get("login", "") for u in (orgs or {}).get("items", []) if is_official(target, u.get("login", ""))][:3]:
        pause("github")
        found = github_search(target, get, context, query=f"{rest} user:{login}", official_only=True)
        if found:
            return found
    return None


def github_search(target: Target, get: Get, context: set[str], query: str = "",
                  official_only: bool = False) -> Found | None:
    """The best repository for the name: the right name, from the maker's own account when there is one, popular,
    and not a fork, copy or translation. A partial match is only a possible one."""
    data = _json(get, f"https://api.github.com/search/repositories?q={quote(query or target.name)}&per_page=10")
    best, best_score = None, 0
    for repo in (data or {}).get("items", [])[:10]:
        match = max(name_score(target.name, repo["name"]), name_score(target.name, repo["full_name"].replace("/", " ")))
        official = is_official(target, repo["full_name"].split("/")[0])
        if not match and not official:
            continue
        about = f"{repo['full_name']} {repo.get('description') or ''} {' '.join(repo.get('topics') or [])}"
        stars = repo.get("stargazers_count", 0)
        score = match + (3 if official and match else 1 if official else 0)
        score += 1 if words(about) & (context | words(target.what)) else 0
        score += 3 if stars >= 10000 else 2 if stars >= 1000 else 1 if stars >= 100 else 0
        score -= 3 if repo.get("fork") or COPY_MARKS.search(repo["name"]) else 0
        if score > best_score:
            best, best_score = (repo, match, official), score
    if not best or best_score < 3 or (official_only and not best[2]):
        return None
    repo, match, official = best
    return Found(target.name, "skills_code" if target.kind == "code" else TARGET_KIND.get(target.kind, "tools"),
                 repo["html_url"], repo["full_name"], "GitHub", best_score, central=target.central,
                 section=target.section, possible=match < 3 and not official, homepage=repo.get("homepage") or "",
                 about=f"{repo.get('description') or ''} {' '.join(repo.get('topics') or [])}")


def app_store(target: Target, get: Get, context: set[str]) -> Found | None:
    for entity in ("macSoftware", "software"):
        data = _json(get, f"https://itunes.apple.com/search?term={quote(target.name)}&entity={entity}&limit=5")
        for app in (data or {}).get("results", []):
            overlap = (words(app.get("description", "")[:800]) - words(target.name)) & (context | words(target.what))
            if name_score(target.name, app.get("trackName", "")) == 3 and len(overlap) >= 3:
                return Found(target.name, TARGET_KIND.get(target.kind, "tools"), app["trackViewUrl"].split("?")[0],
                             app["trackName"], "App Store", 4, central=target.central, section=target.section)
    return None


def wikipedia_search(target: Target, get: Get, context: set[str]) -> Found | None:
    """For a book, film or person Wikidata did not find: an article whose title is the name, never a list."""
    data = _json(get, "https://en.wikipedia.org/w/api.php?action=query&list=search&srlimit=3&format=json&srsearch="
                 + quote(target.name))
    for hit in (data or {}).get("query", {}).get("search", []):
        title = hit.get("title", "")
        snippet = html.unescape(re.sub(r"<[^>]+>", "", hit.get("snippet", "")))
        if "may refer to" in snippet or name_score(target.name, re.sub(r"\s*\(.*\)$", "", title)) < 3:
            continue
        if words(snippet) & context:
            return Found(target.name, TARGET_KIND[target.kind], "https://en.wikipedia.org/wiki/" +
                         quote(title.replace(" ", "_")), title, "Wikipedia", 4, central=target.central)
    return None


def place(target: Target, get: Get, pause) -> Found | None:
    pause("places")
    data = _json(get, f"https://nominatim.openstreetmap.org/search?q={quote(target.name)}&format=json&limit=1")
    for hit in data if isinstance(data, list) else []:
        if hit.get("addresstype") in BIG_PLACE_TYPES and (not target.central or target.guessed):
            return None  # a country or a big city in passing needs no map
        url = f"https://www.openstreetmap.org/{hit.get('osm_type', 'node')}/{hit.get('osm_id', '')}"
        return Found(target.name, "places", url, hit.get("display_name", "")[:120], "OpenStreetMap", 4,
                     central=target.central)
    return None


def crossref(target: Target, get: Get, pause) -> Found | None:
    """A cited work: its DOI when one is written, else Crossref's best match whose title is in the citation."""
    written = DOI.search(target.name)
    if written:
        return Found(target.name, "sources", "https://doi.org/" + written.group(0).rstrip("."), target.name, "DOI", 6,
                     central=target.central)
    letter = re.search(r"\bDCP-LETT-(\d+)", target.name)
    if letter:
        return Found(target.name, "sources", f"https://www.darwinproject.ac.uk/view/letters/DCP-LETT-{letter.group(1)}",
                     target.name, "Darwin Correspondence Project", 6, central=target.central)
    pause("crossref")
    data = _json(get, "https://api.crossref.org/works?rows=3&select=DOI,title,issued&query.bibliographic="
                 + quote(target.name))
    year = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", target.name)
    for item in ((data or {}).get("message") or {}).get("items", []):
        title = ((item.get("title") or [""])[0] or "").strip()
        title_words = words(title)
        if len(title_words) < 2 or len(title_words & words(target.name)) < 0.7 * len(title_words):
            continue
        issued = ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        if year and issued and abs(int(year.group(1)) - int(issued)) > 1:
            continue
        return Found(f"{title} ({issued})" if issued else title, "sources", "https://doi.org/" + item["DOI"],
                     title[:120], "Crossref", 5, central=target.central)
    return None


# ---- web search (the owner's key) ---------------------------------------------------------

def tavily(key: str, get_post=None) -> Search:
    def search(query: str) -> list[dict]:
        try:
            status, data = (get_post or http_post_json)("https://api.tavily.com/search", {"Authorization": f"Bearer {key}"},
                                {"query": query, "max_results": 5, "search_depth": "basic"})
        except OSError:
            return []
        if status in (402, 429, 432, 433):
            raise SearchLimit("Tavily's monthly searches are used up")
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:300]}
                for r in (data or {}).get("results", [])] if status == 200 else []
    return search


def brave(key: str, get: Get) -> Search:
    def search(query: str) -> list[dict]:
        try:
            status, _, body = get(f"https://api.search.brave.com/res/v1/web/search?count=5&q={quote(query)}",
                                  {"X-Subscription-Token": key, "Accept": "application/json"})
        except OSError:
            return []
        if status in (402, 429):
            raise SearchLimit("Brave's credit is used up")
        try:
            data = json.loads(body) if status == 200 else {}
        except ValueError:
            data = {}
        return [{"title": html.unescape(r.get("title", "")), "url": r.get("url", ""),
                 "snippet": html.unescape(re.sub(r"<[^>]+>", "", r.get("description", "")))[:300]}
                for r in (data.get("web") or {}).get("results", [])]
    return search


def from_search(target: Target, search: Search, get: Get, context: set[str]) -> Found | None:
    query = f"{target.name} {target.what or ' '.join(sorted(context, key=len, reverse=True)[:2])}".strip()
    for hit in search(query)[:5]:
        url = hit.get("url", "")
        if not url or on_host(url, GENERIC_HOSTS):
            continue
        if host_names(target.name, url):  # only the thing's own site: a title match let in job ads and articles
            found = check_site(target, _own_root(target.name, url), get, context, "web search", 5)
            if found:
                return found
    return None


def _own_root(name: str, url: str) -> str:
    """The home page of the address that carries the name: careers.manychat.com → https://manychat.com/."""
    squashed = norm(name).replace(" ", "")
    labels = host_of(url).split(".")
    at = next((i for i, label in enumerate(labels[:-1]) if norm(label).replace(" ", "") == squashed), 0)
    return f"https://{'.'.join(labels[at:])}/"


# ---- one thing ----------------------------------------------------------------------------

def resolve(target: Target, get: Get, context: set[str], posted: list["PostPage"], search: Search | None,
            pause) -> list[Found]:
    """The main link and its badges for one thing, best first."""
    if target.kind == "source":
        found = crossref(target, get, pause)
        return [found] if found else []
    if target.kind == "place":
        found = place(target, get, pause)
        return [found] if found else []
    main: Found | None = None
    badges: list[Found] = []
    kind = TARGET_KIND.get(target.kind, "tools")

    for page in posted:  # a repository the post gives: the home of code, a badge for a product
        repo_name = urlsplit(page.url).path.strip("/").split("/")
        if on_host(page.url, ("github.com",)) and len(repo_name) == 2 and name_score(target.name, repo_name[1]) == 3:
            page.claimed = True
            given = Found(target.name, "skills_code" if target.kind == "code" else kind, page.url,
                          "/".join(repo_name), "GitHub (in the post)", 7, central=target.central, role="badge")
            if target.kind == "code":
                given.role = "main"
                return [given]
            badges.append(given)
    for page in posted:  # an address the post gives, or a link on that page with this name
        if on_host(page.url, GENERIC_HOSTS):
            continue
        if host_names(target.name, page.url) or name_score(target.name, page.title) == 3:
            main = Found(target.name, kind, page.url, page.title[:120], "mentioned in the post", 7,
                         central=target.central)
            page.claimed = True
            break
    if main is None:
        for page in posted:
            for href, text in page.anchors:
                if on_host(href, GENERIC_HOSTS) or not (name_score(target.name, text) == 3 or host_names(target.name, href)):
                    continue
                main = check_site(target, href, get, context, "linked from the post", 6, trusted=True)
                if main:
                    break
            if main:
                break

    if target.kind == "code":
        if target.repo:
            data = github_repo(target.repo, get)
            if data:
                main = main or Found(target.name, "skills_code", data["html_url"], data.get("full_name", ""), "GitHub",
                                     7, central=target.central, homepage=data.get("homepage") or "")
        if main is None:
            pause("catalog_skill")
            main = catalog_skill(target, get)
        if main is None:
            pause("github_guess")
            main = github_guess(target, get)
        if main is None or (main.source == "GitHub" and brand(target) and not is_official(target, main.title.split("/")[0])):
            pause("github")
            searched = main or github_search(target, get, context)
            official = github_official(target, get, context, pause) if brand(target) and not (
                searched and is_official(target, searched.title.split("/")[0])) else None
            main = official or searched
        if main is not None and main.homepage and not on_host(_http(main.homepage), GENERIC_HOSTS):
            site = check_site(target, _http(main.homepage), get, context, "the repository's homepage", 5, trusted=True)
            if site:
                site.role = "badge"
                badges.append(site)
        elif main is not None and target.domain and not on_host(target.domain if "//" in target.domain else
                                                              "https://" + target.domain, GENERIC_HOSTS):
            site = check_site(target, _http(target.domain), get, context, "AI's suggestion", 4)
            if site:
                site.role = "badge"
                badges.append(site)
        if main is not None or not target.domain:
            return [f for f in [main, *badges] if f]

    entry = None
    if target.kind in ("tool", "product", "code", "book_media", "person"):
        entry = wikidata(target, get, context, pause)
    if target.kind in ("book_media", "person"):
        if entry and entry["article"]:
            main = Found(target.name, kind, entry["article"], entry["label"], "Wikipedia", 6, central=target.central)
            if entry["site"]:
                site = check_site(target, entry["site"], get, context, "Wikidata", 5, trusted=True)
                if site:
                    site.role = "badge"
                    badges.append(site)
        else:
            pause("wikipedia")
            main = wikipedia_search(target, get, context)
        return [f for f in [main, *badges] if f]

    if main is None and entry and entry["site"]:
        main = check_site(target, entry["site"], get, context, "Wikidata", 6, trusted=True)
    if main is None and target.domain and not on_host(_http(target.domain), GENERIC_HOSTS):
        main = check_site(target, _http(target.domain), get, context, "AI's suggestion", 5)
    repo = None
    if main is None and (target.open_source or target.kind == "tool"):
        pause("github")
        repo = github_search(target, get, context)
        popular = repo and not repo.possible and (target.open_source or repo.score >= 7)
        if not popular:
            repo = None
        elif skills_post(context) and SKILL_REPO.search(f"{repo.title} {repo.homepage} {repo_about(repo)}"):
            main, repo = repo, None  # a skill or plugin in a post about skills: the repository is its home
            target.kind, main.kind = "code", "skills_code"
        elif repo.homepage and not on_host(_http(repo.homepage), GENERIC_HOSTS):
            main = check_site(target, _http(repo.homepage), get, context, "the repository's homepage", 6, trusted=True)
    if main is None and search:
        pause("search")
        try:
            main = from_search(target, search, get, context)
        except SearchLimit:
            search = None
    if entry:  # badges from the same entry
        if entry["repo"] and "github.com" in entry["repo"] and _names_page(target.name, entry["repo"]):
            badges.append(Found(target.name, kind, entry["repo"].removesuffix(".git"), "", "GitHub", 5, role="badge",
                                central=target.central))
        if entry["app"]:
            badges.append(Found(target.name, kind, f"https://apps.apple.com/app/id{entry['app']}", "", "App Store", 5,
                                role="badge", central=target.central))
        if entry["article"] and _names_page(target.name, entry["article"]):
            badges.append(Found(target.name, kind, entry["article"], entry["label"], "Wikipedia", 5, role="badge",
                                central=target.central))
    if repo and not any(b.source.startswith("GitHub") for b in badges):
        repo.role, repo.kind = "badge", kind
        badges.append(repo)
    if main is None:  # no site of its own: an App Store listing or a repository may stand in
        pause("app_store")
        main = app_store(target, get, context)
    if main is None:
        repo = next((b for b in badges if b.source.startswith("GitHub")), None)
        if repo:
            badges.remove(repo)
            main, repo.role = repo, "main"
    if main is None:
        for page in posted:  # made by the post's maker: their site
            maker = page.maker_site()
            if maker and norm(target.name) in norm(page.text):
                main = check_site(target, maker, get, context, "the maker's site", 4, trusted="maker")
                if main:
                    main.title = main.title or "the maker's site"
                    break
    if main is None:
        return []
    main.role = "main"
    return [main, *[b for b in badges if b.url.rstrip("/") != main.url.rstrip("/")]]


def _http(domain: str) -> str:
    return domain if "://" in domain else "https://" + domain.strip("/") + "/"


class PostPage(Page):
    claimed: bool = False

    def maker_site(self) -> str:
        """pebbledesk.example.com is made by example.com."""
        labels = host_of(self.url).split(".")
        return f"https://{'.'.join(labels[1:])}/" if len(labels) > 2 else ""


# ---- alternatives -------------------------------------------------------------------------

def alternatives(product: str, named: set[str], get: Get, search: Search | None, pause) -> list[str]:
    """Up to 5 names suggested as replacements, ranked by how many sources agree. Names the post gave are left out."""
    votes: dict[str, list] = {}
    slug = re.sub(r"[^a-z0-9]+", "-", product.lower()).strip("-")
    pause("alternativeto")
    page = read_page(get, f"https://alternativeto.net/software/{slug}/about/")
    if page and page.status == 200:
        for href, text in page.anchors:
            if re.search(r"alternativeto\.net/software/[^/]+/about/?$", href) and text and slug not in href:
                votes.setdefault(norm(text), [text, 0])[1] += 1
    if search:
        pause("search")
        try:
            for hit in search(f"best {product} alternatives"):
                for name in re.findall(r"\b([A-Z][\w.]+(?: [A-Z][\w.]+)?)\b", f"{hit.get('title', '')} {hit.get('snippet', '')}"):
                    if norm(name) not in (norm(product), "alternative", "best") and len(name) > 2:
                        votes.setdefault(norm(name), [name, 0])[1] += 1
        except SearchLimit:
            pass
    ranked = sorted(votes.values(), key=lambda v: -v[1])
    return [n for n, count in ranked if norm(n) not in named and norm(n) != norm(product)
            and norm(n) not in BIG and (count >= 2 or not search)][:5]


# ---- the whole step -----------------------------------------------------------------------

def find_links(record: dict, caption: str, transcript: str, comments: list[dict] | None, get: Get = http_get,
               search: Search | None = None, skip: set[str] | None = None, author: str = "",
               pause: Callable[[str], None] = lambda source: None) -> list[Found]:
    """Every link worth showing: per thing one main link (possibly with badges), central ones first.
    `skip` holds URLs the owner removed."""
    skip = skip or set()
    context = words(" ".join([record.get("title") or "", record.get("summary") or "", _before_credits(caption)[:1500]]))
    targets, urls = targets_for(record, caption, transcript, comments, author)
    posted: list[PostPage] = []
    for url in urls:  # written, said or shown in the post
        if url in skip or on_host(url, PLATFORM_HOSTS) or (on_host(url, GENERIC_HOSTS) and
                                                           urlsplit(url).path.strip("/") == ""):
            continue
        page = read_page(get, url)
        if page and not parked(page):
            posted.append(PostPage(**page.__dict__))
    results: list[Found] = []
    for target in targets:
        if skipped(target):
            continue
        target.found = [f for f in resolve(target, get, context, posted, search, pause) if f.url not in skip]
        results += target.found
    for page in posted:  # addresses no named thing claimed: their own row
        if not page.claimed and not any(f.url.rstrip("/") == page.url.rstrip("/") for f in results):
            results.append(Found(host_of(page.url), "links", page.url, page.title[:120], "mentioned in the post", 5,
                                 "not checked" if page.status >= 400 else "yes"))
    product = (record.get("alternatives_to") or "").strip()
    if product:
        named = {norm(t.name) for t in targets}
        for name in alternatives(product, named, get, search, pause):
            alt = Target(name, "tool", "central", f"alternative to {product}", section="alternative")
            for f in resolve(alt, get, context, [], search, pause):
                if f.url not in skip:
                    f.section = "alternative"
                    results.append(f)
    order = {True: 0, False: 1}
    return sorted(results, key=lambda f: (f.section != "named", order[f.central]))
