"""Contextual post tabs: the registry, the view model, the store's view columns, the /hub/pv routes and the post view's
tab row. Fictional posts only."""

import json
import sqlite3
import stat

import pytest

from magpiary import categories as cats
from magpiary import views
from magpiary.store import Store

from test_hub import archive, page, post, request

RECIPE_URL = "https://www.instagram.com/reel/ExampleRecipe1/"


# ---- registry ------------------------------------------------------------------------------------------------------

def test_the_registry_is_clean_and_has_every_category():
    assert cats.check() == []
    assert len(cats.CATEGORIES) == 23 and "other" in cats.CATEGORIES
    assert not set(cats.TABS) & set(cats.CORE)
    assert all("mobbin" not in t.providers for t in cats.TABS.values())  # dead search URL (research, 14 Nov)
    assert cats.CATEGORIES["recipe"].tabs[:2] == ("ingredients", "method")


def test_the_ai_prompt_names_every_category_and_its_lent_tab():
    prompt = views.ai_prompt()
    for c in cats.CATEGORIES.values():
        assert f"  {c.id}: " in prompt
        if c.tabs:
            assert f"{c.id} (lends {c.lend})" in prompt
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
    chapters = views.free_view("howto_diy", "", {}, {"chapters": [{"title": "Prep", "start_time": 75}]})
    assert chapters["tabs"]["steps"]["items"] == [{"name": "Prep", "at": "1:15"}]
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
    assert visible == ["read", "sum", "deep", "ingredients", "det"] and more == ["method", "rel"]


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
