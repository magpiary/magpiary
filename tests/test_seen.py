"""What the Chrome extension asks the hub: is this link saved already, and which board fits it."""

import json
from datetime import datetime

from test_browser_pairing import _post, add_browser, redeem
from test_setup import A, env  # noqa: F401  (the throwaway hub fixture)

from magpiary import boards, seen

THREAD_1 = "https://www.threads.com/@ada/post/AAA111/"
THREAD_2 = "https://www.threads.com/@ada/post/BBB222/"
THREAD_3 = "https://www.threads.com/@bo/post/CCC333/"


def paired(env):
    _, code = add_browser(env)
    return json.loads(redeem(env, code)[1])["key"]


def save(env, key, url, **extra):
    item = {"id": f"i{abs(hash((url, str(extra))))}", "url": url, "shared_at": "2026-10-31T00:42:51+05:30", **extra}
    assert _post(env, "/v1/items", json.dumps({"items": [item]}), key)[0] == 200


def ask(env, key, path, body):
    status, data = _post(env, path, json.dumps(body), key)
    return status, (json.loads(data) if data else {})


def test_seen_answers_only_for_links_asked_and_needs_a_key(env):
    key = paired(env)
    save(env, key, A)
    status, out = ask(env, key, "/v1/seen", {"urls": [A + "?igsh=x", "https://www.instagram.com/reel/NOPE999/", "not a link"]})
    assert status == 200
    hit, miss, junk = out["results"].values()
    assert hit["saved"] and hit["count"] == 1 and hit["last"].startswith("2026-10-31T00:42:51") and hit["id"] > 0
    assert miss == {"saved": False} and junk == {"saved": False}
    assert _post(env, "/v1/seen", json.dumps({"urls": [A]}))[0] == 401           # no key
    assert _post(env, "/v1/seen", json.dumps({"urls": "x"}), key)[0] == 400


def test_seen_counts_repeat_saves_trash_and_the_instagram_twin(env):
    key = paired(env)
    save(env, key, "https://www.instagram.com/p/ZZZ111/")
    save(env, key, "https://www.instagram.com/p/ZZZ111/", )
    assert ask(env, key, "/v1/seen", {"urls": ["https://www.instagram.com/reels/ZZZ111/"]})[1]["results"].popitem()[1]["saved"]  # same post, other address
    item = env.mac.store.items()[0]
    env.mac.store._db.execute("UPDATE items SET shelf='trash' WHERE id=?", (item["id"],))
    assert ask(env, key, "/v1/seen", {"urls": ["https://www.instagram.com/p/ZZZ111/"]})[1]["results"].popitem()[1] == {"saved": False}


def board(env, name):
    return boards.create(env.mac.store, name)


def test_suggest_the_board_you_just_saved_to(env):
    key = paired(env)
    logo = board(env, "Logo ideas")
    board(env, "Trip")
    assert ask(env, key, "/v1/suggest", {"url": THREAD_3})[1] == {"suggestion": None}   # nothing saved to a board yet
    save(env, key, THREAD_1, board=logo)
    got = ask(env, key, "/v1/suggest", {"url": "https://example.com/a"})[1]["suggestion"]
    assert got["id"] == logo and got["name"] == "Logo ideas" and "just now" in got["reason"]


def test_suggest_the_board_that_already_has_the_same_author(env):
    key = paired(env)
    logo, trip = board(env, "Logo ideas"), board(env, "Trip")
    save(env, key, THREAD_1, board=logo)
    save(env, key, THREAD_3, board=trip)
    # both were just saved: age the pending marks so only the author signal is left
    old = "2026-10-30T10:00:00+05:30"
    env.mac.store._db.execute("UPDATE board_pending SET created_at=?", (old,))
    got = ask(env, key, "/v1/suggest", {"url": THREAD_2})[1]["suggestion"]
    assert got["id"] == logo and "@ada" in got["reason"]
    later = datetime.fromisoformat(env.mac.store.now()).timestamp() + 5 * 3600
    assert seen.suggest(env.mac.store, "https://example.com/other", now=later) is None   # no author, nothing recent


def test_a_stale_save_suggests_nothing_and_suggest_needs_a_key(env):
    key = paired(env)
    logo = board(env, "Logo ideas")
    save(env, key, THREAD_1, board=logo)
    later = datetime.fromisoformat(env.mac.store.now()).timestamp() + 3 * 3600
    out = seen.suggest(env.mac.store, "https://example.com/x", now=later)
    assert out is None
    assert _post(env, "/v1/suggest", json.dumps({"url": A}))[0] == 401


def test_seen_ignores_identifiers_on_ordinary_pages_and_a_trailing_slash(env):
    key = paired(env)
    save(env, key, "https://example.com/story")                                   # as the phone saves it: no query string at all
    page = "https://example.com/story?ref=newsletter&utm_source=x&mc_eid=abc"
    out = ask(env, key, "/v1/seen", {"urls": [page, "https://example.com/story/", "https://example.com/other"]})[1]["results"]
    assert out[page]["saved"] and out["https://example.com/story/"]["saved"] and not out["https://example.com/other"]["saved"]
    save(env, key, "https://example.com/item?id=7")                               # a page whose address needs its query
    got = ask(env, key, "/v1/seen", {"urls": ["https://example.com/item?id=7&ref=home", "https://example.com/item?id=8"]})[1]["results"]
    assert got["https://example.com/item?id=7&ref=home"]["saved"] and not got["https://example.com/item?id=8"]["saved"]
