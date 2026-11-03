"""Shared boards (M9 task 4): two Macs, each with its own library and identity, fill one board through a fake relay
or a fake bucket; the board each sees is the replay of both members' events."""

import json
import re

import pytest

from magpiary import boards, boardsync, identity
from magpiary.store import Store
from test_boardsync import Relays, Storage


def make(store, name, via="nostr"):
    """A board that is already shared (most tests are about syncing); a solo one comes from boards.create."""
    board_id = boards.create(store, name)
    boards.share(store, board_id, via)
    return board_id


class TwoMacs:
    """Mac A (the creator) and Mac B, each with its own config folder (identity, keys) and database."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.stores = {m: Store(tmp_path / f"{m}.db") for m in "abc"}
        self.keys = {}
        for m in "abc":
            self.use(m)
            self.keys[m] = identity.public_key()
            self.store.set_setting(identity.NAME, {"a": "Alex Example", "b": "Asha", "c": "Ravi"}[m])

    def use(self, mac):
        self.mp.setenv("MAGPIARY_CONFIG", str(self.tmp / f"config-{mac}"))
        self.store = self.stores[mac]
        return self.store

    def join(self, mac, board_id, creator_mac="a"):
        """What an invite will do (task 6): the board key and the board, on another Mac."""
        self.use(creator_mac)
        key, board = boards.board_key(board_id), self.store.board(board_id)
        store = self.use(mac)
        boards.remember_key(board_id, key)
        store.save_board(board_id, board["name"], board["creator"], board["via"])
        boards.write(store, board_id, "profile", **boards.profile_body(store))


def item(url, title, tags=("travel",)):
    return {"canonical_url": url, "ai_title": title, "summary": f"About {title}.", "ai_type": "place",
            "source": "instagram", "author": "examplecreator", "tags": list(tags)}


REEL1, REEL2, REEL3 = (f"https://www.instagram.com/reel/{c}/" for c in ("AAA", "BBB", "CCC"))


@pytest.fixture
def macs(tmp_path, monkeypatch):
    start = int(boards.time.time()) - 1_000_000  # before the relay's clock, which stamps the events it carries
    ticks = iter(range(start, start + 1_000_000, 7))
    monkeypatch.setattr(boards.time, "time", lambda: next(ticks))  # every event a moment after the last
    two = TwoMacs(tmp_path, monkeypatch)
    yield two
    for s in two.stores.values():
        s.close()


def test_two_macs_fill_one_board_through_relays(macs):
    relays = Relays()
    nostr = boardsync.Nostr(connect=relays.connect)
    a = macs.use("a")
    board_id = make(a, "Lisbon trip")
    boards.add_card(a, board_id, item(REEL1, "Pastel de nata spot"))
    boards.add_card(a, board_id, item(REEL2, "Tram 28"))
    assert boards.sync(a, board_id, nostr) == {"ok": True, "sent": 4, "got": 0, "error": ""}
    assert boards.outbox(a, board_id) == []  # all published

    macs.join("b", board_id)
    b = macs.store
    boards.add_card(b, board_id, item(REEL1, "Best nata in Lisbon"))  # the same reel: one card, two people
    boards.add_card(b, board_id, item(REEL3, "Miradouro at sunset"))
    boards.vote(b, board_id, REEL2, 1)
    result = boards.sync(b, board_id, nostr)
    assert result["ok"] and result["got"] == 4 and result["sent"] == 4

    a = macs.use("a")
    assert boards.sync(a, board_id, nostr)["got"] == 4
    for mac in "ab":
        view = boards.view(macs.use(mac), board_id)
        cards = {c["url"]: c for c in view["cards"]}
        assert view["name"] == "Lisbon trip" and len(cards) == 3
        assert set(cards[REEL1]["adders"]) == {macs.keys["a"], macs.keys["b"]} and cards[REEL1]["shared"]
        assert cards[REEL1]["title"] == "Pastel de nata spot"  # the first adder's card
        assert cards[REEL2]["score"] == 1 and not cards[REEL2]["shared"]
        assert {m["name"] for m in view["members"].values()} == {"Alex Example", "Asha"}
        assert view["members"][macs.keys["a"]]["creator"] and not view["members"][macs.keys["b"]]["creator"]
    assert [c["url"] for c in boards.sort_cards(view["cards"], "shared")] == [REEL1]
    assert boards.sort_cards(view["cards"], "votes")[0]["url"] == REEL2
    assert {c["url"] for c in boards.sort_cards(view["cards"], member=macs.keys["b"])} == {REEL1, REEL3}
    assert boards.sync(b, board_id, nostr)["got"] == 0  # nothing new: nothing read twice


def test_votes_change_cards_come_off_and_only_the_creator_renames_or_removes(macs):
    storage = Storage()
    a = macs.use("a")
    assert boardsync.connect_b2("main-id", "main-secret", storage) is None  # A's own bucket
    board_id = make(a, "Flat hunt", via="bucket")
    bucket = boards.connector_for(a.board(board_id), call=storage)
    boards.add_card(a, board_id, item(REEL1, "Sunny flat"))
    boards.sync(a, board_id, bucket)
    shared = boardsync.load_bucket()  # an invite will carry a key of B's own (task 6)

    macs.join("b", board_id)
    b = macs.store
    b_bucket = boardsync.bucket_connector(shared, call=storage)
    boards.vote(b, board_id, REEL1, 1)
    boards.vote(b, board_id, REEL1, -1)  # changed their mind: the latest counts
    boards.add_card(b, board_id, item(REEL2, "Dark flat"))
    boards.remove_card(b, board_id, REEL2)
    with pytest.raises(PermissionError):
        boards.rename(b, board_id, "Mine now")
    boards.sync(b, board_id, b_bucket)

    a = macs.use("a")
    boards.sync(a, board_id, bucket)
    view = boards.view(a, board_id)
    assert [c["url"] for c in view["cards"]] == [REEL1] and view["cards"][0]["score"] == -1
    boards.rename(a, board_id, "Flat hunt 2027")
    boards.remove_member(a, board_id, macs.keys["b"])
    view = boards.view(a, board_id)
    assert view["name"] == "Flat hunt 2027" and set(view["members"]) == {macs.keys["a"]}
    assert view["cards"][0]["votes"] == {}  # a removed member's votes no longer count


def test_events_that_are_not_what_they_claim_are_dropped(macs):
    relays = Relays()
    nostr = boardsync.Nostr(connect=relays.connect)
    a = macs.use("a")
    board_id = make(a, "Recipes")
    boards.sync(a, board_id, nostr)
    macs.join("b", board_id)
    key = boards.board_key(board_id)

    def sent_by_b(event, member=None):
        text = json.dumps(event, sort_keys=True, separators=(",", ":"))
        sealed = boardsync.seal(key, json.dumps({"e": text, "s": identity.sign(text.encode())}).encode())
        return boardsync.Fetched(member or macs.keys["b"], event["seq"], sealed, f"ref{event['seq']}")

    base = {"v": 1, "board": board_id, "member": macs.keys["b"], "at": 1, "type": "add", "url": REEL1, "title": "x"}
    bad = [sent_by_b({**base, "seq": 1}, member=macs.keys["a"]),            # claims to be examplecreator else
           sent_by_b({**base, "seq": 2, "board": "another"}),               # another board's event
           sent_by_b({**base, "seq": 3, "type": "delete_everything"}),       # not a kind of event
           boardsync.Fetched(macs.keys["b"], 4, boardsync.seal(boardsync.new_board_key(), b"{}"), "ref4"),  # wrong key
           boardsync.Fetched(macs.keys["b"], 5, b"garbage", "ref5"),
           sent_by_b({**base, "seq": 7, "url": "javascript:alert(1)"}),      # kept, but no card: not a web address
           sent_by_b({**base, "seq": 8, "rename": "x", "title": "y" * 5000})]  # good, cut to size
    mismatched = sent_by_b({**base, "seq": 9})
    mismatched.seq = 10                                                     # the number outside differs
    a = macs.use("a")
    assert boards.ingest(a, board_id, bad + [mismatched]) == 2
    view = boards.view(a, board_id)
    assert len(view["cards"]) == 1 and len(view["cards"][0]["title"]) == boards.LIMITS["title"]
    assert "rename" not in view["cards"][0]


def test_board_keys_stay_in_a_private_file_not_the_database(macs, tmp_path):
    import stat

    a = macs.use("a")
    board_id = make(a, "Gifts")
    path = tmp_path / "config-a" / "boards.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    key_hex = boards.board_key(board_id).hex()
    assert key_hex.encode() not in (tmp_path / "a.db").read_bytes()
    with pytest.raises(ValueError):
        make(a, "   ")
    with pytest.raises(ValueError):
        make(a, "Needs a bucket", via="bucket")


def test_sync_all_keeps_each_boards_time_or_error(macs):
    relays, storage = Relays(), Storage()
    a = macs.use("a")
    ok_board = make(a, "Trip")
    assert boardsync.connect_b2("main-id", "main-secret", storage) is None
    bucket_board = make(a, "Flats", via="bucket")
    boardsync._save_bucket(None)  # the bucket was removed from this Mac
    told = []
    totals = boards.sync_all(a, relays.connect, storage, log=told.append)
    assert totals == {"boards": 1, "sent": 2, "got": 0, "failed": 1}
    assert a.board(ok_board)["synced_at"] and not a.board(ok_board)["sync_error"]
    assert a.board(bucket_board)["sync_error"] == "No bucket is connected on this Mac."
    assert told == ["synced 1 board(s): sent 2, received 0"]
    down = Relays(down=set(boardsync.RELAYS))
    boards.write(a, ok_board, "rename", name="Trip 2")
    totals = boards.sync_all(a, down.connect, storage, log=told.append)
    assert totals["failed"] == 2 and "No relay took it" in a.board(ok_board)["sync_error"]
    assert boards.outbox(a, ok_board)  # kept until a relay takes it


def test_settings_lists_boards_with_their_sync_and_a_sync_now(mac, monkeypatch, tmp_path):
    from test_hub import page, post

    relays = Relays()
    mac.server.hub.relay_connect = relays.connect
    mac.server.hub.sync_boards = mac.server.hub._sync_here  # no board lane in the test service: sync right here
    body = page(mac, "/settings/boards")[2]
    assert "Sync now" not in body and "No boards yet" in body  # no boards yet: only the empty note
    board_id = make(mac.store, "Recipes")
    body = page(mac, "/settings/boards")[2]
    assert "Your boards" in body and "Recipes" in body and "Not synced yet" in body and "1 member" in body
    status, headers, _ = post(mac, "/hub/boards/sync", next="/settings/boards")
    assert "Syncing%20your%20boards%20now" in headers["Location"]
    assert re.search(r"Synced [^<]+ through Nostr relays", page(mac, "/settings/boards")[2])
    assert relays.events[boardsync.RELAYS[0]]  # published
    assert mac.store.board(board_id)["synced_at"]


def test_a_friend_joins_with_a_short_code_and_the_invite_is_marked_used(macs):
    relays = Relays()
    a = macs.use("a")
    board_id = make(a, "Goa")
    code = boards.make_invite(a, board_id, relay_connect=relays.connect)
    assert re.fullmatch(r"MAG-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}", code)
    parked = json.dumps(relays.events)
    assert boards.board_key(board_id).hex() not in parked and "Goa" not in parked  # sealed on the relays
    boards.sync_all(a, relays.connect)

    b = macs.use("b")
    typed = code.lower().replace("-", " ").replace("0", "o")  # typed loosely
    assert boards.join(b, typed, relays.connect) == board_id
    with pytest.raises(ValueError, match="already on"):
        boards.join(b, code, relays.connect)
    boards.sync_all(b, relays.connect)
    assert boards.view(b, board_id)["name"] == "Goa" and len(boards.view(b, board_id)["members"]) == 2

    c = macs.use("c")  # the same code works for anyone it is sent to
    assert boards.join(c, code, relays.connect) == board_id
    boards.sync_all(c, relays.connect)

    a = macs.use("a")
    assert boards.make_invite(a, board_id, relay_connect=relays.connect) == code  # Invite again: the same code
    boards.sync_all(a, relays.connect)
    assert {macs.keys["b"], macs.keys["c"]} <= set(boards.view(a, board_id)["members"])
    assert [i["state"] for i in a.invites(board_id)] == ["shared"]
    with pytest.raises(ValueError, match="board you made"):
        boards.join(a, code, relays.connect)
    new = boards.board_code(a, board_id, relay_connect=relays.connect, renew=True)["code"]
    assert new != code and boards.make_invite(a, board_id, relay_connect=relays.connect) == new


def test_bad_and_old_invites_are_refused(macs, monkeypatch):
    relays = Relays()
    a = macs.use("a")
    board_id = make(a, "Goa")
    code = boards.make_invite(a, board_id, relay_connect=relays.connect)
    b = macs.use("b")
    for bad, why in (("hello", "doesn't look like an invite code"), ("MAG-0000-0000-0000", "No invite was found"),
                     ("magpiary-board:abc", "damaged")):
        with pytest.raises(ValueError, match=why):
            boards.join(b, bad, relays.connect)
    with pytest.raises(ValueError, match="Couldn't reach the relays"):
        boards.join(b, code, Relays(down=set(boardsync.RELAYS)).connect)
    real = boards.time.time()
    monkeypatch.setattr(boards.time, "time", lambda: real + 8 * 86400)
    with pytest.raises(ValueError, match="expired"):
        boards.join(b, code, relays.connect)
    assert b.boards() == []


def test_removing_a_member_deletes_their_key_and_locks_them_out_of_what_comes_next(macs):
    storage, relays = Storage(), Relays()
    a = macs.use("a")
    assert boardsync.connect_b2("main-id", "main-secret", storage) is None
    board_id = make(a, "Flats", via="bucket")
    code = boards.make_invite(a, board_id, storage, relays.connect)
    assert set(storage.keys) == {"k1", "k2"}  # this Mac's key and the code's key
    boards.sync_all(a, relays.connect, storage)
    for m in "bc":
        store = macs.use(m)
        boards.join(store, code, relays.connect)
        boards.add_card(store, board_id, item({"b": REEL2, "c": REEL3}[m], f"{m}'s flat"))
        assert boards.sync_all(store, relays.connect, storage)["failed"] == 0  # through the code's key

    a = macs.use("a")
    boards.sync_all(a, relays.connect, storage)
    assert len(boards.view(a, board_id)["members"]) == 3
    assert set(storage.keys) == {"k1", "k2", "k3", "k4"}  # each member got a key of their own
    personal = {}
    for m in "bc":
        store = macs.use(m)
        boards.sync_all(store, relays.connect, storage)  # the inbox brings it; the board now syncs with it
        personal[m] = boards._keys()[board_id]["bucket"]["key_id"]
    assert sorted(personal.values()) == ["k3", "k4"]

    a = macs.use("a")
    boards.remove_member(a, board_id, macs.keys["b"], storage)
    assert personal["b"] not in storage.keys and "k2" not in storage.keys  # B's key and the code's key are gone
    assert personal["c"] in storage.keys
    boards.add_card(a, board_id, item(REEL1, "After B left"))
    boards.sync_all(a, relays.connect, storage)

    c = macs.use("c")
    assert boards.sync_all(c, relays.connect, storage)["failed"] == 0
    view_c = boards.view(c, board_id)
    assert REEL1 in {x["url"] for x in view_c["cards"]} and macs.keys["b"] not in view_c["members"]
    assert len(boards.board_keys(board_id)) == 2  # C picked up the new board key

    b = macs.use("b")
    result = boards.sync_all(b, relays.connect, storage)
    assert result["failed"] == 1 and "refused" in b.board(board_id)["sync_error"]
    assert len(boards.board_keys(board_id)) == 1  # B never got the new key
    a = macs.use("a")
    assert boards.make_invite(a, board_id, storage, relays.connect) != code  # removing examplecreator retired the code


def test_a_code_renews_after_seven_days_and_its_key_goes_a_week_later(macs, monkeypatch):
    storage, relays = Storage(), Relays()
    a = macs.use("a")
    boardsync.connect_b2("main-id", "main-secret", storage)
    board_id = make(a, "Flats", via="bucket")
    first = boards.make_invite(a, board_id, storage, relays.connect)
    assert "k2" in storage.keys
    real = boards.time.time()
    monkeypatch.setattr(boards.time, "time", lambda: real + 8 * 86400)
    second = boards.make_invite(a, board_id, storage, relays.connect)
    assert second != first and "k2" in storage.keys  # the old code's key waits a week for its members
    monkeypatch.setattr(boards.time, "time", lambda: real + 15 * 86400)
    boards.sync_all(a, relays.connect, storage)
    assert "k2" not in storage.keys and "k3" in storage.keys


def test_the_phone_asks_about_active_boards_only_and_the_post_becomes_a_card_once_read(mac, phone, tmp_path):
    from datetime import timedelta

    from test_hub import archive

    assert phone.run("") == "" and phone.boards_file.strip() == ""  # no boards: nothing to ask about
    phone.run("https://www.instagram.com/reel/NOBOARD/")
    assert phone.asked == []  # straight to the library
    board_id = make(mac.store, "Lisbon trip")
    make(mac.store, "Flats")
    phone.run("https://www.instagram.com/reel/FIRSTSHARE/", pick="Flats")  # the very next share already asks
    assert phone.asked[-1][0] == "Just my library" and set(phone.asked[-1][1:]) == {"Lisbon trip", "Flats"}
    away = phone.run("https://www.instagram.com/reel/AWAY/", at_home=False, pick="Flats")
    assert away == "Saved. It will send when you're home." and len(phone.asked) == 2  # away: the saved list asks
    message = phone.run("https://www.instagram.com/reel/TOLISBON/?igsh=abc", pick="Lisbon trip")
    assert phone.asked[-1] == ["Just my library", "Flats", "Lisbon trip"] or phone.asked[-1][0] == "Just my library"
    assert message == "Saved 2 items to Magpiary ✅"  # the one queued away from home went with it
    alone = phone.run("https://www.instagram.com/reel/ALONE/", pick="Lisbon trip")
    assert alone == "Saved, and on its way to Lisbon trip ✅"
    url = "https://www.instagram.com/reel/TOLISBON/"
    assert url in {r["canonical_url"] for r in mac.store.board_pending()}
    assert boards.settle_pending(mac.store) == 0  # not fetched yet: it waits
    archive(mac, tmp_path, url, "instagram", {"text": "Pastel de nata", "author": "chef"})
    with mac.store._lock:
        mac.store._db.execute("UPDATE items SET ai_status='done', ai_title='Best nata' WHERE canonical_url=?", (url,))
    assert boards.settle_pending(mac.store) == 1
    assert [c["title"] for c in boards.view(mac.store, board_id)["cards"]] == ["Best nata"]
    assert mac.store.get_item(url)["shelf"] == "board"  # kept for the board only (the board's switch is off)
    assert mac.store.get_item("https://www.instagram.com/reel/NOBOARD/")["shelf"] == "inbox"

    pending = len(mac.store.board_pending())
    phone.run("https://www.instagram.com/reel/JUSTME/")  # the first choice: library only
    assert len(mac.store.board_pending()) == pending

    mac.clock.t += timedelta(days=30)  # a month later, nothing changed on either board
    phone.run("")
    assert phone.boards_file.strip() == ""
    phone.run("https://www.instagram.com/reel/LATER/")
    asked = len(phone.asked)
    phone.run("https://www.instagram.com/reel/LATER2/")
    assert len(phone.asked) == asked  # not asked: both boards went quiet


def test_a_board_is_active_while_new_or_recently_changed():
    from datetime import date, datetime, timedelta

    class FakeStore:
        def __init__(self, boards_, events):
            self._b, self._e = boards_, events

        def boards(self):
            return self._b

        def board_events(self, board_id):
            return self._e.get(board_id, [])

        def now(self):
            return "2026-11-20T09:00:00"

    def stamp(d):
        return datetime(d.year, d.month, d.day, 9).timestamp()

    today = date(2026, 11, 20)
    store = FakeStore(
        [{"id": "a" * 16, "name": "New (2027)!", "joined_at": "2026-11-18T10:00:00"},
         {"id": "b" * 16, "name": "Quiet", "joined_at": "2026-10-01T10:00:00"},
         {"id": "c" * 16, "name": "Busy", "joined_at": "2026-10-01T10:00:00"}],
        {"b" * 16: [{"at": stamp(today - timedelta(days=20))}], "c" * 16: [{"at": stamp(today - timedelta(days=3))}]})
    lines = boards.phone_list(store, today).splitlines()
    assert [ln.split("\t")[1] for ln in lines] == ["Busy", "New 2027 !"]  # most recently changed first; no pattern characters
    busy, new = (ln.split("\t")[0].split() for ln in lines)
    assert busy[0] == "20261120" and busy[-1] == "20261123"  # 7 days from the last change
    assert new[-1] == "20261124"  # 7 days from when it was made


def test_the_board_list_needs_the_phones_key(mac, phone):
    import urllib.error
    import urllib.request

    make(mac.store, "Gifts")
    req = urllib.request.Request(mac.url + "/v1/boards", headers={"Authorization": "Bearer wrong"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 401


def test_the_creator_renames_a_board_from_its_page(mac):
    from test_hub import page, post

    mac.server.hub.relay_connect, mac.server.hub.sync_boards = Relays().connect, mac.server.hub._sync_here
    board_id = make(mac.store, "Test Board")
    assert "Rename the board" in page(mac, f"/board/{board_id}")[2]
    post(mac, "/hub/boards/rename", board=board_id, name="  Lisbon   2027 ", next=f"/board/{board_id}")
    assert boards.view(mac.store, board_id)["name"] == "Lisbon 2027"
    assert boards.rename(mac.store, board_id, "Lisbon 2027") == 0  # the same name: nothing written
    mac.store.add_board_event(board_id, "f" * 64, 1, 1, "profile", {"name": "Asha"}, "")
    other = make(mac.store, "Theirs")
    with mac.store._lock:
        mac.store._db.execute("UPDATE boards SET creator=? WHERE id=?", ("f" * 64, other))
    assert "Rename the board" not in page(mac, f"/board/{other}")[2]


def test_a_board_choice_on_the_post_itself_still_counts(mac, phone):
    board_id = make(mac.store, "Old style")
    body = '{"items":[{"id":"x1","url":"https://www.instagram.com/reel/OLDSTYLE/","board":"' + board_id + '","v":1}]}'
    assert phone.post(body)["message"] == "Saved, and on its way to Old style ✅"
    assert mac.store.board_pending()[0]["board_id"] == board_id


def test_a_past_friend_gets_an_invite_straight_in_their_magpiary(macs):
    relays = Relays()
    a = macs.use("a")
    trip = make(a, "Goa")
    code = boards.make_invite(a, trip, relay_connect=relays.connect)
    boards.sync_all(a, relays.connect)
    b = macs.use("b")
    boards.join(b, code, relays.connect)
    boards.sync_all(b, relays.connect)
    a = macs.use("a")
    boards.sync_all(a, relays.connect)

    recipes = make(a, "Recipes")
    assert [m["name"] for m in boards.friends(a, recipes)] == ["Asha"]  # shared Goa with Asha
    assert boards.friends(a, trip) == []  # already on it
    boards.invite_friend(a, recipes, macs.keys["b"], relay_connect=relays.connect)
    boards.sync_all(a, relays.connect)
    parked = json.dumps(relays.events)
    assert "Recipes" not in parked and boards.board_key(recipes).hex() not in parked

    c = macs.use("c")  # examplecreator else finds nothing in their inbox
    assert boards.check_inbox(c, relays.connect) == 0
    b = macs.use("b")
    boards.sync_all(b, relays.connect)  # the inbox is checked while syncing
    offers = b.offers()
    assert [(o["name"], boards.sender_name(b, o["sender"])) for o in offers] == [("Recipes", "Alex Example")]
    assert boards.check_inbox(b, relays.connect) == 0  # not offered twice
    assert boards.accept_offer(b, offers[0]["invite"], relays.connect) == recipes
    assert b.offers() == [] and b.board(recipes)["name"] == "Recipes"


def test_unused_invite_notes_are_deleted_from_the_relays_and_the_current_code_stays(macs, monkeypatch):
    relays = Relays()
    a = macs.use("a")
    board_id = make(a, "Goa")
    first = boards.make_invite(a, board_id, relay_connect=relays.connect)
    second = boards.board_code(a, board_id, relay_connect=relays.connect, renew=True)["code"]  # New code
    other = make(a, "Flats")
    boards.invite_friend(a, other, macs.keys["c"], relay_connect=relays.connect)  # a recent invite for one friend
    stray = boardsync.Nostr(connect=relays.connect).park("abc", b"made before notes were recorded")
    notes = lambda: {ev["id"] for ev in relays.events[boardsync.RELAYS[0]] if ev["kind"] == boardsync.KIND and
                     any(x[0] == "i" for x in ev["tags"])}
    assert len(notes()) == 4
    assert boards.clean_relays(a, relays.connect) == 2  # the replaced code and the unknown note
    assert stray not in notes() and len(notes()) == 2
    b = macs.use("b")
    assert boards.join(b, second, relays.connect) == board_id  # the current code still works
    with pytest.raises(ValueError, match="No invite was found"):
        boards.join(b, first, relays.connect)
    a = macs.use("a")
    real = boards.time.time()
    assert boards.clean_relays(a, relays.connect, now=real + 9 * 86400) == 2  # a week on: the rest too


def test_two_quick_presses_of_invite_make_one_code(macs):
    import threading

    relays = Relays()
    a = macs.use("a")
    board_id = make(a, "Goa")
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(boards.make_invite(a, board_id, relay_connect=relays.connect)))
               for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(set(codes)) == 1 and len(a.invites(board_id)) == 1


def test_a_boards_library_switch_decides_where_phone_shares_go(mac, phone, tmp_path):
    from test_hub import post

    board_id = make(mac.store, "Trip")
    phone.run("https://www.instagram.com/reel/ONLYBOARD/", pick="Trip")
    only = "https://www.instagram.com/reel/ONLYBOARD/"
    assert mac.store.get_item(only)["shelf"] == "board"
    assert only not in {i["canonical_url"] for i in mac.store.hub_items("inbox")}  # not in the library
    phone.run("https://www.instagram.com/reel/KEPT/")  # in the library first...
    phone.run("https://www.instagram.com/reel/KEPT/", pick="Trip")  # ...then to the board: stays in the library
    assert mac.store.get_item("https://www.instagram.com/reel/KEPT/")["shelf"] == "inbox"

    _, headers, _ = post(mac, "/hub/boards/to-library", board=board_id, value="1", next=f"/board/{board_id}")
    assert mac.store.board(board_id)["to_library"] == 1 and "1%20added%20to%20your%20library" in headers["Location"]
    assert mac.store.get_item(only)["shelf"] == "inbox"  # what was waiting for the board moved over
    phone.run("https://www.instagram.com/reel/BOTH/", pick="Trip")
    assert mac.store.get_item("https://www.instagram.com/reel/BOTH/")["shelf"] == "inbox"
    assert mac.store.from_library(board_id, dry=True) == 2  # ONLYBOARD and BOTH came in through the switch
    _, headers, _ = post(mac, "/hub/boards/to-library", board=board_id, next=f"/board/{board_id}")
    assert mac.store.board(board_id)["to_library"] == 0 and "2%20left%20your%20library" in headers["Location"]
    assert mac.store.get_item(only)["shelf"] == "board" and mac.store.get_item("https://www.instagram.com/reel/BOTH/")["shelf"] == "board"
    assert mac.store.get_item("https://www.instagram.com/reel/KEPT/")["shelf"] == "inbox"  # saved on its own: stays


def test_a_new_board_is_solo_and_never_syncs_until_shared(macs):
    relays = Relays()
    a = macs.use("a")
    board_id = boards.create(a, "Mine")
    boards.add_card(a, board_id, item(REEL1, "A place"))
    assert not a.board(board_id)["shared"] and [b["id"] for b in a.boards_to_sync()] == []
    with pytest.raises(ValueError):
        boards.board_code(a, board_id)  # nothing to invite to yet
    assert boards.sync_all(a, relay_connect=relays.connect)["boards"] == 0 and not any(relays.events.values())
    boards.share(a, board_id)
    assert [b["id"] for b in a.boards_to_sync()] == [board_id]
    assert boards.sync_all(a, relay_connect=relays.connect)["sent"] >= 3  # what was written while solo goes out now
    boards.unshare(a, board_id)  # alone on it: back to solo
    assert not a.board(board_id)["shared"]


def test_existing_boards_are_sorted_by_who_is_on_them(macs):
    a = macs.use("a")
    relays = Relays()
    nostr = boardsync.Nostr(connect=relays.connect)
    alone, together = make(a, "Alone"), make(a, "Together")
    boards.sync(a, together, nostr)
    macs.join("b", together)
    boards.sync(macs.store, together, nostr)
    a = macs.use("a")
    boards.sync(a, together, nostr)
    a.set_setting("boards_sharing_sorted", "")
    assert boards.sort_sharing(a) == 1
    assert not a.board(alone)["shared"] and a.board(together)["shared"]
    assert boards.sort_sharing(a) == 0  # only once


def test_deleting_a_board_archives_it_and_it_ends_for_the_others(macs):
    relays = Relays()
    nostr = boardsync.Nostr(connect=relays.connect)
    a = macs.use("a")
    board_id = make(a, "Trip")
    boards.sync(a, board_id, nostr)
    macs.join("b", board_id)
    boards.sync(macs.store, board_id, nostr)
    a = macs.use("a")
    boards.sync(a, board_id, nostr)
    boards.end_board(a, board_id)
    assert a.board(board_id)["archived_at"] and a.boards() == [] and len(a.boards(archived=True)) == 1
    boards.sync_all(a, relay_connect=relays.connect)  # the 'deleted' notice goes out once
    b = macs.use("b")
    boards.sync(b, board_id, nostr)
    assert b.board(board_id)["ended"] and boards.view(b, board_id)["ended"]
    with pytest.raises(PermissionError):
        boards.add_card(b, board_id, item(REEL2, "Late"))
    boards.dismiss_board(b, board_id)
    assert b.board(board_id) is None
    a = macs.use("a")
    boards.restore_board(a, board_id)
    assert a.boards()[0]["id"] == board_id
    boards.add_card(a, board_id, item(REEL3, "Back again"))  # writable again
    assert a.purge_archived_boards() == []  # nothing archived yet
    boards.end_board(a, board_id)
    assert a.purge_archived_boards() == []  # not old enough
    a.update_board(board_id, archived_at="2000-01-01T00:00:00")
    assert a.purge_archived_boards() == [board_id] and a.board(board_id) is None


def test_a_member_leaves_and_their_cards_stay(macs):
    relays = Relays()
    nostr = boardsync.Nostr(connect=relays.connect)
    a = macs.use("a")
    board_id = make(a, "Trip")
    boards.sync(a, board_id, nostr)
    macs.join("b", board_id)
    b = macs.store
    boards.add_card(b, board_id, item(REEL1, "Mine"))
    boards.sync(b, board_id, nostr)
    boards.leave_board(b, board_id, relays.connect)
    assert b.board(board_id) is None
    a = macs.use("a")
    with pytest.raises(PermissionError):
        boards.leave_board(a, board_id, relays.connect)  # the creator can't leave
    boards.sync(a, board_id, nostr)
    v = boards.view(a, board_id)
    assert [c["url"] for c in v["cards"]] == [REEL1] and len(boards.people(v)) == 1
