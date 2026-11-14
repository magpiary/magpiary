"""The category tab renderers (hub_views.py): every render kind, escaping, saved ticks and servings, the servings scaler,
search links without lookups.py, lookups' exact links, and whole fictional posts through the hub. Fictional data only."""

import json
import os
import re
from fractions import Fraction
from pathlib import Path

import pytest

from magpiary import categories as cats
from magpiary import hub_views as hv
from magpiary import views

from test_hub import archive, page, post

EVIL = '<img src=x onerror="alert(1)">'
ITEM = {"id": 7, "canonical_url": "https://www.instagram.com/reel/ExampleViews1/",
        "caption": "Serves 4. Tickets at https://tickets.example.org/show and more."}


def render(tab_id, items, text="", state=None, view=None, item=None):
    return hv.render_tab(cats.TABS[tab_id], {"text": text, "items": items}, view or {}, state or {}, item or ITEM)


def attributes(html):
    from html.parser import HTMLParser
    seen = set()

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            seen.update(name for name, _ in attrs)
            assert tag not in ("script", "img", "iframe", "image"), tag
    P().feed(html)
    return seen


def no_raw_html(html):
    assert "<img" not in html and "onerror=\"" not in html
    assert " on" + "click=" not in html.lower() and "javascript:" not in html.lower()


# ---- every kind ------------------------------------------------------------------------------------------------------

KINDS = {
    "checklist": ("ingredients", [{"name": "Spaghetti", "amount": "200 g", "group": "Pasta"}, {"name": EVIL, "amount": "1 1/2 tbsp", "group": "Sauce"}]),
    "steps": ("method", [{"name": "Boil water", "at": "0:05", "amount": "5 min"}, {"name": EVIL, "value": "echo <b>"}]),
    "cards": ("tracks", [{"name": "Night Drive", "detail": "The Example Band", "kind": "song"}, {"name": EVIL, "detail": EVIL}]),
    "places": ("places", [{"name": "Harbour Café", "group": "Old Town"}, {"name": EVIL, "group": EVIL}]),
    "palette": ("palette", [{"name": "Sea", "value": "#1A2B3C"}, {"name": EVIL, "value": "red;background:url(x)"}]),
    "specs": ("specs", [{"name": "Battery", "detail": "10 hours"}, {"name": EVIL, "detail": EVIL}]),
    "proscons": ("proscons", [{"name": "Light", "kind": "pro"}, {"name": "Pricey", "kind": "con"}, {"name": EVIL}]),
    "quotes": ("snippets", [{"name": "List files", "value": "ls -la <dir>", "kind": "command"}, {"name": "Ada", "value": EVIL, "kind": "quote"}]),
    "notes": ("visual", [{"name": "Bold type", "detail": "condensed", "group": "Type"}, {"name": EVIL, "group": EVIL}]),
    "flashcards": ("quiz", [{"name": "What is 2+2?", "detail": "4"}, {"name": EVIL, "detail": EVIL}]),
    "timeline": ("itinerary", [{"name": "Breakfast", "group": "Day 1"}, {"name": "Museum", "group": "Day 1"}, {"name": EVIL, "group": "Day 2"}]),
    "event": ("when", [{"name": "Night market", "value": "2026-12-01T19:00", "group": "Pier 3", "amount": "Free"}, {"name": EVIL, "value": EVIL}]),
}


def test_every_render_kind_has_a_renderer_and_a_test():
    assert set(hv.RENDERERS) == set(cats.RENDERS) == set(KINDS)
    assert {cats.TABS[t].render for t, _ in KINDS.values()} == set(cats.RENDERS)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_kind_renders_its_items_and_escapes_everything(kind):
    tab_id, items = KINDS[kind]
    html = render(tab_id, items, text="Intro <script>x</script>")
    assert f'class="pvv pv-{kind}"' in html and 'data-pvtab="' + tab_id + '"' in html and 'data-pvid="7"' in html
    assert "Intro &lt;script&gt;x&lt;/script&gt;" in html and "<script>" not in html
    no_raw_html(html)
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert 'aria-live="polite"' in html  # each pane announces its own feedback


def test_empty_tab_shows_its_empty_text_or_only_its_text():
    tab = cats.TABS["tracks"]
    assert tab.empty_text in hv.render_tab(tab, {"text": "", "items": []}, {}, {}, ITEM)
    html = hv.render_tab(tab, {"text": "Only a note", "items": [{"name": "  "}]}, {}, {}, ITEM)
    assert "Only a note" in html and tab.empty_text not in html and "pvcard" not in html
    assert tab.empty_text in hv.render_tab(tab, None, None, None, ITEM)  # junk in, a calm pane out


# ---- checklist, steps, servings ----------------------------------------------------------------------------------------

def test_checklist_groups_restores_ticks_and_counts():
    items = KINDS["checklist"][1]
    key = hv.item_key(items[0])
    assert re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", key)  # the /hub/pv/state key rule
    html = render("equipment", [{"name": "Pot"}, {"name": "Pan"}, {"name": "Lid", "group": "Extras"}],
                  state={hv.item_key({"name": "Pan"}): "1"})
    assert html.count('type="checkbox"') == 3 and html.count(" checked") == 1
    assert '<span data-pvdone>1</span> of 3 ticked' in html
    assert html.index("Pan") < html.index('class="pvgh">Extras') and "data-pvcopylist" in html
    assert 'class="pvrow on"' in html


def test_tick_keys_survive_a_rebuild_and_differ_by_group():
    a, b = {"name": "Salt", "group": "Sauce"}, {"name": " salt ", "group": "sauce", "detail": "new"}
    assert hv.item_key(a) == hv.item_key(b) != hv.item_key({"name": "Salt", "group": "Dough"})


@pytest.mark.parametrize("amount, factor, want", [
    ("200 g", Fraction(2), "400 g"), ("1 1/2 cups", Fraction(3, 2), "2 1/4 cups"), ("2-3 cloves", Fraction(2), "4-6 cloves"),
    ("½ tsp", Fraction(3), "1 1/2 tsp"), ("1½ cups", Fraction(2), "3 cups"), ("0.5 kg", Fraction(3, 2), "0.75 kg"),
    ("a pinch", Fraction(2), "a pinch"), ("to taste", Fraction(5), "to taste"), ("3 eggs", Fraction(1, 3), "1 eggs"),
    ("200 g", Fraction(1), "200 g"), ("", Fraction(2), ""), ("1/0 cup", Fraction(2), "1/0 cup"),
])
def test_scale_amount(amount, factor, want):
    assert hv.scale_amount(amount, factor) == want


def test_ingredients_scale_by_saved_servings_from_the_post():
    items = [{"name": "Pasta", "amount": "200 g"}, {"name": "Salt", "amount": "a pinch"}]
    html = render("ingredients", items)  # caption says "Serves 4"
    assert 'data-base="4"' in html and '<output class="pvservn" aria-live="polite">4</output>' in html and ">200 g<" in html
    html = render("ingredients", items, state={"servings": "6"})
    assert 'data-chosen="6"' in html and ">300 g<" in html and 'data-amt="200 g"' in html and ">a pinch<" in html
    assert 'data-pvservby="0">Reset' in html  # not the default: Reset shows
    unknown = {"id": 1, "canonical_url": "https://example.org/p"}
    html = render("ingredients", items, state={"servings": "2"}, item=unknown)
    assert 'data-base="0"' in html and "×2" in html and ">400 g<" in html and ">Batch<" in html
    for junk in ("99", "-1", "abc", ""):
        assert 'data-chosen="1"' in render("ingredients", items, state={"servings": junk}, item=unknown)
    assert "pvserv" not in render("equipment", items)  # only Ingredients scales


def test_steps_are_numbered_tickable_and_jump_the_video():
    html = render("method", KINDS["steps"][1] + [{"name": "Rest", "at": "soon"}], state={hv.item_key({"name": "Boil water"}): "1"})
    assert '<span class="pvnum" aria-hidden="true">1</span>' in html and '<span class="pvnum" aria-hidden="true">3</span>' in html
    assert 'data-t="0:05"' in html and html.count("data-t=") == 1  # "soon" is not a time: no jump button
    assert "<span data-pvdone>1</span> of 3 done" in html
    assert '<small class="pvdetail pvval">echo &lt;b&gt;</small>' in html
    assert 'data-pvcopy="echo &lt;b&gt;"' not in html  # a method step is not a command to copy
    setup = render("setup", [{"name": "Install it", "value": "echo <b>"}])
    assert "<code>echo &lt;b&gt;</code>" in setup and 'data-pvcopy="echo &lt;b&gt;"' in setup
    assert 'class="tline' not in html  # the transcript's highlighter must not pick these up


# ---- cards, links, lookups ---------------------------------------------------------------------------------------------

def test_cards_fall_back_to_search_links_without_lookups(monkeypatch):  # as if session B's module were missing
    html = render("tracks", [{"name": "Night Drive", "detail": "The Example Band", "kind": "song"}])
    assert "https://open.spotify.com/search/Night%20Drive%20The%20Example%20Band" in html
    assert "https://music.apple.com/search?term=Night%20Drive%20The%20Example%20Band" in html
    assert 'target="_blank" rel="noopener noreferrer"' in html and ">song<" in html
    for tab in cats.TABS.values():  # every card tab can at least search somewhere
        if tab.render in ("cards", "places"):
            assert hv.links_for(tab, {"name": "Example"}, {}), tab.id


def test_card_links_come_from_lookups_and_survive_its_bugs(monkeypatch):
    class Fake:
        @staticmethod
        def search_links(providers, item, tab, links=()):
            return [{"provider": "spotify", "label": "Spotify", "url": "https://open.spotify.com/search/x"},
                    {"provider": "bad", "label": "Bad", "url": "javascript:alert(1)"}]
    monkeypatch.setattr(hv.lookups, "search_links", Fake.search_links)
    assert [r["provider"] for r in hv.links_for(cats.TABS["tracks"], {"name": "x"}, {})] == ["spotify"]

    def broken(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(hv.lookups, "search_links", broken)
    assert hv.links_for(cats.TABS["tracks"], {"name": "x"}, {}) == []  # no buttons, but the post view still draws


def test_cards_show_lookup_year_and_exact_url_and_refuse_bad_ones(monkeypatch):
    view = {"lookups": {"titles": {"the example  film": {  # lookups.key: one space, lower case; this key is not it
        "tvmaze": {"status": "ok", "url": "https://www.tvmaze.com/shows/1/x", "year": "1999"}},
        "the example film": {
        "tvmaze": {"status": "ok", "url": "https://www.tvmaze.com/shows/1/the-example-film", "title": "The Example Film",
                   "year": "1999", "thumb": "https://static.tvmaze.com/uploads/images/medium_portrait/1/1.jpg"},
        "wikidata": {"status": "none", "at": "2026-11-14"},
        "wikipedia": {"status": "failed", "url": "https://en.wikipedia.org/wiki/Nope", "year": "1888"},
        "musicbrainz": {"status": "ok", "url": "javascript:alert(1)"}}}}}
    html = render("titles", [{"name": "The  Example\tFilm", "kind": "film"}], view=view)
    assert 'class="pvchip pvyear">1999<' in html and "1888" not in html and "wikipedia.org/wiki/Nope" not in html
    assert 'class="pvprov exact" href="https://www.tvmaze.com/shows/1/the-example-film"' in html and ">TVmaze<" in html
    assert "javascript:" not in html and "imdb.com/find/?q=The%20Example%20Film" in html
    assert "static.tvmaze.com" not in html and "<img" not in html  # remote thumbnails are never loaded


def test_a_value_url_is_a_link_only_when_the_post_contains_it(monkeypatch):
    html = render("tickets", [{"name": "Show", "value": "https://tickets.example.org/show"},
                              {"name": "Other", "value": "https://made-up.example.com/x"}, {"name": "Code", "value": "SAVE10"}])
    assert 'href="https://tickets.example.org/show"' in html and 'made-up.example.com' not in html  # nor as "Official site"
    assert 'data-pvcopy="SAVE10"' in html


def test_a_value_that_repeats_the_name_or_detail_is_not_shown_and_copy_boxes_only_where_copying_fits():
    # real-post test, 14 Nov: a genre and a source sat in `value` and were drawn as copy boxes
    html = render("artists", [{"name": "Example Trio", "detail": "Jazz trio", "value": "jazz"},
                              {"name": "The Example Band", "detail": "Indie", "value": "The Example Band"},
                              {"name": "Solo Example", "detail": "Folk", "value": "Signed in 2021"}])
    assert "data-pvcopy" not in html and "pvcode" not in html
    assert '<small class="pvdetail pvval">Signed in 2021</small>' in html and "pvval\">jazz" not in html
    assert html.count("pvval") == 1
    notes = render("claims", [{"name": "Prices will fall", "kind": "prediction", "value": "Prices will fall."}])
    assert "pvval" not in notes and "data-pvcopy" not in notes
    code = render("caveats", [{"name": "Pin the version", "kind": "command", "value": "pip install example==1.2"}])
    assert 'data-pvcopy="pip install example==1.2"' in code
    tickets = render("tickets", [{"name": "Early bird", "value": "EARLY20"}])
    assert 'data-pvcopy="EARLY20"' in tickets
    quote = render("quotes", [{"name": "Ada Example", "value": "Ada Example"}])
    assert quote.count("Ada Example") == 2 and "pvwho\"></span>" in quote  # the text once, plus its copy button; no "— Ada"
    assert hv.literal({"name": "A", "value": "  "}) == "" and hv.literal({"name": "Sea", "value": "#1a2b3c"}) == "#1a2b3c"


def test_http_url():
    assert hv.http_url("https://example.org/a?b=c") and hv.http_url("http://example.org")
    for bad in ("javascript:alert(1)", "data:text/html,x", "//example.org", "https://", "https://a b", 'https://x"y', None, 5):
        assert hv.http_url(bad) == ""


def test_places_draw_a_map_when_lookups_have_coordinates(monkeypatch):
    items = [{"name": "Harbour Café", "group": "Old Town"}, {"name": "Hill Park", "group": "Old Town"}, {"name": "Nowhere"},
             {"name": "Gone"}]
    plain = render("places", items)
    assert "pvmap" not in plain and "google.com/maps/search/?api=1&amp;query=Harbour%20Caf%C3%A9%20Old%20Town" in plain
    assert "maps.apple.com" in plain
    view = {"lookups": {"places": {"harbour café | old town": {"nominatim": {"status": "ok", "lat": 52.37, "lon": 4.89,
                                                                  "url": "https://www.openstreetmap.org/node/1"}},
                                   "hill park | old town": {"nominatim": {"status": "ok", "lat": 52.38, "lon": 4.91}},
                                   "nowhere": {"nominatim": {"status": "ok", "lat": 999.0, "lon": 4.0}},
                                   "gone": {"nominatim": {"status": "failed", "lat": 1.0, "lon": 1.0}}}}}
    html = render("places", items, view=view)
    assert html.count('class="pvdot"') == 2 and 'data-pvjumpto="pvc-places-0"' in html and 'id="pvc-places-1"' in html
    assert '<span class="pvpin" aria-hidden="true">1</span>' in html and "no map is downloaded" in html
    assert 'class="pvprov exact" href="https://www.openstreetmap.org/node/1"' in html
    assert html.count("openstreetmap.org/search") == 3  # the card with the exact OSM page drops the OSM search
    assert "<image" not in html and "tile" not in html  # nothing is fetched from a map server
    spots = render("spots", [{"name": "Noodle Bar"}])
    assert "google.com/maps" in spots and "opentable.com" in spots


# ---- the rest ------------------------------------------------------------------------------------------------------------

def test_palette_only_takes_real_hex_colours():
    html = render("palette", KINDS["palette"][1] + [{"name": "Sand", "detail": "walls, #e8d9b0"}])
    assert 'style="--sw:#1a2b3c;--ink:#fff"' in html and 'data-pvcopy="#1a2b3c"' in html
    assert 'style="--sw:#e8d9b0;--ink:#111"' in html
    assert "url(x)" not in html.split("pvswatches")[1].split("no hex")[0] or "red;background" not in html.split("style=")[-1]
    assert html.count('class="pvsw nohex"') == 1


def test_specs_proscons_quotes_notes_timeline_flashcards():
    specs = render("specs", [{"name": "Weight", "detail": "1.2 kg", "group": "Body"}])
    assert '<th scope="row">Weight</th><td>1.2 kg' in specs and 'scope="colgroup">Body' in specs
    pc = render("proscons", KINDS["proscons"][1])
    assert pc.index("Light") < pc.index("pvside-con") < pc.index("Pricey") and "Also said" in pc
    q = render("snippets", KINDS["quotes"][1])
    assert "<pre><code>ls -la &lt;dir&gt;</code></pre>" in q and "<blockquote>&lt;img" in q and q.count("data-pvcopy=") == 2
    notes = render("visual", KINDS["notes"][1])
    assert '<h5 class="pvgh">Type</h5>' in notes and "condensed" in notes
    tl = render("itinerary", KINDS["timeline"][1])
    assert tl.count('class="pvtg"') == 2 and tl.index("Day 1") < tl.index("Museum") < tl.index("Day 2")
    fc = render("quiz", KINDS["flashcards"][1])
    assert fc.count('class="pvfc" aria-expanded="false"') == 2 and "data-pvflipall" in fc and 'class="pvfcb" aria-hidden="true"' in fc


def test_event_builds_calendar_data_only_from_a_real_date():
    html = render("when", KINDS["event"][1] + [{"name": "All day fair", "value": "2026-12-05"}, {"name": "Bad", "value": "2026-13-40"}, {"name": "Soon"}])
    assert 'data-start="20261201T190000" data-end="20261201T210000" data-allday="0"' in html
    assert 'data-start="20261205" data-end="20261206" data-allday="1"' in html
    assert html.count("data-pvical") == 2 and "Tue 1 Dec 2026, 19:00" in html and 'data-place="Pier 3"' in html
    assert "Date not given in the post" in html


def test_no_inline_handlers_or_styles_beyond_swatches():
    for kind, (tab_id, items) in KINDS.items():
        html = render(tab_id, items)
        attrs = attributes(html)
        assert not [a for a in attrs if a.startswith("on")], kind
        assert "style" not in attrs or kind == "palette", kind


# ---- whole posts through the hub (snapshots for review) -----------------------------------------------------------------

POSTS = {
    "recipe": ("https://www.instagram.com/reel/ExampleViewsRecipe/", {"ingredients": {"text": "Serves 2.", "items": [
        {"name": "Spaghetti", "amount": "200 g", "group": "Pasta"}, {"name": "Lemon", "amount": "1", "group": "Sauce"},
        {"name": "Olive oil", "amount": "2 tbsp", "group": "Sauce"}]},
        "method": {"text": "", "items": [{"name": "Boil the pasta", "at": "0:04", "amount": "9 min"}, {"name": "Toss with lemon", "at": "0:20"}]},
        "swaps": {"text": "", "items": [{"name": "Lime for lemon", "kind": "swap"}]}}),
    "music": ("https://www.instagram.com/reel/ExampleViewsMusic/", {"tracks": {"text": "", "items": [
        {"name": "Night Drive", "detail": "The Example Band", "kind": "song", "at": "0:10"}, {"name": "Paper Moons", "detail": "Fictional Duo", "kind": "album"}]},
        "artists": {"text": "", "items": [{"name": "The Example Band", "detail": "synth pop"}]}}),
    "travel": ("https://www.instagram.com/reel/ExampleViewsTravel/", {"places": {"text": "", "items": [
        {"name": "Harbour Café", "group": "Old Town", "detail": "Breakfast by the water"}, {"name": "Hill Park", "group": "Old Town"}]},
        "itinerary": {"text": "", "items": [{"name": "Café", "group": "Day 1"}, {"name": "Park walk", "group": "Day 1"}, {"name": "Museum", "group": "Day 2"}]},
        "plan": {"text": "", "items": [{"name": "Best time", "detail": "Spring"}, {"name": "Budget", "detail": "Mid-range"}]}}),
    "design_inspiration": ("https://www.instagram.com/reel/ExampleViewsDesign/", {"visual": {"text": "Loud type, quiet colour.", "items": [
        {"name": "Condensed sans", "group": "Type"}, {"name": "Grain overlay", "group": "Imagery"}]},
        "palette": {"text": "", "items": [{"name": "Ink", "value": "#14213d"}, {"name": "Saffron", "value": "#fca311"}, {"name": "Paper", "value": "#e5e5e5"}]}}),
    "gadgets": ("https://www.instagram.com/reel/ExampleViewsGadget/", {"specs": {"text": "", "items": [{"name": "Battery", "detail": "10 hours"}, {"name": "Weight", "detail": "1.2 kg"}]},
        "proscons": {"text": "", "items": [{"name": "Light", "kind": "pro"}, {"name": "Pricey", "kind": "con"}]}}),
    "learning": ("https://www.instagram.com/reel/ExampleViewsLearn/", {"ideas": {"text": "", "items": [{"name": "Spaced repetition beats cramming"}]},
        "quiz": {"text": "", "items": [{"name": "What beats cramming?", "detail": "Spaced repetition"}, {"name": "How often to review?", "detail": "On a widening schedule"}]}}),
    "events_deals": ("https://www.instagram.com/reel/ExampleViewsEvent/", {"when": {"text": "", "items": [
        {"name": "Night market", "value": "2026-12-01T19:00", "group": "Pier 3", "amount": "Free", "detail": "Bring cash"}]},
        "prep": {"text": "", "items": [{"name": "Bring a tote bag"}]}}),
    "ai_coding": ("https://www.instagram.com/reel/ExampleViewsCode/", {"snippets": {"text": "", "items": [
        {"name": "Start the server", "value": "uv run example serve --port 9000", "kind": "command"}]},
        "setup": {"text": "", "items": [{"name": "Install uv", "value": "brew install uv", "at": "0:12"}]}}),
}


@pytest.mark.parametrize("category", sorted(POSTS))
def test_fictional_posts_render_through_the_hub(mac, tmp_path, category, monkeypatch):
    url, tabs = POSTS[category]
    item_id, folder = archive(mac, tmp_path, url, "instagram", {"text": f"An example {category} post", "author": "Example Maker", "duration": 30.0},
                              {"record.json": json.dumps({"title": f"Example {category}", "summary": "A fictional post.", "key_points": [],
                                                          "type": "other", "entities": {}, "suggested_tags": []}).encode()})
    views.save(folder, {"version": 1, "category": category, "category2": "", "by": "ai", "engine": "test:model",
                        "made_at": "2026-11-14T10:00:00", "tabs": tabs, "lookups": {}})
    status, _, body = page(mac, f"/item/{item_id}")
    assert status == 200
    for tab_id in tabs:
        assert f'data-pane="{tab_id}"' in body and f'data-pvtab="{tab_id}"' in body, tab_id
    assert f'data-pvid="{item_id}"' in body
    no_raw_html(body.split('data-pane="sum"')[1])
    first = next(iter(tabs))
    if cats.TABS[first].render in ("checklist", "steps"):
        key = hv.item_key(tabs[first]["items"][0])
        assert json.loads(post(mac, "/hub/pv/state", id=item_id, tab=first, key=key, value="1")[2]) == {"ok": True}
        again = page(mac, f"/item/{item_id}?tab={first}")[2]
        assert f'data-pvkey="{key}" checked' in again
    if os.environ.get("MAGPIARY_SNAPSHOTS"):  # a folder outside the repo, for review (never written by default)
        out = Path(os.environ["MAGPIARY_SNAPSHOTS"])
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{category}.html").write_text(body)


def test_ingredients_servings_round_trip_through_the_route(mac, tmp_path, monkeypatch):
    url, tabs = POSTS["recipe"]
    item_id, folder = archive(mac, tmp_path, url, "instagram", {"text": "Pasta", "author": "Example Maker", "duration": 30.0})
    views.save(folder, {"version": 1, "category": "recipe", "by": "ai", "engine": "test:model", "tabs": tabs, "lookups": {}})
    assert json.loads(post(mac, "/hub/pv/state", id=item_id, tab="ingredients", key="servings", value="4")[2]) == {"ok": True}
    body = page(mac, f"/item/{item_id}?tab=ingredients")[2]
    assert 'data-base="2" data-chosen="4"' in body and ">400 g<" in body and ">4 tbsp<" in body


# ---- review 14 Nov 2026 (Codex) ---------------------------------------------------------------------------------------

def test_an_ai_written_url_never_becomes_an_official_site_but_a_found_link_does():
    """Correctness 11 / security 3: an Alternatives card linked https://attacker.example/ as "Official site"."""
    items = [{"name": "Paletteer", "detail": "lighter", "value": "https://attacker.example/"}]
    html = render("alternatives", items)
    assert "attacker.example" not in html and "Official site" not in html
    rows = [{"name": "Paletteer", "url": "https://paletteer.example/app"}]
    html = hv.render_tab(cats.TABS["alternatives"], {"text": "", "items": items}, {}, {}, ITEM, rows)
    assert 'href="https://paletteer.example/app"' in html and "Official site" in html and "attacker.example" not in html
    # verify pass: the AI-written summary repeating its invention proves nothing; only the post's own text, exactly
    told = {**ITEM, "summary": "Try https://attacker.example/ for more.", "caption": "See https://attacker.example/x"}
    assert "attacker.example" not in render("alternatives", items, item=told)
    assert hv.in_post("https://tickets.example.org/show", ITEM) and not hv.in_post("https://tickets.example.org/sh", ITEM)
    # second verify pass: a malformed URL (a space) failed http_url, kept its value, and official_url read its host
    bad = [{"name": "Paletteer", "detail": "lighter", "value": "https://attacker.example/private page"}]
    html = render("alternatives", bad)
    assert "Official site" not in html and 'href="https://attacker.example' not in html  # shown only as inert text
    assert hv.in_post("https://tickets.example.org/show", {"caption": "at https://tickets.example.org/show."})


def test_an_event_at_the_end_of_the_calendar_still_renders():
    """Security 6: 9999-12-31 passed date validation, then adding the length raised OverflowError."""
    html = render("when", [{"name": "Far future", "value": "9999-12-31"}, {"name": "Late", "value": "9999-12-31T23:30"},
                           {"name": "Soon", "value": "2026-12-01"}])
    assert "Far future" in html and "Late" in html and html.count("data-pvical") == 1


def test_links_keeps_an_add_link_entry_point_when_empty(mac, tmp_path):
    """Correctness 10: with no links the Links pane (and its Add form) was gone, and ?tab=links could not open it."""
    item_id, folder = archive(mac, tmp_path, "https://www.instagram.com/reel/ExampleNoLinks/", "instagram",
                              {"text": "A fictional tool demo", "author": "Example Maker", "duration": 30.0},
                              {"record.json": json.dumps({"title": "Example tool", "summary": "A fictional tool.",
                                                          "key_points": [], "type": "tool", "entities": {},
                                                          "suggested_tags": []}).encode()})
    mac.store.set_setting("ai_mode", "private")
    body = page(mac, f"/item/{item_id}")[2]
    assert 'data-tab="links"' in body.split('class="pvmorelist">')[1].split("</div>")[0]  # in More while empty
    add = re.search(r'<a class="pvprimary find" href="([^"]+)" data-tabto="links">', body)
    assert add and add.group(1).replace("&amp;", "&") == f"/item/{item_id}?tab=links#links"
    asked = page(mac, f"/item/{item_id}?tab=links")[2]
    assert 'data-pane="links"' in asked and 'data-tab="links" class="on"' in asked
    # verify pass: any saved post (not only tools) reaches Links and its Add form, from More
    other_id, _ = archive(mac, tmp_path, "https://www.instagram.com/reel/ExampleNoLinks2/", "instagram",
                          {"text": "A fictional pasta", "author": "Example Maker", "duration": 30.0})
    body = page(mac, f"/item/{other_id}")[2]
    more = body.split('class="pvmorelist">')[1].split("</div>")[0]
    assert 'data-tab="links"' in more and 'data-pane="links"' in body and "/hub/links/add" in body.split('data-pane="links"')[1]


JS_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const handlers = {};
class Element {}
class HTMLInputElement extends Element {}
class HTMLDetailsElement extends Element {}
const server = {};  // what the hub stored, in the order requests finished
let n = 0;
const delays = [60, 5];  // the first request (tick) is slow, the second (untick) fast
const refuse = process.argv[3] === "refuse";  // the hub is locked: every save is refused
async function fetch(url, opts) {
  const p = new URLSearchParams(opts.body), wait = delays[n++] ?? 1;
  await new Promise((r) => setTimeout(r, wait));
  if (refuse) return { ok: false, json: async () => ({ ok: false }) };
  server[p.get("key")] = p.get("value");
  return { ok: true, json: async () => ({ ok: true }) };
}
const root = { dataset: { pvid: "7", pvtab: "ingredients" }, querySelector: () => null, querySelectorAll: () => [] };
const row = { classList: { toggle() {}, add() {}, remove() {} }, querySelector: () => null, animate() {} };
root.prepend = () => {};
const box = Object.assign(new HTMLInputElement(), { checked: false, defaultChecked: false, dataset: { pvkey: "i.abc" },
  matches: () => true, closest: (sel) => (sel === "li" ? row : root) });
const document = { addEventListener: (t, f) => { (handlers[t] ||= []).push(f); }, querySelector: () => null,
                   createElement: () => ({ setAttribute() {}, remove() {} }),
                   querySelectorAll: () => [] };
const ctx = { window: {}, document, fetch, URLSearchParams, setTimeout, clearTimeout, console, Element, HTMLInputElement,
              HTMLDetailsElement, matchMedia: () => ({ matches: true }), addEventListener() {}, innerWidth: 1000,
              navigator: {}, WeakMap, Map, Promise };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
(async () => {
  box.checked = true; const a = Promise.all(handlers.change.map((f) => f({ target: box })));
  box.checked = false; const b = Promise.all(handlers.change.map((f) => f({ target: box })));
  await a; await b;
  console.log(JSON.stringify({ stored: server["i.abc"] ?? null, shown: box.checked }));
})();
"""


def test_quick_tick_then_untick_is_stored_as_unticked(tmp_path):
    """Correctness 12: the two saves ran at once; when the tick finished last the hub kept it ticked."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = tmp_path / "harness.js"
    script.write_text(JS_HARNESS)
    js = Path(hv.__file__).parent / "static" / "views.js"
    for mode, want in (("ok", {"stored": "", "shown": False}), ("refuse", {"stored": None, "shown": False})):
        done = subprocess.run([node, str(script), str(js), mode], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[-2000:]
        assert json.loads(done.stdout.strip().splitlines()[-1]) == want, mode  # verify pass: two refusals show unticked
