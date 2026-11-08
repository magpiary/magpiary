"""'Save what I see': the Chrome extension sends the page as the owner saw it; the Mac archives the post from it.
Every page here is made up (example.org, example.net); nothing is fetched."""

import base64
import json
import re
from pathlib import Path

import pytest

from magpiary import capture
from magpiary.archive import fetch_item
from magpiary.store import Store
from magpiary.worker import fetch_due

JPEG = b"\xff\xd8\xff\xe0" + b"1" * 100
PNG = b"\x89PNG\r\n" + b"2" * 100
URL = "https://writers.example.org/a-quiet-guide-to-paper-gardens-0f3c"
PIC1, PIC2 = "https://img.example.net/paper-1.jpg", "https://img.example.net/paper-2.png"

PAGE = {
    "title": "A quiet guide to paper gardens",
    "byline": "Robin Example",
    "published": "2026-10-02T09:00:00Z",
    "site": "Writers Example",
    "blocks": [
        {"t": "p", "text": "Fold the stems first."},
        {"t": "h", "level": 2, "text": "Tools"},
        {"t": "li", "ordered": False, "text": "Bone folder"},
        {"t": "li", "ordered": False, "text": "<script>alert(1)</script>"},
        {"t": "img", "src": PIC1, "alt": "A folded tulip", "caption": "The first fold"},
        {"t": "img", "src": PIC2, "alt": ""},
        {"t": "secret", "text": "dropped"},
        {"t": "img", "src": "javascript:alert(1)"},
    ],
}


def mhtml_with(url: str, data: bytes) -> str:
    """A tiny browser copy of a page holding one picture, as Chrome's pageCapture writes it."""
    pic = base64.b64encode(data).decode()
    copy = ("From: <Saved by Blink>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; type=\"text/html\"; "
            "boundary=\"----B\"\r\n\r\n------B\r\nContent-Type: text/html\r\nContent-Location: " + URL + "\r\n\r\n<p>x</p>\r\n"
            "------B\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\nContent-Location: " + url + "\r\n\r\n"
            + pic + "\r\n------B--\r\n")
    return base64.b64encode(copy.encode()).decode()


def shot() -> str:
    return "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


def test_a_capture_is_private_from_the_first_byte_and_keeps_only_known_blocks(tmp_path):
    folder = capture.save(URL, "c-1", PAGE, shot(), mhtml_with(PIC2, PNG))
    assert folder.stat().st_mode & 0o777 == 0o700
    assert folder.parent.stat().st_mode & 0o777 == 0o700
    for name in ("page.json", "screen.jpg", "page.mhtml"):
        assert (folder / name).stat().st_mode & 0o777 == 0o600
    got = capture.latest(URL)
    kinds = [b["t"] for b in got.page["blocks"]]
    assert kinds == ["p", "h", "li", "li", "img", "img"]   # unknown kinds and non-web pictures are dropped
    assert got.pictures() == [PIC1, PIC2]
    assert "Fold the stems first." in got.text() and "- Bone folder" in got.text()
    assert capture.latest("https://writers.example.org/other") is None


@pytest.mark.parametrize("bad", [{"id": "../x"}, {"page": {"blocks": "no"}}, {"screen": "data:image/jpeg;base64,!!"},
                                 {"screen": "data:image/jpeg;base64," + base64.b64encode(b"GIF8").decode()}])
def test_a_capture_of_the_wrong_shape_is_refused(bad):
    args = {"id": "c-1", "page": PAGE, "screen": shot(), **bad}
    with pytest.raises(capture.BadCapture):
        capture.save(URL, args["id"], args["page"], args["screen"])


def test_the_post_is_archived_from_the_capture_with_a_backup_picture_and_a_reading_order(tmp_path):
    capture.save(URL, "c-1", PAGE, shot(), mhtml_with(PIC2, PNG))
    asked = []

    def get(url):
        asked.append(url)
        return (200, JPEG) if url == PIC1 else (403, b"")   # the second picture needs a login: the browser's copy has it
    folder = fetch_item({"canonical_url": URL, "source": "other", "kind": None}, tmp_path / "library", get,
                        capture=capture.latest(URL))
    assert URL not in asked                                   # the page itself is not read again
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["title"] == "A quiet guide to paper gardens" and meta["author"] == "Robin Example"
    assert meta["media"] == ["media-01.jpg", "media-02.png"] and meta["captured"] is True
    assert (folder / "media-02.png").read_bytes() == PNG
    assert (folder / "screen.jpg").read_bytes() == JPEG
    article = json.loads((folder / "article.json").read_text())
    assert [b.get("file") for b in article["blocks"] if b["t"] == "img"] == ["media-01.jpg", "media-02.png"]


def test_the_fetch_lane_uses_the_capture_once_and_clears_it(tmp_path):
    store = Store(tmp_path / "m.db")
    _, key = store.add_phone("Chrome", kind="browser")
    phone = store.phone_for_key(key)
    store.receive(phone, [{"id": "i1", "url": URL}])
    capture.save(URL, "c-1", PAGE, shot())
    calls = []

    def get(url):
        calls.append(url)
        return (200, JPEG) if url in (PIC1, PIC2) else (500, b"")
    assert fetch_due(store, tmp_path / "library", get, pause=lambda s: None) == 1
    assert URL not in calls
    assert capture.latest(URL) is None
    item = store.items()[0]
    assert item["status"] == "archived" and (Path(item["archive_dir"]) / "article.json").exists()
    store.close()


def test_a_newer_capture_that_arrives_during_a_fetch_is_read_next(tmp_path):
    store = Store(tmp_path / "m.db")
    _, key = store.add_phone("Chrome", kind="browser")
    store.receive(store.phone_for_key(key), [{"id": "i1", "url": URL}])
    capture.save(URL, "c-1", PAGE, shot())

    def get(url):
        if url == PIC1 and not capture.latest(URL).id == "c-2":
            capture.save(URL, "c-2", {**PAGE, "title": "Second look"}, shot())   # saved again while this fetch runs
        return 200, JPEG
    fetch_due(store, tmp_path / "library", get, pause=lambda s: None)
    assert capture.latest(URL).id == "c-2"
    assert store.items()[0]["status"] == "queued"            # archived again from the newer capture
    fetch_due(store, tmp_path / "library", lambda u: (200, JPEG), pause=lambda s: None)
    folder = Path(store.items()[0]["archive_dir"])
    assert json.loads((folder / "meta.json").read_text())["title"] == "Second look"
    assert capture.latest(URL) is None
    store.close()


# ---- the hub route ----------------------------------------------------------------------------------------------

def body(**extra):
    return json.dumps({"capture": "c-1", "item": {"id": "i1", "url": URL + "?utm_source=x", "shared_at": "2026-11-04T10:00:00+05:30"},
                       "page": PAGE, "screen": shot(), **extra})


def test_the_extension_sends_a_capture_and_the_link_is_saved_with_it(mac):
    _, key = mac.store.add_phone("Chrome", kind="browser")
    status, reply = mac.raw_post(key, body(), "/v1/capture")
    assert status == 200 and reply["capture"] == "c-1" and reply["accepted"] == ["i1"]
    assert mac.counts() == {URL: 1}                           # cleaned like any save
    assert capture.latest(URL).id == "c-1"
    status, reply = mac.raw_post(key, body(), "/v1/capture")   # the reply was lost and it is sent again
    assert status == 200 and reply["capture"] == "c-1" and mac.counts() == {URL: 1}


def test_a_capture_sent_again_after_the_mac_used_it_changes_nothing(mac):
    """The reply was lost after the Mac had already archived from the capture: the retry is acknowledged, and the post
    is not read or summarised again (review, 5 Nov 2026)."""
    _, key = mac.store.add_phone("Chrome", kind="browser")
    assert mac.raw_post(key, body(), "/v1/capture")[0] == 200
    capture.done(capture.latest(URL))                          # the fetch lane used it
    mac.store.fetch_succeeded(URL, "/nowhere")
    status, reply = mac.raw_post(key, body(), "/v1/capture")   # the extension never heard back, so it sends again
    assert status == 200 and reply["capture"] == "c-1"
    assert capture.latest(URL) is None and mac.store.items()[0]["status"] == "archived" and mac.counts() == {URL: 1}


def test_only_the_paired_browser_sends_captures(mac):
    _, phone_key = mac.store.add_phone("Phone")
    assert mac.raw_post(phone_key, body(), "/v1/capture")[0] == 403
    assert mac.raw_post("nope", body(), "/v1/capture")[0] == 401
    _, key = mac.store.add_phone("Chrome", kind="browser")
    assert mac.raw_post(key, body(capture="../../x"), "/v1/capture")[0] == 400
    assert mac.raw_post(key, "{", "/v1/capture")[0] == 400
    assert mac.counts() == {} and capture.latest(URL) is None


def test_capturing_a_saved_post_again_archives_it_again(mac):
    _, key = mac.store.add_phone("Chrome", kind="browser")
    mac.raw_post(key, json.dumps({"items": [{"id": "i0", "url": URL}]}))
    mac.store.fetch_succeeded(URL, "/nowhere")
    assert mac.store.items()[0]["status"] == "archived"
    status, reply = mac.raw_post(key, body(), "/v1/capture")
    assert status == 200 and mac.counts() == {URL: 2}
    assert mac.store.items()[0]["status"] == "queued"


# ---- the extension -----------------------------------------------------------------------------------------------

def test_the_extension_names_no_site_beyond_the_pick_mode_ones():
    folder = Path(__file__).parents[1] / "src" / "magpiary" / "extension"
    text = " ".join(p.read_text() for p in folder.glob("*.js")) + (folder / "popup.html").read_text() + (folder / "manifest.json").read_text()
    assert not re.search(r"(?i)medium\.com|behance|substack|paywall|bypass", text)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["host_permissions"] == ["http://127.0.0.1/*"]   # no new site access for captures
    assert "pageCapture" in manifest["permissions"] and "cookies" not in manifest["permissions"]


# ---- the post page ------------------------------------------------------------------------------------------------

def test_a_captured_page_opens_on_its_reader_view_with_everything_escaped(mac, tmp_path):
    from test_hub import archive, page, request

    article = {**PAGE, "blocks": [{**b, "file": "media-01.jpg"} if b["t"] == "img" and b["src"] == PIC1 else b
                                  for b in capture.clean_page(PAGE)["blocks"] if b["t"] != "img" or b["src"] == PIC1]}
    item_id, _ = archive(mac, tmp_path, URL, "other", {"title": PAGE["title"], "text": "Fold the stems first.", "media": ["media-01.jpg"]},
                         {"media-01.jpg": JPEG, "screen.jpg": JPEG, "article.json": json.dumps(article).encode()})
    status, _, html = page(mac, f"/item/{item_id}")
    assert status == 200
    assert 'data-tab="read" class="on"' in html                # opens on Read
    assert "<h2 class=\"rdtitle\">A quiet guide to paper gardens</h2>" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html
    assert f'/media/{item_id}/media-01.jpg' in html and "The first fold" in html
    assert f'/media/{item_id}/screen.jpg' in html and "What I saw" in html
    assert request(mac, "GET", f"/media/{item_id}/screen.jpg")[0] == 200
    assert request(mac, "GET", f"/media/{item_id}/article.json")[0] == 404   # only pictures and videos are served


def test_an_instagram_item_has_no_read_tab_even_if_an_older_save_left_a_reader_view(mac, tmp_path):
    from test_hub import archive, page

    ig = "https://www.instagram.com/p/Carousel8/"
    article = {"title": "t", "blocks": [{"t": "img", "src": PIC1, "file": "media-01.jpg"}, {"t": "p", "text": "9 likes"}]}
    item_id, _ = archive(mac, tmp_path, ig, "instagram", {"title": "t", "media": ["media-01.jpg"]},
                         {"media-01.jpg": JPEG, "article.json": json.dumps(article).encode()})
    status, _, html = page(mac, f"/item/{item_id}")
    assert status == 200 and 'data-tab="read"' not in html and 'class="reader"' not in html


def captured_post(mac, tmp_path):
    from test_hub import archive

    article = {**PAGE, "blocks": [{**b, "file": "media-01.jpg"} if b["t"] == "img" and b["src"] == PIC1 else b
                                  for b in capture.clean_page(PAGE)["blocks"] if b["t"] != "img" or b["src"] == PIC1]}
    return archive(mac, tmp_path, URL, "other", {"title": PAGE["title"], "media": ["media-01.jpg"]},
                   {"media-01.jpg": JPEG, "article.json": json.dumps(article).encode()})


def test_download_pdf_is_made_on_the_mac_and_falls_back_to_a_print_page(mac, tmp_path, monkeypatch):
    from magpiary import hub_card, reader
    from test_hub import page, post, request

    item_id, _ = captured_post(mac, tmp_path)
    assert f'href="/item/{item_id}/pdf" data-pdf download' in page(mac, f"/item/{item_id}")[2]
    made = []
    monkeypatch.setattr(reader, "make_pdf", lambda html: made.append(html) or b"%PDF-1.7 made")
    status, headers, data = request(mac, "GET", f"/item/{item_id}/pdf")      # a GET never starts a browser: any site can ask for one
    assert status == 200 and made == [] and "Save as PDF" in data.decode() and "default-src 'none'" in headers["Content-Security-Policy"]
    status, headers, data = post(mac, "/hub/pdf", id=str(item_id))
    assert status == 200 and data == b"%PDF-1.7 made" and headers["Content-Type"] == "application/pdf"
    assert headers["Content-Disposition"] == 'attachment; filename="A-quiet-guide-to-paper-gardens.pdf"'
    assert "data:image/jpeg;base64," in made[0] and "/media/" not in made[0]   # every picture inside: no network needed
    assert "&lt;script&gt;" in made[0] and "<script>" not in made[0]
    assert request(mac, "POST", "/hub/pdf", {"id": str(item_id)})[0] == 403  # without the page's token
    with hub_card.PDF_LOCK:                                                   # one drawing at a time
        assert post(mac, "/hub/pdf", id=str(item_id))[0] == 429
    monkeypatch.setattr(reader, "make_pdf", lambda html: None)                 # no browser on this Mac
    assert post(mac, "/hub/pdf", id=str(item_id))[0] == 503
    assert request(mac, "GET", "/item/999/pdf")[0] == 404 and post(mac, "/hub/pdf", id="999")[0] == 404


def test_a_real_pdf_is_drawn_offline_when_a_browser_is_installed(tmp_path):
    from magpiary import reader, sources

    if not any(Path(b).exists() for b in sources.BROWSERS):
        pytest.skip("no Chrome, Chromium, Edge or Brave on this Mac")
    folder = tmp_path / "post"
    folder.mkdir()
    (folder / "media-01.png").write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e5273de30000000049454e44ae426082"))
    article = {"title": "Paper gardens", "blocks": [{"t": "p", "text": "Fold the stems first."},
                                                    {"t": "img", "src": PIC1, "file": "media-01.png"}]}
    html = reader.print_html(article, folder, URL).replace("</body>", '<img src="https://img.example.net/x.png"></body>')
    data = reader.make_pdf(html)   # the stray web picture is refused by the shut network, the PDF is still made
    assert data and data.startswith(b"%PDF")


def test_posts_from_other_sites_show_that_sites_name_and_icon(mac, tmp_path, monkeypatch):
    from magpiary import icons, ui
    from magpiary.worker import icons_due

    assert ui.site_name("https://www.behance.net/gallery/123/Paper-Gardens") == "Behance"
    assert ui.site_name("https://someone.medium.com/a-quiet-guide-0f3c") == "Medium"
    assert ui.site_name("https://news.bbc.co.uk/x") == "BBC"
    assert ui.site_name("https://blog.example.org/post") == "example.org"
    assert ui.source_label({"source": "other", "canonical_url": "https://www.behance.net/gallery/1/x"}) == "Behance"
    assert ui.source_label({"source": "instagram", "canonical_url": "https://www.instagram.com/p/x/"}) == "Instagram"
    assert "Behance" in ui.source_badge("other", "https://www.behance.net/gallery/1/x") and "<svg" in ui.source_badge("other", "https://www.behance.net/g")
    asked = []
    mac.store.add_link("https://www.behance.net/gallery/1/x")
    icons_due(mac.store, get=lambda url, headers, limit: asked.append(url) or (200, url, PNG))
    assert asked[0] == "https://behance.net/favicon.ico"     # the site a post came from gets its icon, fetched once
    badge = ui.source_badge("other", "https://www.behance.net/gallery/1/x")
    assert '<img class="siteico' in badge and 'src="/icon/behance.net"' in badge


def test_rows_and_pictures_side_by_side_are_kept_and_drawn_together(tmp_path):
    from magpiary import reader

    page = capture.clean_page({"blocks": [
        {"t": "row", "items": ["Paper", "Craft", "<b>Slow</b>", 7]},
        {"t": "img", "src": PIC1, "group": 3}, {"t": "img", "src": PIC2, "group": 3},
        {"t": "img", "src": "https://img.example.net/alone.jpg"}]})
    assert page["blocks"][0] == {"t": "row", "items": ["Paper", "Craft", "<b>Slow</b>"]}
    assert [b.get("group") for b in page["blocks"][1:]] == [3, 3, None]
    for name in ("media-01.jpg", "media-02.jpg", "media-03.jpg"):
        (tmp_path / name).write_bytes(JPEG)
    files = iter(["media-01.jpg", "media-02.jpg", "media-03.jpg"])
    article = {"blocks": [b if b["t"] == "row" else {**b, "file": next(files)} for b in page["blocks"]]}
    html = reader.blocks_html(article, tmp_path, lambda n: f"/m/{n}")
    assert '<p class="rdrow"><span>Paper</span><span>Craft</span><span>&lt;b&gt;Slow&lt;/b&gt;</span></p>' in html
    assert html.count('<div class="rdgal" style="--n:2">') == 1
    assert html.index("/m/media-02.jpg") < html.index("</div>") < html.index("/m/media-03.jpg")   # the lone picture sits below
    assert capture.Capture(tmp_path, page).text().startswith("Paper · Craft · <b>Slow</b>")


def test_a_page_reading_that_reached_the_last_slide_is_marked_complete_and_others_are_not(tmp_path):
    from magpiary.capture import Capture, clean_page

    page = {"title": "t", "blocks": [{"t": "img", "src": "https://cdn.example/a.jpg"}]}
    assert "slides_complete" not in clean_page(page)
    assert "slides_complete" not in clean_page({**page, "slides_complete": "yes"})  # only a real true counts
    kept = clean_page({**page, "slides_complete": True})
    assert kept["slides_complete"] is True
    assert Capture(tmp_path, kept).fetched().meta["slides_complete"] is True
    assert "slides_complete" not in Capture(tmp_path, clean_page(page)).fetched().meta


def test_an_instagram_capture_has_no_reader_view_so_no_picture_is_shown_twice(tmp_path):
    ig = "https://www.instagram.com/p/Carousel9/"
    page = {"title": "t", "blocks": [{"t": "img", "src": PIC1}, {"t": "img", "src": PIC2}, {"t": "p", "text": "9 likes"}]}
    capture.save(ig, "c-ig", page)
    folder = fetch_item({"canonical_url": ig, "source": "instagram", "kind": "post"}, tmp_path / "library",
                        lambda url: (200, JPEG), capture=capture.latest(ig))
    assert not (folder / "article.json").exists()
    assert json.loads((folder / "meta.json").read_text())["media"] == ["media-01.jpg", "media-02.jpg"]
