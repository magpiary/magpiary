"""M2: source adapters, the archive writer and the fetch worker, against recorded (made-up) responses."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from magpiary import sources
from magpiary.archive import fetch_item, slug
from magpiary.sources import FetchFailed, describe
from magpiary.store import Store
from magpiary.tools import YtDlpError, classify
from magpiary.worker import fetch_due

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n" + b"0" * 100

THREADS_HTML = b"""<html><head><title>Threads</title>
<meta property="og:title" content="Alex Example (@alex.example) on Threads">
<meta property="og:description" content="Line one &amp; more.
Line two.">
<meta property="og:image" content="https://cdn.example/threads.jpg">
</head></html>"""

# Threads' embed page (recorded shape, fictional post): the post page has only the cover, the embed has the file.
THREADS_EMBED_HTML = b"""<html><body><div class="SoloMediaContainer" id="u_0_2_he">
<div class="SingleInnerMediaContainerVideo SingleInnerMediaContainer"><video controls="1" loop="1" class="">
<source src="https://video.cdn.example/o1/v/t16/clip.mp4?_nc_cat=104&amp;_nc_sid=1d576d" /></video>
<div class="VideoPlayOverlay"><div class="VideoPlayButton"></div></div></div></div>
<div class="PostDateContainer"><span class="Timestamp">8:44 AM &middot; Nov 2, 2026</span></div>
<div class="ActionBarContainer"><span class="ActionBarIcon"><svg></svg><span class="ActionBarCount">51</span></span>
<span class="ActionBarIcon"><svg></svg><span class="ActionBarCount">1</span></span>
<span class="ActionBarIcon"><svg></svg><span class="ActionBarCount">5</span></span>
<span class="ActionBarIcon"><svg></svg><span class="ActionBarCount">1.2K</span></span></div></body></html>"""
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 100

REDDIT_RSS = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<category term="ExampleWorkshop" label="r/ExampleWorkshop"/>
<entry><author><name>/u/poster</name></author><title>A question about queues</title>
<published>2026-10-20T10:00:00+00:00</published>
<content type="html">&lt;div class="md"&gt;&lt;p&gt;Body &amp;amp; text&lt;/p&gt;&lt;/div&gt;
&lt;a href="https://i.redd.it/abc123.jpg"&gt;img&lt;/a&gt;</content></entry>
<entry><author><name>/u/helper</name></author><title>comment</title>
<updated>2026-10-20T11:00:00+00:00</updated><content type="html">&lt;p&gt;Use SQLite.&lt;/p&gt;</content></entry>
</feed>"""

X_JSON = json.dumps({
    "__typename": "Tweet", "text": "Short text https://t.co/x", "created_at": "2026-10-13T20:51:33.000Z",
    "favorite_count": 930, "conversation_count": 12, "user": {"name": "Rowan Example", "screen_name": "examplecreator"},
    "note_tweet": {"note_tweet_results": {"result": {"text": "The full long text."}}},
    "mediaDetails": [{"type": "photo", "media_url_https": "https://pbs.example/1.jpg"}]}).encode()

LINKEDIN_HTML = b"""<html><head><meta property="og:title" content="A post title">
<meta property="og:description" content="What the post says.">
<meta property="og:image" content="https://media.example/li.jpg"></head></html>"""

IG = "https://www.instagram.com/reel/Example0020/"
IG_INFO = {"title": "Video by examplecreator", "description": "Caption #tag", "uploader": "Rowan Example",
           "uploader_id": "11111111111", "channel": "examplecreator", "timestamp": 1760000000, "like_count": 5, "comment_count": 2}


class FakeYtDlp:
    """Stands in for yt-dlp: canned info per URL, writes small media files on download."""

    def __init__(self, infos=None, fail=None, fail_download=None):
        self.infos, self.fail, self.fail_download = infos or {}, fail or {}, fail_download or {}
        self.downloads = []

    def info(self, url):
        if url in self.fail:
            raise YtDlpError(*self.fail[url])
        if url not in self.infos:
            raise YtDlpError("unsupported", "Unsupported URL")
        return self.infos[url]

    def download(self, url, folder: Path, on_progress=None):
        self.downloads.append(url)
        if url in self.fail_download:
            (folder / "media-01.mp4.part").write_bytes(b"half")
            raise YtDlpError(*self.fail_download[url])
        (folder / "media-01.mp4").write_bytes(b"video")
        (folder / "thumbnail.jpg").write_bytes(JPEG)

    def version(self):
        return "2026.10.21"


def pages(mapping):
    def get(url):
        if url not in mapping:
            return 404, b""
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, tuple) else (200, value)
    return get


def item(url, source, kind=None):
    return {"canonical_url": url, "source": source, "kind": kind}


# ---- adapters -----------------------------------------------------------------------------

def test_threads_reads_text_author_and_image_from_one_page():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    got = describe("threads", url, pages({url: THREADS_HTML}), FakeYtDlp())
    assert got.meta["text"] == "Line one & more.\nLine two."
    assert (got.meta["author"], got.meta["author_handle"]) == ("Alex Example", "alex.example")
    assert got.images == ["https://cdn.example/threads.jpg"] and not got.video


def test_threads_video_comes_from_the_embed_page_and_the_page_picture_is_its_cover():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    got = describe("threads", url, pages({url: THREADS_HTML, url.rstrip("/") + "/embed": THREADS_EMBED_HTML}), FakeYtDlp())
    assert got.videos == ["https://video.cdn.example/o1/v/t16/clip.mp4?_nc_cat=104&_nc_sid=1d576d"]
    assert got.images == [] and got.poster == "https://cdn.example/threads.jpg"


def test_threads_counts_and_day_come_from_the_embed_page_in_the_action_bars_order():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    got = describe("threads", url, pages({url: THREADS_HTML, url.rstrip("/") + "/embed": THREADS_EMBED_HTML}), FakeYtDlp())
    assert (got.meta["like_count"], got.meta["comment_count"], got.meta["repost_count"], got.meta["share_count"]) == (51, 1, 5, 1200)
    assert got.meta["published_at"] == "2026-11-02"


def test_threads_post_without_a_video_still_gets_its_counts():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    embed = THREADS_EMBED_HTML.replace(b"<video", b"<div").replace(b"</video>", b"</div>")
    got = describe("threads", url, pages({url: THREADS_HTML, url.rstrip("/") + "/embed": embed}), FakeYtDlp())
    assert got.videos == [] and got.images == ["https://cdn.example/threads.jpg"] and got.meta["like_count"] == 51


def test_threads_leaves_a_zero_count_out_of_the_page_but_keeps_its_place():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    embed = THREADS_EMBED_HTML.replace(b'<span class="ActionBarCount">1</span>', b"").replace(b'<span class="ActionBarCount">5</span>', b"")
    got = describe("threads", url, pages({url: THREADS_HTML, url.rstrip("/") + "/embed": embed}), FakeYtDlp())
    assert (got.meta["like_count"], got.meta["comment_count"], got.meta["repost_count"], got.meta["share_count"]) == (51, 0, 0, 1200)


def test_threads_counts_are_skipped_when_the_embed_layout_changes():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    embed = THREADS_EMBED_HTML.replace(b'<span class="ActionBarCount">1.2K</span>', b'</span><span class="ActionBarIcon">')  # five icons, not four
    got = describe("threads", url, pages({url: THREADS_HTML, url.rstrip("/") + "/embed": embed}), FakeYtDlp())
    assert "like_count" not in got.meta and got.meta["published_at"] == "2026-11-02"


def test_threads_video_post_archives_the_video_file(tmp_path):
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    get = pages({url: THREADS_HTML, url.rstrip("/") + "/embed": THREADS_EMBED_HTML,
                 "https://video.cdn.example/o1/v/t16/clip.mp4?_nc_cat=104&_nc_sid=1d576d": MP4,
                 "https://cdn.example/threads.jpg": JPEG})
    folder = fetch_item(item(url, "threads"), tmp_path, get, FakeYtDlp(),
                        run=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "12.5\n", ""))
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["like_count"] == 51 and meta["share_count"] == 1200
    assert meta["media"] == ["media-01.mp4"] and meta["fetched_with"] == "page + embed page" and (folder / "media-01.mp4").read_bytes() == MP4
    assert meta["thumbnail"] == "thumbnail.jpg" and (folder / "thumbnail.jpg").read_bytes() == JPEG


def test_threads_video_that_cannot_be_downloaded_keeps_its_cover(tmp_path):
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    get = pages({url: THREADS_HTML, url.rstrip("/") + "/embed": THREADS_EMBED_HTML, "https://cdn.example/threads.jpg": JPEG})
    folder = fetch_item(item(url, "threads"), tmp_path, get, FakeYtDlp())
    assert json.loads((folder / "meta.json").read_text())["media"] == ["media-01.jpg"]


def test_threads_page_without_post_text_is_flagged():
    url = "https://www.threads.com/@alex.example/post/Example0015/"
    with pytest.raises(FetchFailed) as err:
        describe("threads", url, pages({url: b"<html><title>Threads</title></html>"}), FakeYtDlp())
    assert err.value.reason == "unknown"


def test_reddit_feed_gives_post_images_and_comments():
    url = "https://www.reddit.com/r/exampleworkshop/comments/1abc/"
    got = describe("reddit", url, pages({url.rstrip("/") + "/.rss": REDDIT_RSS}), FakeYtDlp())
    assert got.meta["title"] == "A question about queues" and got.meta["text"] == "Body & text\n\nimg"
    assert got.meta["author"] == "poster" and got.meta["community"] == "r/ExampleWorkshop"
    assert got.images == ["https://i.redd.it/abc123.jpg"]
    assert got.discussion == [{"author": "helper", "published_at": "2026-10-20T11:00:00+00:00", "text": "Use SQLite."}]


def test_reddit_bot_check_page_is_not_mistaken_for_a_post():
    url = "https://www.reddit.com/r/exampleworkshop/comments/1abc/"
    with pytest.raises(FetchFailed, match="bot check"):
        describe("reddit", url, pages({url.rstrip("/") + "/.rss": b"<html>Welcome to Reddit</html>"}), FakeYtDlp())


def test_x_embed_feed_gives_full_text_counts_and_photos():
    url = "https://x.com/examplecreator/status/2222222222222222222"
    feed = f"https://cdn.syndication.twimg.com/tweet-result?id=2222222222222222222&lang=en&token={sources._x_token('2222222222222222222')}"
    got = describe("x", url, pages({feed: X_JSON}), FakeYtDlp())
    assert got.meta["text"] == "The full long text." and got.meta["author_handle"] == "examplecreator"
    assert got.meta["like_count"] == 930 and got.images == ["https://pbs.example/1.jpg"] and not got.video


def test_x_deleted_post():
    url = "https://x.com/examplecreator/status/1"
    feed = f"https://cdn.syndication.twimg.com/tweet-result?id=1&lang=en&token={sources._x_token('1')}"
    with pytest.raises(FetchFailed) as err:
        describe("x", url, pages({feed: b'{"__typename":"TweetTombstone"}'}), FakeYtDlp())
    assert err.value.reason == "deleted"


def test_linkedin_text_post_uses_the_page_and_a_video_post_uses_yt_dlp():
    url = "https://www.linkedin.com/posts/examplecreator_hi-ugcPost-1-AbC/"
    text_post = describe("linkedin", url, pages({url: LINKEDIN_HTML}), FakeYtDlp())
    assert text_post.meta["text"] == "What the post says." and text_post.images and not text_post.video
    video_post = describe("linkedin", url, pages({url: LINKEDIN_HTML}),
                          FakeYtDlp(infos={url: {"formats": [{}], "duration": 42}}))
    assert video_post.video and video_post.images == [] and video_post.meta["duration"] == 42


def test_instagram_uses_yt_dlp_and_a_photo_post_falls_back_to_the_page():
    got = describe("instagram", IG, pages({}), FakeYtDlp(infos={IG: IG_INFO}))
    assert got.video and got.meta["text"] == "Caption #tag" and got.meta["author_handle"] == "examplecreator"
    assert got.meta["published_at"].startswith("2025-10-09")
    photo = "https://www.instagram.com/p/Photo1/"
    got = describe("instagram", photo, pages({photo: LINKEDIN_HTML}),
                   FakeYtDlp(fail={photo: ("no_video", "No video formats found")}))
    assert not got.video and got.images == ["https://media.example/li.jpg"]


@pytest.mark.parametrize("status, reason", [(404, "deleted"), (410, "deleted"), (429, "rate_limited"),
                                            (403, "login_wall"), (500, "unknown")])
def test_page_errors_become_reasons(status, reason):
    url = "https://example.com/a"
    with pytest.raises(FetchFailed) as err:
        describe("other", url, pages({url: (status, b"")}), FakeYtDlp())
    assert err.value.reason == reason


def test_network_failure_is_unknown_and_retryable():
    url = "https://example.com/a"
    with pytest.raises(FetchFailed) as err:
        describe("other", url, pages({url: TimeoutError()}), FakeYtDlp())
    assert err.value.reason == "unknown"


@pytest.mark.parametrize("stderr, reason", [
    ("ERROR: [Instagram] X: Instagram sent an empty media response. ... use --cookies-from-browser", "rate_limited"),
    ("ERROR: Unsupported URL: https://www.threads.com/x", "unsupported"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader", "deleted"),
    ("ERROR: [twitter] 1: No video could be found in this tweet", "no_video"),
    ("ERROR: something new and strange", "unknown"),
])
def test_yt_dlp_errors_become_reasons(stderr, reason):
    assert classify(stderr)[0] == reason


# ---- archive writer -------------------------------------------------------------------------

@pytest.mark.parametrize("url, source, expected", [
    (IG, "instagram", "instagram-Example0020-61e2b519"),
    ("https://www.youtube.com/watch?v=Example0005", "youtube", "youtube-Example0005-71d8d240"),
    ("https://x.com/a/status/185", "x", "x-185-72512958"),
])
def test_folder_names_are_readable_and_stable(url, source, expected):
    assert slug(url, source) == expected


def test_other_sites_and_long_codes_get_a_hash():
    assert slug("https://example.com/a/b", "other").startswith("other-") and "/" not in slug("https://example.com/a/b", "other")
    long = slug("https://www.linkedin.com/posts/" + "x" * 80 + "/", "linkedin")
    assert len(long) < 60 and long.startswith("linkedin-")


def test_a_video_post_is_archived_with_media_thumbnail_caption_and_details(tmp_path):
    import subprocess
    folder = fetch_item(item(IG, "instagram", "reel"), tmp_path, pages({}), FakeYtDlp(infos={IG: IG_INFO}),
                        run=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "12.5\n", ""))
    assert folder == tmp_path / "instagram-Example0020-61e2b519"
    assert sorted(p.name for p in folder.iterdir()) == ["caption.txt", "media-01.mp4", "meta.json", "thumbnail.jpg"]
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["url"] == IG and meta["kind"] == "reel" and meta["media"] == ["media-01.mp4"]
    assert meta["thumbnail"] == "thumbnail.jpg" and "yt-dlp 2026.10.21" in meta["fetched_with"]
    assert (folder / "caption.txt").read_text() == "Caption #tag"
    assert meta["duration"] == 12.5  # measured by ffprobe: Instagram does not report it


def test_images_are_downloaded_only_if_they_really_are_images(tmp_path):
    url = "https://x.com/examplecreator/status/5"
    feed = f"https://cdn.syndication.twimg.com/tweet-result?id=5&lang=en&token={sources._x_token('5')}"
    data = json.loads(X_JSON)
    data["mediaDetails"] = [{"type": "photo", "media_url_https": u} for u in
                            ("https://pbs.example/1.jpg", "https://pbs.example/2.png", "https://pbs.example/evil.jpg")]
    get = pages({feed: json.dumps(data).encode(), "https://pbs.example/1.jpg": JPEG,
                 "https://pbs.example/2.png": PNG, "https://pbs.example/evil.jpg": b"<script>alert(1)</script>"})
    folder = fetch_item(item(url, "x"), tmp_path, get, FakeYtDlp())
    assert json.loads((folder / "meta.json").read_text())["media"] == ["media-01.jpg", "media-02.png"]
    assert json.loads((folder / "meta.json").read_text())["thumbnail"] == "media-01.jpg"


def test_reddit_comments_are_kept_for_later(tmp_path):
    url = "https://www.reddit.com/r/exampleworkshop/comments/1abc/"
    folder = fetch_item(item(url, "reddit"), tmp_path,
                        pages({url.rstrip("/") + "/.rss": REDDIT_RSS, "https://i.redd.it/abc123.jpg": JPEG}), FakeYtDlp())
    assert json.loads((folder / "discussion.json").read_text())[0]["author"] == "helper"


def test_a_failed_download_leaves_no_folder_behind(tmp_path):
    fake = FakeYtDlp(infos={IG: IG_INFO}, fail_download={IG: ("rate_limited", "HTTP Error 429")})
    with pytest.raises(FetchFailed) as err:
        fetch_item(item(IG, "instagram"), tmp_path, pages({}), fake)
    assert err.value.reason == "rate_limited" and list(tmp_path.iterdir()) == []


def test_fetching_again_replaces_the_folder_whole(tmp_path):
    fake = FakeYtDlp(infos={IG: IG_INFO})
    folder = fetch_item(item(IG, "instagram"), tmp_path, pages({}), fake)
    (folder / "stale.txt").write_text("old")
    fetch_item(item(IG, "instagram"), tmp_path, pages({}), fake)
    assert not (folder / "stale.txt").exists() and sorted(p.name for p in tmp_path.iterdir()) == ["instagram-Example0020-61e2b519"]


# ---- the worker and the store ---------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 23, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    def __call__(self):
        return self.t


@pytest.fixture
def store():
    clock = Clock()
    s = Store(":memory:", now=clock)
    s.clock = clock
    phone, _ = s.add_phone("Test phone")
    s.phone = phone
    return s


def share(store, url, n=[0]):
    n[0] += 1
    store.receive(store.phone, [{"id": f"d{n[0]}", "url": url}])


def test_worker_archives_due_items_and_records_the_folder(store, tmp_path):
    share(store, IG)
    assert fetch_due(store, tmp_path, pages({}), FakeYtDlp(infos={IG: IG_INFO}), pause=lambda s: None,
                     update=lambda force=False: False) == 1
    got = store.get_item(IG)
    assert got["status"] == "archived" and got["archive_dir"] == str(tmp_path / "instagram-Example0020-61e2b519")
    assert store.due_for_fetch() == []


def test_short_links_are_left_to_the_expander(store):
    share(store, "https://redd.it/abc1")
    assert store.due_for_fetch() == []


def test_a_passing_problem_is_retried_on_schedule_and_a_lasting_one_waits_for_retry(store, tmp_path):
    private = "https://www.instagram.com/reel/Private1/"
    share(store, IG)
    share(store, private)
    fake = FakeYtDlp(fail={IG: ("rate_limited", "empty media response"), private: ("private", "Private video")})
    fetch_due(store, tmp_path, pages({}), fake, pause=lambda s: None, update=lambda force=False: False)
    passing, lasting = store.get_item(IG), store.get_item(private)
    assert passing["status"] == "needs_attention" and passing["reason"] == "rate_limited" and passing["next_retry_at"]
    assert lasting["reason"] == "private" and lasting["next_retry_at"] is None
    assert store.due_for_fetch() == []
    store.clock.t += timedelta(minutes=6)
    assert [i["canonical_url"] for i in store.due_for_fetch()] == [IG]
    assert store.retry(private) and store.get_item(private)["status"] == "queued"
    assert not store.retry(private)  # only a flagged item can be retried


def test_yt_dlp_is_updated_and_the_fetch_tried_once_more(store, tmp_path):
    share(store, IG)
    fake = FakeYtDlp(fail={IG: ("unknown", "something changed")})
    updates = []

    def update(force=False):
        updates.append(1)
        fake.fail.clear()  # the new yt-dlp works
        fake.infos[IG] = IG_INFO
        return True

    assert fetch_due(store, tmp_path, pages({}), fake, pause=lambda s: None, update=update) == 1
    assert updates == [1] and store.get_item(IG)["status"] == "archived"


def test_pages_are_fetched_one_at_a_time_with_a_pause_between(store, tmp_path):
    urls = [f"https://www.instagram.com/reel/Code{i}/" for i in range(3)]
    for u in urls:
        share(store, u)
    pauses = []
    fetch_due(store, tmp_path, pages({}), FakeYtDlp(infos={u: IG_INFO for u in urls}),
              pause=pauses.append, update=lambda force=False: False)
    assert pauses == ["instagram", "instagram"]


def test_an_older_database_gains_the_archive_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE items (canonical_url TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT, "
                     "first_phone_id INTEGER, last_phone_id INTEGER, first_shared_at TEXT, last_shared_at TEXT, "
                     "saved_count INTEGER NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, "
                     "reason TEXT, reason_detail TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT, "
                     "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.close()
    s = Store(path)
    assert {"archive_dir", "archived_at"} <= {r["name"] for r in s._db.execute("PRAGMA table_info(items)")}
    Store(path)  # and opening it again changes nothing


EMBED = (b'<script>{"display_url\\":\\"https:\\\\/\\\\/cdn.example\\\\/v\\\\/one.webp?a=1\\u0026b=2\\"},'
         b'{"display_url\\":\\"https:\\\\/\\\\/cdn.example\\\\/v\\\\/two.jpg?x=%3D\\"},'
         b'{"display_url\\":\\"https:\\\\/\\\\/cdn.example\\\\/v\\\\/one.webp?a=9\\"}</script>')


def test_an_instagram_photo_carousel_keeps_every_photo_and_the_details(tmp_path):
    post = "https://www.instagram.com/p/Carousel1/"
    info = {"_type": "playlist", "uploader": "Tess Example", "description": "Caption", "timestamp": 1760000000,
            "entries": [None, None]}
    get = pages({post + "embed/captioned/": EMBED, "https://cdn.example/v/one.webp?a=1&b=2": b"RIFF0000WEBP" + b"0" * 50,
                 "https://cdn.example/v/two.jpg?x=%3D": JPEG})
    got = describe("instagram", post, get, FakeYtDlp(infos={post: info}))
    assert got.images == ["https://cdn.example/v/one.webp?a=1&b=2", "https://cdn.example/v/two.jpg?x=%3D"]
    assert not got.video and got.meta["author"] == "Tess Example" and got.meta["parts"] == 2
    folder = fetch_item(item(post, "instagram"), tmp_path, get, FakeYtDlp(infos={post: info}))
    assert json.loads((folder / "meta.json").read_text())["media"] == ["media-01.webp", "media-02.jpg"]


def test_a_timeout_on_one_post_does_not_hold_up_the_posts_after_it(store, tmp_path):
    """Review 4 Nov 2026: a yt-dlp timeout escaped and stopped the pass on the same oldest post every time."""
    slow = "https://www.instagram.com/reel/Slow1/"
    share(store, slow)
    share(store, IG)

    class Timing(FakeYtDlp):
        def info(self, url):
            if url == slow:
                raise subprocess.TimeoutExpired("yt-dlp", 120)
            return super().info(url)
    assert fetch_due(store, tmp_path, pages({}), Timing(infos={IG: IG_INFO}), pause=lambda s: None) == 1
    assert store.get_item(slow)["status"] == "needs_attention" and store.get_item(slow)["next_retry_at"]


def test_one_malformed_link_is_refused_alone_and_the_rest_of_the_batch_is_saved(store):
    results = store.receive(store.phone, [{"id": "ok1", "url": IG}, {"id": "bad1", "url": "https://example.com:abc/a"}])
    assert [(r.id, r.status) for r in results] == [("ok1", "new"), ("bad1", "rejected")]


def test_a_saved_login_is_sent_only_to_its_own_site(monkeypatch):
    """Review 3, 4 Nov 2026: a page fetched with the login passed the cookie to every host it pointed at."""
    from magpiary import login, worker

    sent = []
    monkeypatch.setattr(login, "cookie_header", lambda site, url="": "session=abcd")
    monkeypatch.setattr(worker, "http_get", lambda url, *rest, cookie=None: sent.append((url, cookie)))
    get = worker._get_with_login(worker.http_get, "example.com")
    for url in ("https://www.example.com/post", "https://img.example.com/a.jpg", "https://collector.test/i.jpg",
                "http://example.com/plain"):
        get(url)
    assert sent == [("https://www.example.com/post", "session=abcd"), ("https://img.example.com/a.jpg", "session=abcd"),
                    ("https://collector.test/i.jpg", None), ("http://example.com/plain", None)]



def test_a_cookie_goes_only_where_a_browser_would_send_it(tmp_path, monkeypatch):
    """Review 5, 4 Nov 2026: cookies of a.github.io reached b.github.io, and a path or secure flag was ignored."""
    from magpiary import login

    jar = tmp_path / "jar.txt"
    jar.write_text("# Netscape HTTP Cookie File\n"
                   "a.github.io\tFALSE\t/\tTRUE\t0\tsa\t1\n"
                   ".github.io\tTRUE\t/\tTRUE\t0\tall\t2\n"
                   "#HttpOnly_a.github.io\tFALSE\t/private\tTRUE\t0\tdeep\t3\n"
                   "a.github.io\tFALSE\t/\tFALSE\t0\tplain\t4\n")
    monkeypatch.setattr(login, "login_path", lambda domain: jar)
    assert login.cookie_header("github.io", "https://a.github.io/x") == "sa=1; all=2; plain=4"
    assert login.cookie_header("github.io", "https://a.github.io/private/p") == "sa=1; all=2; deep=3; plain=4"
    assert login.cookie_header("github.io", "https://b.github.io/x") == "all=2"
    assert login.cookie_header("github.io", "http://a.github.io/x") == "plain=4"
