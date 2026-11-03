"""The extension's JavaScript cleaner must give the same answer as the Mac's cleaner.py for every link."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from magpiary.cleaner import UnsupportedLink, clean

EXT = Path(__file__).resolve().parent.parent / "src" / "magpiary" / "extension"
LINKS = [
    "https://www.instagram.com/reel/AAAA111/?igsh=abc&utm_source=ig_web_copy_link",
    "https://www.instagram.com/someone/reel/AAAA111/",
    "https://www.instagram.com/reels/AAAA111/",
    "https://www.instagram.com/p/BBBB222/?img_index=2#x",
    "https://www.instagram.com/tv/CCCC333/",
    "https://www.instagram.com/share/reel/DDDD444/",
    "https://www.instagram.com/someone/",
    "https://www.threads.com/@someone/post/EEEE555?xmt=zz&slof=1",
    "https://www.threads.com/@someone/post/EEEE555/media",
    "https://www.threads.net/t/FFFF666",
    "https://www.threads.com/@someone",
    "https://x.com/someone/status/1234567890?s=20&t=abc",
    "https://twitter.com/someone/status/1234567890",
    "https://t.co/abcDEF",
    "https://www.reddit.com/r/Design/comments/AbC123/a_title/?utm_name=x",
    "https://www.reddit.com/r/Design/s/XyZ987",
    "https://redd.it/abc123",
    "https://www.youtube.com/watch?v=Example0005&si=tracker&t=10s",
    "https://youtu.be/Example0005?si=abc",
    "https://www.youtube.com/shorts/Example0005?feature=share",
    "https://www.youtube.com/feed/subscriptions",
    "https://www.linkedin.com/posts/someone_topic-activity-123-AbCd?utm_source=share",
    "https://lnkd.in/p/abc123",
    "https://example.com/article?id=7&utm_campaign=x&fbclid=y&si=z",
    "https://Example.COM/a/b/?",
    "see this https://example.com/page?igsh=1.",
    "https://example.com/post?ref=newsletter&id=7&ref_src=tw&mc_eid=abc&spm=a2.b",
    "https://example.com/post?ref=home",
    "https://www.nytimes.com/2026/10/30/article.html?smid=share&referrer=foo&campaign=x",
    "not a link",
    "ftp://example.com/file",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_cleaner_matches_python_cleaner():
    script = ("const {clean}=require(process.argv[1]);"
              "const links=JSON.parse(process.argv[2]);console.log(JSON.stringify(links.map(l=>clean(l))));")
    out = subprocess.run(["node", "-e", script, str(EXT / "clean.js"), json.dumps(LINKS)],
                         capture_output=True, text=True, check=True).stdout
    for link, js in zip(LINKS, json.loads(out), strict=True):
        try:
            py = clean(link)
        except UnsupportedLink:
            assert "error" in js, f"{link}: python refuses, js gave {js}"
            continue
        assert "error" not in js, f"{link}: js refused ({js})"
        assert (js["url"], js["source"], js.get("kind"), bool(js.get("needsExpansion"))) == (py.url, py.source, py.kind, py.needs_expansion), link
