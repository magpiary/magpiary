"""Contextual post tabs: the registry, the view model, the store's view columns, the /hub/pv routes and the post view's
tab row. Fictional posts only."""

import json
import sqlite3
import stat
from pathlib import Path

import pytest

from magpiary import categories as cats
from magpiary import views
from magpiary.store import Store

from test_hub import archive, lib, page, post, request  # noqa: F401  (lib is a fixture)

RECIPE_URL = "https://www.instagram.com/reel/ExampleRecipe1/"


# ---- registry ------------------------------------------------------------------------------------------------------

def test_the_registry_is_clean_and_has_every_category():
    assert cats.check() == []
    assert len(cats.CATEGORIES) == 23 and "other" in cats.CATEGORIES
    assert not set(cats.TABS) & set(cats.CORE)
    assert all("mobbin" not in t.providers for t in cats.TABS.values())  # dead search URL (research, 14 Nov)
    assert cats.CATEGORIES["recipe"].tabs[:2] == ("ingredients", "method")


def test_the_ai_schema_names_every_category():
    schema = views.ai_schema()
    assert schema["category"]["enum"] == list(cats.IDS)


# ---- shape ----------------------------------------------------------------------------------------------------------

def test_tidy_view_caps_and_drops_junk():
    long = "x" * 900
    raw = {"category": "nonsense", "category2": "recipe", "tabs": {
        "ingredients": {"text": "", "items": ["flour", {"name": "eggs", "amount": "2", "bogus": "y"}, {"detail": "no name"},
                                              7, {"name": "flour"}, {"name": long, "detail": long}] + [f"i{n}" for n in range(60)]},
        "read": {"items": ["core tab ids are not category tabs"]},
        "unknown_tab": {"items": ["x"]},
        "method": {"text": "", "items": []},
        "swaps": "not a dict"}}
    view = views.tidy_view(raw, by="rules")
    assert view["category"] == "other" and view["category2"] == "recipe" and view["by"] == "rules"
    assert set(view["tabs"]) == {"ingredients"}
    items = view["tabs"]["ingredients"]["items"]
    assert items[0] == {"name": "flour"} and items[1] == {"name": "eggs", "amount": "2"}
    assert len(items) == views.MAX_ITEMS and all(len(i["name"]) <= 200 and len(i.get("detail", "")) <= 400 for i in items)
    assert views.tidy_view({"category": "recipe", "category2": "recipe"})["category2"] == ""
    assert views.tidy_view("garbage")["category"] == "other"
    many = {t: {"items": ["a"]} for t in list(cats.TABS)[:20]}
    assert len(views.tidy_view({"tabs": many})["tabs"]) == views.MAX_TABS


def test_save_writes_a_private_file_whole(tmp_path):
    view = views.tidy_view({"category": "recipe", "tabs": {"ingredients": {"items": ["flour"]}}}, engine="test:model")
    views.save(tmp_path, view)
    path = tmp_path / views.FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob(".view-*"))
    loaded = views.load(tmp_path)
    assert loaded["tabs"]["ingredients"]["items"] == [{"name": "flour"}] and loaded["engine"] == "test:model"
    path.write_text('{"version": 99}')
    assert views.load(tmp_path) is None and views.load(None) is None


# ---- category by rules ---------------------------------------------------------------------------------------------

GUESSES = [
    ("recipe", {"type": "recipe", "title": "Weeknight lemon pasta", "suggested_tags": ["recipe", "dinner"]}),
    ("music", {"type": "other", "format": "list", "title": "Five albums for a rainy day",
               "list_items": [{"name": "Album One", "kind": "music"}, {"name": "Album Two", "kind": "music"}]}),
    ("travel", {"type": "place", "title": "Three days on a quiet island", "suggested_tags": ["travel", "itinerary"]}),
    ("food_places", {"type": "place", "title": "Where to eat in the old town", "suggested_tags": ["restaurant", "street food"]}),
    ("ai_coding", {"type": "tool", "title": "A prompt that writes your tests", "suggested_tags": ["ai", "prompt", "coding"]}),
    ("gadgets", {"type": "tool", "format": "review", "title": "Example Phone 3 review", "suggested_tags": ["phone", "camera"]}),
    ("film_tv", {"type": "other", "format": "list", "title": "Films for a cosy night",
                 "list_items": [{"name": "Film A", "kind": "film"}, {"name": "Show B", "kind": "show"}]}),
    ("fitness", {"type": "howto", "title": "20 minute leg workout", "suggested_tags": ["workout", "squat", "gym"]}),
    ("news_opinion", {"type": "news_opinion", "format": "news", "title": "The new city transport policy explained"}),
    ("other", {"type": "other", "title": "My cat being silly", "suggested_tags": ["cat", "funny"]}),
]


@pytest.mark.parametrize("want,record", GUESSES, ids=[g[0] for g in GUESSES])
def test_guess_picks_the_category_from_what_is_known(want, record):
    assert views.guess(record)[0] == want


def test_guess_finds_a_second_category_in_another_group():
    record = {"type": "place", "title": "Food crawl and things to do in an old port city",
              "suggested_tags": ["travel", "street food", "restaurant", "itinerary", "cafe"]}
    assert views.guess(record) == ("travel", "")  # food_places scores as high but is in the same group: no lent tab
    assert views.guess({"type": "recipe", "title": "Pasta night", "suggested_tags": ["recipe", "song", "playlist", "album"]}) \
        == ("recipe", "music")


# ---- tabs without AI -------------------------------------------------------------------------------------------------

def test_free_view_fills_what_it_can_without_ai():
    record = {"type": "recipe", "extras": {"ingredients": ["200 g pasta", "2 lemons"], "steps": ["Boil", "Toss"]},
              "list_items": [{"name": "Song X", "kind": "music", "by": "Band Y"}],
              "link_targets": [{"name": "Corner Café", "kind": "place", "what": "breakfast"}, {"kind": "place"}]}
    view = views.free_view("recipe", "music", record, {})
    assert [i["name"] for i in view["tabs"]["ingredients"]["items"]] == ["200 g pasta", "2 lemons"]
    assert [i["name"] for i in view["tabs"]["method"]["items"]] == ["Boil", "Toss"]
    assert view["tabs"]["tracks"]["items"] == [{"name": "Song X", "detail": "Band Y", "kind": "music"}]
    assert view["by"] == "rules" and views.needs_build(view)
    # the real meta shape, from the source adapter (review 14 Nov 2026: the test used yt-dlp's start_time and hid it)
    from magpiary.sources import _from_info

    meta = _from_info({"title": "t", "chapters": [{"start_time": 75.0, "end_time": 90, "title": "Prep"},
                                                  {"start_time": 0, "title": "Intro"}]})
    assert meta["chapters"][0] == {"start": 75.0, "title": "Prep"}
    chapters = views.free_view("howto_diy", "", {}, meta)
    assert chapters["tabs"]["steps"]["items"] == [{"name": "Prep", "at": "1:15"}, {"name": "Intro", "at": "0:00"}]
    places = views.free_view("travel", "", {"link_targets": [{"name": "Lighthouse", "kind": "place"}],
                                            "entities": {"places": ["Lighthouse", "Harbour"]}}, {})
    assert [i["name"] for i in places["tabs"]["places"]["items"]] == ["Lighthouse", "Harbour"]
    assert views.free_view("other", "", record, {})["tabs"] == {}


def test_needs_build_until_an_ai_built_the_view():
    assert views.needs_build({"category": "recipe", "by": "rules"})
    assert views.needs_build({"category": "recipe", "by": "owner"})
    assert not views.needs_build({"category": "recipe", "by": "owner", "engine": "gemini:x"})
    assert not views.needs_build({"category": "recipe", "by": "ai", "engine": "gemini:x"})
    assert not views.needs_build({"category": "other", "by": "rules"})
    # review 14 Nov: a free view under a category the summary chose (by "ai") was built by nobody
    assert views.needs_build({"category": "recipe", "by": "ai", "engine": ""})


def test_tidy_items_keeps_distinct_items_that_share_a_name():
    """Review 14 Nov: Hello by Adele and Hello by Lionel Richie were merged into one song."""
    items = views.tidy_items([{"name": "Hello", "detail": "Adele"}, {"name": "Hello", "detail": "Lionel Richie"},
                              {"name": "Hello", "detail": "adele"}, {"name": "Tea", "amount": "1 tsp"},
                              {"name": "Tea", "amount": "2 tsp"}, {"name": "Hello", "detail": "Adele"}])
    assert [(i["name"], i.get("detail") or i.get("amount")) for i in items] == [
        ("Hello", "Adele"), ("Hello", "Lionel Richie"), ("Tea", "1 tsp"), ("Tea", "2 tsp")]


@pytest.mark.parametrize("broken", [
    {"category": ["recipe"]}, {"category2": {"x": 1}}, {"by": ["ai"]},
    {"tabs": [{"tab": ["ingredients"], "items": [{"name": "x"}]}, {"tab": 5}]},
    {"lookups": {"tracks": ["invalid"]}}, {"lookups": {"tracks": {"hello": ["x"], "bye": {"musicbrainz": "ok"}}}},
    {"lookups": ["x"]}, {"tabs": {"ingredients": {"items": "flour", "text": ["x"]}}}])
def test_a_malformed_view_file_never_breaks_loading(tmp_path, broken):
    """Review 14 Nov: a list as category or tab id raised TypeError in load (the wall); a list in lookups broke the worker."""
    (tmp_path / views.FILE).write_text(json.dumps({"version": 1, "category": "recipe", "engine": "e",
                                                   "tabs": {"ingredients": {"items": [{"name": "salt"}]}}} | broken))
    view = views.load(tmp_path)
    assert view is not None and isinstance(view["category"], str) and isinstance(view["by"], str)
    assert all(isinstance(t, str) and isinstance(b, dict) for t, b in view["tabs"].items())
    for keys in view["lookups"].values():
        assert all(isinstance(k, str) and all(isinstance(e, dict) for e in apis.values()) for k, apis in keys.items())
    from magpiary import lookups

    lookups.wanted(view, "2026-11-14")  # the worker's planning step
    item = {"id": 1, "category": None, "category_by": None}
    assert views.current(item, {}, {}, tmp_path)["category"]


# ---- tab order -------------------------------------------------------------------------------------------------------

def _view(category, tabs, second=""):
    return {"category": category, "category2": second, "tabs": {t: {"text": "", "items": [{"name": "x"}]} for t in tabs}}


def test_tab_plan_order_cap_and_more():
    full = {"read": False, "deep": False, "links": True, "rel": True, "tr": True}
    visible, more = views.tab_plan(_view("recipe", ["ingredients", "method", "swaps", "equipment"]), full)
    assert visible == ["sum", "ingredients", "method", "swaps", "det"]
    assert more == ["equipment", "links", "rel", "tr"]
    visible, more = views.tab_plan(_view("recipe", ["method"]), {"rel": True})
    assert visible == ["sum", "method", "rel", "det"] and more == []
    visible, more = views.tab_plan(_view("other", []), {})
    assert visible == ["sum", "det"] and more == []


def test_tab_plan_puts_read_first_and_counts_it():
    visible, more = views.tab_plan(_view("recipe", ["ingredients", "method"]), {"read": True, "deep": True, "rel": True})
    assert visible == ["read", "sum", "ingredients", "method", "det"] and more == ["deep", "rel"]


def test_tab_plan_never_gives_a_category_slot_to_deeper_dive():
    # real-post test, 14 Nov: Deeper dive took a slot, so only 2 category tabs showed before More
    core = {"deep": True, "links": True, "rel": True, "tr": True}
    visible, more = views.tab_plan(_view("recipe", ["ingredients", "method", "swaps", "equipment"]), core)
    assert visible == ["sum", "ingredients", "method", "swaps", "det"]
    assert more == ["equipment", "deep", "links", "rel", "tr"]
    visible, more = views.tab_plan(_view("recipe", ["method"]), core)
    assert visible == ["sum", "method", "deep", "links", "det"] and more == ["rel", "tr"]


def test_tab_plan_skips_empty_and_owner_hidden_tabs():
    view = _view("recipe", ["ingredients", "method", "swaps"])
    view["tabs"]["swaps"] = {"text": "", "items": []}
    visible, more = views.tab_plan(view, {}, {"recipe": ["ingredients"]})
    assert visible == ["sum", "method", "det"] and more == []


def test_tab_plan_adds_the_lent_tab_of_the_second_category():
    view = _view("travel", ["places", "itinerary", "spots"], second="food_places")
    visible, _ = views.tab_plan(view, {})
    assert visible == ["sum", "places", "itinerary", "spots", "det"]
    assert views.tab_plan(view, {}, {"food_places": ["spots"]})[0] == ["sum", "places", "itinerary", "det"]
    assert "tips" not in views.tab_plan(_view("travel", ["places", "tips"], second="food_places"), {})[0][3:]


def test_hidden_tabs_setting_ignores_junk():
    assert views.hidden_tabs('{"recipe": ["swaps", 3, {"a": 1}, "nope"], "nope": ["swaps"], "music": "tracks"}') \
        == {"recipe": ["swaps"]}
    assert views.hidden_tabs("not json") == {} and views.hidden_tabs("[1]") == {} and views.hidden_tabs("") == {}


# ---- store -----------------------------------------------------------------------------------------------------------

def test_store_migrates_an_older_database_safely(tmp_path):
    path = tmp_path / "old.db"
    Store(path).close()
    db = sqlite3.connect(path)  # an older database: the new columns and table are missing, one save is there
    for col in ("category", "category2", "category_by", "view_status", "view_detail"):
        db.execute(f"ALTER TABLE items DROP COLUMN {col}")
    db.execute("DROP TABLE view_state")
    db.execute("INSERT INTO items (canonical_url, source, status, created_at, updated_at) "
               "VALUES ('https://example.com/p/1', 'web', 'archived', '2026-11-01', '2026-11-01')")
    db.commit()
    db.close()
    store = Store(path)
    item_id = store.id_for("https://example.com/p/1")
    item = store.item_by_id(item_id)
    assert item["category"] is None and item["view_status"] is None and item["view_detail"] == ""
    assert store.view_state("https://example.com/p/1") == {}
    store.close()
    Store(path).close()  # opening again changes nothing


def test_store_category_state_queue_and_hidden_tabs(tmp_path):
    store = Store(tmp_path / "m.db")
    url = "https://example.com/p/2"
    store.add_link(url)
    item_id = store.id_for(url)
    assert store.set_category(item_id, "recipe", "recipe", "rules")
    assert store.item_by_id(item_id)["category2"] == ""
    assert not store.set_category(item_id, "nonsense", "", "ai") and not store.set_category(item_id, "music", "", "nobody")
    assert store.set_category(item_id, "travel", "food_places", "owner")
    assert not store.set_category(item_id, "music", "", "ai")  # the owner's choice stays
    assert store.item_by_id(item_id)["category"] == "travel"
    store.set_view_state(url, "ingredients", "0", "1")
    store.set_view_state(url, "ingredients", "servings", "4")
    store.set_view_state(url, "ingredients", "0", "1")
    assert store.view_state(url) == {"ingredients": {"0": "1", "servings": "4"}}
    store.set_view_state(url, "ingredients", "0", "")
    assert store.view_state(url) == {"ingredients": {"servings": "4"}}
    assert store.queue_view(item_id) and not store.queue_view(item_id)
    assert [i["id"] for i in store.views_due_items(5)] == [item_id]
    store.set_view_status(item_id, "done")
    assert store.views_due_items() == [] and store.queue_view(item_id)
    assert store.hidden_tabs() == {}
    assert store.set_hidden_tabs({"recipe": ["swaps", "swaps", "bogus"], "x": ["y"]}) == {"recipe": ["swaps"]}
    assert store.hidden_tabs() == {"recipe": ["swaps"]}
    store.close()


def test_deleting_for_good_removes_ticks_and_old_orphans_are_cleaned(tmp_path):
    """Review 14 Nov: purge_trash left view_state rows (the URL and ticks) after the post was deleted for good."""
    path = tmp_path / "m.db"
    store = Store(path)
    url, other = "https://example.com/p/3", "https://example.com/p/4"
    store.add_link(url)
    store.add_link(other)
    store.set_view_state(url, "ingredients", "i.abc", "1")
    store.set_view_state(other, "ingredients", "i.abc", "1")
    store.set_shelf(store.id_for(url), "trash")
    store.purge_trash(everything=True)
    assert store.view_state(url) == {} and store.view_state(other) == {"ingredients": {"i.abc": "1"}}
    store._db.execute("INSERT INTO view_state VALUES ('https://example.com/gone', 'method', 'i.x', '1', '')")
    store.close()
    store = Store(path)  # opening cleans rows left by an older version
    assert store.view_state("https://example.com/gone") == {} and store.view_state(other)
    store.close()


# ---- the post view over HTTP ----------------------------------------------------------------------------------------

RECORD = {"title": "Ten-minute lemon pasta", "summary": "A quick pasta.", "key_points": [], "type": "recipe",
          "entities": {}, "suggested_tags": ["recipe"],
          "extras": {"ingredients": ["200 g pasta", "1 lemon"], "steps": ["Boil the pasta", "Add the lemon"]}}
VIEW = {"version": 1, "category": "recipe", "category2": "", "by": "ai", "engine": "test:model", "made_at": "2026-11-14T10:00:00",
        "tabs": {"ingredients": {"text": "", "items": [{"name": "Pasta", "amount": "200 g"}, {"name": "<b>Lemon</b>"}]},
                 "method": {"text": "", "items": [{"name": "Boil the pasta", "at": "0:05"}]},
                 "swaps": {"text": "Use lime instead.", "items": [{"name": "Lime for lemon", "kind": "swap"}]},
                 "equipment": {"text": "", "items": [{"name": "Large pot"}]}}, "lookups": {}}


@pytest.fixture
def recipe(mac, tmp_path):
    item_id, folder = archive(mac, tmp_path, RECIPE_URL, "instagram",
                              {"text": "Lemon pasta in ten minutes", "author": "Cook Example", "duration": 40.0},
                              {"record.json": json.dumps(RECORD).encode()})
    return item_id, folder


def _nav(body):
    nav = body[body.index('<nav class="tabs pvtabs"'):]
    return nav[:nav.index("</nav>")]


def test_a_recipe_post_shows_its_tabs_in_order_with_more(mac, recipe):
    item_id, folder = recipe
    views.save(folder, VIEW)
    body = page(mac, f"/item/{item_id}")[2]
    nav = _nav(body)
    order = [nav.index(f">{label}") for label in ("Summary", "Ingredients", "Method", "Swaps &amp; notes", "Details", "More")]
    assert order == sorted(order)
    more = nav[nav.index('<details class="pvmore'):]
    assert "Equipment" in more and "Related" in more
    assert "Transcript" not in nav and ">Links<" not in nav  # no speech, no links: hidden, not greyed
    assert 'data-pane="equipment"' in body and "Large pot" in body
    assert "&lt;b&gt;Lemon&lt;/b&gt;" in body and "<b>Lemon</b>" not in body  # AI text is escaped
    assert "Build this view" not in body
    assert "/static/views.css" in body and "/static/views.js" in body
    assert request(mac, "GET", "/static/views.js")[0] == 200


def test_an_unbuilt_recipe_offers_build_this_view(mac, recipe, monkeypatch):
    from magpiary import engines
    monkeypatch.setattr(engines, "options", lambda store, *a, **k: [{"id": "test", "kind": "key", "key": None, "label": "Test", "free": False}])  # Smart with something that can write
    item_id, _ = recipe
    body = page(mac, f"/item/{item_id}")[2]
    nav = _nav(body)
    assert nav.index(">Ingredients") < nav.index(">Method") < nav.index(">Details")  # free tabs from the summary's extras
    assert 'action="/hub/pv/build"' in body and "Build this view" in body
    from magpiary import modes
    mac.store.set_setting(modes.SETTING, "private")
    assert "Build this view" not in page(mac, f"/item/{item_id}")[2]


def test_pv_routes_validate_and_reply(mac, recipe, monkeypatch):
    item_id, _ = recipe
    status, _, data = post(mac, "/hub/pv/state", id=item_id, tab="ingredients", key="0", value="1")
    assert status == 200 and json.loads(data) == {"ok": True}
    assert mac.store.view_state(RECIPE_URL) == {"ingredients": {"0": "1"}}
    assert post(mac, "/hub/pv/state", id=item_id, tab="nope", key="0", value="1")[0] == 400
    assert post(mac, "/hub/pv/state", id=item_id, tab="ingredients", key="bad key!", value="1")[0] == 400
    assert post(mac, "/hub/pv/state", id=item_id, tab="ingredients", key="0", value="x" * 201)[0] == 400
    assert post(mac, "/hub/pv/state", id=999, tab="ingredients", key="0", value="1")[0] == 404
    assert request(mac, "POST", "/hub/pv/state", {"csrf": "wrong", "id": item_id, "tab": "ingredients", "key": "0",
                                                  "value": "1"})[0] == 403
    from magpiary import engines, modes
    monkeypatch.setattr(engines, "options", lambda store, *a, **k: [{"id": "test", "kind": "key", "key": None, "label": "Test", "free": False}])  # Smart with something that can write
    status, _, data = post(mac, "/hub/pv/build", id=item_id)
    assert status == 200 and json.loads(data)["detail"] == "queued"
    assert json.loads(post(mac, "/hub/pv/build", id=item_id)[2])["detail"] == "already queued"
    assert post(mac, "/hub/pv/category", id=item_id, category="nope")[0] == 400
    status, headers, _ = post(mac, "/hub/pv/category", id=item_id, category="food_places", next=f"/item/{item_id}")
    assert status == 303 and headers["Location"] == f"/item/{item_id}"
    item = mac.store.item_by_id(item_id)
    assert (item["category"], item["category_by"]) == ("food_places", "owner")
    assert "Building the" in page(mac, f"/item/{item_id}")[2]
    mac.store.set_view_status(item_id, "done")
    mac.store.set_setting(modes.SETTING, "private")
    assert json.loads(post(mac, "/hub/pv/build", id=item_id)[2]) == {"ok": False, "detail": "private"}
    assert json.loads(post(mac, "/hub/pv/category", id=item_id, category="recipe")[2]) == {"ok": True}
    assert mac.store.item_by_id(item_id)["view_status"] == "done"  # Private: nothing queued


def test_private_change_category_to_ai_only_tabs_says_why(mac, recipe):
    """Sandbox, 14 Nov: in Private mode, Change category to a category no free source fills left Summary and Details with
    no hint; now the Summary says the tabs are written by AI. A category with free tabs (recipe) shows no hint."""
    from magpiary import modes
    item_id, _ = recipe
    mac.store.set_setting(modes.SETTING, "private")
    hint = "This category’s tabs are written by AI. Turn on Smart mode to build them."
    post(mac, "/hub/pv/category", id=item_id, category="news_opinion")
    body = page(mac, f"/item/{item_id}")[2]
    assert hint in body and "Build this view" not in body and 'href="/settings/ai"' in body
    post(mac, "/hub/pv/category", id=item_id, category="recipe")
    assert hint not in page(mac, f"/item/{item_id}")[2]  # its ingredients fill without AI
    post(mac, "/hub/pv/category", id=item_id, category="other")
    assert hint not in page(mac, f"/item/{item_id}")[2]  # nothing to build
    mac.store.set_setting(modes.SETTING, "smart")  # chosen, but no key: nothing can write
    post(mac, "/hub/pv/category", id=item_id, category="news_opinion")
    body = page(mac, f"/item/{item_id}")[2]
    assert hint not in body and "This category’s tabs are written by AI. Add an AI key to build them." in body


def test_private_mode_offers_no_link_search_and_the_worker_sends_none(mac, lib):
    """Sandbox, 14 Nov: "Find the link for git" showed in Private mode and would have searched GitHub, Wikidata and the
    web for it. Private links only what the post itself writes (specs, Links v2 section 8)."""
    from magpiary import modes, worker
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({"title": "A git trick", "summary": "s", "type": "tool", "key_points": [],
                                                    "suggested_tags": [], "entities": {"tools": ["git"]}}))
    mac.store._db.execute("UPDATE items SET ai_status='done', links_status='done' WHERE rowid=?", (lib["ig"],))
    assert "Find the link for git" in page(mac, f"/item/{lib['ig']}")[2]
    mac.store.set_setting(modes.SETTING, "private")
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert "Find the link" not in body and "Add a link yourself" in body
    mac.store.add_link_by_owner(lib["ig"], "Example docs", "https://docs.example.com", "links")  # so the Links tab shows
    body = page(mac, f"/item/{lib['ig']}?tab=links")[2]
    assert "Find more links" not in body and "Private mode: Magpiary looks up no links." in body
    post(mac, "/hub/links/again", id=lib["ig"])
    assert not mac.store.item_by_id(lib["ig"])["links_force"]
    mac.store._db.execute("UPDATE items SET links_force=1 WHERE rowid=?", (lib["ig"],))  # asked for before Private

    def no_network(*a, **k):
        raise AssertionError("a link search ran in Private mode")
    assert worker.links_due(mac.store, get=no_network, pause=lambda s: None) == 0
    assert mac.store.item_by_id(lib["ig"])["links_force"] == 1  # it waits for Smart
