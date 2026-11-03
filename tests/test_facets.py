"""Facets, search that reads what was typed, saved views: fictional posts, no AI and no network."""

import json
from datetime import date

from magpiary import brain, facets
from magpiary.query import understand
from test_hub import archive, page, post
from test_hub import lib  # noqa: F401  (the fixture)

KNOWN = {"setting": {"kitchen": 2, "gym": 1}, "mood": {"calm": 2}, "format": {"screen recording": 1, "talking head": 1}}
TODAY = date(2026, 11, 3)


def test_tidy_facets_keeps_known_keys_short_lowercase_and_unique():
    got = facets.tidy_facets({"setting": ["Kitchen.", "kitchen", " Bright   Room "], "bogus": ["x"], "mood": "Calm",
                              "people": ["a" * 100]})
    assert got["setting"] == ["kitchen", "bright room"] and got["mood"] == ["calm"] and "bogus" not in got
    assert len(got["people"][0]) == facets.MAX_LEN
    assert facets.tidy_facets("nonsense") == {}


def test_brain_tidy_carries_the_look_and_facets():
    record = brain.tidy({"title": "T", "summary": "S", "key_points": [], "type": "other",
                         "look": "  A man  chops garlic.  ", "facets": {"setting": ["Kitchen"]}})
    assert record["look"] == "A man chops garlic." and record["facets"] == {"setting": ["kitchen"]}


def test_length_and_plain_format_need_no_ai():
    assert facets.local_facets(12, True, True) == {"length": ["short"]}
    assert facets.local_facets(600, False, True) == {"length": ["long"], "format": ["text on screen"]}
    assert facets.local_facets(None, True, False) == {}


def test_understand_reads_dates_sources_types_and_known_facets():
    got = understand("calm recipe from last month on instagram", KNOWN, today=TODAY)
    kinds = {p.kind: p.value for p in got.parts}
    assert kinds == {"facet": "calm", "type": "recipe", "date": "last month", "source": "instagram"}
    assert (got.since, got.until) == (date(2026, 10, 1), date(2026, 10, 31)) and got.rest == ""


def test_understand_leaves_unknown_words_and_honours_removed_parts():
    got = understand("kitchen pasta", KNOWN, today=TODAY)
    assert [p.value for p in got.parts] == ["kitchen"] and got.rest == "pasta"
    kept = understand("kitchen pasta", KNOWN, today=TODAY, no={"facet:setting:kitchen"})
    assert kept.parts == [] and kept.rest == "kitchen pasta"
    assert understand("a plain question", KNOWN, today=TODAY).rest == "a plain question"


def test_months_and_longest_facet_first():
    got = understand("screen recording in october", KNOWN, today=TODAY)
    assert {p.value for p in got.parts} == {"screen recording", "in october"}
    assert (got.since, got.until) == (date(2026, 10, 1), date(2026, 10, 31))


def test_owner_edits_survive_and_a_removed_value_stays_removed(mac, tmp_path, lib):  # noqa: F811
    store, url = mac.store, mac.store.item_by_id(lib["ig"])["canonical_url"]
    store.save_facets(url, {"setting": ["kitchen"], "mood": ["calm"]})
    store.add_facet(url, "setting", "Garden")
    store.remove_facet(url, "mood", "calm")
    store.save_facets(url, {"setting": ["kitchen"], "mood": ["calm"]})  # the summary is run again
    assert store.facets_for(url) == {"setting": ["garden", "kitchen"]}
    assert store.urls_with_facets([("setting", "garden"), ("setting", "kitchen")]) == {url}
    assert store.urls_with_facets([("mood", "calm")]) == set()


def test_search_shows_what_it_read_and_a_view_can_be_saved(mac, tmp_path, lib):  # noqa: F811
    store, url = mac.store, mac.store.item_by_id(lib["ig"])["canonical_url"]
    store.save_facets(url, {"setting": ["kitchen"]})
    status, _, body = page(mac, "/?q=kitchen+on+instagram")
    assert status == 200 and "Read as" in body and "1 found" in body and "Pasta carbonara" in body
    assert "Rust tutorial" not in body
    _, _, body = page(mac, "/?q=kitchen+on+instagram&no=source%3Asource%3Ainstagram")
    assert "Read as" in body and 'class="uchip"' in body and "Instagram<i" not in body  # the source is plain words again
    post(mac, "/hub/view/save", q="kitchen", no="")
    assert [v["name"] for v in store.views()] == ["kitchen"]
    data = json.loads(page(mac, "/search.json?q=")[2])
    assert data["views"] == [{"id": store.views()[0]["id"], "name": "kitchen", "q": "kitchen", "no": "", "n": 1}]
    post(mac, "/hub/view/delete", view=str(store.views()[0]["id"]))
    assert store.views() == []


def test_the_look_is_searchable_and_shown_on_the_post(mac, tmp_path, lib):  # noqa: F811
    store = mac.store
    item = store.item_by_id(lib["ig"])
    record = {"title": "Pasta", "summary": "Carbonara", "type": "recipe", "key_points": [], "suggested_tags": [], "entities": {},
              "look": "A man cooks under yellow captions.", "facets": {"mood": ["calm"]}}
    store.brain_succeeded(item["canonical_url"], brain.tidy(record), "", apply_tags=False)
    assert "1 found" in page(mac, "/?q=yellow+captions")[2]
    card = page(mac, f"/item/{lib['ig']}")[2]
    assert "A man cooks under yellow captions." in card and "<small>Mood</small>" in card and "calm" in card
    store.remove_facet(item["canonical_url"], "mood", "calm")
    assert '<small>Mood</small>' not in page(mac, f"/item/{lib['ig']}")[2]
