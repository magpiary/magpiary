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
