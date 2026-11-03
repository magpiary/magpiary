"""Short-link expansion: follow a short link's redirects on the Mac, then clean the result.

Logged out and cookie-free by design. The network is injected (`fetch`) so tests
replay recorded redirects. Only the final, cleaned link is ever kept; the short
code can identify the sharer.
"""

import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import parse_qs, urljoin, urlsplit

from magpiary.cleaner import CleanLink, UnsupportedLink, clean
from magpiary.network import public_urlopen

FAILURE_REASON = "short link not expanded"
MAX_HOPS = 5
TIMEOUT_SECONDS = 15

# One hop: returns (HTTP status, Location header or None). Raises OSError on network failure.
Fetch = Callable[[str], tuple[int, str | None]]

# Waits between retries: minutes, then hours, about a day in total (~22h).
RETRY_DELAYS_SECONDS = [5 * 60, 15 * 60, 60 * 60, 3 * 3600, 6 * 3600, 12 * 3600]


class ExpansionFailed(Exception):
    """The short link could not be turned into a post link (right now)."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.reason = FAILURE_REASON
        self.detail = detail


def retry_delay(attempts_so_far: int) -> int | None:
    """Seconds to wait before the next try, or None once the day is used up."""
    if attempts_so_far < len(RETRY_DELAYS_SECONDS):
        return RETRY_DELAYS_SECONDS[attempts_so_far]
    return None


def expand(link: CleanLink, fetch: Fetch) -> CleanLink:
    """Expand a short link (needs_expansion=True) into its cleaned post link."""
    if not link.needs_expansion:
        return link
    url = link.url
    for _ in range(MAX_HOPS):
        try:
            status, location = fetch(url)
        except OSError as err:  # includes timeouts and URLError
            raise ExpansionFailed(f"network error: {type(err).__name__}") from err
        if not (300 <= status < 400 and location):
            raise ExpansionFailed(f"no redirect (HTTP {status})")
        url = _unwrap_login(urljoin(url, location))
        try:
            result = clean(url)
        except UnsupportedLink as err:
            if urlsplit(url).scheme in ("http", "https") and _is_same_family(link, url):
                continue  # an intermediate hop, keep following
            raise ExpansionFailed(f"expanded to an unsupported link: {err}") from err
        if not result.needs_expansion and result.source == link.source:
            return result
        if result.needs_expansion:
            url = result.url  # another short link: keep following
            continue
        raise ExpansionFailed("expanded to a different site")
    raise ExpansionFailed("too many redirects")


def _is_same_family(link: CleanLink, url: str) -> bool:
    """Intermediate hops (consent or login pages) stay on the original site."""
    try:
        return clean(link.url).source == _site_of(url)
    except UnsupportedLink:
        return False


def _site_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for source, domains in {"instagram": ("instagram.com",), "threads": ("threads.net", "threads.com"),
                            "x": ("x.com", "twitter.com", "t.co"), "reddit": ("reddit.com", "redd.it"),
                            "linkedin": ("linkedin.com", "lnkd.in")}.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return source
    return ""


def _unwrap_login(url: str) -> str:
    """Logged-out Instagram sometimes redirects to a login page with the post in `next`."""
    parts = urlsplit(url)
    if "login" in parts.path:
        nxt = parse_qs(parts.query).get("next")
        if nxt:
            return urljoin(url, nxt[0])
    return url


def http_fetch(url: str) -> tuple[int, str | None]:
    """Real fetch: one hop, no cookies, no body kept. Used by the service, never by tests."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) Magpiary/0.0"}, method="GET")
    try:
        with public_urlopen(request, timeout=TIMEOUT_SECONDS, redirects=False) as response:
            return response.status, response.headers.get("Location")
    except urllib.error.HTTPError as err:  # 3xx arrive here because redirects are off
        return err.code, err.headers.get("Location")
