"""The receiver seen from outside: what the phone sends, what the Mac replies and keeps."""

import json
import os
import sqlite3
import urllib.error
import urllib.request

import pytest

from fakephone import CouldNotConnect, Phone
from magpiary.expand import FAILURE_REASON, RETRY_DELAYS_SECONDS
from magpiary.worker import process_due

IG = "https://www.instagram.com"
A, B = f"{IG}/reel/AAAA111/", f"{IG}/reel/BBBB222/"
THREADS_POST = "https://www.threads.com/@examplecreator/post/CCCC333/"


def item(url, item_id="id-1", **extra):
    return {"id": item_id, "url": url, "shared_at": "2026-10-23T12:00:00+05:30", **extra}


def body(*items):
    return json.dumps({"items": list(items)})


# ---- ping ---------------------------------------------------------------------------------

def test_ping_needs_no_key_and_reveals_nothing_stored(mac, phone):
    phone.run(A)
    with urllib.request.urlopen(mac.url + "/v1/ping") as r:
        reply = json.loads(r.read())
    assert reply == {"ok": True, "service": "magpiary", "v": 1, "uid": os.getuid()}


# ---- the phone's everyday runs --------------------------------------------------------------

def test_share_with_tracking_tail_is_stored_clean_and_outbox_clears(mac, phone):
    msg = phone.run(A + "?igsh=abc&utm_source=ig_web_copy_link")
    assert mac.counts() == {A: 1}
    assert phone.waiting() == 0
    assert "Saved to Magpiary" in msg


def test_same_reel_twice_is_one_item_saved_twice(mac, phone):
    phone.run(A + "?igsh=abc")
    msg = phone.run("Look at this " + A + "?igsh=zzz\nthanks")
    assert mac.counts() == {A: 2}
    assert "Already in Magpiary" in msg and "2" in msg


def test_youtube_keeps_only_the_video_id(mac, phone):
    phone.run("https://www.youtube.com/watch?v=Example0005&si=track&t=42s")
    phone.run("https://youtu.be/Example0006?si=track")
    phone.run("https://youtube.com/shorts/Example0007?feature=share")
    assert sorted(mac.counts()) == [
        "https://www.youtube.com/watch?v=Example0005",
        "https://www.youtube.com/watch?v=Example0006",
        "https://www.youtube.com/watch?v=Example0007",
    ]


def test_the_mac_cleans_again_even_if_the_phone_did_not(mac, phone):
    status, reply = mac.raw_post(phone.key, body(item(A + "?igsh=leak&utm_source=x#frag")))
    assert status == 200 and reply["accepted"] == ["id-1"]
    assert mac.counts() == {A: 1}


def test_run_with_nothing_shared_is_acknowledged_silently(mac, phone):
    msg = phone.run("")
    assert msg == "" and phone.waiting() == 0 and mac.counts() == {}


def test_away_from_home_nothing_is_sent_then_everything_flushes(mac, phone):
    msg = phone.run(B + "?igsh=away", at_home=False)
    assert "send when you're home" in msg and phone.waiting() == 1 and mac.counts() == {}
    phone.run("", at_home=True)
    assert mac.counts() == {B: 1} and phone.waiting() == 0


def test_offline_shares_wait_and_flush_in_one_batch(mac, phone):
    mac.stop()
    with pytest.raises(CouldNotConnect):
        phone.run(A + "?utm_source=x")                  # the one slow failure
    assert "wasn't reachable" in phone.run(THREADS_POST + "?utm_source=x")   # the next one, right after, does not even try
    assert phone.waiting() == 2
    mac.start()
    msg = phone.run("")
    assert mac.counts() == {A: 1, THREADS_POST: 1} and phone.waiting() == 0
    assert "Saved 2 items" in msg


def test_junk_is_rejected_and_retired_from_the_outbox(mac, phone):
    msg = phone.run("not a link at all")
    assert mac.counts() == {} and phone.waiting() == 0
    reply = json.loads(phone.sent_bodies[-1])
    answer = phone.post(json.dumps(reply))  # signed, as the Shortcut sends (its key alone is refused once it signs)
    assert answer["rejected"] == [{"id": reply["items"][0]["id"], "reason": "unsupported_link"}]
    assert "can't save" in msg


def test_other_websites_are_accepted_with_the_safe_default(mac, phone):
    # sent straight to the Mac, as a phone that kept the query would (the Shortcut itself drops it)
    mac.raw_post(phone.key, body(item("https://example.com/article?id=7&utm_source=x")))
    assert list(mac.counts()) == ["https://example.com/article?id=7"]


# ---- failures must not lose anything --------------------------------------------------------

def test_a_503_does_not_lose_the_reel_and_the_retry_stores_it_once(mac, phone):
    mac.server.fail_next_posts = 1
    msg = phone.run(A)
    assert phone.waiting() == 1 and mac.counts() == {} and "didn't accept" in msg
    phone.run("")
    assert mac.counts() == {A: 1} and phone.waiting() == 0


def test_a_wrong_key_keeps_the_reel_on_the_phone(mac):
    bad = Phone(mac, "wrong-key")
    msg = bad.run(A)
    assert bad.waiting() == 1 and mac.counts() == {} and "didn't accept" in msg


def test_resending_a_batch_after_a_lost_reply_changes_nothing(mac, phone):
    batch = body(item(A, "id-1"), item(B, "id-2"))
    mac.raw_post(phone.key, batch)
    status, reply = mac.raw_post(phone.key, batch)  # the phone never saw the first reply
    assert status == 200 and reply["accepted"] == ["id-1", "id-2"]
    assert [r["status"] for r in reply["results"]] == ["replay", "replay"]
    assert mac.counts() == {A: 1, B: 1}


def test_the_item_is_in_the_database_before_the_reply(mac, phone):
    mac.raw_post(phone.key, body(item(A)))
    other = sqlite3.connect(mac.db_path)  # a separate connection sees only committed data
    try:
        assert other.execute("select saved_count from items").fetchall() == [(1,)]
    finally:
        other.close()


def test_items_survive_a_restart_of_the_store(mac, phone, clock):
    from magpiary.store import Store
    phone.run(A)
    mac.stop()
    mac.store.close()
    mac.store = Store(mac.db_path, now=clock.now)
    mac.start()
    assert mac.counts() == {A: 1}
    phone.run(A)
    assert mac.counts() == {A: 2}


# ---- keys and phones ------------------------------------------------------------------------

def test_each_item_records_which_phone_sent_it(mac, phone):
    _, key2 = mac.store.add_phone("Second iPhone")
    Phone(mac, key2).run(B)
    phone.run(A)
    assert {i["canonical_url"]: i["phone"] for i in mac.store.items()} == {
        A: "Test iPhone", B: "Second iPhone"}


def test_revoking_one_phone_leaves_the_other_working(mac, phone):
    _, key2 = mac.store.add_phone("Second iPhone")
    second = Phone(mac, key2)
    assert mac.store.revoke_phone("Test iPhone")
    assert "didn't accept" in phone.run(A) and phone.waiting() == 1
    assert "Saved to Magpiary" in second.run(B)
    assert mac.counts() == {B: 1}


def test_missing_or_empty_key_is_refused(mac):
    assert mac.raw_post(None, body(item(A)))[0] == 401
    assert mac.raw_post("", body(item(A)))[0] == 401


def test_keys_are_not_stored_in_clear(mac, phone, tmp_path):
    mac.store.close()
    for f in tmp_path.glob("magpiary.db*"):
        assert phone.key.encode() not in f.read_bytes()
    from magpiary.store import Store
    mac.store = Store(mac.db_path, now=mac.clock.now)  # so the fixture can close it


def test_the_key_never_appears_in_the_log(mac, phone, capfd):
    phone.run(A)
    Phone(mac, "another-secret-key").run(B)
    out = capfd.readouterr()
    assert phone.key not in out.out + out.err and "another-secret-key" not in out.out + out.err


def test_the_database_file_is_private(mac):
    assert oct(mac.db_path.stat().st_mode & 0o777) == "0o600"


def test_duplicate_phone_names_are_refused(mac, phone):
    with pytest.raises(ValueError):
        mac.store.add_phone("Test iPhone")


# ---- limits and junk requests ---------------------------------------------------------------

def test_too_many_items_are_refused_and_nothing_is_stored(mac, phone):
    items = [item(f"{IG}/reel/X{n:04d}/", f"id-{n}") for n in range(1001)]
    status, _ = mac.raw_post(phone.key, body(*items))
    assert status == 413 and mac.counts() == {}


def test_an_oversized_request_is_refused(mac, phone):
    try:
        status, _ = mac.raw_post(phone.key, body(item(A, note="x" * 1_100_000)))
    except (urllib.error.URLError, ConnectionError):
        status = 413  # the Mac hangs up before reading the upload: also a refusal
    assert status == 413 and mac.counts() == {}


@pytest.mark.parametrize("payload", ["not json", "{}", '{"items": "nope"}', ""])
def test_malformed_bodies_get_400(mac, phone, payload):
    assert mac.raw_post(phone.key, payload)[0] == 400


def test_unknown_paths_get_404(mac, phone):
    assert mac.raw_post(phone.key, body(), path="/v1/other")[0] == 404


def test_bad_items_inside_a_batch_are_rejected_one_by_one(mac, phone):
    items = ["a string", {"url": A}, {"id": "x" * 200, "url": A}, {"id": "ok", "url": 7},
             item(A, "good")]
    status, reply = mac.raw_post(phone.key, body(*items))
    assert status == 200 and reply["accepted"] == ["good"]
    assert [r["reason"] for r in reply["rejected"]] == ["bad_item", "bad_id", "bad_id", "bad_url"]
    assert mac.counts() == {A: 1}


def test_notes_are_capped_and_treated_as_plain_text(mac, phone):
    mac.raw_post(phone.key, body(item(A, note="<script>alert(1)</script>" + "x" * 5000)))
    stored = mac.store.get_item(A)["note"]
    assert len(stored) == 2000 and stored.startswith("<script>")  # kept as data, not interpreted


# ---- short links ----------------------------------------------------------------------------

def replay_fetch(recorded):
    def fetch(url):
        if url not in recorded:
            raise ConnectionError(url)
        return recorded[url]
    return fetch


SHORT = "https://www.threads.com/share/ExampleShare3"
SHORT_STORED = "https://www.threads.com/share/ExampleShare3/"


def test_a_short_link_is_stored_at_once_then_expanded_in_the_background(mac, phone):
    phone.run(SHORT)
    assert mac.counts() == {SHORT_STORED: 1} and phone.waiting() == 0   # acked and durable
    fetch = replay_fetch({SHORT_STORED: (302, THREADS_POST + "?xmt=AQ")})
    assert process_due(mac.store, fetch, pause=lambda: None) == 1
    assert mac.counts() == {THREADS_POST: 1}
    assert mac.store.get_item(THREADS_POST)["status"] == "queued"
    assert "ExampleShare3" not in json.dumps(mac.store.items())               # the sharer's code is gone


def test_a_short_link_that_fails_is_flagged_and_retried_on_schedule(mac, phone, clock):
    phone.run(SHORT)
    nothing = replay_fetch({})
    process_due(mac.store, nothing, pause=lambda: None)
    item_ = mac.store.get_item(SHORT_STORED)
    assert item_["status"] == "needs_attention" and item_["reason"] == FAILURE_REASON
    assert process_due(mac.store, nothing, pause=lambda: None) == 0
    assert mac.store.get_item(SHORT_STORED)["attempts"] == 1            # not due yet: no new attempt
    clock.advance(RETRY_DELAYS_SECONDS[0] + 1)
    fetch = replay_fetch({SHORT_STORED: (302, THREADS_POST)})
    assert process_due(mac.store, fetch, pause=lambda: None) == 1
    done = mac.store.get_item(THREADS_POST)
    assert done["status"] == "queued" and done["reason"] is None and done["attempts"] == 0  # the fetch stage counts its own tries


def test_retries_stop_after_the_schedule_and_the_item_stays_flagged(mac, phone, clock):
    phone.run(SHORT)
    nothing = replay_fetch({})
    for delay in RETRY_DELAYS_SECONDS:
        process_due(mac.store, nothing, pause=lambda: None)
        clock.advance(delay + 1)
    process_due(mac.store, nothing, pause=lambda: None)
    final = mac.store.get_item(SHORT_STORED)
    assert final["status"] == "needs_attention" and final["next_retry_at"] is None
    assert mac.store.due_for_expansion() == []


def test_a_short_link_to_a_post_already_stored_merges_the_counts(mac, phone):
    phone.run(THREADS_POST)
    phone.run(SHORT)
    fetch = replay_fetch({SHORT_STORED: (302, THREADS_POST)})
    process_due(mac.store, fetch, pause=lambda: None)
    assert mac.counts() == {THREADS_POST: 2}


# ---- signed sends (0.1.5): the key never crosses the Wi-Fi ------------------------------------

def send(mac, headers: dict, data: bytes, path: str = "/v1/items", method: str = "POST") -> int:
    req = urllib.request.Request(mac.url + path, data=data if method == "POST" else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_a_signed_send_is_stored_and_its_board_list_read(mac, phone):
    phone.run(A)
    assert mac.counts() == {A: 1}
    assert send(mac, phone.signed("GET /v1/boards"), b"", "/v1/boards", "GET") == 200


def test_a_changed_body_a_wrong_clock_or_another_request_is_refused(mac, phone):
    data = body(item(B)).encode()
    signed = phone.signed("POST /v1/items", data)
    assert send(mac, signed, body(item(A)).encode()) == 401                   # someone swapped the body
    assert send(mac, phone.signed("GET /v1/boards"), data) == 401             # a GET's signature on a POST
    assert send(mac, {**signed, "X-Magpiary-Device": "0" * 24}, data) == 401  # not a phone of this Mac
    mac.clock.advance(11 * 60)
    assert send(mac, signed, data) == 401                                     # older than ten minutes
    assert send(mac, phone.signed("POST /v1/items", data), data) == 200       # signed again, now
    assert mac.counts() == {B: 1}


def test_an_old_shortcut_key_works_until_that_phone_first_signs(mac, phone):
    bearer = {"Authorization": f"Bearer {phone.key}"}
    assert send(mac, bearer, body(item(A)).encode()) == 200                   # an older Shortcut, not yet updated
    phone.run(B)                                                              # the new Shortcut signs
    assert send(mac, bearer, body(item(A, "id-2")).encode()) == 401           # a key seen on the Wi-Fi is now useless
    assert send(mac, bearer, b"", "/v1/boards", "GET") == 401
    assert mac.store.list_phones()[0]["signed_at"]
