"""Lookups for the contextual tabs: search links (no network) and the free-API worker step with recorded, fictional
answers. Nothing here goes to the internet."""

import json
import stat
from urllib.parse import unquote, urlsplit

import pytest

from magpiary import categories as cats
from magpiary import lookups, views
from magpiary.store import Store

POST = "https://www.instagram.com/reel/ExampleLookup1/"


# ---- search links ----------------------------------------------------------------------------------------------------

def test_every_registry_provider_has_a_pattern():
    used = {p for t in cats.TABS.values() for p in t.providers}
    assert used <= set(lookups.PROVIDERS)
    for pid, (label, pattern, verified) in lookups.PROVIDERS.items():
        assert label and isinstance(verified, bool)
        assert pid == "official" or (pattern.startswith("https://") and pattern.count("{q}") == 1)
    assert "mobbin" not in lookups.PROVIDERS  # dead search URL (research, 14 Nov)
    assert not lookups.PROVIDERS["npm"][2] and lookups.PROVIDERS["spotify"][2]


def test_search_links_encode_every_script_and_add_the_narrowing_detail():
    item = {"name": "Midnight Lantern & Co?", "detail": "Ｔhe Fictional Band", "kind": "song"}
    links = lookups.search_links(cats.TABS["tracks"].providers, item, cats.TABS["tracks"])
    assert [l["provider"] for l in links] == list(cats.TABS["tracks"].providers)
    spotify = links[0]["url"]
    assert spotify.startswith("https://open.spotify.com/search/") and "&" not in spotify.split("/search/")[1]
    assert unquote(spotify.split("/search/")[1]) == "Midnight Lantern & Co? Ｔhe Fictional Band"
    apple = links[1]["url"]
    assert urlsplit(apple).query.count("=") == 1 and "%26" in apple and "%3F" in apple
    # non-Latin names are kept (NFC), decomposed input is composed, control characters go
    cafe = lookups.search_links(["google_maps"], {"name": "Café 東京\n", "group": "Kyoto"}, "places")[0]["url"]
    assert unquote(cafe.split("query=")[1]) == "Café 東京 Kyoto"
    hindi = lookups.search_links(["google"], {"name": "मसाला चाय", "detail": "why go"}, "spots")[0]["url"]
    assert unquote(hindi.split("q=")[1]) == "मसाला चाय"  # spots narrow by group, not by detail
    assert lookups.search_links(["google", "nonsense"], {"name": "  "}, "places") == []
    assert lookups.search_links(["nonsense"], {"name": "x"}, "places") == []


def test_official_only_from_the_post_or_found_links():
    tab = cats.TABS["made_with"]
    assert [l["provider"] for l in lookups.search_links(tab.providers, {"name": "Paletteer"}, tab)] == ["google", "wikipedia"]
    from_post = lookups.search_links(["official"], {"name": "Paletteer", "value": "https://paletteer.example/p?utm_source=x"}, tab)
    assert from_post == [{"provider": "official", "label": "Official site", "url": "https://paletteer.example/"}]
    rows = [{"name": "Paletteer", "url": "https://en.wikipedia.org/wiki/Paletteer"},
            {"name": "Other App", "url": "https://other.example/"},
            {"name": "paletteer", "url": "https://paletteer.example/app"}]
    assert lookups.search_links(["official"], {"name": "Paletteer"}, tab, links=rows)[0]["url"] == "https://paletteer.example/app"
    assert lookups.search_links(["official"], {"name": "Paletteer"}, tab, links=rows[:2]) == []


# ---- fake network ----------------------------------------------------------------------------------------------------

MB_RECORDING = {"recordings": [
    {"id": "rec-wrong", "score": 100, "title": "Midnight Lantern", "artist-credit": [{"name": "Someone Else"}]},
    {"id": "rec-1", "score": 98, "title": "Midnight Lantern (Remastered)", "first-release-date": "1987-05-02",
     "artist-credit": [{"name": "The Fictional Band"}]}]}
NOMINATIM = [{"lat": "41.38", "lon": "2.17", "display_name": "Plaça Exemple, Barcelona, Spain", "osm_type": "node",
              "osm_id": 12345}]
OPENLIB = {"docs": [{"key": "/works/OL1W", "title": "The Paper Orchard", "author_name": ["Ana Example"],
                     "first_publish_year": 2003, "cover_i": 42}]}
TVMAZE = [{"score": 1.0, "show": {"name": "Harbour Lights", "premiered": "2019-03-01", "url": "https://www.tvmaze.com/shows/1/harbour-lights",
                                  "image": {"medium": "https://static.tvmaze.com/uploads/images/medium_portrait/1/1.jpg"}}}]
WIKIDATA = {"search": [{"id": "Q1", "label": "Glass Meadow", "description": "novel"},
                       {"id": "Q2", "label": "Glass Meadow", "description": "2014 film by Jo Example"}]}


class Net:
    """Recorded answers by host; records every request."""

    def __init__(self, answers=None, fail=()):
        self.answers = answers or {}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, url, headers):
        host = urlsplit(url).hostname
        self.calls.append((host, url, headers))
        if host in self.fail:
            raise OSError("offline")
        status, body = self.answers.get(host, (200, b"{}"))
        return status, url, body if isinstance(body, bytes) else json.dumps(body).encode()


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def run_with(net, clock=None, allow=lambda: True, requests=20):
    clock = clock or Clock()
    return lookups.Run(net, allow=allow, requests=requests, pacer=lookups.Pacer(clock.time, clock.sleep))


def test_enrich_checks_title_and_artist_and_sends_a_generic_agent():
    net = Net({"musicbrainz.org": (200, MB_RECORDING)})
    view = {"tabs": {}, "lookups": {}}
    out = lookups.enrich(view, "tracks", [{"name": "Midnight Lantern", "detail": "The Fictional Band", "kind": "song"},
                                          {"name": "Some Playlist", "kind": "playlist"}],
                         run=run_with(net), today="2026-11-14")
    entry = out["midnight lantern"]["musicbrainz"]
    assert entry["status"] == "ok" and entry["url"] == "https://musicbrainz.org/recording/rec-1" and entry["year"] == "1987"
    assert "some playlist" not in out and len(net.calls) == 1
    host, url, headers = net.calls[0]
    assert headers["User-Agent"].startswith("Magpiary/") and "(+https://magpiary.com)" in headers["User-Agent"]
    assert "%22Midnight%20Lantern%22" in url and "fmt=json" in url


def test_each_api_fills_its_fields():
    net = Net({"nominatim.openstreetmap.org": (200, NOMINATIM), "openlibrary.org": (200, OPENLIB),
               "api.tvmaze.com": (200, TVMAZE), "www.wikidata.org": (200, WIKIDATA)})
    run = run_with(net)
    place = lookups.enrich({}, "places", [{"name": "Plaça Exemple", "group": "Barcelona"}], run=run, today="2026-11-14")
    assert place["plaça exemple"]["nominatim"] | {} == {"status": "ok", "at": "2026-11-14", "lat": 41.38, "lon": 2.17,
                                                       "url": "https://www.openstreetmap.org/node/12345",
                                                       "title": "Plaça Exemple, Barcelona, Spain"}
    wrong_city = lookups.enrich({}, "spots", [{"name": "Plaça Exemple", "group": "Lisbon"}], run=run, today="2026-11-14")
    assert wrong_city["plaça exemple"]["nominatim"]["status"] == "none"
    book = lookups.enrich({}, "books", [{"name": "The Paper Orchard", "detail": "Ana Example"}], run=run)["the paper orchard"]["openlibrary"]
    assert book["year"] == "2003" and book["thumb"] == "https://covers.openlibrary.org/b/id/42-M.jpg"
    show = lookups.enrich({}, "titles", [{"name": "Harbour Lights", "kind": "show"}], run=run)["harbour lights"]["tvmaze"]
    assert show["year"] == "2019" and show["thumb"].startswith("https://static.tvmaze.com/")
    film = lookups.enrich({}, "titles", [{"name": "Glass Meadow", "kind": "film"}], run=run)["glass meadow"]["wikidata"]
    assert film["url"] == "https://www.wikidata.org/wiki/Q2" and film["year"] == "2014"


def test_untrusted_answers_are_reduced_to_safe_fields():
    evil = {"pages": [{"key": "Jo_Example", "title": "Jo Example", "thumbnail": {"url": "https://evil.example/x.png"}}]}
    net = Net({"en.wikipedia.org": (200, evil)})
    out = lookups.enrich({}, "people", [{"name": "Jo Example"}], run=run_with(net))["jo example"]["wikipedia"]
    assert out["url"] == "https://en.wikipedia.org/wiki/Jo_Example" and "thumb" not in out
    junk = Net({"nominatim.openstreetmap.org": (200, [{"lat": "999", "lon": "1"}])})
    assert lookups.enrich({}, "places", [{"name": "Nowhere"}], run=run_with(junk))["nowhere"]["nominatim"]["status"] == "none"


def test_rate_limit_one_second_between_musicbrainz_calls():
    clock = Clock()
    net = Net({"musicbrainz.org": (200, {"recordings": []}), "en.wikipedia.org": (200, {"pages": []})})
    run = run_with(net, clock)
    lookups.enrich({}, "tracks", [{"name": f"Song {n}"} for n in range(3)], run=run)
    assert clock.slept == [1.1, 1.1]
    lookups.enrich({}, "people", [{"name": "A Person"}], run=run)  # another API is not held back by MusicBrainz
    assert clock.slept == [1.1, 1.1]
    clock.now += 5
    lookups.enrich({}, "tracks", [{"name": "Song later"}], run=run)
    assert clock.slept == [1.1, 1.1]  # enough time passed


def test_budget_caps_requests():
    net = Net({"musicbrainz.org": (200, {"recordings": []})})
    run = run_with(net, requests=2)
    out = lookups.enrich({}, "tracks", [{"name": f"Song {n}"} for n in range(5)], run=run)
    assert len(net.calls) == 2 and len(out) == 2


def test_failure_keeps_old_data_and_is_not_done():
    old = {"tracks": {"midnight lantern": {"musicbrainz": {"status": "failed", "at": "2026-11-10", "url": "https://musicbrainz.org/recording/old"}}}}
    net = Net(fail={"musicbrainz.org"})
    out = lookups.enrich({"lookups": old}, "tracks", [{"name": "Midnight Lantern"}, {"name": "Second Song"}],
                         run=run_with(net), today="2026-11-14")
    assert out["midnight lantern"]["musicbrainz"] == {"url": "https://musicbrainz.org/recording/old", "status": "failed", "at": "2026-11-14"}
    assert out["second song"]["musicbrainz"]["status"] == "failed"
    assert len(net.calls) == 1  # an API that failed is not asked again in the same run
    # failed today: not asked again today; tomorrow it is
    view = {"tabs": {"tracks": {"items": [{"name": "Midnight Lantern"}]}}, "lookups": {"tracks": out}}
    assert lookups.wanted(view, "2026-11-14") == []
    assert [t for t, _, _ in lookups.wanted(view, "2026-11-15")] == ["tracks"]
    limited = Net({"musicbrainz.org": (503, b"")})
    assert lookups.enrich({}, "tracks", [{"name": "X"}], run=run_with(limited))["x"]["musicbrainz"]["status"] == "failed"


# ---- the worker step ------------------------------------------------------------------------------------------------

def built_post(tmp_path, store, tabs, url=POST):
    folder = tmp_path / f"post-{abs(hash(url)) % 1000}"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    item_id = store.id_for(url)
    store.set_view_status(item_id, "done")
    views.save(folder, views.tidy_view({"category": "music", "tabs": tabs}, engine="test:model"))
    return folder


@pytest.fixture
def store(tmp_path):
    lookups._quiet.clear()
    return Store(tmp_path / "m.db")


TRACKS = {"tracks": {"items": [{"name": "Midnight Lantern", "detail": "The Fictional Band", "kind": "song"}]}}


def test_lookups_due_saves_into_the_view_privately(tmp_path, store):
    folder = built_post(tmp_path, store, TRACKS)
    net = Net({"musicbrainz.org": (200, MB_RECORDING)})
    clock = Clock()
    assert lookups.lookups_due(store, get=net, pacer=lookups.Pacer(clock.time, clock.sleep), today="2026-11-14") == 1
    view = views.load(folder)
    assert view["lookups"]["tracks"]["midnight lantern"]["musicbrainz"]["year"] == "1987"
    assert view["tabs"] == views.tidy_view({"tabs": TRACKS})["tabs"] and view["engine"] == "test:model"
    assert stat.S_IMODE((folder / views.FILE).stat().st_mode) == 0o600
    assert lookups.lookups_due(store, get=net, pacer=lookups.Pacer(clock.time, clock.sleep), today="2026-11-14") == 0
    assert len(net.calls) == 1  # done is done


def test_private_mode_refuses_at_the_moment_of_use(tmp_path, store):
    folder = built_post(tmp_path, store, {"tracks": {"items": [{"name": f"Song {n}"} for n in range(4)]}})
    store.set_setting("ai_mode", "private")
    net = Net({"musicbrainz.org": (200, {"recordings": []})})
    assert lookups.lookups_due(store, get=net) == 0 and net.calls == []
    store.set_setting("ai_mode", "smart")
    clock = Clock()

    def sleep(seconds):  # the owner switches to Private while the worker waits for the rate limit
        clock.sleep(seconds)
        store.set_setting("ai_mode", "private")
    assert lookups.lookups_due(store, get=net, pacer=lookups.Pacer(clock.time, sleep), today="2026-11-14") == 1
    assert len(net.calls) == 1  # the first went out before the switch; nothing after it
    saved = views.load(folder)["lookups"]["tracks"]
    assert list(saved) == ["song 0"] and saved["song 0"]["musicbrainz"]["status"] == "none"


def test_paused_link_finding_stops_lookups(tmp_path, store):
    built_post(tmp_path, store, TRACKS)
    store.set_paused("links", True)
    net = Net()
    assert lookups.lookups_due(store, get=net) == 0 and net.calls == []


def test_a_view_rebuilt_meanwhile_is_not_overwritten(tmp_path, store):
    folder = built_post(tmp_path, store, TRACKS)

    def get(url, headers):  # Change category rebuilds the view while the request is out
        views.save(folder, views.tidy_view({"category": "books", "tabs": {"books": {"items": [{"name": "A Book"}]}}},
                                           engine="test:model", by="owner"))
        return 200, url, json.dumps(MB_RECORDING).encode()
    clock = Clock()
    assert lookups.lookups_due(store, get=get, pacer=lookups.Pacer(clock.time, clock.sleep)) == 0
    view = views.load(folder)
    assert view["category"] == "books" and view["lookups"] == {}


def test_offline_run_keeps_old_lookups(tmp_path, store):
    folder = built_post(tmp_path, store, {"tracks": {"items": [{"name": "Midnight Lantern"}, {"name": "New Song"}]}})
    view = views.load(folder)
    view["lookups"] = {"tracks": {"midnight lantern": {"musicbrainz": {"status": "ok", "at": "2026-11-01",
                                                                       "url": "https://musicbrainz.org/recording/rec-1"}}}}
    views.save(folder, view)
    clock = Clock()
    lookups.lookups_due(store, get=Net(fail={"musicbrainz.org"}), pacer=lookups.Pacer(clock.time, clock.sleep),
                        today="2026-11-14")
    saved = views.load(folder)["lookups"]["tracks"]
    assert saved["midnight lantern"]["musicbrainz"]["url"] == "https://musicbrainz.org/recording/rec-1"
    assert saved["new song"]["musicbrainz"] == {"status": "failed", "at": "2026-11-14"}
