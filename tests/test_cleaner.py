"""The link-cleaning table in docs/specs.md is the spec: one row per case."""

import pytest

from magpiary.cleaner import CleanLink, UnsupportedLink, clean

IG = "https://www.instagram.com"

# (input, canonical url, source, kind, needs_expansion)
CASES = [
    # Instagram: tracking dropped, reels/ becomes reel/, host prefixes accepted
    (f"{IG}/reel/Example0001/?igsh=example-tracking&utm_source=ig_web_copy_link", f"{IG}/reel/Example0001/", "instagram", "reel", False),
    ("https://instagram.com/reel/Example0002", f"{IG}/reel/Example0002/", "instagram", "reel", False),
    ("https://m.instagram.com/reel/Example0002/?igshid=abc#frag", f"{IG}/reel/Example0002/", "instagram", "reel", False),
    (f"{IG}/reels/Example0001/?xmt=1", f"{IG}/reel/Example0001/", "instagram", "reel", False),
    (f"{IG}/p/Example0003/?img_index=2", f"{IG}/p/Example0003/", "instagram", "post", False),
    (f"{IG}/tv/Abc_123/", f"{IG}/tv/Abc_123/", "instagram", "tv", False),
    (f"{IG}/exampleuser/reel/Example0001/?igsh=x", f"{IG}/reel/Example0001/", "instagram", "reel", False),
    # Instagram share links: held for expansion
    ("https://www.instagram.com/share/reel/ExampleShare4/?igsh=zz", f"{IG}/share/reel/ExampleShare4/", "instagram", None, True),
    ("https://www.instagram.com/share/ExampleShare4", f"{IG}/share/ExampleShare4/", "instagram", None, True),
    # Threads
    ("https://www.threads.net/@examplecreator/post/Example0014?xmt=AQ&slof=1", "https://www.threads.com/@examplecreator/post/Example0014/", "threads", "post", False),
    ("https://threads.com/@examplecreator/post/Example0014/", "https://www.threads.com/@examplecreator/post/Example0014/", "threads", "post", False),
    ("https://www.threads.com/share/ExampleShare3", "https://www.threads.com/share/ExampleShare3/", "threads", None, True),
    # X
    ("https://x.com/examplecreator/status/1111111111111111111?s=46&t=abc", "https://x.com/examplecreator/status/1111111111111111111", "x", "post", False),
    ("https://twitter.com/examplecreator/status/1111111111111111111", "https://x.com/examplecreator/status/1111111111111111111", "x", "post", False),
    ("https://mobile.twitter.com/examplecreator/status/185?ref_src=x", "https://x.com/examplecreator/status/185", "x", "post", False),
    ("https://t.co/ExampleShare6?amp=1", "https://t.co/ExampleShare6", "x", None, True),
    # Reddit
    ("https://www.reddit.com/r/ExampleWorkshop/comments/1abc2de/some_title/?utm_source=share&utm_medium=ios_app", "https://www.reddit.com/r/exampleworkshop/comments/1abc2de/", "reddit", "post", False),
    ("https://old.reddit.com/r/exampleworkshop/comments/1abc2de/", "https://www.reddit.com/r/exampleworkshop/comments/1abc2de/", "reddit", "post", False),
    ("https://redd.it/1abc2de?share_id=x", "https://redd.it/1abc2de", "reddit", None, True),
    ("https://www.reddit.com/r/exampleworkshop/s/ExampleShare5?utm_source=share", "https://www.reddit.com/r/exampleworkshop/s/ExampleShare5", "reddit", None, True),
    # YouTube: only v survives; shorts and youtu.be map to watch
    ("https://www.youtube.com/watch?v=Example0005&si=abc&t=42s&feature=share", "https://www.youtube.com/watch?v=Example0005", "youtube", "video", False),
    ("https://m.youtube.com/watch?v=Example0005", "https://www.youtube.com/watch?v=Example0005", "youtube", "video", False),
    ("https://www.youtube.com/shorts/Example0005?si=abc", "https://www.youtube.com/watch?v=Example0005", "youtube", "short", False),
    ("https://youtu.be/Example0005?si=abc&t=3", "https://www.youtube.com/watch?v=Example0005", "youtube", "video", False),
    # LinkedIn: the path is the identity; lnkd.in short links are expanded
    ("https://www.linkedin.com/posts/examplemaker_sample-notes-ugcPost-1234567890123456789-GPBL/?utm_source=social_share_send&rcm=ACoA", "https://www.linkedin.com/posts/examplemaker_sample-notes-ugcPost-1234567890123456789-GPBL/", "linkedin", "post", False),
    ("https://linkedin.com/feed/update/urn:li:activity:7000000000000000000?utm_medium=ios_app", "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000000/", "linkedin", "post", False),
    ("https://lnkd.in/p/Ex4mpL3a", "https://lnkd.in/p/Ex4mpL3a", "linkedin", None, True),
    # Anything else: drop known tracking and the fragment, keep the rest
    ("https://Example.com/article?id=7&utm_source=a&utm_campaign=b&fbclid=z&gclid=y&si=1&s=2&t=3&share_id=4&igsh=5&xmt=6#top", "https://example.com/article?id=7", "other", None, False),
    ("https://example.com/p?page=2&q=cats", "https://example.com/p?page=2&q=cats", "other", None, False),
    ("https://example.com/", "https://example.com/", "other", None, False),
]


@pytest.mark.parametrize("raw, url, source, kind, expand", CASES)
def test_table(raw, url, source, kind, expand):
    assert clean(raw) == CleanLink(url, source, kind, expand)


@pytest.mark.parametrize("raw, url", [
    ("Look at this https://www.instagram.com/reel/Example0001/?igsh=zzz\nthanks", f"{IG}/reel/Example0001/"),
    ("(https://x.com/a/status/1?s=20).", "https://x.com/a/status/1"),
])
def test_link_is_found_inside_text(raw, url):
    assert clean(raw).url == url


@pytest.mark.parametrize("raw", [
    "", "   ", "hello", "ftp://example.com/x", "javascript:alert(1)",
    "https://www.instagram.com/exampleuser/",           # a profile, not a post
    "https://www.youtube.com/watch?v=short",         # bad video id
    "https://www.youtube.com/",
    "https://x.com/examplecreator",
    "https://www.threads.com/@examplecreator",
    "https://www.reddit.com/r/exampleworkshop/",
])
def test_unsupported(raw):
    with pytest.raises(UnsupportedLink):
        clean(raw)


@pytest.mark.parametrize("raw", [c[0] for c in CASES if not c[4]])
def test_cleaning_is_idempotent(raw):
    once = clean(raw)
    assert clean(once.url).url == once.url  # kind may be lost (shorts become watch links)


def test_sharer_ids_never_survive():
    for raw, url, *_ in CASES:
        for marker in ("igsh", "igshid", "utm_", "xmt", "share_id", "fbclid", "gclid"):
            assert marker not in url, (raw, url)
