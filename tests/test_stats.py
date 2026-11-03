"""Popularity numbers and the very slow refresh queue: recorded answers, no network, no waiting."""

import json

import pytest

from magpiary import stats
from magpiary.store import Store
from magpiary.sources import FetchFailed, Fetched


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


def archived(store, tmp_path, name, source_url, **meta):
    store.add_link(source_url)
    folder = tmp_path / name
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"stats_at": "2026-10-01T09:00:00+00:00", **meta}))
    store.fetch_succeeded(source_url, str(folder))
    return source_url


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def details(result):
    def get(source, url):
        if isinstance(result, Exception):
            raise result
        return Fetched(meta=dict(result))
    return get


def test_the_table_is_seeded_from_what_each_post_saved_and_keeps_one_earlier_snapshot(store, tmp_path):
    url = archived(store, tmp_path, "a", "https://www.instagram.com/reel/AAA1/", like_count=120, comment_count=4, view_count=9000)
    assert store.stats_backfill() == 1 and store.stats_backfill() == 0
    row = store.stats_for(url)
    assert (row["likes"], row["comments"], row["views"]) == (120, 4, 9000) and row["prev_likes"] is None
    store.stats_save(url, 150, 6, None)
    row = store.stats_for(url)
    assert row["likes"] == 150 and row["views"] is None and row["prev_likes"] == 120 and row["prev_views"] == 9000


def test_a_refresh_goes_one_post_at_a_time_with_a_gap_per_site_and_a_daily_cap(store, tmp_path):
    urls = [archived(store, tmp_path, f"p{i}", f"https://www.instagram.com/reel/IG{i}X/", like_count=1) for i in range(20)]
    assert store.stats_enqueue(urls, kind="auto") == 20 and store.stats_enqueue(urls) == 0  # a post is queued once
    clock, state, seen = Clock(), {"next": {}, "stopped": {}}, []

    def get(source, url):
        seen.append(url)
        return Fetched(meta={"like_count": 99})

    assert stats.step(store, now=clock, gap=lambda: 300, details=get, state=state) == "ok" and len(seen) == 1
    assert stats.step(store, now=clock, gap=lambda: 300, details=get, state=state) == ""  # the gap is not over
    clock.t += 301
    assert stats.step(store, now=clock, gap=lambda: 300, details=get, state=state) == "ok" and len(seen) == 2
    for _ in range(40):
        clock.t += 301
        stats.step(store, now=clock, gap=lambda: 300, details=get, state=state)
    assert len(seen) == stats.AUTO_DAILY_CAP and len(store.stats_queue_counts()) == 1  # the automatic refresh stops at its cap; the rest wait for tomorrow


def test_one_login_wall_skips_that_post_but_two_in_a_row_stop_the_site_for_a_day(store, tmp_path):
    a = archived(store, tmp_path, "a", "https://www.instagram.com/reel/WALL1/", like_count=5)
    b = archived(store, tmp_path, "b", "https://www.instagram.com/reel/WALL2/", like_count=5)
    c = archived(store, tmp_path, "c", "https://www.instagram.com/reel/GONE1/", like_count=5)
    store.stats_enqueue([a, b])
    clock, state = Clock(), {"next": {}, "stopped": {}}
    wall = details(FetchFailed("login_wall", "x"))
    assert stats.step(store, now=clock, gap=lambda: 1, details=wall, state=state) == "restricted"  # an age-limited post, not the site
    assert store.item_by_url(a)["login_only"] == 1 and store.stats_queue_counts() == {"instagram": 1}  # flagged for good
    clock.t += 5
    assert stats.step(store, now=clock, gap=lambda: 1, details=wall, state=state) == "stopped:instagram:login_wall"
    assert store.stats_queue_counts() == {"instagram": 1}  # still waiting, not lost
    assert stats.step(store, now=clock, gap=lambda: 1, details=details({}), state={"next": {}, "stopped": {}}) == ""  # a restart keeps the stop
    clock.t += 3600
    assert stats.step(store, now=clock, gap=lambda: 1, details=details({}), state=state) == ""  # still stopped
    clock.t += 24 * 3600
    store.stats_dequeue(b)
    store.stats_enqueue([c])
    assert stats.step(store, now=clock, gap=lambda: 1, details=details(FetchFailed("deleted", "HTTP 404")), state=state) == "unavailable"
    assert store.stats_for(c)["state"] == "unavailable" and store.stats_enqueue([c]) == 0  # not asked again for 30 days


def test_a_post_that_reads_fine_clears_the_login_walls_in_a_row(store, tmp_path):
    urls = [archived(store, tmp_path, f"w{i}", f"https://www.instagram.com/reel/WW{i}Z/", like_count=5) for i in range(3)]
    clock, state = Clock(), {"next": {}, "stopped": {}}
    for url, d, want in zip(urls, (details(FetchFailed("login_wall", "x")), details({"like_count": 9}), details(FetchFailed("login_wall", "x"))),
                            ("restricted", "ok", "restricted")):
        store.stats_enqueue([url])
        clock.t += 300
        assert stats.step(store, now=clock, gap=lambda: 1, details=d, state=state) == want  # never two walls in a row


def test_pause_estimate_and_the_weekly_queue(store, tmp_path):
    urls = [archived(store, tmp_path, f"q{i}", f"https://www.instagram.com/reel/QQ{i}Z/") for i in range(3)]
    store.stats_enqueue(urls)
    store.set_paused("stats", True)
    assert stats.step(store, now=Clock(), gap=lambda: 1, details=details({}), state={"next": {}, "stopped": {}}) == ""
    est = stats.estimate({"instagram": 100, "youtube": 3})
    assert est["posts"] == 103 and est["seconds"] > 86400  # 100 posts at 40 a day is three days
    assert "days" in stats.human(est["seconds"]) and stats.human(30) == "about a minute"
    store.stats_clear_queue()
    assert stats.weekly_queue(store) == 0  # the first start only begins the clock
    store.set_setting("stats_auto_at", "2026-01-01T00:00:00+00:00")
    assert stats.weekly_queue(store) == 3 and stats.weekly_queue(store) == 0  # then once a week
    store.set_setting("stats_auto", "0")
    store.set_setting("stats_auto_at", "")
    assert stats.weekly_queue(store) == 0


def test_opens_are_counted_once_per_visit_and_recent_ones_weigh_more(store, tmp_path):
    url = archived(store, tmp_path, "o", "https://www.instagram.com/reel/OPEN1/", like_count=1)
    store.open_record(url)
    store.open_record(url)  # a re-draw right after: not a second visit
    assert round(store.opens_weighted()[url], 2) == 1.0
    store._db.execute("UPDATE opens SET at='2026-01-01T00:00:00+00:00'")
    store._db.commit()
    store.open_record(url)
    assert 1.0 < store.opens_weighted()[url] < 1.1  # the old visit has almost faded


def test_a_stats_refresh_never_uses_the_owners_login():
    """Owner rule: refreshing numbers reads posts logged out. The default downloader carries no cookies file."""
    from magpiary.tools import YtDlp
    assert YtDlp().cookies is None
    import inspect
    from magpiary import stats
    assert "cookies" not in inspect.getsource(stats).replace("login or cookies", "")  # nothing in stats.py touches them


def test_the_proxy_is_saved_privately_checked_and_only_added_to_the_refresh_downloader(tmp_path, monkeypatch):
    from magpiary import keys, proxy
    from magpiary.tools import YtDlp
    monkeypatch.setattr(keys, "_path", lambda: tmp_path / "keys.json")
    assert proxy.get() == "" and proxy.save("not a proxy") and proxy.save("ftp://h:1") and proxy.save("socks5h://h") and proxy.save("socks5h://h:abc")
    assert proxy.save("socks5://user:secret@proxy.example:1080") == ""
    assert (tmp_path / "stats-proxy").stat().st_mode & 0o777 == 0o600
    assert proxy.mask(proxy.get()) == "socks5://proxy.example:1080" and "secret" not in proxy.mask(proxy.get())
    assert "--proxy" in YtDlp(proxy=proxy.get())._base() and "--proxy" not in YtDlp()._base()
    assert proxy.save("socks5h://user:10.0.0.5:1080") and proxy.mask("socks5h://user:10.0.0.5:1080") == ""  # no @: not accepted
    (tmp_path / "stats-proxy").write_text("socks5h://user:10.0.0.5:1080")
    assert proxy.get() == ""  # a damaged saved file is ignored, so Settings still opens
    assert proxy.save("") == "" and proxy.get() == ""
    assert proxy.save("SOCKS5H://us er:p@ss:w/rd#x@10.0.0.5:1080").startswith("There is a space")
    assert proxy.save("SOCKS5H://user:p@ss:w/rd#x@10.0.0.5:1080") == ""  # odd characters in a password are encoded for us
    assert proxy.get() == "socks5h://user:p%40ss%3Aw%2Frd%23x@10.0.0.5:1080"
    asked = []
    ok, words = proxy.test("socks5://p:1", run=lambda cmd, **k: asked.append(cmd) or type("R", (), {"returncode": 0, "stdout": "9.9.9.9" if "--proxy" in cmd else "1.1.1.1"})())
    assert ok and "9.9.9.9" in words


def test_instagrams_empty_media_response_counts_as_a_restricted_post_not_a_site_wide_limit(store, tmp_path):
    a = archived(store, tmp_path, "e", "https://www.instagram.com/reel/EMPTY1/", like_count=5)
    store.stats_enqueue([a])
    clock, state = Clock(), {"next": {}, "stopped": {}}
    err = FetchFailed("rate_limited", "Instagram sent an empty media response. Check if this post is accessible")
    assert stats.step(store, now=clock, gap=lambda: 1, details=details(err), state=state) == "restricted"
    assert store.item_by_url(a)["login_only"] == 1
    b = archived(store, tmp_path, "f", "https://www.instagram.com/reel/REAL429/", like_count=5)
    store.stats_enqueue([b])
    clock.t += 5
    assert stats.step(store, now=clock, gap=lambda: 1, details=details(FetchFailed("rate_limited", "HTTP 429")), state=state) == "stopped:instagram:rate_limited"


def test_login_only_posts_are_never_queued_and_keep_as_a_link_leaves_needs_attention(store, tmp_path):
    a = archived(store, tmp_path, "l1", "https://www.instagram.com/reel/LOGIN1/", like_count=5)
    b = archived(store, tmp_path, "l2", "https://www.instagram.com/reel/PLAIN1/", like_count=5)
    store.mark_login_only(a)
    assert store.stats_enqueue([a, b]) == 1 and store.stats_queue_counts() == {"instagram": 1}
    item = store.item_by_url(b)
    assert store.keep_as_link(item["id"], archive=True) and store.item_by_url(b)["login_only"] == 2
    assert store.item_by_url(b)["shelf"] == "archive"


def test_the_nest_button_stays_clickable_while_the_mac_is_working():
    """The Nest button gets the .busy class when work is running; the loading-button rule must not switch its clicks off."""
    from pathlib import Path
    css = (Path(__file__).parent.parent / "src/magpiary/static/indigo.css").read_text()
    rule = next(line for line in css.splitlines() if "pointer-events: none; opacity: 1;" in line and ".busy" in line)
    assert ".ubtn:not(.nestbtn)" in rule


def test_a_queued_post_that_becomes_login_only_is_not_refreshed(store, tmp_path):
    url = archived(store, tmp_path, "queued-private", "https://www.instagram.com/reel/QUEUEDPRIVATE/")
    assert store.stats_enqueue([url]) == 1
    store.mark_login_only(url)
    seen = []
    stats.step(store, now=Clock(), gap=lambda: 1,
               details=lambda *args: seen.append(args) or Fetched(meta={}))
    assert seen == [] and store.stats_queue_counts() == {}
