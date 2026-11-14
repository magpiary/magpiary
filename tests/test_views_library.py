"""Contextual post tabs outside the post view (owner decisions 6 and 11, 14 Nov 2026): the category on wall tiles, the
Category filter and search words, Change category in a post's ... menu, Settings > Advanced > Post tabs by category, and
Ask's category starters. Fictional posts only."""

import html
import json
import random
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from magpiary import categories as cats
from magpiary import hub_wall, views
from magpiary.hub_ask import suggestions
from magpiary.query import understand

from test_hub import archive, page, post
from test_views import GUESSES

RECIPE = "https://www.instagram.com/reel/ExampleLibRecipe/"
SONGS = "https://www.instagram.com/reel/ExampleLibSongs/"
CAT = "https://www.instagram.com/reel/ExampleLibCat/"


# ---- views.scores (one token pass) gives the points of the plain whole-word rule it replaced ----------------------

def _reference_scores(record, meta=None):
    """The first rules scorer: one whole-word regex per category word (about 3 ms a post). The oracle for views.scores."""
    from magpiary.brain import type_of
    kind = type_of(record) if record.get("type") else ""
    kinds = [x.get("kind") for x in record.get("list_items") or [] if isinstance(x, dict)]
    text = views._text(record, meta, None)
    out = {}
    for c in cats.CATEGORIES.values():
        s = (2 if kind and kind in c.types else 0) + (1 if record.get("format") and record["format"] in c.formats else 0)
        s += min(6, 2 * sum(1 for k in kinds if k in c.list_kinds))
        s += min(4, sum(1 for w in c.words if re.search(r"(?<![a-z0-9])" + re.escape(w.strip()) + r"(?![a-z0-9])", text)))
        if s:
            out[c.id] = s
    return out


@pytest.mark.parametrize("want,record", GUESSES, ids=[g[0] for g in GUESSES])
def test_scores_match_the_reference_rule(want, record):
    assert views.scores(record) == _reference_scores(record)
    assert views.guess(record)[0] == want


def test_scores_match_on_every_category_word():
    words = [w for c in cats.CATEGORIES.values() for w in c.words]
    rng = random.Random(7)
    for _ in range(300):
        picked = rng.sample(words, 6)
        glue = rng.choice([" ", "-", ", ", "s ", "x"])
        record = {"title": glue.join(picked), "suggested_tags": rng.sample(words, 2), "type": rng.choice(["tool", "place", "other"])}
        meta = {"text": "Caption: " + " ".join(rng.sample(words, 4)) + " café!"}
        assert views.scores(record, meta) == _reference_scores(record, meta), record


# ---- a small library -------------------------------------------------------------------------------------------------

def _done(mac, url, ai_type, title):
    mac.store._db.execute("UPDATE items SET ai_status='done', ai_type=?, ai_title=? WHERE canonical_url=?", (ai_type, title, url))


@pytest.fixture
def lib(mac, tmp_path):
    recipe_id, recipe_dir = archive(mac, tmp_path, RECIPE, "instagram", {"text": "Lemon pasta in ten minutes", "author": "Cook Example"},
                                    {"record.json": json.dumps({"type": "recipe", "title": "Weeknight lemon pasta",
                                                                "suggested_tags": ["recipe", "dinner"]}).encode()})
    songs_id, _ = archive(mac, tmp_path, SONGS, "instagram", {"text": "Five albums for a rainy day", "author": "Music Example"},
                          {"record.json": json.dumps({"type": "other", "format": "list", "title": "Five albums for a rainy day",
                                                      "list_items": [{"name": "Album One", "kind": "music"},
                                                                     {"name": "Album Two", "kind": "music"}]}).encode()})
    cat_id, _ = archive(mac, tmp_path, CAT, "instagram", {"text": "My cat being silly", "author": "Pet Example"},
                        {"record.json": json.dumps({"type": "other", "title": "My cat being silly"}).encode()})
    _done(mac, RECIPE, "recipe", "Weeknight lemon pasta")
    _done(mac, SONGS, "other", "Five albums for a rainy day")
    _done(mac, CAT, "other", "My cat being silly")
    return {"recipe": recipe_id, "songs": songs_id, "cat": cat_id, "recipe_dir": recipe_dir}


def _tile(body, item_id):
    m = re.search(rf'<div class="tile[^"]*" data-id="{item_id}".*?(?=<div class="tile|</section>)', body, re.S)
    assert m, item_id
    return m.group(0)


def _kind(tile):
    m = re.search(r'<span class="kind(?: long)?"><i class="kd"[^>]*></i><span class="kn">([^<]*)</span></span>', tile)
    return html.unescape(m.group(1)) if m else ""


def _hrefs(html):
    return [h.replace("&amp;", "&") for h in re.findall(r'href="(/[^"]*)"', html)]


# ---- 1. the category on each tile ------------------------------------------------------------------------------------

def test_tiles_name_the_category(mac, lib):
    body = page(mac)[2]
    assert _kind(_tile(body, lib["recipe"])) == "Recipes" and 'data-cat="recipe"' in _tile(body, lib["recipe"])
    assert _kind(_tile(body, lib["songs"])) == "Music"
    assert _kind(_tile(body, lib["cat"])) == "Other"
    # a stored category wins over the rules, and the tile notices the change
    mac.store.set_category(lib["cat"], "fitness", by="ai")
    assert _kind(_tile(page(mac)[2], lib["cat"])) == "Fitness"


def test_a_built_view_and_the_owner_decide_the_tile(mac, lib):
    views.save(lib["recipe_dir"], views.tidy_view({"category": "food_places", "tabs": {}}, engine="test:model"))
    mac.store.set_view_status(lib["recipe"], "done")
    assert _kind(_tile(page(mac)[2], lib["recipe"])) == "Restaurants & cafés"
    mac.store.set_category(lib["recipe"], "travel", by="owner")
    assert _kind(_tile(page(mac)[2], lib["recipe"])) == "Travel"


def test_private_mode_tiles_show_the_rules_category(mac, lib):
    from magpiary import modes
    mac.store._db.execute("UPDATE items SET ai_status=NULL")
    mac.store.set_setting(modes.SETTING, "private")
    body = page(mac)[2]
    assert _kind(_tile(body, lib["recipe"])) == "Recipes"
    assert _kind(_tile(body, lib["cat"])) == ""  # "Other" says nothing without a summary


# ---- 2. the Category filter -----------------------------------------------------------------------------------------

def test_the_filter_lists_categories_with_counts_by_group(mac, lib):
    body = page(mac)[2]
    panel = body[body.index('<div class="fgroup fcats">'):]
    panel = panel[:panel.index('<div class="fgroup"><h5>')]
    assert "Travel &amp; food" in panel and "Music, film &amp; books" in panel
    chips = dict(re.findall(r'data-cat="(\w+)">([^<]+)<span class="n">', panel))
    assert chips == {"recipe": "Recipes", "music": "Music", "other": "Other"}
    counts = dict(re.findall(r'data-cat="(\w+)">[^<]+<span class="n">(\d+)</span>', panel))
    assert counts == {"recipe": "1", "music": "1", "other": "1"}


def test_filtering_by_category_and_the_url_round_trip(mac, lib):
    body = page(mac, "/?cat=music&source=instagram")[2]
    wall = body[body.index('id="wallbody"'):]
    assert f'data-id="{lib["songs"]}"' in wall and f'data-id="{lib["recipe"]}"' not in wall
    active = body[body.index('class="activef"'):]
    active = active[:active.index("</div>")]
    assert "Music" in active
    off = [h for h in _hrefs(active) if "source=instagram" in h and "cat=" not in h]
    assert off, "the Music chip's link drops only the category"
    recipe_chip = next(h for h in _hrefs(body) if "cat=recipe" in h)
    assert parse_qs(urlsplit(recipe_chip).query) == {"source": ["instagram"], "cat": ["recipe"]}
    assert f'data-id="{lib["recipe"]}"' in page(mac, recipe_chip)[2]
    # unknown values are ignored, and an empty category says so
    assert f'data-id="{lib["recipe"]}"' in page(mac, "/?cat=nonsense")[2]
    assert "Nothing matches these filters" in page(mac, "/?cat=fitness")[2]


def test_search_words_read_as_categories(mac, lib):
    got = understand("music from last month", {}, category_name=cats.name)
    assert [(p.kind, p.value, p.label) for p in got.parts if p.kind == "category"] == [("category", "music", "Music")]
    assert understand("recipes", {}).parts[0].kind == "type"  # a type word stays a type
    body = page(mac, "/?q=music")[2]
    assert f'data-id="{lib["songs"]}"' in body and f'data-id="{lib["recipe"]}"' not in body
    assert 'class="uchip"' in body and ">Music<" in body
    chip = re.search(r'<a class="uchip" href="([^"]+)"', body).group(1).replace("&amp;", "&")
    assert parse_qs(urlsplit(chip).query)["no"] == ["category:category:music"]  # the chip can be undone
    assert 'class="uchip"' not in page(mac, chip)[2]  # undone: "music" is searched as a word


# ---- 3. Change category ----------------------------------------------------------------------------------------------

def test_the_post_menu_changes_the_category(mac, lib):
    item_id = lib["cat"]
    body = page(mac, f"/item/{item_id}")[2]
    menu = body[body.index('<details class="catpick">'):]
    menu = menu[:menu.index("</details>")]
    assert 'action="/hub/pv/category"' in menu and f'name="id" value="{item_id}"' in menu
    assert '<span class="catnow">Other</span>' in menu
    values = re.findall(r'name="category" value="(\w+)"', menu)
    assert sorted(values) == sorted(cats.IDS)
    assert re.search(r'class="catopt on" aria-pressed="true">Other<', menu)
    next_ = re.search(r'name="next" value="([^"]+)"', menu).group(1)
    status, headers, _ = post(mac, "/hub/pv/category", id=item_id, category="books", next=next_)
    assert status == 303 and headers["Location"] == f"/item/{item_id}"
    item = mac.store.item_by_id(item_id)
    assert (item["category"], item["category_by"]) == ("books", "owner")
    assert '<span class="catnow">Books &amp; reading</span>' in page(mac, f"/item/{item_id}")[2]
    assert _kind(_tile(page(mac)[2], item_id)) == "Books & reading"


def test_no_category_menu_in_the_trash(mac, lib):
    mac.store._db.execute("UPDATE items SET shelf='trash' WHERE rowid=?", (lib["cat"],))
    assert 'class="catpick"' not in page(mac, f"/item/{lib['cat']}")[2]


# ---- 4. Settings > Advanced > Post tabs by category -------------------------------------------------------------------

def test_settings_turn_tabs_off_and_back_on(mac):
    body = page(mac, "/settings/appearance")[2]
    block = body[body.index('id="posttabs"'):]
    assert 'data-ptcat="recipe"' in block and 'data-ptcat="other"' not in block
    recipe = block[block.index('data-ptcat="recipe"'):]
    recipe = recipe[:recipe.index("</form>")]
    assert re.findall(r'data-tab="(\w+)"', recipe) == list(cats.CATEGORIES["recipe"].tabs)
    assert ">Summary<" not in block and ">Details<" not in block  # always shown, so not listed
    assert 'value="swaps:0"' in recipe and 'class="ptpill on"' in recipe

    status, headers, _ = post(mac, "/hub/views/tabs", category="recipe", toggle="swaps:0", next="/settings/appearance#pt-recipe")
    assert status == 303 and headers["Location"] == "/settings/appearance#pt-recipe"
    post(mac, "/hub/views/tabs", category="recipe", toggle="equipment:0")
    assert mac.store.hidden_tabs() == {"recipe": ["equipment", "swaps"]}
    body = page(mac, "/settings/appearance")[2]
    assert 'value="swaps:1" class="ptpill" aria-pressed="false"' in body and "2 tabs hidden" in body

    post(mac, "/hub/views/tabs", category="recipe", toggle="swaps:1")
    assert mac.store.hidden_tabs() == {"recipe": ["equipment"]}
    for junk in ({"category": "recipe", "toggle": "tracks:0"}, {"category": "nope", "toggle": "swaps:0"},
                 {"category": "recipe", "toggle": "swaps:maybe"}, {"category": "recipe", "toggle": "sum:0"}):
        post(mac, "/hub/views/tabs", **junk)
    assert mac.store.hidden_tabs() == {"recipe": ["equipment"]}
    post(mac, "/hub/views/tabs", reset="1")
    assert mac.store.hidden_tabs() == {}
    assert "Every category shows all its tabs" in page(mac, "/settings/appearance")[2]


def test_a_hidden_tab_leaves_the_post_view(mac, lib):
    views.save(lib["recipe_dir"], views.tidy_view({"category": "recipe", "tabs": {
        "ingredients": {"items": [{"name": "Pasta"}]}, "method": {"items": [{"name": "Boil"}]}}}, engine="test:model"))
    nav = page(mac, f"/item/{lib['recipe']}")[2]
    assert 'data-tab="method"' in nav
    post(mac, "/hub/views/tabs", category="recipe", toggle="method:0")
    nav = page(mac, f"/item/{lib['recipe']}")[2]
    assert 'data-tab="method"' not in nav and 'data-tab="ingredients"' in nav


# ---- 5. Ask starters -------------------------------------------------------------------------------------------------

def test_ask_starters_follow_the_category(mac, lib):
    recipe = mac.store.item_by_id(lib["recipe"])
    got = suggestions("post", [recipe], "Weeknight lemon pasta")
    assert got[0].startswith("The summary isn't enough") and got[1] == cats.CATEGORIES["recipe"].ask[0]
    assert got[2].startswith("Find a well-reviewed version")  # the recipe's own question stays
    songs = suggestions("post", [mac.store.item_by_id(lib["songs"])], "Five albums")
    assert songs[1:] == list(cats.CATEGORIES["music"].ask[:2]) and len(songs) == 3
    other = suggestions("post", [mac.store.item_by_id(lib["cat"])], "My cat")
    assert other[1] == "Find the original source and check whether the claims hold up."  # Other keeps the general ones
    mac.store.set_category(lib["cat"], "travel", by="owner")
    assert suggestions("post", [mac.store.item_by_id(lib["cat"])], "My cat")[1:] == list(cats.CATEGORIES["travel"].ask[:2])
    assert suggestions("library", [], "your library")[0] == "What should I try first from my saves?"
