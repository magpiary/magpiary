"""The connections map: the graph made from Related's scores, its pages, and the small map on a post (fictional saves)."""

import json

from magpiary import graph
from magpiary import related as rel
from magpiary.hub_map import local_map_html
from test_hub import page
from test_related import add, fake_embedder, library  # noqa: F401  (the fixture)


def ids(store, urls):
    return {k: f"p{store.id_for(u)}" for k, u in urls.items()}


def build(store):
    return graph.library_graph(rel.load(store), store)


def test_the_graph_has_every_save_related_edges_with_reasons_and_shared_things(library):
    store, urls = library
    pid = ids(store, urls)
    g = build(store)
    posts = {n["id"]: n for n in g["nodes"] if n["kind"] == "post"}
    assert set(posts) == set(pid.values())
    pairs = {frozenset((e["a"], e["b"])): e for e in g["edges"] if e["score"]}
    assert frozenset((pid["p1"], pid["p2"])) in pairs                       # the same topic and a shared name
    assert "Guanciale" in pairs[frozenset((pid["p1"], pid["p2"]))]["why"]
    assert all(e["score"] >= rel.RELATED_MIN for e in pairs.values())
    assert frozenset((pid["p1"], pid["r1"])) not in pairs                    # pasta and rust stay apart
    hubs = {n["label"]: n for n in g["nodes"] if n["kind"] != "post"}
    assert hubs["Guanciale"]["n"] == 2 and hubs["#cooking"]["n"] == 4        # a thing and a tag many saves share
    assert {e["b"] for e in g["edges"] if not e["score"] and e["b"].startswith("n:")} == {"n:guanciale", "n:cargo"}


def test_each_save_keeps_only_its_strongest_links(library, monkeypatch):
    store, urls = library
    monkeypatch.setattr(graph, "EDGES_PER_POST", 1)
    g = build(store)
    per_post: dict[str, int] = {}
    for e in g["edges"]:
        if e["score"]:
            per_post[e["a"]] = per_post.get(e["a"], 0) + 1
            per_post[e["b"]] = per_post.get(e["b"], 0) + 1
    assert max(per_post.values()) <= 4  # one chosen by itself plus those that chose it, never the whole topic


def test_a_not_related_mark_removes_the_edge(library):
    store, urls = library
    pid = ids(store, urls)
    key = frozenset((pid["p1"], pid["p2"]))
    assert key in {frozenset((e["a"], e["b"])) for e in build(store)["edges"] if e["score"]}
    store.mark_not_related(urls["p1"], urls["p2"])
    assert key not in {frozenset((e["a"], e["b"])) for e in build(store)["edges"] if e["score"]}


def test_piles_colour_the_saves_and_are_listed_with_their_size(library):
    store, urls = library
    rel.rebuild_piles(store, regroup=True, namer=lambda *a: None)
    g = build(store)
    pid = ids(store, urls)
    posts = {n["id"]: n for n in g["nodes"] if n["kind"] == "post"}
    pasta = posts[pid["p1"]]["pile"]
    assert pasta is not None and all(posts[pid[k]]["pile"] == pasta for k in ("p2", "p3", "p4"))
    pile = next(p for p in g["piles"] if p["id"] == pasta)
    assert pile["n"] >= 4 and pile["colour"]
    assert posts[pid["r1"]]["pile"] != pasta


def test_the_map_around_one_post_is_small_and_centred(library):
    store, urls = library
    pid = ids(store, urls)
    g = graph.item_graph(rel.load(store), store, store.id_for(urls["p1"]))
    assert g["centre"] == pid["p1"]
    posts = {n["id"] for n in g["nodes"] if n["kind"] == "post"}
    assert posts == {pid["p1"], pid["p2"], pid["p3"], pid["p4"]}
    assert any(n["label"] == "Guanciale" for n in g["nodes"])
    assert all(e["a"] in {n["id"] for n in g["nodes"]} and e["b"] in {n["id"] for n in g["nodes"]} for e in g["edges"])
    assert graph.item_graph(rel.load(store), store, 99999)["nodes"] == []


def test_the_local_map_fragment_and_its_empty_message(library):
    store, urls = library
    lib = rel.load(store)
    html = local_map_html(store, store.id_for(urls["p1"]), lib)
    assert 'data-map-src="/graph.json?scope=item&amp;id=' in html and "Open the full map" in html
    assert "Nothing is connected" in local_map_html(store, store.id_for(urls["c1"]), lib)


def test_the_map_page_and_its_data_over_http(mac, tmp_path):
    for code, title, things in (("A1", "Pasta carbonara", ["Guanciale"]), ("A2", "Pasta amatriciana", ["Guanciale"]),
                                ("A3", "Rust ownership", ["Cargo"])):
        add(mac.store, tmp_path, code, title, things, ["cooking" if "Pasta" in title else "coding"])
    rel.refresh_vectors(mac.store, fake_embedder())
    status, headers, body = page(mac, "/map")
    assert status == 200 and 'data-map-src="/graph.json?scope=all"' in body and "/static/map.js" in body
    status, headers, body = page(mac, "/graph.json")
    data = json.loads(body)
    assert status == 200 and headers["Content-Type"] == "application/json" and len(data["nodes"]) >= 3
    first = next(n["item"] for n in data["nodes"] if n["kind"] == "post")
    status, _, body = page(mac, f"/graph.json?scope=item&id={first}")
    assert json.loads(body)["centre"] == f"p{first}"
    assert page(mac, "/static/map.js")[0] == 200 and page(mac, "/static/map.css")[0] == 200


def test_the_map_page_waits_for_two_saves(mac):
    status, _, body = page(mac, "/map")
    assert status == 200 and "Nothing to connect yet" in body
