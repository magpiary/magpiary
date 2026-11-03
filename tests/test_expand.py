"""Expansion tests replay recorded redirects. No live calls."""

import pytest

from magpiary.cleaner import clean
from magpiary.expand import FAILURE_REASON, ExpansionFailed, expand, retry_delay


def replay(recorded):
    """A fake fetch: url -> (status, location). Unknown urls fail like a dead network."""
    seen = []

    def fetch(url):
        seen.append(url)
        if url not in recorded:
            raise ConnectionError(url)
        return recorded[url]

    fetch.seen = seen
    return fetch


RECORDED = {
    # Threads share link -> post (with the sharer's code riding along)
    "https://www.threads.com/share/ExampleShare3/": (302, "https://www.threads.com/@examplecreator/post/Example0014?xmt=AQ&slof=1"),
    # Reddit /s/ and redd.it
    "https://lnkd.in/p/Ex4mpL3a": (301, "https://www.linkedin.com/posts/examplecreator_hello-ugcPost-123-AbCd/?utm_source=social_share_send&rcm=ACoA"),
    "https://www.reddit.com/r/exampleworkshop/s/ExampleShare5": (301, "https://www.reddit.com/r/ExampleWorkshop/comments/1abc2de/some_title/?utm_source=share"),
    "https://redd.it/1abc2de": (301, "https://www.reddit.com/r/exampleworkshop/comments/1abc2de/some_title/"),
    # Instagram share -> reel, straight and via a login page
    "https://www.instagram.com/share/reel/ExampleShare4/": (302, "https://www.instagram.com/reel/Example0001/?igsh=example-tracking"),
    "https://www.instagram.com/share/ExampleLogin/": (302, "https://www.instagram.com/accounts/login/?next=%2Freel%2FExample0002%2F%3Figsh%3Dx"),
    # X t.co
    "https://t.co/ExampleShare6": (301, "https://x.com/examplecreator/status/1111111111111111111?s=46"),
    # two hops: reddit short link -> another short link -> post
    "https://redd.it/2hop": (301, "https://www.reddit.com/r/exampleworkshop/s/Example0021"),
    "https://www.reddit.com/r/exampleworkshop/s/Example0021": (301, "https://www.reddit.com/r/exampleworkshop/comments/1zzz9zz/t/"),
}


@pytest.mark.parametrize("short, expected", [
    ("https://www.threads.com/share/ExampleShare3", "https://www.threads.com/@examplecreator/post/Example0014/"),
    ("https://www.reddit.com/r/exampleworkshop/s/ExampleShare5", "https://www.reddit.com/r/exampleworkshop/comments/1abc2de/"),
    ("https://redd.it/1abc2de", "https://www.reddit.com/r/exampleworkshop/comments/1abc2de/"),
    ("https://lnkd.in/p/Ex4mpL3a", "https://www.linkedin.com/posts/examplecreator_hello-ugcPost-123-AbCd/"),
    ("https://www.instagram.com/share/reel/ExampleShare4/", "https://www.instagram.com/reel/Example0001/"),
    ("https://www.instagram.com/share/ExampleLogin", "https://www.instagram.com/reel/Example0002/"),
    ("https://t.co/ExampleShare6", "https://x.com/examplecreator/status/1111111111111111111"),
    ("https://redd.it/2hop", "https://www.reddit.com/r/exampleworkshop/comments/1zzz9zz/"),
])
def test_short_links_expand_to_clean_post_links(short, expected):
    result = expand(clean(short), replay(RECORDED))
    assert result.url == expected
    assert not result.needs_expansion


def test_sharer_code_is_gone_after_expansion():
    result = expand(clean("https://www.threads.com/share/ExampleShare3"), replay(RECORDED))
    assert "ExampleShare3" not in result.url and "xmt" not in result.url


def test_link_that_needs_no_expansion_makes_no_request():
    fetch = replay({})
    link = clean("https://www.instagram.com/reel/Example0001/")
    assert expand(link, fetch) == link and fetch.seen == []


@pytest.mark.parametrize("recorded", [
    {},                                                                         # network down
    {"https://t.co/ExampleShare6": (200, None)},                                     # no redirect
    {"https://t.co/ExampleShare6": (404, None)},                                     # dead link
    {"https://t.co/ExampleShare6": (302, "https://example.com/elsewhere")},          # unrelated site
    {"https://t.co/ExampleShare6": (302, "https://x.com/examplecreator")},                  # not a post
    {"https://t.co/ExampleShare6": (302, "javascript:alert(1)")},                    # hostile location
])
def test_failures_carry_the_needs_attention_reason(recorded):
    with pytest.raises(ExpansionFailed) as caught:
        expand(clean("https://t.co/ExampleShare6"), replay(recorded))
    assert caught.value.reason == FAILURE_REASON


def test_redirect_loop_gives_up():
    loop = {"https://t.co/ExampleShare6": (302, "https://t.co/ExampleShare6")}
    fetch = replay(loop)
    with pytest.raises(ExpansionFailed, match="too many"):
        expand(clean("https://t.co/ExampleShare6"), fetch)
    assert len(fetch.seen) <= 5


def test_retry_gaps_grow_and_stop_after_about_a_day():
    delays = []
    attempts = 0
    while (d := retry_delay(attempts)) is not None:
        delays.append(d)
        attempts += 1
    assert delays == sorted(delays) and delays[0] == 300
    assert 20 * 3600 <= sum(delays) <= 26 * 3600
    assert retry_delay(attempts + 5) is None


def test_http_fetch_reports_a_redirect_without_following_it(monkeypatch):
    """The real fetch, against a local server (no internet)."""
    import threading
    import socket
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from magpiary.expand import http_fetch
    from magpiary import network

    # This fixture deliberately runs on loopback; production blocks it (test_network.py).
    monkeypatch.setattr(network, "_connect_public", socket.create_connection)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "https://example.com/final")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert http_fetch(f"http://127.0.0.1:{server.server_port}/x") == (302, "https://example.com/final")
    finally:
        server.shutdown()
