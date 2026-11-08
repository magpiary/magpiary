"""The Instagram carousel reader (extension/instagram.js) on a fictional page that behaves like Instagram's: only the slide on
screen and its neighbours are in the page, and the Next button is gone at the last slide. Skipped unless Playwright and Chrome
for Testing are present:  uv run --with playwright pytest tests/test_extension_instagram.py"""

import glob
import os
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

EXT = Path(__file__).resolve().parent.parent / "src" / "magpiary" / "extension"
CHROME = os.environ.get("MAGPIARY_CHROMIUM") or next(iter(sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))), "")
pytestmark = pytest.mark.skipif(not CHROME or not Path(CHROME).exists(), reason="Chrome for Testing is not installed")

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")

PAGE = """<!doctype html><html lang="en"><head><title>Tess Example on Instagram</title>
<meta property="og:title" content="Tess Example on Instagram"><meta property="og:description" content="9 likes - tessexample: A fictional caption">
<style>body{margin:0}.slide{width:480px;height:600px;display:block}.ava{width:32px;height:32px}.more{width:300px;height:400px}</style></head>
<body><main><div id="post"><ul id="slides"></ul><button aria-label="Like">like</button></div>
<div id="nav"></div>
<ul id="comments"><li><img class="ava" src="https://ig.test/avatar1.jpg"></li><li><img class="ava" src="https://ig.test/avatar2.jpg"></li></ul>
<div><a href="/p/OTHER1/"><img class="more" src="https://ig.test/more1.jpg"></a><a href="/p/OTHER2/"><img class="more" src="https://ig.test/more2.jpg"></a></div></main>
<script>
const N = %d; let at = 0;
function draw() {
  const ul = document.getElementById("slides"); ul.innerHTML = "";
  for (let i = Math.max(0, at - 1); i <= Math.min(N - 1, at + 1); i++) {
    const li = document.createElement("li"); const im = document.createElement("img"); im.className = "slide";
    im.src = "https://ig.test/s" + (i + 1) + ".jpg?stp=x&n=" + at; li.appendChild(im); ul.appendChild(li);   // the query changes; the file does not
  }
  const nav = document.getElementById("nav"); nav.innerHTML = "";
  if (at > 0) { const b = document.createElement("button"); b.setAttribute("aria-label", "Go back"); b.onclick = () => { at--; setTimeout(draw, 80); }; nav.appendChild(b); }
  if (at < N - 1) { const b = document.createElement("button"); b.setAttribute("aria-label", "Next"); b.onclick = () => { at++; setTimeout(draw, 80); }; nav.appendChild(b); }
}
draw();
</script></body></html>"""


def run(slides: int):
    script = (EXT / "instagram.js").read_text().strip().rstrip(";")
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        page = browser.new_page()
        page.route("https://ig.test/**", lambda route: route.fulfill(
            status=200, content_type="text/html" if route.request.url.endswith("/post") else "image/png",
            body=(PAGE % slides).encode() if route.request.url.endswith("/post") else PNG))
        page.goto("https://ig.test/post")
        page.wait_for_selector("#slides img")
        page.wait_for_timeout(200)
        result = page.evaluate(script)
        position = page.evaluate("at")
        browser.close()
    return result, position


def test_the_reader_collects_every_slide_in_order_and_leaves_the_post_on_its_first_slide():
    page, position = run(12)
    pictures = [b["src"].split("?")[0] for b in page["blocks"] if b["t"] == "img"]
    assert pictures == [f"https://ig.test/s{n}.jpg" for n in range(1, 13)]
    assert position == 0
    assert [b["text"] for b in page["blocks"] if b["t"] == "p"] == ["9 likes - tessexample: A fictional caption"]
    assert page["title"] == "Tess Example on Instagram" and page["site"] == "Instagram"


def test_the_reader_leaves_out_avatars_and_the_other_posts_grid():
    page, _ = run(4)
    sources = " ".join(b.get("src", "") for b in page["blocks"])
    assert "avatar" not in sources and "more" not in sources


def test_the_reader_stops_at_twenty_slides():
    page, _ = run(30)
    assert len([b for b in page["blocks"] if b["t"] == "img"]) == 20


def test_a_page_with_no_slide_list_reads_nothing_so_the_link_is_saved():
    script = (EXT / "instagram.js").read_text().strip().rstrip(";")
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        page = browser.new_page()
        page.set_content("<html><body><main><p>Nothing to see</p></main></body></html>")
        result = page.evaluate(script)
        browser.close()
    assert result["blocks"] == []
