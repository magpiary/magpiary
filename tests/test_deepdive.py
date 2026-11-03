"""Deeper dive: off by default, once per post, sections for long videos, the creator's own subtitles, and its words
reaching search, Ask, the note and the link search. Recorded answers only; all names are fictional."""

import json
from pathlib import Path
from types import SimpleNamespace

from magpiary import deepdive
from magpiary.brain import tidy
from magpiary.store import Store
from test_hub import page, post

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello and <c>welcome</c>

00:00:04.000 --> 00:00:06.500
Hello and welcome

00:01:02.000 --> 00:01:05.000
Grids give the eye a rest
"""


def saved(store, tmp_path, code="dv1", meta=None, record=None):
    url = f"https://www.youtube.com/watch?v={code:_<11}"
    folder = tmp_path / code
    folder.mkdir()
    meta = {"url": url, "source": "youtube", "media": ["media-01.mp4"], "text": "Notes at https://notes.example.com/grids",
            **(meta or {})}
    (folder / "meta.json").write_text(json.dumps(meta))
    (folder / "record.json").write_text(json.dumps(record or tidy({"title": "Grids", "summary": "A talk about grids.", "key_points": [],
                                                                    "type": "design", "entities": {}, "suggested_tags": []})))
    (folder / "transcript.json").write_text(json.dumps({"segments": [{"start": 5, "end": 9, "text": "grids calm the eye"},
                                                                     {"start": 1900, "end": 1905, "text": "type scales"}]}))
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    return url, folder


class Answers:
    """A fake engine: hands back recorded answers in order and keeps what it was asked."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, system, schema, parts, images):
        self.asked.append((system, schema, parts, images))
        return json.dumps(self.answers.pop(0))


def no_network(*a, **k):
    return 404, b""


def test_subtitles_read_from_vtt_without_tags_or_repeats():
    assert deepdive.parse_vtt(VTT) == [{"start": 1.0, "end": 4.0, "text": "Hello and welcome"},
                                       {"start": 62.0, "end": 65.0, "text": "Grids give the eye a rest"}]


def test_long_videos_split_by_chapters_else_quarter_hours_and_big_ones_ask_first():
    chapters = {"duration": 600, "chapters": [{"start": 0, "title": "Intro"}, {"start": 300, "title": "Grids"}]}
    assert [(s["title"], s["start"], s["end"]) for s in deepdive.sections_for(chapters, 600)] == [("Intro", 0, 300), ("Grids", 300, 600)]
    assert len(deepdive.sections_for({}, 7200)) == 8 and len(deepdive.sections_for({}, 600)) == 1
    assert deepdive.estimate({"duration": 600})["calls"] == 1 and not deepdive.needs_confirm({"duration": 600})
    assert deepdive.estimate({"duration": 7200})["calls"] == 9 and deepdive.needs_confirm({"duration": 7200})
    assert not deepdive.needs_confirm(chapters)  # 2 parts + the overview = 3 calls: starts at once


def test_off_by_default_suggested_only_past_the_minutes(tmp_path):
    store = Store(tmp_path / "m.db")
    assert not deepdive.enabled(store)
    assert deepdive.suggested(store, {"duration": 21 * 60}) and not deepdive.suggested(store, {"duration": 19 * 60})
    store.set_setting(deepdive.LONG, "0")
    assert not deepdive.suggested(store, {"duration": 5 * 3600})  # 0 never suggests


def test_a_short_post_is_one_call_with_everything(tmp_path):
    store = Store(tmp_path / "m.db")
    url, folder = saved(store, tmp_path, meta={"source": "instagram", "duration": 40, "author_handle": "pebble.notes"})
    (folder / "discussion.json").write_text(json.dumps([{"author": "u1", "text": "the grid file is linked in bio"}]))
    ask = Answers({"overview": "Grids calm a layout.\nThey also speed up work.", "sections": [{"title": "Why", "at": "0:05", "summary": "Rest."}],
                   "takeaways": ["Use 8 px steps"], "quotes": [{"text": "grids calm the eye", "at": "0:05"}],
                   "named": [{"name": "Pebble Grid", "kind": "tool", "at": "0:05"}]})
    pages = lambda u, h=None: (200, u, b"<html><title>Grid notes</title><body><article><p>" + b"Grid notes. " * 10 + b"</p></article></body></html>")  # noqa: E731
    profile = lambda u: (200, b'<meta property="og:description" content="Designer. Files: https://files.example.com/grid">')  # noqa: E731
    item = next(i for i in store.due_for_brain() if i["canonical_url"] == url)
    result = deepdive.run(item, store, ask, get_page=pages, get_profile=profile, frame_run=lambda c, t: SimpleNamespace(returncode=1))
    system, schema, parts, _ = ask.asked[0]
    text = parts[0]["text"]
    assert len(ask.asked) == 1 and schema is deepdive.WHOLE_SCHEMA
    assert "u1: the grid file is linked in bio" in text and "Grid notes" in text and "https://files.example.com/grid" in text
    assert "grids calm the eye" in text  # the transcript made on the Mac (not a YouTube post: no subtitles asked for)
    assert result["named"][0]["name"] == "Pebble Grid" and result["bio_links"] == ["https://files.example.com/grid"]
    assert json.loads((folder / "deep.json").read_text())["overview"].startswith("Grids calm")


def test_a_long_video_is_read_part_by_part_then_as_a_whole_from_the_creators_subtitles(tmp_path):
    store = Store(tmp_path / "m.db")
    url, folder = saved(store, tmp_path, meta={"duration": 3600})

    class Subs:  # yt-dlp asked for uploaded subtitles only: it writes a .vtt
        def _base(self):
            return ["yt-dlp"]

        def run(self, command, timeout):
            assert "--write-subs" in command and "--write-auto-subs" not in command
            out = Path(command[command.index("-o") + 1])
            Path(str(out) + ".en.vtt").write_text(VTT)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
    parts = [{"title": f"Part {n}", "summary": f"Part {n} says things.", "takeaways": [f"t{n}"], "quotes": [],
              "named": [{"name": f"Thing {n}", "kind": "book_media"}]} for n in range(1, 5)]
    ask = Answers(*parts, {"overview": "The whole talk, in four parts.", "takeaways": ["Keep it simple"], "quotes": []})
    item = next(i for i in store.due_for_brain() if i["canonical_url"] == url)
    result = deepdive.run(item, store, ask, ytdlp=Subs(), get_page=lambda u, h=None: (404, u, b""), get_profile=no_network,
                          frame_run=lambda c, t: SimpleNamespace(returncode=1))
    assert len(ask.asked) == 5 and [a[1] for a in ask.asked] == [deepdive.SECTION_SCHEMA] * 4 + [deepdive.OVERVIEW_SCHEMA]
    assert "Hello and welcome" in ask.asked[0][2][0]["text"] and "grids calm the eye" not in ask.asked[0][2][0]["text"]
    assert "PART 2 OF 4, from 15:00 to 30:00" in ask.asked[1][2][0]["text"]
    assert result["text_from"] == "the creator's subtitles" and len(result["sections"]) == 4
    assert result["sections"][1]["at"] == "15:00" and [n["at"] for n in result["named"]][:2] == ["0:00", "15:00"]


def test_once_per_post_and_its_words_reach_search_the_note_and_links(tmp_path):
    from magpiary.worker import _with_deep, deep_due

    store = Store(tmp_path / "m.db")
    url, folder = saved(store, tmp_path, meta={"source": "instagram", "duration": 30})
    item_id = store.id_for(url)
    assert store.queue_deep(item_id) and not store.queue_deep(item_id)  # already queued
    ask = Answers({"overview": "Quokka layouts explained.", "named": [{"name": "Grid Talk", "kind": "video"}, {"name": "Pebble", "kind": "tool"}]})
    notes = tmp_path / "notes"
    made = deep_due(store, notes, asker=ask)
    assert made == 1 and store.item_by_id(item_id)["deep_status"] == "done"
    assert not store.queue_deep(item_id)  # once per post
    assert any(r["canonical_url"] == url for r in store.hub_items(query="quokka"))
    assert "## Deeper dive" in (notes / f"{folder.name}.md").read_text()
    merged = _with_deep(json.loads((folder / "record.json").read_text()), folder)
    assert {"name": "Pebble", "kind": "tool", "role": "passing"} in merged["link_targets"]
    assert merged["list_items"][0]["name"] == "Grid Talk"


def test_a_failed_deeper_dive_can_be_tried_again(tmp_path):
    from magpiary.brain import BrainFailed
    from magpiary.worker import deep_due

    store = Store(tmp_path / "m.db")
    url, _ = saved(store, tmp_path, meta={"source": "instagram", "duration": 30})
    item_id = store.id_for(url)
    store.queue_deep(item_id)

    def broken(*a):
        raise BrainFailed("busy", "the service is busy")
    deep_due(store, tmp_path / "notes", asker=broken)
    item = store.item_by_id(item_id)
    assert item["deep_status"] == "failed" and "busy" in item["deep_detail"]
    assert store.queue_deep(item_id)


def test_bio_links_are_remembered_a_week_and_a_refusal_gives_none(tmp_path):
    store = Store(tmp_path / "m.db")
    calls = []

    def profile(url):
        calls.append(url)
        return 200, b'<meta name="description" content="Links: https://shop.example.com">'
    assert deepdive.bio_links(store, "instagram", "pebble.notes", profile, now=1000) == ["https://shop.example.com"]
    assert deepdive.bio_links(store, "instagram", "pebble.notes", profile, now=2000) == ["https://shop.example.com"]
    assert calls == ["https://www.instagram.com/pebble.notes/"]  # remembered
    assert deepdive.bio_links(store, "threads", "someone", lambda u: (403, b""), now=1000) == []
    assert deepdive.bio_links(store, "reddit", "x", profile) == [] and deepdive.bio_links(store, "x", "bad/handle", profile) == []


def test_the_tab_shows_only_when_on_and_asks_first_for_big_ones(mac, tmp_path):
    url, folder = saved(mac.store, tmp_path, meta={"duration": 7200})
    mac.store.brain_succeeded(url, json.loads((folder / "record.json").read_text()), "", apply_tags=False)
    item_id = mac.store.id_for(url)
    assert 'data-tab="deep"' not in page(mac, f"/item/{item_id}")[2]  # off by default
    mac.store.set_setting(deepdive.ON, "1")
    mac.store.set_setting(deepdive.ENGINE, "claude_code")
    body = page(mac, f"/item/{item_id}?tab=deep")[2]
    assert 'action="/hub/deep"' in body and "data-confirm=" in body and "about 9 AI calls" in body and "Suggested" in body
    post(mac, "/hub/deep", id=str(item_id), next=f"/item/{item_id}?tab=deep")
    assert mac.store.item_by_id(item_id)["deep_status"] == "queued"
    assert "Deeper dive under way" in page(mac, f"/item/{item_id}?tab=deep")[2]
