"""The connections map, worked out on this Mac from the scores Related already keeps (no AI, no key, no quota).

Posts are nodes. An edge joins two posts whose Related score clears RELATED_MIN, carrying the same one-line reason
Related shows. Each post keeps only its few strongest edges, so a big library stays readable. The things many posts
share (a tool, a place, a book, a tag) become small hub nodes the posts hang from, like Obsidian's backlinks.
Piles colour the posts; the page folds a pile into one node when there are many.

`library_graph` is the whole map, `item_graph` the small one around a single post ("Connected to").
"""

import numpy as np

from magpiary import related as rel
from magpiary import ui

EDGES_PER_POST = 5   # a post's strongest links; more would make a hairball
MAX_EDGES = 6000     # a safety net for a very large library
HUB_MIN = 2          # a thing needs this many posts before it is drawn as a hub
HUB_WEIGHT = 0.3     # and must be rarer than this (the same cut Related uses for its reasons)
MAX_HUBS = 40
LOCAL_NEIGHBOURS = 12
LOCAL_HUBS = 6


def _facts(store) -> dict[str, dict]:
    """Type, thumbnail and author per post, from the library's own listing."""
    return {i["canonical_url"]: i for i in store.hub_items("kept", compact=True, limit=1_000_000)}


def _pile_of(store) -> tuple[dict[str, int], list[dict]]:
    owner, piles = {}, []
    for p in store.piles():
        members = [u for u in p["members"] if u]
        if not members:
            continue
        piles.append({"id": p["id"], "name": p["name"], "n": len(members),
                      "colour": ui.PILE_COLOURS[p["id"] % len(ui.PILE_COLOURS)]})
        for u in members:
            owner.setdefault(u, p["id"])
    return owner, piles


def _post(lib: rel.Library, i: int, facts: dict, owner: dict) -> dict:
    row = lib.rows[i]
    f = facts.get(row["canonical_url"], {})
    return {"id": f"p{row['id']}", "kind": "post", "item": row["id"], "label": rel.title_of(row)[:90],
            "type": f.get("ai_type") or "other", "source": row.get("source") or "",
            "pile": owner.get(row["canonical_url"])}


def _hubs(lib: rel.Library, among: list[int], limit: int) -> dict[str, dict]:
    """Things (named or tagged) shared by two or more of `among`, rarest and most shared first."""
    found: dict[str, dict] = {}
    for i in among:
        for key, shown in lib.named[i].items():
            if lib.name_weight.get(key, 0.0) >= HUB_WEIGHT and not key.startswith("http"):
                h = found.setdefault("n:" + key, {"kind": "thing", "label": shown, "w": lib.name_weight[key], "posts": []})
                h["posts"].append(i)
        for key in rel.tag_set(lib.rows[i]):
            if len(key) <= 24:
                h = found.setdefault("t:" + key, {"kind": "tag", "label": "#" + key, "w": 0.6, "posts": []})
                h["posts"].append(i)
    keep = [(k, h) for k, h in found.items() if len(h["posts"]) >= HUB_MIN]
    keep.sort(key=lambda kv: (-len(kv[1]["posts"]) * kv[1]["w"], kv[0]))
    return dict(keep[:limit])


def _pair_edges(lib: rel.Library, pairs) -> list[dict]:
    return [{"a": f"p{lib.rows[i]['id']}", "b": f"p{lib.rows[j]['id']}", "score": round(float(lib.scores[i, j]), 2),
             "why": rel.reason(lib, i, j)} for i, j in pairs]


def library_graph(lib: rel.Library, store) -> dict:
    """Everything: every post, its strongest links, the shared things, and the piles."""
    n = len(lib.rows)
    facts = _facts(store)
    owner, piles = _pile_of(store)
    nodes = [_post(lib, i, facts, owner) for i in range(n)]
    pairs: set[tuple[int, int]] = set()
    if n > 1:
        order = np.argsort(-lib.scores, axis=1)[:, :EDGES_PER_POST]
        for i in range(n):
            for j in order[i]:
                if lib.scores[i, j] >= rel.RELATED_MIN:
                    pairs.add((min(i, int(j)), max(i, int(j))))
    ranked = sorted(pairs, key=lambda p: -lib.scores[p])[:MAX_EDGES]
    edges = _pair_edges(lib, ranked)
    for key, h in _hubs(lib, list(range(n)), MAX_HUBS).items():
        nodes.append({"id": key, "kind": h["kind"], "label": h["label"], "n": len(h["posts"])})
        edges += [{"a": f"p{lib.rows[i]['id']}", "b": key, "score": 0, "why": ""} for i in h["posts"]]
    return {"nodes": nodes, "edges": edges, "piles": piles, "types": _count(nodes, "type"), "sources": _count(nodes, "source")}


def item_graph(lib: rel.Library, store, item_id: int) -> dict:
    """The post in the middle, what is related to it, the things it shares with them, and links among the neighbours."""
    centre = next((i for i, r in enumerate(lib.rows) if r["id"] == item_id), None)
    if centre is None:
        return {"nodes": [], "edges": [], "piles": [], "types": {}, "sources": {}, "centre": ""}
    facts = _facts(store)
    owner, piles = _pile_of(store)
    order = [int(j) for j in np.argsort(-lib.scores[centre])
             if lib.scores[centre, j] >= rel.RELATED_MIN][:LOCAL_NEIGHBOURS]
    members = [centre, *order]
    nodes = [_post(lib, i, facts, owner) for i in members]
    pairs = [(centre, j) for j in order]
    pairs += [(a, b) for k, a in enumerate(order) for b in order[k + 1:] if lib.scores[a, b] >= rel.RELATED_MIN]
    edges = _pair_edges(lib, pairs)
    shared = {k: h for k, h in _hubs(lib, members, 100).items() if centre in h["posts"] and len(h["posts"]) >= 2}
    for key, h in list(shared.items())[:LOCAL_HUBS]:
        nodes.append({"id": key, "kind": h["kind"], "label": h["label"], "n": len(h["posts"])})
        edges += [{"a": f"p{lib.rows[i]['id']}", "b": key, "score": 0, "why": ""} for i in h["posts"]]
    return {"nodes": nodes, "edges": edges, "piles": piles, "types": _count(nodes, "type"),
            "sources": _count(nodes, "source"), "centre": f"p{item_id}"}


def _count(nodes: list[dict], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for n in nodes:
        if n["kind"] == "post" and n.get(field):
            out[n[field]] = out.get(n[field], 0) + 1
    return out
