"""The contextual-tabs fixtures (tests/fixtures/views: one fictional post per category, two with a second category) load,
plan their tabs and render through the hub. The sandbox hub (scripts/smoke/views_sandbox.sh) loads the same posts with
the same loader, so this also checks the sandbox. Fictional data only."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from magpiary import categories as cats
from magpiary import views

from test_hub import page

FIXTURES = Path(__file__).parent / "fixtures" / "views"
POSTS = sorted(p.name for p in FIXTURES.iterdir() if (p / "meta.json").is_file())
SANDBOX = Path(__file__).parents[1] / "scripts" / "smoke" / "views_sandbox_hub.py"


def sandbox():
    spec = importlib.util.spec_from_file_location("views_sandbox_hub", SANDBOX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # the module only defines functions unless run as a script
    return mod


def read(name, file):
    return json.loads((FIXTURES / name / file).read_text())


def test_one_fixture_per_category_and_two_with_a_second():
    assert POSTS == sorted(cats.IDS)
    seconds = {n: read(n, "view.json")["category2"] for n in POSTS if read(n, "view.json")["category2"]}
    assert len(seconds) >= 2 and all(s in cats.CATEGORIES and s != n for n, s in seconds.items())


def test_fixtures_are_fictional():
    """No real post links or handles: example-style ids, invented names (codex-review-lessons section 9)."""
    for name in POSTS:
        meta = read(name, "meta.json")
        assert re.search(r"Fixture|Fx[A-Z]|fixture|/fx0|example", meta["url"]), meta["url"]
        assert "example" in (meta["author_handle"] + meta["author"]).lower() or meta["author"].startswith("u/fixture"), name
    blob = "\n".join((p.read_text()) for p in FIXTURES.rglob("*.json"))
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", blob)  # no email addresses
    for url in re.findall(r"https?://[^\s\"']+", blob):
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        assert host in {"instagram.com", "youtube.com", "threads.com", "reddit.com", "linkedin.com", "example.com",
                        "openstreetmap.org", "musicbrainz.org", "openlibrary.org", "wikidata.org"}, url


@pytest.mark.parametrize("name", POSTS)
def test_each_fixture_loads_tidy_and_plans_its_tabs(name):
    raw = read(name, "view.json")
    view = views.load(FIXTURES / name)
    assert view and view["category"] == name and view["by"] == "ai" and view["engine"]
    assert view["tabs"] == raw["tabs"] == views.tidy_view(raw)["tabs"]  # written as tidy_view writes it
    record = read(name, "record.json")
    assert record["category"] == name and record.get("category2", "") == view["category2"] and "view" not in record
    category = cats.CATEGORIES[name]
    if category.tabs:  # every tab of its category has made-up content
        assert set(category.tabs) <= set(view["tabs"]), set(category.tabs) - set(view["tabs"])
    lent = cats.CATEGORIES[view["category2"]].lend if view["category2"] else ""
    if lent:
        assert lent in view["tabs"]
    core = {"read": False, "deep": False, "links": False, "rel": True, "tr": (FIXTURES / name / "transcript.json").is_file()}
    visible, more = views.tab_plan(view, core)
    assert visible[0] == "sum" and visible[-1] == "det" and len(visible) <= views.VISIBLE
    planned = visible + more
    assert len(planned) == len(set(planned))
    assert [t for t in planned if t in cats.TABS] == [t for t in category.tabs] + ([lent] if lent else [])
    assert ("tr" in planned) == core["tr"] and "rel" in planned


def test_place_lookups_carry_coordinates():
    for name, tab in (("travel", "places"), ("food_places", "spots")):
        view = views.load(FIXTURES / name)
        found = view["lookups"][tab]
        assert len(found) >= 4
        for entry in found.values():
            osm = entry["nominatim"]
            assert osm["status"] == "ok" and -90 <= osm["lat"] <= 90 and -180 <= osm["lon"] <= 180


@pytest.fixture
def loaded(mac, tmp_path):
    library = tmp_path / "library"
    mac.server.hub.library = library
    mod = sandbox()
    mod.quiet(mac.store)
    return mod.load_fixtures(mac.store, library, FIXTURES)


def test_every_fixture_post_renders_with_every_category_tab(mac, loaded):
    assert sorted(loaded) == POSTS
    for name, item_id in loaded.items():
        view = views.load(FIXTURES / name)
        status, _, body = page(mac, f"/item/{item_id}")
        assert status == 200, name
        for tab_id in view["tabs"]:
            assert f'data-pane="{tab_id}"' in body and f'data-tab="{tab_id}"' in body, (name, tab_id)
        assert ('data-pane="tr"' in body) == (FIXTURES / name / "transcript.json").is_file(), name
        scripts = re.findall(r"<script\b[^>]*>", body, re.I)
        assert all("src=" in s or "nonce=" in s for s in scripts), (name, scripts)  # no script tag came from the data
        assert "Build this view" not in body  # every view is built (and Private mode never offers it)
        if view["tabs"]:
            chip = re.search(r'<b style="[^"]*" data-cat="([a-z_]*)">([^<]*)</b>', body)
            assert chip and chip.groups() == (name, cats.name(name).replace("&", "&amp;")), name  # the header chip names the category, as on the wall


def test_the_wall_lists_every_fixture_with_its_category(mac, loaded):
    body = page(mac, "/")[2]
    for name in POSTS:
        assert f'data-cat="{name}"' in body, name
    travel = page(mac, "/?cat=travel")[2]
    assert "3 days in Lisbon" in travel and "One-pan lemon garlic orzo" not in travel


def test_ticks_and_servings_on_a_fixture_post(mac, loaded):
    from test_hub import post
    from magpiary import hub_views as hv

    item_id = loaded["recipe"]
    orzo = views.load(FIXTURES / "recipe")["tabs"]["ingredients"]["items"][0]
    for key, value in ((hv.item_key(orzo), "1"), ("servings", "6")):
        assert json.loads(post(mac, "/hub/pv/state", id=item_id, tab="ingredients", key=key, value=value)[2]) == {"ok": True}
    body = page(mac, f"/item/{item_id}?tab=ingredients")[2]
    assert f'data-pvkey="{hv.item_key(orzo)}" checked' in body and ">450 g<" in body


def test_narrow_window_fixes_found_in_the_sandbox():
    """Found clicking through the sandbox at 420 px (14 Nov 2026): the tab row's edge-fade mask hid the open More menu,
    and the post page's tap-target padding (negative margins on outside links) made the search-link chips overlap."""
    static = Path(views.__file__).parent / "static"
    css = (static / "views.css").read_text()
    assert re.search(r"\.tabs\.pvtabs:has\(\.pvmore\[open\]\) \{ -webkit-mask-image: none !important; mask-image: none !important; \}", css)
    phone = (static / "phone.css").read_text()
    rule = next(line for line in phone.splitlines() if 'a[target="_blank"]:not(.pvprimary)' in line and "margin-block: -10px" in line)
    assert ":not(.pvprov)" in rule
