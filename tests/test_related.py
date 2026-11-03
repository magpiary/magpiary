"""Related content and Piles (M4): made-up meaning vectors, no model and no network."""

import html
import io
import json

import numpy as np
import pytest

from magpiary import related as rel
from magpiary.embed import EmbedFailed, ensure_model
from magpiary.store import Store
from magpiary.worker import related_due
from test_hub import page, post

TOPICS = {"pasta": 0, "rust": 1, "garden": 2, "chess": 3}


def fake_embedder(calls=None):
    """A vector per topic word in the text, with a little noise so no two items are identical."""
    def embed(texts):
        if calls is not None:
            calls.append(len(texts))
        out = []
        for n, text in enumerate(texts):
            v = np.full(8, 0.01) + 0.002 * (len(text) % 7)
            for word, axis in TOPICS.items():
                if word in text.lower():
                    v[axis] += 1.0
            out.append((v / np.linalg.norm(v)).tolist())
        return out
    return embed


def add(store, tmp_path, code, title, things=(), tags=()):
    url = f"https://www.instagram.com/reel/{code}/"
    folder = tmp_path / "library" / code
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"url": url}))
    record = {"title": title, "summary": title, "type": "other", "suggested_tags": list(tags), "key_points": [],
              "extras": {}, "entities": {"tools": list(things), "links": ["https://example.com"]}}
    (folder / "record.json").write_text(json.dumps(record))
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.brain_succeeded(url, record, "", apply_tags=False)
    return url


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path / "m.db")
    urls = {
        "p1": add(store, tmp_path, "P1", "Pasta carbonara", ["Guanciale"], ["cooking"]),
        "p2": add(store, tmp_path, "P2", "Pasta all'amatriciana", ["Guanciale"], ["cooking"]),
        "p3": add(store, tmp_path, "P3", "Fresh pasta by hand", [], ["cooking"]),
        "p4": add(store, tmp_path, "P4", "Pasta water tricks", [], ["cooking"]),
        "r1": add(store, tmp_path, "R1", "Rust ownership explained", ["Cargo"], ["coding"]),
        "r2": add(store, tmp_path, "R2", "Rust async in an hour", ["Cargo"], ["coding"]),
        "g1": add(store, tmp_path, "G1", "Garden tomatoes"),
        "c1": add(store, tmp_path, "C1", "Chess openings"),
    }
    rel.refresh_vectors(store, fake_embedder())
    yield store, urls
    store.close()


def titles(store, urls):
    return sorted(store.get_item(u)["ai_title"] for u in urls)


def test_related_ranks_by_topic_named_things_and_tags_with_a_reason(library):
    store, u = library
    lib = rel.load(store)
    found = rel.related(lib, u["p1"])
    assert found[0]["row"]["canonical_url"] == u["p2"] and found[0]["reason"] == "Both mention Guanciale"
    assert {f["row"]["canonical_url"] for f in found} == {u["p2"], u["p3"], u["p4"]}
    assert rel.related(lib, u["r1"])[0]["reason"] == "Both mention Cargo"
    assert rel.related(lib, u["c1"]) == []  # nothing else is about chess


def test_not_related_takes_a_pair_out_for_good(library):
    store, u = library
    store.mark_not_related(u["p2"], u["p1"])
    found = rel.related(rel.load(store), u["p1"])
    assert u["p2"] not in {f["row"]["canonical_url"] for f in found}


def test_vectors_are_made_once_and_again_only_when_the_text_changes(library):
    store, u = library
    calls = []
    assert rel.refresh_vectors(store, fake_embedder(calls)) == 0 and calls == []
    store.set_tags(store.id_for(u["g1"]), "gardening")
    assert rel.refresh_vectors(store, fake_embedder(calls)) == 2  # both readings of that one save


def by_name(store):
    return {frozenset(p["members"]): p for p in store.piles()}


def test_every_save_is_in_a_pile_named_from_what_it_shares(library):
    store, u = library
    rel.rebuild_piles(store)
    piles = by_name(store)
    assert set(piles) == {frozenset({u["p1"], u["p2"], u["p3"], u["p4"]}), frozenset({u["r1"], u["r2"]}),
                          frozenset({u["g1"]}), frozenset({u["c1"]})}
    pasta = piles[frozenset({u["p1"], u["p2"], u["p3"], u["p4"]})]
    assert "Pasta" in pasta["name"] or "Cooking" in pasta["name"]
    assert "Cargo" in piles[frozenset({u["r1"], u["r2"]})]["name"]
    assert "Chess" in piles[frozenset({u["c1"]})]["name"]  # a pile of one is named from its own words
    o = rel.overview(rel.load(store), pasta["members"])
    assert o["count"] == 4 and o["sources"] == {"instagram": 4} and ("#cooking", 4) in o["common"]
    assert rel.subtitle(rel.load(store), pasta["members"], pasta["name"])


def test_a_new_save_slots_into_the_closest_pile_and_counts_as_new(library, tmp_path):
    store, u = library
    rel.rebuild_piles(store)
    pasta = next(p for p in store.piles() if u["p1"] in p["members"])
    url = add(store, tmp_path, "P5", "Pasta e fagioli", [], ["cooking"])
    rel.refresh_vectors(store, fake_embedder())
    rel.rebuild_piles(store)
    assert url in store.pile(pasta["id"])["members"] and store.new_in_pile(pasta["id"]) == 1
    store.pile_seen(pasta["id"])
    assert store.new_in_pile(pasta["id"]) == 0


def test_the_owners_pile_edits_stick_when_piles_are_made_again(library):
    store, u = library
    rel.rebuild_piles(store)
    pile = next(p for p in store.piles() if u["p1"] in p["members"])
    store.rename_pile(pile["id"], "Italian food")
    store.remove_from_pile(pile["id"], u["p4"])
    rel.rebuild_piles(store, regroup=True)
    again = store.pile(pile["id"])
    assert again["name"] == "Italian food" and u["p4"] not in again["members"]
    assert any(p["members"] == [u["p4"]] for p in store.piles())  # every save stays in some pile

    store.delete_pile(pile["id"])
    rel.rebuild_piles(store, regroup=True)
    gone = {u["p1"], u["p2"], u["p3"]}
    assert all(len(gone & set(p["members"])) < 2 for p in store.piles())  # a deleted pile is never made again
    assert {x for p in store.piles() for x in p["members"]} == set(u.values())  # and every save is still in one


def test_split_and_merge(library):
    store, u = library
    rel.rebuild_piles(store)
    pile = next(p for p in store.piles() if u["p1"] in p["members"])
    new = store.split_pile(pile["id"], [u["p3"], u["p4"]], "Pasta basics")
    assert set(store.pile(new)["members"]) == {u["p3"], u["p4"]}
    assert set(store.pile(pile["id"])["members"]) == {u["p1"], u["p2"]}
    rel.rebuild_piles(store, regroup=True)
    assert store.pile(new)["name"] == "Pasta basics" and set(store.pile(pile["id"])["members"]) == {u["p1"], u["p2"]}
    assert store.merge_piles(new, pile["id"])
    assert set(store.pile(pile["id"])["members"]) == {u["p1"], u["p2"], u["p3"], u["p4"]} and store.pile(new) is None


def test_the_worker_makes_vectors_then_piles_and_survives_a_missing_model(library):
    store, u = library
    assert related_due(store, embedder=fake_embedder()) == 0 and len(store.piles()) == 4

    def broken(texts):
        raise EmbedFailed("no network")
    logged = []
    store.set_tags(store.id_for(u["c1"]), "games")
    assert related_due(store, embedder=broken, log=logged.append) == 0 and "no network" in logged[0]


def test_a_downloaded_model_file_with_the_wrong_checksum_is_not_kept(tmp_path):
    class Body(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    with pytest.raises(EmbedFailed, match="checksum"):
        ensure_model(tmp_path / "model", opener=lambda url, timeout: Body(b"not the model"))
    assert list((tmp_path / "model").iterdir()) == []


# ---- the hub ---------------------------------------------------------------------------------

def test_the_item_page_shows_related_and_the_piles_pages_let_the_owner_edit(mac, tmp_path):
    store = mac.store
    u = {k: add(store, tmp_path, k.upper(), t, things, ["cooking"]) for k, t, things in (
        ("p1", "Pasta carbonara", ["Guanciale"]), ("p2", "Pasta amatriciana", ["Guanciale"]),
        ("p3", "Fresh pasta", []), ("c1", "Chess openings", []), ("g1", "Garden tomatoes", []),
        ("r1", "Rust ownership", []))}
    related_due(store, embedder=fake_embedder())
    ids = {k: store.id_for(v) for k, v in u.items()}
    body = page(mac, f"/item/{ids['p1']}?tab=rel")[2]
    assert "Related" in body and "Pasta amatriciana" in body and "Both mention Guanciale" in body
    assert 'class="pvpile"' in body and "Not related" in body
    assert "More like this" not in page(mac, "/")[2]  # decided in C1+: not on tiles, in the post's Related tab
    assert "Pasta amatriciana" in page(mac, f"/item/{ids['p1']}/related")[2]

    pile = next(p for p in store.piles() if u["p1"] in p["members"])
    assert html.escape(pile["name"]) in page(mac, "/?view=piles")[2]
    status, headers, _ = post(mac, "/hub/pile/rename", pile=str(pile["id"]), name="Dinner", next=f"/pile/{pile['id']}")
    body = page(mac, f"/pile/{pile['id']}")[2]
    assert status == 303 and "Dinner" in body and "ptags" in body and "Split off" in body
    post(mac, "/hub/pile/delete", pile=str(pile["id"]), next="/piles")
    assert "Dinner" not in page(mac, "/?view=piles")[2]
    status, headers, _ = post(mac, "/hub/piles/regroup", next="/piles")
    assert status == 303 and "Regroup everything" in page(mac, "/?view=piles")[2]

    related_due(store, embedder=fake_embedder())
    post(mac, "/hub/not-related", id=str(ids["p1"]), other=str(ids["p2"]), next=f"/item/{ids['p1']}")
    assert "Pasta amatriciana" not in page(mac, f"/item/{ids['p1']}/related")[2]


def test_a_save_moved_by_hand_stays_through_a_regroup(mac, tmp_path):
    store = mac.store
    u = {k: add(store, tmp_path, k.upper(), t, things, ["cooking"]) for k, t, things in (
        ("p1", "Pasta carbonara", ["Guanciale"]), ("p2", "Pasta amatriciana", ["Guanciale"]),
        ("p3", "Fresh pasta", []), ("c1", "Chess openings", []), ("g1", "Garden tomatoes", []))}
    related_due(store, embedder=fake_embedder())
    home = next(p for p in store.piles() if u["p1"] in p["members"])
    target = store.new_pile("Chess and more")
    post(mac, "/hub/bulk", ids=str(store.id_for(u["p1"])), action="pile", pile=str(target))
    assert [p["id"] for p in store.piles() if u["p1"] in p["members"]] == [target]
    post(mac, "/hub/piles/regroup", next="/?view=piles")
    assert [p["id"] for p in store.piles() if u["p1"] in p["members"]] == [target]
    assert home["id"] != target


# ---- search by meaning (M7b) --------------------------------------------------------------------

class FakeMeaning:
    """Stands in for embed.Warm: a search's vector from the same topic words as the saves'."""
    def __init__(self):
        self.asked = []

    def query(self, text):
        self.asked.append(text)
        return fake_embedder()([text])[0]


def test_by_meaning_finds_saves_about_the_idea_and_nothing_for_a_stranger(library):
    store, urls = library
    close = rel.by_meaning(store, fake_embedder()(["pasta"])[0])
    assert set(close) == {urls["p1"], urls["p2"], urls["p3"], urls["p4"]}
    assert rel.by_meaning(store, fake_embedder()(["nothing alike"])[0]) == {}


def test_search_blends_meaning_matches_after_the_word_matches_and_typing_asks_words_first(mac, tmp_path):
    store = mac.store
    for code, title in (("P1", "Pasta carbonara"), ("P2", "Pasta water tricks"), ("R1", "Rust ownership"),
                        ("G1", "Garden tomatoes"), ("C1", "Chess openings"), ("R2", "Rust async")):
        add(store, tmp_path, code, title)
    related_due(store, embedder=fake_embedder())
    mac.server.hub.meaning = FakeMeaning()
    body = page(mac, "/?q=carbonara+pasta")[2]  # the word match first, then the other pasta save by meaning
    assert body.index("Pasta carbonara") < body.index("Pasta water tricks") and "Rust ownership" not in body
    words = page(mac, "/?q=carbonara&words=1")[2]  # while typing: words only, the model is not asked
    assert "Pasta carbonara" in words and "Pasta water tricks" not in words
    assert mac.server.hub.meaning.asked == ["carbonara pasta"]
    mac.server.hub.meaning = None  # no model: words only, nothing breaks
    assert "Pasta water tricks" not in page(mac, "/?q=carbonara")[2]


def test_the_warm_model_answers_searches_and_lets_go_when_idle_or_broken(tmp_path):
    import io

    from magpiary.embed import FILES, Warm
    for name in FILES:
        (tmp_path / name).write_text("x")
    started = []

    class Child:
        def __init__(self, *a, **k):
            started.append(1)
            self.stdin, self.stdout, self.dead = io.StringIO(), io.StringIO("[0.6, 0.8]\n"), False

        def poll(self):
            return 0 if self.dead else None

        def wait(self, timeout=None):
            self.dead = True

        def kill(self):
            self.dead = True

    warm = Warm(tmp_path, idle=60, spawn=Child)
    assert warm.query("cheap food") == [0.6, 0.8] and '"prefix": "query"' in warm._child.stdin.getvalue()
    assert warm.query("again") is None and warm._child is None  # no answer: stopped, search falls back to words
    warm.stop()
    assert Warm(tmp_path / "missing", spawn=Child).query("x") is None and len(started) == 1  # never downloads


def test_a_pile_that_grows_too_big_splits_into_distinct_sub_topics_and_names_come_from_the_namer():
    import numpy as np

    from magpiary import related as rel

    n = 30
    scores = np.full((n, n), 1.4, dtype=np.float32)  # one broad topic: everything is a little close
    for block in (range(0, 15), range(15, 30)):
        for i in block:
            for j in block:
                scores[i, j] = 3.0
    np.fill_diagonal(scores, rel.BLOCKED)
    rows = [{"canonical_url": f"https://example.com/{i}", "title": f"post {i}"} for i in range(n)]
    lib = rel.Library(rows, [{}] * n, [set()] * n, scores, scores, {}, {})
    parts = rel.partition(lib)
    assert sorted(len(g) for g in parts) == [15, 15]  # one big AI-like pile became two distinct ones
    assert sorted(i for g in parts for i in g) == list(range(n))  # and every save is in exactly one pile
