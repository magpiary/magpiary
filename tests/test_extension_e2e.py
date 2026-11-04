"""The Chrome extension in a real Chromium, against a throwaway hub. Skipped unless Playwright and Chrome for Testing are present:
    uv run --with playwright pytest tests/test_extension_e2e.py
The extension copy used here has its port and site access patched for the test hub; the files under extension/ are untouched."""

import glob
import json
import os
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pytest

pw = pytest.importorskip("playwright.sync_api")
from test_setup import env  # noqa: E402,F401  (the throwaway hub fixture)

EXT = Path(__file__).resolve().parent.parent / "src" / "magpiary" / "extension"
CHROME = os.environ.get("MAGPIARY_CHROMIUM") or next(iter(sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))), "")
pytestmark = pytest.mark.skipif(not CHROME or not Path(CHROME).exists(), reason="Chrome for Testing is not installed")

# a feed shaped like Threads: three posts, one with a quoted post inside, and Instagram-style extras
PAGE = """<!doctype html><html><body style="margin:0;font:16px sans-serif">
<div id="a" style="height:150px;border:1px solid #ccc"><a href="https://www.threads.com/@ada/post/AAA111?xmt=zz&slof=1">1h</a> first post
  <a href="https://www.threads.com/@ada/post/AAA111/media?igsh=q">media</a><p>words words</p></div>
<div id="b" style="height:150px;border:1px solid #ccc"><a href="https://www.threads.com/@bo/post/BBB222?xmt=yy">2h</a> second post<p>more words</p></div>
<div id="c" style="height:200px;border:1px solid #ccc"><a href="https://www.threads.com/@cy/post/CCC333">3h</a> third post with a quote
  <div id="q" style="margin:30px;height:80px;border:1px solid #999"><a href="https://www.threads.com/@dee/post/DDD444">quoted</a> quoted text</div></div>
<div id="d" style="height:100px;border:1px solid #ccc"><a href="https://www.instagram.com/reel/audio/99/">audio page</a> not a post</div>
</body></html>"""


def only_test_hub(ext, port):
    """The copy talks to the throwaway hub only, never to a real Magpiary on 8765 and up."""
    bg = (ext / "background.js").read_text()
    assert "const PORTS = Array.from" in bg
    (ext / "background.js").write_text(re.sub(r"const PORTS = Array\.from\([^;]+;", f"const PORTS = [{port}];", bg))


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def browser(tmp_path, env):  # noqa: F811
    ext = tmp_path / "ext"
    shutil.copytree(EXT, ext)
    manifest = json.loads((ext / "manifest.json").read_text())
    manifest["host_permissions"] = [f"http://127.0.0.1:{env.mac.port}/*", "http://127.0.0.1/*"]  # the test hub, and the test page
    (ext / "manifest.json").write_text(json.dumps(manifest))
    only_test_hub(ext, env.mac.port)
    site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    with pw.sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path / "profile"), executable_path=CHROME, headless=False,
            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--headless=new"])
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        yield ctx, sw, site.server_port, env
        ctx.close()
    site.shutdown()


def pair(ctx, sw, env):
    status, headers, _ = env.post("/hub/browsers/add", name="Chrome", next="/settings/phones")
    code = unquote(re.search(r"chromecode=([^&]+)", headers["Location"]).group(1))
    popup = ctx.new_page()
    popup.goto(f"chrome-extension://{sw.url.split('/')[2]}/popup.html")
    popup.wait_for_selector("#pair:not([hidden])")
    popup.fill("#code", code)
    popup.click("#pairgo")
    popup.wait_for_selector("#welcome:not([hidden])")   # "Chrome is paired" stays until Got it
    popup.evaluate("chrome.storage.local.remove('welcomePending')")
    popup.reload()
    popup.wait_for_selector("#save:not([hidden])")
    return popup


def test_pair_then_save_cleaned_link_then_revoked_keeps_the_outbox(browser):
    ctx, sw, _, env = browser
    pair(ctx, sw, env)
    r = sw.evaluate("save({url: 'https://www.instagram.com/reel/AAAA111/?igsh=abc&utm_source=x', note: 'for the logo brief'})")
    assert r["state"] == "ok"
    assert env.mac.counts() == {"https://www.instagram.com/reel/AAAA111/": 1}
    stamped = env.mac.store.items()[0]["last_shared_at"][:10]
    assert stamped == sw.evaluate("localStamp().slice(0, 10)")   # the owner's local date, so it lands under Today
    assert sw.evaluate("save({url: 'https://www.instagram.com/reel/AAAA111/'})")["savedCount"] == 2
    assert sw.evaluate("save({url: 'https://www.instagram.com/someone/'})")["state"] == "unsupported"
    env.post("/hub/phones/remove", name="Chrome")
    gone = sw.evaluate("save({url: 'https://example.com/a?utm_source=z'})")
    assert gone["state"] == "revoked" and gone["waiting"] == 1   # kept for later, never lost


def test_pick_mode_chooses_the_post_under_the_pointer_and_saves_it_cleaned(browser):
    ctx, sw, port, env = browser
    pair(ctx, sw, env)
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:{port}/")
    page.bring_to_front()
    tab_id = sw.evaluate("chrome.tabs.query({url: 'http://127.0.0.1/*'}).then(t => t[0].id)")
    sw.evaluate(f"chrome.scripting.executeScript({{target: {{tabId: {tab_id}}}, files: ['clean.js', 'pick.js']}})")
    page.wait_for_function("document.documentElement.lastElementChild.tagName.toLowerCase().startsWith('magpiary-')")
    box = page.locator("#b").bounding_box()
    page.mouse.move(box["x"] + 200, box["y"] + 100)
    page.wait_for_timeout(300)   # the highlight follows the pointer
    page.mouse.click(box["x"] + 200, box["y"] + 100)
    page.keyboard.press("Enter")      # the panel opens with Save focused and the note folded away
    for _ in range(50):
        if env.mac.counts():
            break
        page.wait_for_timeout(100)
    assert env.mac.counts() == {"https://www.threads.com/@bo/post/BBB222/": 1}   # post B, tracking gone
    page.wait_for_function("!document.documentElement.lastElementChild.tagName.toLowerCase().startsWith('magpiary-')")  # pick mode ended


def start_pick(ctx, sw, port):
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:{port}/")
    tab_id = sw.evaluate("chrome.tabs.query({url: 'http://127.0.0.1/*'}).then(t => t[0].id)")
    sw.evaluate(f"chrome.scripting.executeScript({{target: {{tabId: {tab_id}}}, files: ['clean.js', 'pick.js']}})")
    page.wait_for_function("document.documentElement.lastElementChild.tagName.toLowerCase().startsWith('magpiary-')")
    return page


def pick_and_save(page, selector, dx, dy, tabs=0):
    box = page.locator(selector).bounding_box()
    page.mouse.move(box["x"] + dx, box["y"] + dy)
    page.wait_for_timeout(300)
    page.mouse.click(box["x"] + dx, box["y"] + dy)
    for _ in range(tabs):
        page.keyboard.press("Tab")
    page.keyboard.press("Enter")


def test_pick_mode_ignores_audio_pages_and_handles_a_quoted_post(browser):
    ctx, sw, port, env = browser
    pair(ctx, sw, env)
    page = start_pick(ctx, sw, port)
    pick_and_save(page, "#d", 100, 50)                    # an audio page: not a post, nothing opens
    page.wait_for_timeout(300)
    assert env.mac.counts() == {}
    # the pick-mode overlay is closed: the page itself cannot see inside it
    assert page.evaluate("document.documentElement.lastElementChild.shadowRoot") is None
    # on a post that quotes another, the outer part offers both (first is the outer post); inside the quote it is the quote
    pick_and_save(page, "#q", 20, 40)
    for _ in range(50):
        if env.mac.counts():
            break
        page.wait_for_timeout(100)
    assert env.mac.counts() == {"https://www.threads.com/@dee/post/DDD444/": 1}


def test_pick_mode_board_picker_is_ours_and_works_by_keyboard(browser):
    from magpiary import boards

    ctx, sw, port, env = browser
    board_id = boards.create(env.mac.store, "Logo ideas")
    pair(ctx, sw, env)
    page = start_pick(ctx, sw, port)
    box = page.locator("#a").bounding_box()
    page.mouse.move(box["x"] + 200, box["y"] + 100)
    page.wait_for_timeout(300)
    page.mouse.click(box["x"] + 200, box["y"] + 100)
    page.wait_for_timeout(500)            # the board list arrives from the hub
    for _ in range(3):
        page.keyboard.press("Shift+Tab")  # Save → Cancel → Add note → the board button
    page.keyboard.press("Enter")          # opens our list, focus on "Just my library"
    page.keyboard.press("ArrowDown")      # "Logo ideas"
    page.keyboard.press("Enter")
    for _ in range(3):
        page.keyboard.press("Tab")        # Add note → Cancel → Save
    page.keyboard.press("Enter")
    for _ in range(50):
        if env.mac.counts():
            break
        page.wait_for_timeout(100)
    rows = env.mac.store._db.execute("SELECT board_id, canonical_url FROM board_pending").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(board_id, "https://www.threads.com/@ada/post/AAA111/")]


def popup_for(ctx, sw, tab_url):
    """The toolbar panel as if `tab_url` were the page in front (the test cannot put the panel over a real tab)."""
    popup = ctx.new_page()
    popup.add_init_script("chrome.tabs.query = async () => [{id: 1, url: %s}];" % json.dumps(tab_url))
    popup.goto(f"chrome-extension://{sw.url.split('/')[2]}/popup.html")
    popup.wait_for_selector("#save:not([hidden])")
    return popup


def test_panel_says_a_page_is_already_saved_and_offers_save_again(browser):
    ctx, sw, port, env = browser
    pair(ctx, sw, env)
    fresh = popup_for(ctx, sw, "https://www.threads.com/@ada/post/AAA111?xmt=zz")
    fresh.wait_for_timeout(600)
    assert not fresh.locator("#seen").is_visible()
    assert "Save again" not in fresh.locator("#savego").inner_text()
    assert sw.evaluate("save({url: 'https://www.threads.com/@ada/post/AAA111/'})")["state"] == "ok"
    saved = popup_for(ctx, sw, "https://www.threads.com/@ada/post/AAA111?xmt=zz")
    saved.wait_for_selector("#seen:not([hidden])")
    assert "Saved just now" in saved.locator("#seentitle").inner_text()
    assert "Save again" in saved.locator("#savego").inner_text()
    assert "/item/" in saved.locator("#seenopen").get_attribute("href")


def test_panel_suggests_the_board_you_just_used_and_one_click_chooses_it(browser):
    from magpiary import boards

    ctx, sw, port, env = browser
    logo = boards.create(env.mac.store, "Logo ideas")
    pair(ctx, sw, env)
    quiet = popup_for(ctx, sw, "https://www.threads.com/@ada/post/ZZZ999")
    quiet.wait_for_timeout(600)
    assert not quiet.locator("#suggest").is_visible()          # nothing saved to a board yet: no guess
    assert sw.evaluate(f"save({{url: 'https://www.threads.com/@bo/post/BBB222/', board: '{logo}'}})")["state"] == "ok"
    popup = popup_for(ctx, sw, "https://www.threads.com/@ada/post/ZZZ999")
    popup.wait_for_selector("#suggest:not([hidden])")
    assert popup.locator("#sugname").inner_text() == "Logo ideas" and "just now" in popup.locator("#sugwhy").inner_text()
    popup.click("#sugbtn")
    assert popup.locator("#picklabel").inner_text() == "Logo ideas" and popup.locator("#board").input_value() == logo
    assert not popup.locator("#suggest").is_visible()


def test_pick_mode_panel_says_already_saved(browser):
    ctx, sw, port, env = browser
    pair(ctx, sw, env)
    assert sw.evaluate("save({url: 'https://www.threads.com/@bo/post/BBB222/'})")["state"] == "ok"
    page = start_pick(ctx, sw, port)
    box = page.locator("#b").bounding_box()
    page.mouse.move(box["x"] + 200, box["y"] + 100)
    page.wait_for_timeout(500)
    page.mouse.click(box["x"] + 200, box["y"] + 100)
    page.wait_for_timeout(700)
    cdp = ctx.new_cdp_session(page)    # the closed overlay is not in the page's DOM, but it is in what a screen reader sees
    names = " | ".join(str((n.get("name") or {}).get("value", "")) for n in cdp.send("Accessibility.getFullAXTree")["nodes"])
    assert "Already saved just now" in names and "Save again" in names


# ---- "Save what I see": a made-up article at a made-up address, mapped to a local server
ARTICLE = """<!doctype html><html lang="en"><head><title>Paper gardens | Writers Example</title>
<meta property="og:site_name" content="Writers Example"><meta name="author" content="Robin Example">
<meta property="article:published_time" content="2026-10-02T09:00:00Z"></head>
<body style="margin:0;font:16px sans-serif">
<header><nav><a href="/">Home</a> <a href="/me">Signed in as Reader Person</a></nav></header>
<main><article>
  <h1>A quiet guide to paper gardens</h1>
  <p>Fold the stems first, then the petals, and keep the creases sharp so the flower stands on its own.</p>
  <h2>Tools</h2><ul><li>Bone folder</li><li>Thin paper</li></ul>
  <figure><img src="/tulip-small.png" srcset="/tulip-small.png 200w, /tulip.png 800w" width="400" height="300" alt="A folded tulip">
  <figcaption>The first fold</figcaption></figure>
  <p>Glue nothing. A good fold holds better than glue ever will, and it can be opened again later.</p>
  <img src="/avatar.png" width="32" height="32" alt="author photo">
  <button>Follow</button>
</article>
<aside class="recommended">Recommended for Reader Person: ten more gardens</aside></main>
<footer>Writers Example footer</footer>
</body></html>"""
PIXEL = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                      "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e5273de30000000049454e44ae426082")


class Writers(BaseHTTPRequestHandler):
    def do_GET(self):
        png = self.path.endswith(".png")
        self.send_response(200)
        self.send_header("Content-Type", "image/png" if png else "text/html")
        self.end_headers()
        self.wfile.write(PIXEL if png else ARTICLE.encode())

    def log_message(self, *args):
        pass


def test_save_what_i_see_sends_the_article_screenshot_and_page_copy(tmp_path, env):  # noqa: F811
    from magpiary import capture

    ext = tmp_path / "ext"
    shutil.copytree(EXT, ext)
    manifest = json.loads((ext / "manifest.json").read_text())
    manifest["host_permissions"] = ["<all_urls>"]   # the test stands in for the owner's click (activeTab) with plain access
    (ext / "manifest.json").write_text(json.dumps(manifest))
    only_test_hub(ext, env.mac.port)
    site = ThreadingHTTPServer(("127.0.0.1", 0), Writers)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(tmp_path / "profile"), executable_path=CHROME, headless=False,
                args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--headless=new",
                      f"--host-resolver-rules=MAP writers.example.org 127.0.0.1:{site.server_port}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            pair(ctx, sw, env)
            page = ctx.new_page()
            page.goto("http://writers.example.org/paper-gardens?utm_source=feed")
            page.bring_to_front()
            page.wait_for_function("document.images[0].complete")
            tab_id = sw.evaluate("chrome.tabs.query({url: 'http://writers.example.org/*'}).then(t => t[0].id)")
            r = sw.evaluate(f"saveSeen({{tabId: {tab_id}, url: 'http://writers.example.org/paper-gardens?utm_source=feed', note: 'for the craft board'}})")
            assert r["state"] == "ok" and not r["linkOnly"]
            assert sw.evaluate("captures('readonly', (s) => s.count())") == 0   # acknowledged, so cleared
            ctx.close()
    finally:
        site.shutdown()
    url = "http://writers.example.org/paper-gardens"
    assert env.mac.counts() == {url: 1}
    got = capture.latest(url)
    page_json = got.page
    assert page_json["title"] == "A quiet guide to paper gardens" and page_json["byline"] == "Robin Example"
    words = json.dumps(page_json)
    assert "Reader Person" not in words and "footer" not in words and "Follow" not in words   # only the article
    assert [b["t"] for b in page_json["blocks"]] == ["p", "h", "li", "li", "img", "p"]
    assert page_json["blocks"][4]["src"] == "http://writers.example.org/tulip.png"   # the largest size offered
    assert page_json["blocks"][4]["caption"] == "The first fold"
    assert got.screen and got.screen.read_bytes()[:3] == b"\xff\xd8\xff"
    assert got.backup() == {"http://writers.example.org/tulip.png": PIXEL}   # the picture, from the browser's own copy
