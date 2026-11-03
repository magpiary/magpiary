"""List posts (round-ups, "media I consumed", "10 tools"): every item is kept with who made it and the poster's note,
and gets its own link: videos from a YouTube search on the Mac, articles from the owner's search key. Recorded
answers only (no live calls). All names are fictional."""

from magpiary.brain import build_evidence, tidy, tidy_list
from magpiary.links import Target, article_search, find_links, targets_for, youtube_match

ITEMS = [{"name": "The Story of Blue Paint", "kind": "video", "by": "Paint Lab", "note": "my new fav series", "slide": 2},
         {"name": "Why Grids Feel Calm", "kind": "article", "by": "Pebble Notes", "note": "", "slide": 3},
         {"name": "The Story of Blue Paint", "kind": "video", "by": "", "note": "repeat", "slide": 4},
         {"name": "Quiet Harbour", "kind": "comic", "by": "", "slide": 300}]

RECORD = {"title": "Things I watched in May", "summary": "A designer's monthly round-up.", "key_points": [], "type": "other",
          "entities": {}, "suggested_tags": [], "list_items": ITEMS}


def videos(answers):
    asked = []

    def search(query):
        asked.append(query)
        return answers
    search.asked = asked
    return search


def test_list_items_are_tidied_in_order_without_repeats():
    items = tidy_list(ITEMS)
    assert [i["name"] for i in items] == ["The Story of Blue Paint", "Why Grids Feel Calm", "Quiet Harbour"]
    assert items[2]["kind"] == "other" and items[2]["slide"] == 0  # unknown kind, impossible slide number
    assert tidy(RECORD)["list_items"] == items
    assert tidy({**RECORD, "list_items": "nope"})["list_items"] == []


def test_list_items_come_first_as_link_targets():
    targets, _ = targets_for({**RECORD, "list_items": tidy_list(ITEMS),
                              "link_targets": [{"name": "Why Grids Feel Calm", "kind": "tool", "role": "passing"}]}, "", "", None)
    assert [(t.name, t.kind, t.by) for t in targets[:2]] == [("The Story of Blue Paint", "video", "Paint Lab"),
                                                          ("Why Grids Feel Calm", "article", "Pebble Notes")]
    assert targets[1].central  # the list's version wins over the AI's passing tag


def test_a_video_needs_its_title_and_the_channel_the_post_gives():
    target = Target("The Story of Blue Paint", "video", by="Paint Lab")
    right = {"title": "The Story of Blue Paint", "channel": "Paint Lab", "url": "https://www.youtube.com/watch?v=a1"}
    copy = {"title": "The Story of Blue Paint (reaction)", "channel": "Someone Else", "url": "https://www.youtube.com/watch?v=b2"}
    found = youtube_match(target, videos([copy, right]))
    assert found.url.endswith("v=a1") and not found.possible and found.kind == "videos"
    assert youtube_match(target, videos([copy])) is None  # part of the title, someone else's channel: a reaction or a copy
    reupload = {**right, "channel": "Someone Else", "url": "https://www.youtube.com/watch?v=d4"}
    assert youtube_match(target, videos([reupload])).possible  # the whole title, another channel: only a possible match
    assert youtube_match(target, videos([{"title": "Blue", "channel": "Paint Lab", "url": "https://www.youtube.com/watch?v=c3"}])) is None


def test_an_article_comes_from_the_search_key_and_must_name_its_author():
    target = Target("Why Grids Feel Calm", "article", by="Pebble Notes")
    hits = [{"title": "Why Grids Feel Calm", "url": "https://www.instagram.com/p/x/"},
            {"title": "Why Grids Feel Calm - by Ana", "url": "https://pebblenotes.example.com/p/why-grids"}]
    found = article_search(target, lambda q: hits, "articles")
    assert found.url == "https://pebblenotes.example.com/p/why-grids" and not found.possible


def test_find_links_gives_every_list_item_its_link():
    yt = videos([{"title": "The Story of Blue Paint", "channel": "Paint Lab", "url": "https://www.youtube.com/watch?v=a1"}])
    found = find_links({**RECORD, "list_items": tidy_list(ITEMS[:2])}, "", "", None, get=lambda url, h=None: (404, url, b""),
                       search=lambda q: [{"title": "Why Grids Feel Calm", "url": "https://pebblenotes.example.com/p/why-grids"}],
                       videos=yt)
    assert {f.name: f.url for f in found} == {"The Story of Blue Paint": "https://www.youtube.com/watch?v=a1",
                                              "Why Grids Feel Calm": "https://pebblenotes.example.com/p/why-grids"}
    assert yt.asked == ["The Story of Blue Paint Paint Lab"]


def test_text_read_on_the_mac_goes_into_the_evidence(tmp_path):
    parts = build_evidence({"source": "instagram", "text": "round-up"}, None, [], [], tmp_path, None, "",
                           [{"at": None, "text": "The Story of Blue Paint"}, {"at": 4.0, "text": "Paint Lab"}])
    text = parts[0]["text"]
    assert "TEXT READ FROM THE IMAGES AND FRAMES ON THE MAC" in text
    assert "[-] The Story of Blue Paint" in text and "[0:04] Paint Lab" in text


def test_a_new_summary_finds_links_again(tmp_path):
    from magpiary.store import Store

    store = Store(tmp_path / "m.db")
    url = "https://www.instagram.com/p/abc/"
    store.add_link(url)
    store.fetch_succeeded(url, str(tmp_path))
    store.save_found_links(url, [])
    record = {**tidy(RECORD), "engine": {}}
    store.brain_succeeded(url, record, "", False)
    assert any(i["canonical_url"] == url for i in store.due_for_links())  # queued for the link search with the new record's names


# ---- pages that hide what they hold -------------------------------------------------------

from magpiary.sources import FetchFailed, other, readable  # noqa: E402

ARTICLE = (b'<html><head><title>Grids</title><meta property="og:image" content="https://cdn.example.com/cover.jpg">'
           b'<meta name="description" content="Short."></head><body><nav><p>Home</p><p>About</p></nav>'
           b'<article><h1>Why Grids Feel Calm</h1><p>Rows and columns give the eye a place to rest.</p>'
           b'<img src="/img/grid-1.jpg"><img src="https://cdn.example.com/avatar.png"><img src="x.jpg" width="16">'
           b'<script>alert(1)</script><p>Rows and columns give the eye a place to rest.</p></article>'
           b'<footer><p>Copyright</p></footer></body></html>')


def test_a_page_gives_its_reading_text_and_pictures_without_menus():
    text, images = readable(ARTICLE, "https://pebblenotes.example.com/p/grids")
    assert text == "Why Grids Feel Calm\nRows and columns give the eye a place to rest."
    assert images == ["https://pebblenotes.example.com/img/grid-1.jpg"]


def test_a_thin_page_is_drawn_once_by_a_browser_and_a_refusing_page_is_not():
    shell = b'<html><head><title>Board</title></head><body><div id="root"></div></body></html>'
    drawn = []

    def render(url):
        drawn.append(url)
        return ARTICLE
    got = other("https://gallery.example.com/p/1", lambda u: (200, shell), None, render)
    assert drawn == ["https://gallery.example.com/p/1"] and "eye a place to rest" in got.meta["text"]
    assert got.fetched_with.startswith("page (drawn") and got.images[0] == "https://cdn.example.com/cover.jpg"
    full = other("https://pebblenotes.example.com/p/grids", lambda u: (200, ARTICLE.replace(b"</article>", b"<p>" + b"x" * 500 + b"</p></article>")), None, render)
    assert len(drawn) == 1 and full.fetched_with == "page"  # enough text already: no browser
    try:
        other("https://www.behance.example/gallery/1", lambda u: (403, b""), None, render)
    except FetchFailed as err:
        assert err.reason == "login_wall"
    assert len(drawn) == 1  # a refusal is respected, never drawn another way


# ---- format, topic and the owner's own tags ------------------------------------------------

from magpiary.brain import reuse_tags  # noqa: E402


def test_format_and_topic_are_kept_and_checked():
    got = tidy({**RECORD, "format": "list", "topic": "  Product   Design "})
    assert got["format"] == "list" and got["topic"] == "product design"
    assert tidy({**RECORD, "format": "essay"})["format"] == ""


def test_suggested_tags_use_the_owners_spelling():
    assert reuse_tags(["UI Designs", "figma", "ui-design", "colour"], ["ui design", "Figma"]) == ["ui design", "Figma", "colour"]


def test_the_owners_tags_and_topics_go_into_the_evidence(tmp_path):
    parts = build_evidence({"source": "instagram"}, None, [], [], tmp_path, None, "", None,
                           {"tags": ["ui design", "baking"], "topics": ["product design"]})
    assert "THE OWNER'S EXISTING TAGS: ui design, baking" in parts[0]["text"]
    assert "THE OWNER'S EXISTING TOPICS: product design" in parts[0]["text"]


def test_known_words_lists_tags_by_use_and_topics_from_records(tmp_path):
    import json

    from magpiary.store import Store

    store = Store(tmp_path / "m.db")
    for n, (topic, tags) in enumerate([("product design", ["figma", "ui"]), ("baking", ["figma"])]):
        url = f"https://www.instagram.com/p/k{n}/"
        folder = tmp_path / f"k{n}"
        folder.mkdir()
        record = {**tidy(RECORD), "topic": topic, "suggested_tags": tags, "engine": {}}
        (folder / "record.json").write_text(json.dumps(record))
        store.add_link(url)
        store.fetch_succeeded(url, str(folder))
        store.brain_succeeded(url, record, "", apply_tags=True)
    known = store.known_words()
    assert known["tags"][0] == "figma" and set(known["topics"]) == {"product design", "baking"}


# ---- long videos wait for the owner -------------------------------------------------------

def test_a_long_video_gets_the_normal_summary_straight_away(tmp_path):
    import json

    from magpiary.store import Store
    from magpiary.worker import brain_due

    store = Store(tmp_path / "m.db")
    urls = []
    for code, seconds in (("short", 90), ("long", 3600)):
        url = f"https://www.youtube.com/watch?v={code:_<11}"
        folder = tmp_path / code
        folder.mkdir()
        (folder / "meta.json").write_text(json.dumps({"url": url, "duration": seconds, "media": []}))
        store.add_link(url)
        store.fetch_succeeded(url, str(folder))
        urls.append(url)
    prepared = []
    brain_due(store, tmp_path, prepare=lambda item, progress: prepared.append(item["canonical_url"]),
              process=lambda item, key, progress: None, pause=lambda tier: None)
    assert sorted(prepared) == sorted(urls)  # an hour-long video is read like any other: nothing waits for length


def test_the_creators_chapters_shape_the_key_points(tmp_path):
    parts = build_evidence({"source": "youtube", "chapters": [{"start": 0, "title": "Intro"}, {"start": 125, "title": "Grids"}]},
                           None, [], [], tmp_path, None, "")
    assert "CHAPTERS (the creator's own): 0:00 Intro; 2:05 Grids" in parts[0]["text"]
