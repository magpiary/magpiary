"""Where boards sync (M9 task 3): Nostr relays and an own bucket, against a fake relay and a fake bucket service."""

import json
import re
import stat
from urllib.parse import parse_qs, urlsplit

import pytest

from magpiary import boardsync as bs
from magpiary.config import config_dir
from test_hub import page, post

BOARD = bytes(range(32))


# ---- a fake relay ---------------------------------------------------------------------------------

class Relays:
    """Every relay URL maps to a list of stored events; `down` relays cannot be reached; `limit` refuses big ones."""

    def __init__(self, down=(), limit=10 ** 9):
        self.events, self.down, self.limit = {}, set(down), limit

    def connect(self, url):
        if url in self.down:
            raise ConnectionError("refused")
        return Socket(self, url)


class Socket:
    def __init__(self, relays, url):
        self.relays, self.url, self.out = relays, url, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, text):
        msg = json.loads(text)
        stored = self.relays.events.setdefault(self.url, [])
        if msg[0] == "EVENT" and msg[1]["kind"] == 5:  # a deletion request: only the author's own notes go
            gone = {x[1] for x in msg[1]["tags"] if x[0] == "e"}
            stored[:] = [ev for ev in stored if not (ev["id"] in gone and ev["pubkey"] == msg[1]["pubkey"])]
            self.out.append(["OK", msg[1]["id"], True, ""])
        elif msg[0] == "EVENT":
            ev = msg[1]
            too_big = len(json.dumps(ev)) > self.relays.limit
            if not too_big:
                stored.append(ev)
            self.out.append(["OK", ev["id"], not too_big, "invalid: event too large" if too_big else ""])
        elif msg[0] == "REQ":
            f = msg[2]
            for ev in stored:
                if ev["kind"] in f["kinds"] and ev["created_at"] >= f.get("since", 0) and \
                        (not f.get("#b") or ["b", f["#b"][0]] in ev["tags"]) and \
                        (not f.get("#i") or ["i", f["#i"][0]] in ev["tags"]) and \
                        (not f.get("authors") or ev["pubkey"] in f["authors"]):
                    self.out.append(["EVENT", msg[1], ev])
            self.out.append(["EOSE", msg[1]])

    def recv(self, timeout=None):
        return json.dumps(self.out.pop(0))


# ---- a fake S3 service with Backblaze's own API -----------------------------------------------------

class Storage:
    S3 = "https://s3.eu-central-003.backblazeb2.com"

    def __init__(self):
        self.files, self.buckets, self.keys, self.calls = {}, [], {}, []
        self.main = ("main-id", "main-secret")

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url))
        parts = urlsplit(url)
        if url == bs.B2_AUTH:
            import base64
            given = base64.b64decode(headers["Authorization"].split()[1]).decode().split(":", 1)
            if tuple(given) != self.main:
                return 401, b"{}"
            return 200, json.dumps({"accountId": "acct", "authorizationToken": "tok", "apiInfo": {"storageApi": {
                "apiUrl": "https://api.example", "s3ApiUrl": self.S3, "capabilities": ["writeKeys", "listBuckets"]}}}).encode()
        if parts.netloc == "api.example":
            req, name = json.loads(body), parts.path.rsplit("/", 1)[1]
            if name == "b2_list_buckets":
                return 200, json.dumps({"buckets": self.buckets}).encode()
            if name == "b2_create_bucket":
                self.buckets.append({"bucketName": req["bucketName"], "bucketId": "bid1"})
                return 200, json.dumps(self.buckets[-1]).encode()
            if name == "b2_create_key":
                key = {"applicationKeyId": f"k{len(self.keys) + 1}", "applicationKey": f"s{len(self.keys) + 1}"}
                self.keys[key["applicationKeyId"]] = key["applicationKey"]
                return 200, json.dumps(key).encode()
            if name == "b2_delete_key":
                self.keys.pop(req["applicationKeyId"], None)
                return 200, b"{}"
        key_id = re.search(r"Credential=([^/]+)/", headers["Authorization"]).group(1)
        if key_id not in self.keys:
            return 403, b""
        path = parts.path.split("/", 2)
        name = path[2] if len(path) > 2 else ""
        if method == "PUT":
            self.files[name] = body
            return 200, b""
        if method == "DELETE":
            self.files.pop(name, None)
            return 204, b""
        if name:
            return (200, self.files[name]) if name in self.files else (404, b"")
        prefix = parse_qs(parts.query)["prefix"][0]
        listing = "".join(f"<Key>{k}</Key>" for k in sorted(self.files) if k.startswith(prefix))
        return 200, f"<ListBucketResult>{listing}</ListBucketResult>".encode()


# ---- tests ---------------------------------------------------------------------------------------

def test_sealing_needs_the_board_key_and_the_tag_does_not_give_it_away():
    sealed = bs.seal(BOARD, b"a card")
    assert bs.unseal(BOARD, sealed) == b"a card" and b"a card" not in sealed
    with pytest.raises(ValueError):
        bs.unseal(bs.new_board_key(), sealed)
    assert BOARD.hex()[:16] not in bs.board_tag(BOARD) and bs.board_tag(BOARD) != bs.board_tag(bs.new_board_key())


def test_nostr_publishes_to_every_relay_and_reads_each_event_once():
    relays = Relays(down={bs.RELAYS[2]})
    nostr = bs.Nostr(connect=relays.connect, clock=lambda: 1_800_000_000)
    assert nostr.publish(BOARD, 1, bs.seal(BOARD, b"one")) == 2  # one relay is down: still published
    nostr.publish(BOARD, 2, bs.seal(BOARD, b"two"))
    got = nostr.fetch(BOARD)
    assert sorted(f.seq for f in got) == [1, 2] and {bs.unseal(BOARD, f.sealed) for f in got} == {b"one", b"two"}
    assert got[0].member == bs.identity.public_key()
    assert nostr.fetch(BOARD, seen={f.ref for f in got}) == []  # already read
    assert nostr.fetch(bs.new_board_key()) == []  # another board's events are not mixed in


def test_events_a_relay_made_up_or_changed_are_dropped():
    relays = Relays()
    nostr = bs.Nostr(relays=bs.RELAYS[:1], connect=relays.connect)
    nostr.publish(BOARD, 1, bs.seal(BOARD, b"real"))
    real = relays.events[bs.RELAYS[0]][0]
    relays.events[bs.RELAYS[0]].append({**real, "id": "ab" * 32, "content": "Zm9yZ2Vk"})  # changed content
    relays.events[bs.RELAYS[0]].append({**real, "sig": "00" * 64})  # not signed by its key
    assert [bs.unseal(BOARD, f.sealed) for f in nostr.fetch(BOARD)] == [b"real"]


def test_nostr_refuses_big_events_and_says_when_no_relay_works():
    relays = Relays(limit=100)
    nostr = bs.Nostr(connect=relays.connect)
    with pytest.raises(bs.SyncError, match="Too large"):
        nostr.publish(BOARD, 1, b"x" * (bs.EVENT_MAX + 1))
    with pytest.raises(bs.SyncError, match="No relay took it"):
        nostr.publish(BOARD, 1, bs.seal(BOARD, b"x" * 200))
    down = bs.Nostr(connect=Relays(down=set(bs.RELAYS)).connect)
    with pytest.raises(bs.SyncError, match="No relay could be reached"):
        down.fetch(BOARD)
    status = down.check()
    assert not status.ok and status.detail == "0 of 3 relays answered"


def test_connecting_backblaze_makes_a_private_bucket_and_a_key_for_this_mac():
    storage = Storage()
    assert bs.connect_b2("main-id", "wrong", storage) == "Backblaze refused this key. Check you copied both parts."
    assert bs.connect_b2("main-id", "main-secret", storage) is None
    saved = bs.load_bucket()
    assert saved["bucket"].startswith("magpiary-boards-") and saved["key_id"] == "k1" and saved["endpoint"] == Storage.S3
    path = config_dir() / "storage.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not [f for f in storage.files if f.startswith("boards/check/")]  # the check cleaned up after itself

    bucket = bs.bucket_connector(call=storage)
    bucket.publish(BOARD, 1, bs.seal(BOARD, b"mine"))
    assert bucket.fetch(BOARD) == []  # this Mac's own files are not read back
    friend = "f" * 64
    storage.files[f"boards/{bs.board_tag(BOARD)}/members/{friend}/1.bin"] = bs.seal(BOARD, b"card")
    got = bucket.fetch(BOARD)
    assert got[0].member == friend
    assert len(got) == 1 and got[0].seq == 1 and bs.unseal(BOARD, got[0].sealed) == b"card"
    assert bucket.fetch(BOARD, seen={got[0].ref}) == []
    assert bs.connect_b2("main-id", "main-secret", storage) is None and len(storage.buckets) == 1  # reused
    assert list(storage.keys) == ["k2"]  # connecting again leaves no stray key behind

    bs.remove_bucket(storage)
    assert bs.load_bucket() is None and not storage.keys and storage.buckets  # the bucket itself stays


def test_an_r2_key_is_checked_before_it_is_saved():
    storage = Storage()
    storage.keys["r2key"] = "r2secret"
    error = bs.connect_s3("r2", "https://acct.r2.cloudflarestorage.com", "nobody", "x", "boards", storage)
    assert error and "refused" in error and bs.load_bucket() is None
    assert bs.connect_s3("r2", "not a url", "r2key", "r2secret", "boards", storage).startswith("The address")
    assert bs.connect_s3("r2", "https://acct.r2.cloudflarestorage.com", "r2key", "r2secret", "boards", storage) is None
    assert bs.bucket_connector(call=storage).region == "auto"


def test_the_settings_group_connects_a_saved_backblaze_key_and_checks_relays(mac):
    storage, relays = Storage(), Relays()
    mac.server.hub.sync_call, mac.server.hub.relay_connect = storage, relays.connect
    body = page(mac, "/settings/boards")[2]
    assert "Where boards sync" in body and "Nostr relays" in body and "Use my saved Backblaze key" not in body
    (config_dir() / "b2.env").write_text("B2_KEY_ID=main-id\nB2_APP_KEY=main-secret\n")
    assert "Use my saved Backblaze key" in page(mac, "/settings/boards")[2]
    status, headers, _ = post(mac, "/hub/boards/b2-env", next="/settings/boards")
    assert headers["Location"] == "/settings/boards?saved=bucket#sync" and not (config_dir() / "b2.env").exists()
    body = page(mac, "/settings/boards")[2]
    assert "Backblaze B2" in body and "magpiary-boards-" in body and "main-secret" not in body and not re.search(r"[\">\s]s1[\"<\s]", body)
    _, headers, _ = post(mac, "/hub/boards/check-relays", next="/settings/boards")
    assert "note=3%20of%203%20relays%20answered" in headers["Location"]
    _, headers, _ = post(mac, "/hub/boards/remove-bucket", next="/settings/boards")
    assert headers["Location"].endswith("saved=nobucket#sync") and bs.load_bucket() is None
