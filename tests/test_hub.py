"""The hub over HTTP, the way a browser on the Mac sees it."""

import http.client
import os
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest

from magpiary.hub import backfill_details, details_from_folder

IG = "https://www.instagram.com/reel/Example0020/"
YT = "https://www.youtube.com/watch?v=Example0005"


def request(mac, method, path, form=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", mac.port, timeout=10)
    h = {"Host": host or f"localhost:{mac.port}", **(headers or {})}
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), data


def page(mac, path="/"):
    status, headers, data = request(mac, "GET", path)
    if status == 303 and path.startswith("/board/") and headers["Location"].startswith("/board/"):
        return page(mac, headers["Location"])  # a board's id forwards to its address by name
    return status, headers, data.decode()


def post(mac, path, **form):
    return request(mac, "POST", path, {"csrf": mac.server.hub.csrf, **form})


def archive(mac, tmp_path, url, source, meta, files=None):
    """Store an item as if the worker had fetched it."""
    library = tmp_path / "library"
    mac.server.hub.library = library
    folder = library / f"{source}-{abs(hash(url)) % 10**6}"
    folder.mkdir(parents=True)
    for name, data in (files or {}).items():
        (folder / name).write_bytes(data)
    (folder / "meta.json").write_text(json.dumps({"url": url, "source": source, **meta}))
    if mac.store.get_item(url) is None:
        mac.store.add_link(url)
    mac.store.fetch_succeeded(url, str(folder))
    mac.store.set_details(url, details_from_folder(folder))
    return mac.store.id_for(url), folder


@pytest.fixture
def lib(mac, tmp_path):
    ig_id, _ = archive(mac, tmp_path, IG, "instagram",
                       {"text": "Pasta carbonara recipe", "author": "Chef Alex Example", "author_handle": "chef.example",
                        "like_count": 1200, "repost_count": 5, "share_count": 34, "duration": 31.0, "media": ["media-01.mp4"], "thumbnail": "thumbnail.jpg"},
                       {"media-01.mp4": bytes(range(256)) * 40, "thumbnail.jpg": b"\xff\xd8\xff" + b"0" * 20})
    yt_id, _ = archive(mac, tmp_path, YT, "youtube", {"title": "Rust tutorial", "text": "Learn ownership", "author": "Dev"})
    return {"ig": ig_id, "yt": yt_id}


def test_the_library_shows_cards_with_thumbnail_author_caption_and_source(mac, lib):
    status, headers, body = page(mac)
    assert status == 200 and "Chef Alex Example" in body and "Pasta carbonara recipe" in body
    assert "Rust tutorial" in body and "Learn ownership" not in body  # a YouTube tile shows the video's title
    assert f'/media/{lib["ig"]}/thumbnail.jpg' in body and "Instagram" in body and "YouTube" in body
    assert "script-src 'nonce-" in headers["Content-Security-Policy"]


def test_search_finds_words_in_captions_authors_tags_and_notes(mac, lib):
    assert "Chef Alex Example" in page(mac, "/?q=carbon")[2]           # prefix of a caption word
    assert "Chef Alex Example" not in page(mac, "/?q=ownership")[2]
    post(mac, "/hub/tags", id=lib["yt"], tags="Learning, rust ,learning")
    post(mac, "/hub/note", id=lib["yt"], note="watch on the weekend")
    assert ">Dev<" in page(mac, "/?q=weekend")[2] and ">Dev<" in page(mac, "/?q=learning")[2]
    assert "Nothing matches" in page(mac, '/?q="))%20OR%20*')[2]  # odd input is harmless


def test_tags_are_tidied_and_become_filters(mac, lib):
    post(mac, "/hub/tags", id=lib["ig"], tags="Recipes,  Italian food, recipes,")
    assert mac.store.tags_for(IG) == ["italian food", "recipes"]
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert "#recipes" in body and "#italian food" in body
    filtered = page(mac, "/?tag=recipes")[2]
    assert "Chef Alex Example" in filtered and ">Dev<" not in filtered


def test_source_and_attention_filters(mac, lib):
    assert ">Dev<" in page(mac, "/?source=youtube")[2] and "Chef Alex Example" not in page(mac, "/?source=youtube")[2]
    bad = "https://www.instagram.com/reel/Private1/"
    mac.store.add_link(bad)
    mac.store.fetch_failed(bad, "private", "Private video", retry=False)
    body = page(mac, "/?attention=1")[2]
    assert "The post is private" in body and "Chef Alex Example" not in body


def test_the_item_page_plays_the_video_and_shows_the_details(mac, lib):
    status, _, body = page(mac, f"/item/{lib['ig']}")
    assert status == 200 and f'src="/media/{lib["ig"]}/media-01.mp4"' in body and "<video" in body
    assert 'title="1,200 likes, as of' in body and "<b>1.2K</b>" in body and "0:31" in body and "@chef.example" in body and "Open original" in body
    assert 'title="5 reposts, as of' in body and 'title="34 shares, as of' in body and "cn-repost" in body
    assert 'rel="noopener noreferrer"' in body


def test_a_text_post_shows_its_text(mac, lib):
    assert "Learn ownership" in page(mac, f"/item/{lib['yt']}")[2]


def test_media_is_streamed_with_ranges_so_safari_can_play_video(mac, lib):
    status, headers, data = request(mac, "GET", f"/media/{lib['ig']}/media-01.mp4")
    assert status == 200 and headers["Content-Type"] == "video/mp4" and len(data) == 10240
    status, headers, data = request(mac, "GET", f"/media/{lib['ig']}/media-01.mp4", headers={"Range": "bytes=0-1"})
    assert status == 206 and data == bytes([0, 1]) and headers["Content-Range"] == "bytes 0-1/10240"
    status, _, data = request(mac, "GET", f"/media/{lib['ig']}/media-01.mp4", headers={"Range": "bytes=-3"})
    assert status == 206 and data == bytes([253, 254, 255])
    assert request(mac, "GET", f"/media/{lib['ig']}/media-01.mp4", headers={"Range": "bytes=99999-"})[0] == 416


@pytest.mark.parametrize("name", ["meta.json", "..%2Fx", "media-01.mp4%2F..", "thumbnail.png"])
def test_only_media_files_are_served(mac, lib, name):
    assert request(mac, "GET", f"/media/{lib['ig']}/{name}")[0] == 404


def test_archive_moves_an_item_out_of_the_library_and_back(mac, lib):
    post(mac, "/hub/shelf", id=lib["ig"], shelf="archive", next=f"/item/{lib['ig']}")
    assert "Chef Alex Example" not in page(mac)[2] and "Chef Alex Example" in page(mac, "/?shelf=archive")[2]
    assert "Chef Alex Example" in page(mac, "/?shelf=archive&q=pasta")[2]   # still searchable in its view
    post(mac, "/hub/shelf", id=lib["ig"], shelf="inbox")
    assert "Chef Alex Example" in page(mac)[2]


def test_remove_goes_to_the_trash_with_undo_and_is_deleted_after_30_days(mac, lib, tmp_path):
    folder = mac.store.get_item(IG)["archive_dir"]
    status, headers, _ = post(mac, "/hub/shelf", id=lib["ig"], shelf="trash", next="/")
    assert status == 303 and "Chef Alex Example" not in page(mac)[2]
    assert "deleted for good" in page(mac, "/?shelf=trash")[2]
    post(mac, "/hub/shelf", id=lib["ig"], shelf="inbox")              # undo
    assert "Chef Alex Example" in page(mac)[2]
    post(mac, "/hub/shelf", id=lib["ig"], shelf="trash")
    assert mac.server.hub.purge_old_trash() == 0                     # not yet
    mac.clock.advance(31 * 86400)
    assert mac.server.hub.purge_old_trash() == 1
    assert mac.store.get_item(IG) is None and not os.path.exists(folder)


def test_empty_trash_now_and_resharing_brings_an_item_back(mac, lib):
    post(mac, "/hub/shelf", id=lib["yt"], shelf="trash")
    mac.store.add_link(YT)  # shared again
    assert mac.store.get_item(YT)["shelf"] == "inbox"
    post(mac, "/hub/shelf", id=lib["yt"], shelf="trash")
    post(mac, "/hub/empty-trash", next="/?shelf=trash")
    assert mac.store.get_item(YT) is None


def test_adding_a_link_cleans_it_queues_it_and_opens_its_page(mac, lib):
    woken = []
    mac.server.hub.wake = lambda: woken.append(1)
    status, headers, _ = post(mac, "/hub/add", url="https://www.instagram.com/reel/New1/?igsh=tracking")
    item = mac.store.get_item("https://www.instagram.com/reel/New1/")
    assert status == 303 and headers["Location"] == f"/item/{mac.store.id_for(item['canonical_url'])}"
    assert item["status"] == "queued" and woken == [1]
    assert "Being fetched" in page(mac, headers["Location"])[2]
    status, headers, _ = post(mac, "/hub/add", url="not a link")
    assert headers["Location"] == "/?error=unsupported" and "does not look like a link" in page(mac, "/?error=unsupported")[2]


def test_retry_from_the_item_page(mac, lib):
    bad = "https://www.instagram.com/reel/Private1/"
    mac.store.add_link(bad)
    mac.store.fetch_failed(bad, "private", "Private video", retry=False)
    bad_id = mac.store.id_for(bad)
    assert "Retry now" in page(mac, f"/item/{bad_id}")[2]
    post(mac, "/hub/retry", id=bad_id)
    assert mac.store.get_item(bad)["status"] == "queued"


def test_everything_from_websites_is_escaped(mac, tmp_path):
    evil = "https://www.instagram.com/reel/Evil1/"
    item_id, _ = archive(mac, tmp_path, evil, "instagram", {"text": "<script>alert(1)</script>", "author": "<b>x</b>"})
    for path in ("/", f"/item/{item_id}"):
        body = page(mac, path)[2]
        assert "<script>alert(1)" not in body and "&lt;script&gt;alert(1)" in body and "<b>x</b>" not in body


def test_hub_forms_need_the_secret_field_and_this_mac(mac, lib):
    assert request(mac, "POST", "/hub/shelf", {"id": lib["ig"], "shelf": "trash"})[0] == 403
    assert request(mac, "POST", "/hub/shelf", {"csrf": mac.server.hub.csrf, "id": lib["ig"], "shelf": "trash"},
                   headers={"Origin": "https://evil.example"})[0] == 403
    assert request(mac, "GET", "/", host="evil.example")[0] == 403
    assert request(mac, "GET", f"/media/{lib['ig']}/media-01.mp4", host="evil.example")[0] == 403
    assert mac.store.get_item(IG)["shelf"] == "inbox"


def test_items_archived_before_the_hub_get_their_details(mac, tmp_path):
    url = "https://x.com/a/status/9"
    folder = tmp_path / "library" / "x-9"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"text": "old post", "author": "A", "media": []}))
    mac.store.add_link(url)
    mac.store.fetch_succeeded(url, str(folder))
    assert backfill_details(mac.store) == 1 and mac.store.get_item(url)["caption"] == "old post"
    assert backfill_details(mac.store) == 0


# ---- M3 pages -------------------------------------------------------------------------------

MODELS = {"models": [{"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]}]}


def test_settings_lists_providers_with_guides_and_saves_a_checked_key(mac):
    body = page(mac, "/settings/ai")[2]
    assert "Google Gemini" in body and "OpenRouter (many models, some free)" in body and "Anthropic Claude" in body
    assert "coming soon" not in body and "nvidia/nemotron-3.5-super-vl:free" in body  # suggested models
    assert "https://aistudio.google.com/apikey" in body and "Create API key" in body and "No key yet" in body
    mac.server.hub.call = lambda method, url, key, body, timeout=None: (200, MODELS) if method == "GET" else (200, {})
    status, headers, _ = post(mac, "/hub/keys/add", provider="gemini", tier="free", key="not-a-real-key-123", label="Mine")
    assert headers["Location"] == "/settings/ai?saved=key"
    body = page(mac, "/settings/ai")[2]
    assert "Mine" in body and "gemini-3-flash" in body and "Working" in body and "not-a-real-key-123" not in body
    status, headers, _ = post(mac, "/hub/keys/add", provider="nonsense", tier="paid", key="sk-1")
    assert "Pick%20a%20provider" in headers["Location"]


def test_appearance_is_saved_and_applied_to_every_page(mac):
    post(mac, "/hub/ui", size="l", theme="dark", layout="full", box="9999", next="/settings/appearance")
    assert mac.store.get_setting("ui_size") == "l" and mac.store.get_setting("ui_box") == "2400"
    body = page(mac, "/settings/appearance")[2]
    assert 'data-size="l"' in body and 'data-theme="dark"' in body and 'data-layout="full"' in body
    assert 'name="width" type="range"' not in body and all(f'name="width" value="{w}"' in body for w in (1600, 1920, 2200, 2400, "full"))
    post(mac, "/hub/ui", box="2200")
    assert 'style="--box:2200px;--gs:0.3"' in page(mac)[2]
    post(mac, "/hub/ui", width="1920")  # one Page width control: a width means boxed
    assert 'data-layout="boxed"' in page(mac)[2] and 'style="--box:1920px;--gs:0.3"' in page(mac)[2]
    post(mac, "/hub/ui", width="full")
    assert 'data-layout="full"' in page(mac)[2] and mac.store.get_setting("ui_box") == "1920"
    post(mac, "/hub/ui", width="1234")  # only the offered widths
    assert mac.store.get_setting("ui_box") == "1920"
    post(mac, "/hub/ui", size="huge", theme="neon")  # unknown values change nothing
    assert mac.store.get_setting("ui_size") == "l" and mac.store.get_setting("ui_theme") == "dark"
    post(mac, "/hub/ui", theme="light")  # Follow the Mac and Light are gone: only Indigo and Dark are offered
    assert mac.store.get_setting("ui_theme") == "dark"
    body = page(mac, "/settings/appearance")[2]
    assert "Follow the Mac" not in body and 'name="theme" value="light"' not in body and 'name="theme" value="indigo"' in body


def test_piles_look_is_an_appearance_choice_and_search_is_always_the_spotlight(mac, lib):
    body = page(mac)[2]
    assert 'data-piles="stack"' in body and 'data-search="spot"' in body and "Try designs" not in body
    assert 'id="sizes"' not in body.split('id="view"')[0]  # tile size left the top bar for the wall toolbar
    assert 'id="sizes"' in body and "Tile size" in body
    post(mac, "/hub/ui", piles="folder", next="/settings/appearance")
    body = page(mac, "/settings/appearance")[2]
    assert 'data-piles="folder"' in body and 'data-search="spot"' in body and "Grows in place" not in body
    post(mac, "/hub/ui", piles="collage", search="grow")  # the looks that were dropped change nothing
    assert mac.store.get_setting("ui_piles") == "folder" and mac.store.get_setting("ui_search") == ""


def test_the_nest_drops_down_short_and_its_page_has_four_tabs(mac, lib):
    for n in range(12):
        mac.store.add_link(f"https://www.instagram.com/reel/Wait{n}/")
    drop = page(mac, "/nest?frag=1")[2]
    waiting = sum(mac.store.waiting_items(limit=100).values(), [])
    assert drop.count('class="nrow') == 3 and f"and {len(waiting) - 3} more" in drop, drop[-900:]
    assert 'href="/nest?tab=stats"' in drop
    body = page(mac, "/nest")[2]
    assert all(f'href="/nest?tab={t}"' in body for t in ("now", "needs", "stats", "phones"))
    assert body.count('class="nrow') == len(waiting)
    assert "Nothing needs you" in page(mac, "/nest?tab=needs")[2]
    assert "Average per step" in page(mac, "/nest?tab=stats")[2] or "nothing to time" in page(mac, "/nest?tab=stats")[2]
    assert 'class="ntabs"' in page(mac, "/queue")[2]  # every delivery is the "From your phones" tab


def test_the_live_status_is_json_and_the_activity_page_lists_waiting_items(mac, lib):
    mac.store.add_link("https://www.instagram.com/reel/Wait1/")
    status, headers, data = request(mac, "GET", "/activity.json")
    snap = json.loads(data)
    assert status == 200 and snap["waiting"]["fetch"] == 1 and snap["busy"] is False
    assert request(mac, "GET", "/activity")[0] == 404  # old addresses were removed when M7a closed
    body = page(mac, "/nest")[2]
    assert "to be fetched" in body and "Instagram reel" in body and "Add an AI key in Settings" in body
    assert 'id="ticker"' in body and "1 waiting" in body  # the strip is on every page


def test_the_item_page_shows_the_summary_key_points_and_timing(mac, lib, tmp_path):
    item = mac.store.item_by_id(lib["ig"])
    folder = Path(item["archive_dir"])
    record = {"title": "Carbonara fast", "summary": "Eggs, cheese, pork.", "type": "recipe",
              "key_points": [{"text": "Use guanciale", "at": "0:05"}], "entities": {"products": ["Guanciale"]},
              "extras": {"ingredients": ["eggs"]}, "suggested_tags": ["pasta"], "discussion_summary": "",
              "engine": {"brain": "gemini:gemini-3-flash", "key": "Mine"}, "frames": []}
    (folder / "record.json").write_text(json.dumps(record))
    mac.store.record_timing(IG, "download", 0, 6.2)
    mac.store.record_timing(IG, "summary", 0, 8.0)
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert "Carbonara fast" in body and 'data-t="0:05"' in body and "<li>eggs</li>" in body and "Guanciale" in body
    assert "Suggested tags: #pasta" in body and "using Mine" in body
    assert "How long it took" in body and "6.2s" in body and "14s" in body and "as of" in body


def test_cards_show_their_step(mac, lib):
    mac.store.add_link("https://www.instagram.com/reel/Wait2/")
    assert "Received · waiting its turn" in page(mac)[2]
    assert "✦ Summarise" in page(mac)[2] and "Add a free key" in page(mac)[2]  # no key yet: a nudge, full colour


def test_pages_keep_the_origin_for_their_own_forms(mac):
    # With "no-referrer", browsers send `Origin: null` on form posts and every hub form was refused.
    assert page(mac, "/settings")[1]["Referrer-Policy"] == "same-origin"
    assert request(mac, "POST", "/hub/ui", {"csrf": mac.server.hub.csrf, "size": "s"},
                   headers={"Origin": f"http://localhost:{mac.port}"})[0] == 303


def test_pages_may_ask_for_live_progress(mac):
    # Without connect-src the browser blocked /activity.json: the strip and the Activity page never updated.
    assert "connect-src 'self'" in page(mac, "/nest")[1]["Content-Security-Policy"]


def test_activity_has_master_pause_and_resume(mac):
    assert "Transcribing" in page(mac, "/nest")[2] and "Running" in page(mac, "/nest")[2]
    post(mac, "/hub/control", part="summary", action="pause")
    assert mac.store.paused("summary") and "Paused" in page(mac, "/nest")[2]
    assert json.loads(request(mac, "GET", "/activity.json")[2])["paused_any"] is True
    mac.store.set_setting("ai_budget", "0")
    post(mac, "/hub/control", part="summary", action="resume")
    assert not mac.store.paused("summary") and mac.store.summary_budget() == "all"


def test_the_summary_comes_right_after_the_title_and_before_the_caption(mac, lib):
    item = mac.store.item_by_id(lib["ig"])
    folder = Path(item["archive_dir"])
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert 'class="it-lead' not in body and "capb" in body  # nothing made up when there is no summary
    (folder / "record.json").write_text(json.dumps({"title": "Carbonara fast", "summary": "Use guanciale, not bacon.",
                                                    "type": "recipe", "key_points": [], "entities": {}, "suggested_tags": []}))
    body = page(mac, f"/item/{lib['ig']}")[2]
    head = body.index('class="it-h"')
    # the caption card sits under the video, so it comes before the title in the page; the summary follows the counts
    assert body.index('class="vid"') < body.index('class="pvwho"') < body.index('class="cap2"') < body.index('class="pvwhere"') < head
    assert head < body.index('class="counts pvcounts"') < body.index('class="it-lead')
    assert body.count("Use guanciale, not bacon.</p>") == 1 and "Copy with source" in body


def test_private_mode_shows_its_state_under_the_title(mac, lib):
    mac.store.set_setting("ai_mode", "private")
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert body.index('class="it-h"') < body.index("<b>Private mode</b>") < body.index('class="tabs pvtabs"')
    assert 'class="it-lead' not in body


def test_the_settings_button_keeps_its_name_when_the_label_hides(mac):
    body = page(mac, "/")[2]
    assert re.search(r'<a class="ubtn setbtn[^"]*" href="/settings" id="t-set" aria-label="Settings"', body)


def test_a_transcript_shows_without_a_summary(mac, lib):
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "transcript.json").write_text(json.dumps({"segments": [{"start": 62, "end": 64, "text": "crispy guanciale"}]}))
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert "crispy guanciale" in body and 'data-t="1:02"' in body


def test_the_links_panel_lists_links_lets_the_owner_edit_and_filters_the_library(mac, lib):
    from magpiary.links import Found
    mac.store._db.execute("UPDATE items SET ai_status='done' WHERE canonical_url=?", (IG,))
    mac.store.save_found_links(IG, [Found("frontend-design", "skills_code", "https://github.com/anthropics/skills",
                                          "anthropics/skills", "official skill list", 6),
                                    Found("frontend-design", "skills_code", "https://skills.example", "", "the repository's "
                                          "homepage", 5, role="badge"),
                                    Found("Notes", "tools", "https://notes.example", "", "web search", 5, central=False,
                                          possible=True)])
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert "Skills and code" in body and "frontend-design" in body and "official skill list" in body
    assert "the repository&#x27;s homepage ↗" in body or "the repository's homepage ↗" in body  # a badge on the row
    assert "Show 1 more" in body and "possible match" in body
    assert "Find more links" in body and "Add a link" in body
    assert "Chef Alex Example" in page(mac, "/?links=1")[2] and ">Dev<" not in page(mac, "/?links=1")[2]
    post(mac, "/hub/links/add", id=lib["ig"], name="Recipe site", url="https://recipes.example", kind="links")
    assert "Recipe site" in page(mac, f"/item/{lib['ig']}")[2]


# ---- M7a: the C1+ hub ------------------------------------------------------------------------

def test_static_files_are_served_from_a_fixed_list_and_cached(mac):
    status, headers, data = request(mac, "GET", "/static/hub.css")
    assert status == 200 and headers["Content-Type"].startswith("text/css") and b"--t-design" in data
    assert "immutable" in headers["Cache-Control"]
    assert request(mac, "GET", "/static/fonts/dm-sans.woff2")[1]["Content-Type"] == "font/woff2"
    for bad in ("/static/../hub.py", "/static/fonts/OFL-dm-sans.txt", "/static/nope.js", "/static/%2e%2e/store.py"):
        assert request(mac, "GET", bad)[0] == 404
    body = page(mac)[2]
    assert '<link rel="stylesheet" href="/static/hub.css?v=' in body and "font-src 'self'" in page(mac)[1]["Content-Security-Policy"]
    assert "fonts.googleapis" not in body  # no outside requests


def test_a_post_opens_as_a_card_over_the_wall_or_as_a_page(mac, lib):
    status, headers, data = request(mac, "GET", f"/item/{lib['ig']}?frag=1")
    assert status == 200 and not data.startswith(b"<!doctype") and b'class="it-h"' in data and b"<video" in data
    for tab in ("Summary", "Links", "Related", "Details"):
        assert f">{tab}<" in data.decode()
    assert "data-standalone" in page(mac, f"/item/{lib['ig']}")[2]
    assert request(mac, "GET", "/item/999?frag=1")[0] == 404


def test_search_covers_the_archive_and_quotes_the_matching_line(mac, lib):
    post(mac, "/hub/shelf", id=lib["ig"], shelf="archive")
    body = page(mac, "/?q=carbonara")[2]
    assert "1 found" in body and "Chef Alex Example" in body and "<mark>carbonara</mark>" in body.lower()
    post(mac, "/hub/note", id=lib["yt"], note="borrow the ownership book")
    assert "Your note" in page(mac, "/?q=borrow")[2]


def test_tiles_take_the_type_colour_or_the_source_colour(mac, lib):
    from magpiary import modes
    mac.store._db.execute("UPDATE items SET ai_status='done', ai_type='recipe', ai_title='Carbonara fast' WHERE canonical_url=?", (IG,))
    body = page(mac)[2]
    assert "var(--t-recipe)" in body and '<span class="step">Chef Alex Example</span></a><span class="kind"><i class="kd"' in body and 'href="/?author=Chef+Alex+Example"' in body and ">Recipe<span class=\"n\">1<" in body  # a type filter too
    assert "var(--s-youtube)" in body and "✦ Summarise" in body          # no key yet: source colour and a nudge
    mac.store.set_setting(modes.SETTING, "private")
    body = page(mac)[2]
    assert "var(--s-youtube)" in body and "✦ Summarise" not in body and "Add a free key" not in body


def test_piles_live_on_the_wall(mac, lib):
    assert request(mac, "GET", "/piles")[0] == 404
    assert "Regroup everything" in page(mac, "/?view=piles")[2]
    assert ">Everything<" in page(mac)[2] and 'href="/?view=piles"' in page(mac)[2]


def test_a_post_tells_outside_links_from_library_searches(mac, lib):
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({
        "title": "Sites", "summary": "Some sites.", "type": "tool", "key_points": [], "suggested_tags": [],
        "entities": {"tools": ["Figma"], "links": ["cta.gallery", IG, "javascript:alert(1)"]},
        "extras": {"tool_url": "https://cta.gallery"}}))
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert 'href="https://cta.gallery" target="_blank" rel="noopener noreferrer" aria-label="Open cta.gallery (opens the website)"' in body
    assert 'class="qs" href="/?q=Figma" aria-label="Search your library for Figma"' in body
    assert f'class="xl" href="{IG}"' not in body  # the post's own address is not a chip
    assert 'href="javascript' not in body  # an odd value is only ever a search chip, never a link to run
    assert '<b>Link:</b> <a class="xl" href="https://cta.gallery"' in body


def test_a_photo_post_shows_how_to_move_through_its_photos(mac, tmp_path):
    item_id, _ = archive(mac, tmp_path, "https://www.instagram.com/p/GALLERY1/", "instagram",
                         {"text": "Seven slides", "media": ["media-01.jpg", "media-02.jpg", "media-03.jpg"]},
                         {f"media-0{n}.jpg": b"\xff\xd8\xff" + b"0" * 20 for n in (1, 2, 3)})
    body = page(mac, f"/item/{item_id}")[2]
    assert "data-gallery" in body and "1 / 3" in body and 'aria-label="Next photo"' in body and "3 photos" in body
    assert "scroll sideways" not in body
    single, _ = archive(mac, tmp_path, "https://www.instagram.com/p/GALLERY2/", "instagram",
                        {"text": "One", "media": ["media-01.jpg"]}, {"media-01.jpg": b"\xff\xd8\xff" + b"0" * 20})
    assert "data-gallery" not in page(mac, f"/item/{single}")[2]


def test_settings_redesign_privacy_page_and_the_limit_in_the_nest(mac):
    body = page(mac, "/settings/ai")[2]
    assert "setlook" not in body and "Try designs" not in body  # Rows won; the trial is gone
    assert "/hub/settings/budget" not in body and "had a problem" not in body  # both moved to the Nest
    body = page(mac, "/settings/privacy")[2]
    assert "What leaves this Mac" in body and "Delete my data" in body and "Never leaves" in body
    nest = page(mac, "/nest")[2]
    assert "/hub/settings/budget" in nest and "then pause" in nest
    status, headers, _ = post(mac, "/hub/settings/budget", mode="next", count="5", next="/nest?tab=now")
    assert headers["Location"] == "/nest?tab=now" and mac.store.summary_budget() == "5"


def test_settings_sections_and_the_health_check(mac):
    for path, text in (("/settings", "Your phones"), ("/settings/ai", "Enable Smart Summaries"), ("/settings/ai", "Brave Search key"),
                       ("/settings/phones", "Your phones"), ("/settings/storage", "Your library"),
                       ("/settings/appearance", "Theme")):
        status, _, body = page(mac, path)
        assert status == 200 and text in body, path
    body = page(mac, "/settings/profile")[2]  # Your profile is a section of its own, first in the list, not part of Shared boards
    assert body.index('href="/settings/profile"') < body.index('href="/settings/phones"') < body.index('href="/settings/ai"') and "How friends see you" in body
    assert "How friends see you" not in page(mac, "/settings/boards")[2] and "Where boards sync" in page(mac, "/settings/boards")[2]
    assert "Your identity" in body and "Set up your profile" in body  # the profile's own help
    assert page(mac, "/settings/nope")[0] == 404
    assert "Health" in page(mac, "/doctor")[2]


# ---- the UX pass: bulk actions, search hints, long walls ---------------------------------------------

def test_bulk_actions_archive_restore_tag_and_queue_summaries(mac, lib):
    ids = f"{lib['ig']},{lib['yt']}"
    post(mac, "/hub/bulk", ids=ids, action="archive")
    assert {i["shelf"] for i in mac.store.items()} == {"archive"}
    post(mac, "/hub/bulk", ids=ids, action="inbox")
    post(mac, "/hub/bulk", ids=ids, action="tag", tag="#Later ")
    assert mac.store.tags_for(IG) == ["later"] and mac.store.tags_for(YT) == ["later"]
    post(mac, "/hub/bulk", ids=str(lib["ig"]), action="untag", tag="later")
    assert mac.store.tags_for(IG) == [] and mac.store.tags_for(YT) == ["later"]
    post(mac, "/hub/bulk", ids=ids, action="trash")
    assert {i["shelf"] for i in mac.store.items()} == {"trash"}
    assert request(mac, "POST", "/hub/bulk", {"ids": ids, "action": "inbox"})[0] == 403  # needs the secret field


def test_search_hints_offer_piles_tags_names_sources_and_types(mac, lib):
    post(mac, "/hub/tags", id=lib["ig"], tags="recipes, rust")
    status, headers, data = request(mac, "GET", "/search.json?q=rec")
    hints = json.loads(data)
    assert status == 200 and [t["tag"] for t in hints["tags"]] == ["recipes"]
    assert {s["source"] for s in hints["sources"]} == {"instagram", "youtube"}
    assert "all_piles" in json.loads(request(mac, "GET", "/search.json?q=&piles=1")[2])


def test_long_walls_come_in_parts_with_month_sections(mac, lib, monkeypatch):
    from magpiary import hub_wall
    monkeypatch.setattr(hub_wall, "PAGE", 1)
    body = page(mac)[2]
    assert body.count('class="tile') == 1 and "data-more" in body and "part=1" in body
    status, _, data = request(mac, "GET", "/?part=1")
    assert status == 200 and not data.startswith(b"<!doctype") and data.count(b'class="tile') == 1
    assert "data-sec=" in body


def test_month_sections():
    from datetime import date
    from magpiary import ui
    today = date(2026, 10, 24)
    assert ui.section_of({"last_shared_at": "2026-10-24T09:00:00"}, today) == "Today"
    assert ui.section_of({"last_shared_at": "2026-10-20T09:00:00"}, today) == "This week"
    assert ui.section_of({"last_shared_at": "2026-09-02T09:00:00"}, today) == "September"
    assert ui.section_of({"last_shared_at": "2025-12-02T09:00:00"}, today) == "December 2025"


def test_tiles_carry_their_video_length_and_preview(mac, lib):
    body = page(mac)[2]
    assert f'data-video="/media/{lib["ig"]}/media-01.mp4" data-start="0"' in body and '<span class="dur">0:31</span>' in body
    assert f'data-flip-id="t{lib["ig"]}"' in body


def test_help_page_lists_every_chapter_once_and_every_jump_lands(mac):
    import re
    from collections import Counter

    from magpiary import help as helptext

    listed = [k for _, keys in helptext.HELP_GROUPS for k in keys]
    assert sorted(listed) == sorted(helptext.TOPICS)  # every topic in exactly one group
    assert set(helptext.LOOK) == set(helptext.TOPICS)
    body = page(mac, "/help")[2]
    ids = Counter(re.findall(r' id="([^"]+)"', body))
    assert [i for i, n in ids.items() if n > 1] == []  # no chapter shares an id with the top bar (#t-nest, #t-digest did)
    jumps = re.findall(r'href="#(help-[^"]+)"', body)
    assert len(jumps) > len(helptext.TOPICS) and all(ids[j] == 1 for j in jumps)
    assert "What&#x27;s new" in body or "What's new" in body
    assert "Ask Magpiary" in page(mac, "/settings/ask")[2] and "Turn Ask on" in page(mac, "/settings/ask")[2]
    assert 'href="/help#help-nest"' in page(mac, "/help?frag=1&ctx=nest")[2]  # All help opens at the same chapter


def test_help_column_on_settings_the_help_page_and_the_panel_for_each_page(mac):
    body = page(mac, "/settings/phones")[2]
    assert 'id="sethelp"' in body and "Pair an iPhone" in body and "Right now" in body and "All help" in body
    assert "Get a free Gemini key" not in body  # contextual: only the open section's help
    assert "Summaries are waiting for an AI key" not in page(mac, "/settings/ai")[2]  # Help carries no "needs you" card (owner, 1 Nov): problems live in the Nest
    status, _, body = page(mac, "/help")
    assert status == 200 and all(t in body for t in ("Getting started", "The Nest", "Privacy", 'id="helpq"'))
    frag = page(mac, "/help?frag=1&ctx=nest")[2]
    assert "Why are posts waiting?" in frag and "<html" not in frag
    assert 'id="t-help"' in page(mac)[2]
    assert "What's new" not in page(mac, "/settings")[2]  # only after an update, never on a first install
    mac.store.set_setting("seen_version", "0.0.1")
    assert "What's new" in page(mac, "/settings")[2]
    post(mac, "/hub/whatsnew/seen", next="/settings")
    assert "What's new" not in page(mac, "/settings")[2]


def test_text_on_every_coloured_surface_is_readable_and_collections_never_use_category_colours(mac, lib):
    import runpy
    from magpiary import ui

    check = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "contrast_check.py"))
    assert check["main"]() == 0  # white text passes 4.5:1 on every deep category/source shade and collection colour
    body = page(mac)[2]
    assert 'data-labels="black"' in body and 'class="label"' in body  # the default tile label is the black overlay
    post(mac, "/hub/ui", labels="colour", next="/settings/appearance")  # Settings → Appearance → Tile labels
    body = page(mac)[2]
    assert 'data-labels="colour"' in body and re.search(r'class="label" style="--lc:var\(--[ts]-[a-z_]+-deep\)"', body)
    assert "Tile labels" in page(mac, "/settings/appearance")[2]
    post(mac, "/hub/ui", labels="rainbow")  # an unknown choice changes nothing
    assert 'data-labels="colour"' in page(mac)[2]
    assert "var(--t-" not in ui.pile_colour({"id": 3}) and ui.folder_colour("#f5a300") == "var(--f-butter)"
    assert ui.deep("var(--t-discussion)") == "var(--t-discussion-deep)" and ui.ink("#f5a300") == "#111"


def test_the_receiver_queues_a_whole_page_of_thumbnails():
    from magpiary.receiver import Server

    assert Server.request_queue_size >= 64  # the default 5 refused connections and left broken tiles


def test_board_page_has_no_colour_look_switcher_and_pile_editing_opens_from_one_button(mac, lib):
    from magpiary import hub_boards

    assert not hasattr(hub_boards, "BOARD_LOOKS")  # the owner picked Two glows; the floating switcher is gone
    pid = mac.store.new_pile("Design")
    mac.store.move_to_pile(mac.store.item_by_id(lib["ig"])["canonical_url"], pid)
    body = page(mac, f"/pile/{pid}")[2]
    assert 'id="pileedit"' in body and 'class="phead"' in body and "Edit pile" in body and "Done editing" in body
    assert 'class="stat"' not in body and "1 save" in body  # no cards: one summary line
    assert body.index("Edit pile") < body.index("Delete pile")  # delete lives inside the edit panel


def test_clicking_an_author_filters_the_wall_to_their_posts(mac, lib):
    body = page(mac, "/?author=Chef+Alex+Example")[2]
    assert "By Chef Alex Example" in body and "Chef Alex Example" in body and body.count('class="tile') >= 1
    assert 'class="tile' not in page(mac, "/?author=Nobody")[2] and "Nothing matches" in page(mac, "/?author=Nobody")[2]
    assert "By Chef Alex Example" in page(mac, "/?view=boards&author=Chef+Alex+Example")[2]


def test_the_post_view_is_one_design_with_a_context_slot(mac, lib):
    """Library, Archive, Trash and a pile fill the top bar's left side differently; everything else is the same."""
    body = page(mac, f"/item/{lib['ig']}?frag=1")[2]
    assert 'class="pbar"' in body and 'data-context="library"' in body and '<span class="pwhere">Library</span>' in body
    assert body.index('class="pbar"') < body.index('class="pscroll"') < body.index('class="tabs pvtabs"')
    for icon_label in ("Previous post", "Next post", "Open the original", "Copy the link", "More actions", "Close"):
        assert f'aria-label="{icon_label}"' in body
    assert 'class="cn cn-heart"' in body and "Open original" not in body.split('class="pbar"')[1].split('class="pscroll"')[0].replace("Open the original", "")
    pile = mac.store.save_auto_pile(None, [IG, YT], "Pasta night", keep_name=True)
    in_pile = page(mac, f"/item/{lib['ig']}?frag=1&pile={pile}")[2]
    assert 'data-context="pile"' in in_pile and "Pasta night" in in_pile and "data-pos" in in_pile
    post(mac, "/hub/shelf", id=lib["yt"], shelf="trash", next="/")
    gone = page(mac, f"/item/{lib['yt']}?frag=1")[2]
    assert 'data-context="trash"' in gone and "In the Trash" in gone and "Restore to library" in gone
    post(mac, "/hub/shelf", id=lib["ig"], shelf="archive", next="/")
    assert 'data-context="archive"' in page(mac, f"/item/{lib['ig']}?frag=1")[2]


def test_the_post_offers_its_next_actions_and_says_where_each_block_came_from(mac, lib):
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({
        "title": "Cedar Panels", "summary": "An invented panel toolkit.", "type": "tool", "key_points": [{"at": "0:08", "text": "Modules"}],
        "extras": {"tool_name": "Cedar Panels"}, "entities": {"tools": ["Cedar Panels"]}, "suggested_tags": [],
        "engine": {"brain": "Google Gemini", "key": "Personal"}}))
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert 'class="pvactions"' in body and "Copy with source" in body and "Add a link yourself" in body
    assert 'class="pvact"' not in body  # no separate Add to board button: it is in the … menu
    assert "Find the link for Cedar Panels" in body  # a tool with no link yet gets a Find button
    assert "AI summary · Google Gemini" in body and "Written by" not in body.split('class="pscroll"')[1].split('class="tabs')[0]
    assert "data-addboard" in body and "Caption by the creator" not in body  # a board icon in the top bar; the caption needs no label


def test_a_pile_of_one_post_is_not_shown(mac, lib):
    mac.store.save_auto_pile(None, [mac.store.item_by_id(lib["ig"])["canonical_url"]], "Lonely", keep_name=True)
    assert "Lonely" not in page(mac, "/?view=piles")[2]
    assert "Piles are groups Magpiary makes for you" in page(mac, "/?view=piles")[2]


def test_search_says_why_each_result_matched_and_offers_did_you_mean(mac, lib):
    body = page(mac, "/?q=carbon")[2]
    assert "Chef Alex Example" in body and ("Caption" in body or "Said" in body or "Title" in body)  # a matching line, labelled
    guess = page(mac, "/?q=carbnara")[2]  # a misspelling finds nothing but the library has the word
    assert "Did you mean" in guess and "carbonara" in guess.split("Did you mean")[1][:200].lower()
    assert "Did you mean" not in page(mac, "/?q=carbon")[2]


def test_on_screen_text_is_read_searchable_and_listed_in_details(mac, lib):
    from magpiary.worker import screen_due

    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "frames").mkdir(exist_ok=True)
    (folder / "frames" / "a.jpg").write_bytes(b"x")
    (folder / "frames.json").write_text(json.dumps([{"at": 12.0, "path": "frames/a.jpg"}]))
    fake = lambda path: [("Zebrafinch magnificent kitchen", 0.9), ("ok", 0.9), ("iiiiii", 0.9), ("faint words here", 0.2)]
    assert screen_due(mac.store, read=fake) >= 1
    assert json.loads((folder / "ocr.json").read_text()) == [{"at": 12.0, "text": "Zebrafinch magnificent kitchen"}]  # junk dropped
    assert "On screen" in page(mac, "/?q=zebrafinch")[2]  # found by what was on screen, and labelled so
    details = page(mac, f"/item/{lib['ig']}")[2]
    assert 'class="pvcloud"' in details and "magnificent" in details and 'title="0:12"' in details


def test_on_screen_noise_is_filtered_out():
    from magpiary import ocr

    noise = ["i lili\uffff.\uffff\uffff,...5\uffff.¥a¥amillo ICC.B¥-SA 4. 01.;", "sec109'.. eEC BY-SA 3. 01\";",
             "Photos: Jozge )araffiillo ICC BY-SA 4.Gl,' Msec109 (fL'..BY.-SA 3.0),", "PA R I S 1.7. .Ot.s::2lf26",
             "billion ?(tros In iiot damage,", "Ilffl", "99"]
    real = ["in India gets exactly what it", "blocking highways and railway..", "A PATERNALISTIC", "GDP PER PERSON. CURRENT US$"]
    assert ocr.clean([(t, 0.9) for t in noise]) == []
    assert ocr.clean([(t, 0.9) for t in real]) == real
    words = ocr.cloud([{"at": 4.8, "text": "in India gets exactly what it"}, {"at": 9.0, "text": "India wants growth"}])
    assert words[0]["word"] == "India" and words[0]["count"] == 2 and "what" not in [w["word"].lower() for w in words]


def test_a_post_is_a_page_with_a_breadcrumb_and_arrows_through_the_list_it_came_from(mac, lib):
    mac.store.save_auto_pile(None, [mac.store.item_by_id(lib[k])["canonical_url"] for k in ("ig", "yt")], "Pasta pile", keep_name=True)
    pid = mac.store.piles()[0]["id"]
    body = page(mac, f"/item/{lib['ig']}?from=%2Fpile%2F{pid}")[2]
    assert 'class="postpage"' in body and 'class="crumbbar"' in body and 'id="top"' in body  # the site bar stays
    crumbs = body.split('class="crumbs"')[1].split("</nav>")[0]
    assert ">Library<" in crumbs and ">Piles<" in crumbs and "Pasta pile" in crumbs and 'aria-current="page"' in crumbs
    assert "1 of 2" in body and f'href="/item/{lib["yt"]}?from=%2Fpile%2F{pid}"' in body  # Next, inside the pile
    assert "data-close" not in body.split('class="postpage"')[1].split("</section>")[0]  # no close ×: Back replaces it
    outside = page(mac, f"/item/{lib['ig']}?from=http%3A%2F%2Fevil.example")[2]  # a from outside the hub is ignored
    assert "evil.example" not in outside and ">Library<" in outside.split('class="crumbs"')[1]
    assert page(mac, f"/item/{lib['ig']}?frag=1")[2].count('class="postpage"') == 0  # the pop-up still gets the bare card


def test_posts_always_open_as_a_page_and_there_is_no_choice(mac):
    assert 'data-open="page"' in page(mac, "/")[2]
    assert "Posts open as" not in page(mac, "/settings/appearance")[2]
    post(mac, "/hub/ui", open="popup", next="/")
    assert 'data-open="page"' in page(mac, "/")[2] and 'data-open="popup"' not in page(mac, "/")[2]


def test_slide_in_head_script_and_play_button():
    src = (Path(__file__).parent.parent / "src/magpiary/ui.py").read_text()
    assert "mag-slide" in src and '"slide-in","slidefx"' in src
    assert "pvbig" in (Path(__file__).parent.parent / "src/magpiary/hub_card.py").read_text()


def test_a_carousel_post_plays_every_slide_and_has_one_sound_button(mac, tmp_path):
    cid, folder = archive(mac, tmp_path, "https://www.instagram.com/p/CAROUSEL1/", "instagram",
                          {"text": "Slides", "author": "Chef", "duration": 2.0,
                           "media": ["media-01.mp4", "media-02.mp4", "media-03.jpg"]},
                          {"media-01.mp4": b"v1", "media-02.mp4": b"v2", "media-03.jpg": b"\xff\xd8\xff"})
    (folder / "slides.json").write_text(json.dumps([{"file": "media-01.mp4", "start": 0.0, "duration": 2.0},
                                                    {"file": "media-02.mp4", "start": 2.0, "duration": 3.0}]))
    body = page(mac, f"/item/{cid}")[2]
    assert body.count('<button type="button" class="pvsl') == 3 and "3 slides" in body and 'aria-label="Next slide"' in body
    assert 'data-start="2.0" data-dur="3.0"' in body and 'data-k="i"' in body
    assert 'class="pvvol"' not in body and 'data-pv="mute"' in body  # no volume slider, just mute and unmute


def test_sound_is_kept_between_posts_and_the_big_play_button_has_no_ring():
    js = (Path(__file__).parent.parent / "src/magpiary/static/hub.js").read_text()
    css = (Path(__file__).parent.parent / "src/magpiary/static/hub.css").read_text()
    assert 'sessionStorage.getItem(soundKey)' in js and "rememberSound(true);  // a post opened from a list" in js
    assert ".pvbig { position: absolute;" in css and "rgba(255,255,255,.35)" not in css.split(".pvbig {")[1].split("}")[0]


def test_a_small_picture_falls_back_to_the_original_and_an_open_post_has_its_own_signature(mac, lib):
    status, headers, data = request(mac, "GET", f'/media/{lib["ig"]}/thumbnail.jpg?w=600')
    assert status == 200 and data.startswith(b"\xff\xd8\xff")  # these bytes are not a picture ffmpeg can shrink: the original is served
    before = mac.store.item_signature(lib["ig"])
    post(mac, "/hub/tags", id=lib["ig"], tags="pasta")
    assert mac.store.item_signature(lib["ig"]) != before
    snap = json.loads(request(mac, "GET", f'/activity.json?item={lib["ig"]}')[2])
    assert snap["item_signature"] == mac.store.item_signature(lib["ig"])
    assert snap["item_looking"] is False
    mac.store.find_links_again(lib["ig"])  # the button shows "Looking…" until the search ends, even when it finds nothing new
    assert json.loads(request(mac, "GET", f'/activity.json?item={lib["ig"]}')[2])["item_looking"] is True
    mac.store.save_found_links(mac.store.item_by_id(lib["ig"])["canonical_url"], [])
    assert json.loads(request(mac, "GET", f'/activity.json?item={lib["ig"]}')[2])["item_looking"] is False


def test_glass_strength_has_four_stops_and_is_sent_with_every_page(mac):
    body = page(mac, "/settings/appearance")[2]
    assert 'data-glass="on"' in body and "--gs:0.3" in body and 'name="glass_level"' in body  # on, at the first stop, by default
    assert all(f'data-lv="{n}"' in body for n in (25, 50, 75, 100))
    post(mac, "/hub/ui", glass_level="50", next="/settings/appearance")
    assert "--gs:0.533" in page(mac, "/")[2]
    post(mac, "/hub/ui", glass_level="65", next="/")  # between stops: the nearest one (75)
    assert "--gs:0.767" in page(mac, "/")[2] and mac.store.get_setting("ui_glass_level") == "75"
    post(mac, "/hub/ui", glass_level="900", next="/")  # past the end: 100
    assert "--gs:1" in page(mac, "/")[2]
    post(mac, "/hub/ui", glass_level="5", next="/")  # below the start: 25
    assert "--gs:0.3" in page(mac, "/")[2]
    post(mac, "/hub/ui", glass="off", next="/settings/appearance")
    assert 'name="glass_level"' not in page(mac, "/settings/appearance")[2]  # the slider shows only while glass is on


def test_your_activity_counts_on_the_mac_and_can_be_cleared(mac):
    hub = mac.server.hub
    assert post(mac, "/hub/activity", kind="link")[0] == 200
    post(mac, "/hub/activity", kind="copy")
    post(mac, "/hub/activity", kind="nonsense")  # only the two kinds the page reports are accepted
    hub.store.activity_add("ask")
    counts = hub.store.activity_days(30)
    assert sum(counts["link"].values()) == 1 and sum(counts["copy"].values()) == 1 and "nonsense" not in counts
    body = page(mac, "/settings/privacy")[2]
    assert "Your activity" in body and "Links opened" in body and "Questions asked" in body and "Copy summary" in body
    assert post(mac, "/hub/activity", action="clear", next="/settings/privacy")[0] == 303
    assert hub.store.activity_days(30) == {}


def test_the_checklist_ticks_steps_and_can_be_replayed(mac, tmp_path):
    hub = mac.server.hub
    assert post(mac, "/hub/checklist", action="tick", step="watch")[0] == 200
    post(mac, "/hub/checklist", action="tick", step="bogus")
    assert hub._checklist_state()["done"] == ["watch"]
    post(mac, "/hub/checklist", action="off")
    assert hub._checklist_state()["off"] is True
    post(mac, "/hub/checklist", action="replay")
    assert hub._checklist_state() == {"done": [], "off": False}


def test_the_look_files_are_served_and_the_new_choices_are_saved(mac):
    for name in ("/static/indigo.css", "/static/indigo.js", "/static/vendor/lenis.min.js", "/static/fonts/quicksand.woff2", "/static/art/land-c.webp"):
        assert request(mac, "GET", name)[0] == 200
    body = request(mac, "GET", "/")[2].decode()
    assert 'id="lhsearch"' in body and "/static/art/land-c.webp" in body


def test_a_new_install_ships_with_the_chosen_look(tmp_path):
    """Owner's shipped defaults (1 Nov): dark theme, medium tiles, black-overlay labels, glass on at 25%, page capped at 1,600 px."""
    from magpiary import ui
    from magpiary.store import Store

    store = Store(tmp_path / "fresh.db")
    look = ui.appearance(store)
    assert (look["theme"], look["size"], look["labels"], look["glass"], look["glass_level"]) == ("dark", "m", "black", "on", 25)
    assert (look["layout"], look["box"]) == ("boxed", 1600)
    store.close()


# ---- the Mac app's menu-bar panel --------------------------------------------------------

def test_the_panel_gets_counts_and_the_latest_saves(mac, lib):
    status, headers, body = request(mac, "GET", "/panel.json")
    data = json.loads(body)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert data["saves"] == 2 and data["waiting"] == 0 and data["need"] == 0
    assert {p["id"] for p in data["latest"]} == {lib["ig"], lib["yt"]}
    assert any(p["thumb"].startswith("/media/") for p in data["latest"])


def test_the_panel_says_only_locked_while_the_hub_is_locked(mac, lib, monkeypatch):
    monkeypatch.setattr(mac.server.hub.lock, "is_locked", lambda: True)
    status, _, body = request(mac, "GET", "/panel.json")
    assert status == 200 and json.loads(body) == {"locked": True}
    assert request(mac, "POST", "/hub/panel/save", {"csrf": mac.server.hub.csrf, "url": "https://www.instagram.com/reel/PANEL1/"})[0] == 423


def test_the_panel_polling_does_not_count_as_using_the_hub(mac, lib):
    before = mac.server.hub.lock.active
    request(mac, "GET", "/panel.json")
    assert mac.server.hub.lock.active == before


def test_save_copied_link_says_saved_then_already_saved_then_cant(mac):
    save = lambda url: json.loads(request(mac, "POST", "/hub/panel/save", {"csrf": mac.server.hub.csrf, "url": url})[2])["status"]
    assert save("https://www.instagram.com/reel/PANEL1/?igsh=abc") == "saved"
    assert save("https://www.instagram.com/reel/PANEL1/") == "again"
    assert save("not a link") == "bad"


def test_save_copied_link_needs_the_form_token(mac):
    assert request(mac, "POST", "/hub/panel/save", {"url": "https://www.instagram.com/reel/PANEL2/"})[0] == 403


def test_uninstall_in_settings_follows_how_magpiary_was_installed(mac, monkeypatch):
    monkeypatch.delenv("MAGPIARY_PROGRAM", raising=False)
    assert "magpiary://uninstall" not in request(mac, "GET", "/settings/storage")[2].decode()
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    assert "magpiary://uninstall" in request(mac, "GET", "/settings/storage")[2].decode()


def test_the_glass_button_rule_keeps_its_old_weight():
    """The shared glass rule leaves the busy Nest out through :where(), which adds no weight. Written as
    .nestbtn[data-mood="working"] it outweighed .btn.cta and turned the pink "Open the Nest" button dark (5 Nov 2026)."""
    from pathlib import Path

    css = (Path(__file__).parents[1] / "src/magpiary/static/indigo.css").read_text()
    assert '.ubtn:not(.nestbtn:where([data-mood="working"], [data-mood="needs"]))' in css
    assert '.ubtn:not(.nestbtn[data-mood' not in css
