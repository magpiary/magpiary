"""The hub lock: PIN rules, sleep and idle, Touch ID (WebAuthn) checks, and the hub behind it over HTTP."""

import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from magpiary import lock as lk
from magpiary.store import Store
from test_hub import page, post, request

PIN = "246810"


class Time:
    def __init__(self):
        self.wall = 1_000_000.0
        self.mono = 5_000.0

    def now(self):
        return self.wall

    def tick(self):
        return self.mono

    def pass_awake(self, secs):
        self.wall += secs
        self.mono += secs

    def sleep(self, secs):  # the monotonic clock stops while the Mac sleeps
        self.wall += secs


@pytest.fixture
def t():
    return Time()


@pytest.fixture
def L(tmp_path, t):
    store = Store(tmp_path / "lock.db")
    yield lk.Lock(store, now=t.now, mono=t.tick, screen=lambda: False)
    store.close()


def on(L):
    assert L.turn_on(PIN, PIN) == ""


def test_off_by_default_and_never_locked(L):
    assert not L.enabled and not L.is_locked()


def test_turn_on_checks_the_pin(L):
    assert "6 digits" in L.turn_on("12345", "12345")
    assert "different" in L.turn_on(PIN, "135790")
    assert not L.enabled
    on(L)
    assert L.enabled and not L.locked  # the one who turned it on is let in
    assert PIN not in L.store.get_setting(lk.PIN)  # only a salted hash is kept


def test_a_start_is_locked(L, t):
    on(L)
    again = lk.Lock(L.store, now=t.now, mono=t.tick, screen=lambda: False)
    assert again.is_locked()
    assert again.unlock_with_pin(PIN) == "ok" and not again.is_locked()


def test_wrong_pins_earn_a_wait_that_doubles(L, t):
    on(L)
    L.lock_now()
    for _ in range(lk.TRIES - 1):
        assert L.unlock_with_pin("000000") == "wrong"
    assert L.unlock_with_pin("000000") == "wrong"  # the fifth
    assert L.wait_left() == lk.WAIT
    assert L.unlock_with_pin(PIN) == "wait"  # even the right one waits
    t.pass_awake(lk.WAIT + 1)
    for _ in range(lk.TRIES):
        L.unlock_with_pin("000000")
    assert L.wait_left() == 2 * lk.WAIT
    t.pass_awake(2 * lk.WAIT + 1)
    assert L.unlock_with_pin(PIN) == "ok"
    assert L.store.get_setting(lk.STRIKES) == "0"


def test_parallel_guesses_cannot_bypass_the_pin_cooldown(L, t, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time

    on(L)
    L.lock_now()
    start = threading.Barrier(20)
    checked = []

    def wrong(pin, stored):
        checked.append(pin)
        time.sleep(0.02)  # let all unsynchronized attempts reach hash verification
        return False

    monkeypatch.setattr(lk, "check_hash", wrong)

    def guess(_):
        start.wait(timeout=5)
        return L.unlock_with_pin("000000")

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(guess, range(20)))
    assert results.count("wrong") == lk.TRIES
    assert results.count("wait") == 20 - lk.TRIES
    assert len(checked) == lk.TRIES
    # Restarting the hub does not bypass the persisted cooldown either.
    restarted = lk.Lock(L.store, now=t.now, mono=t.tick, screen=lambda: False)
    assert restarted.unlock_with_pin(PIN) == "wait"
    assert restarted.is_locked()


def test_idle_defaults_to_never(L, t):
    on(L)
    assert L.idle_minutes() == 0
    t.pass_awake(3 * 3600)
    L.tick()
    assert not L.locked


def test_idle_time_locks_and_use_keeps_it_open(L, t):
    on(L)
    assert L.set_idle("15") == ""
    t.pass_awake(10 * 60)
    L.tick(touched=True)
    assert not L.locked
    t.pass_awake(14 * 60)
    L.tick()
    assert not L.locked
    t.pass_awake(2 * 60)
    L.tick()
    assert L.locked


def test_never_means_no_idle_lock(L, t):
    on(L)
    assert L.set_idle("0") == ""
    t.pass_awake(10 * 3600)
    L.tick()
    assert not L.locked


def test_sleep_locks(L, t):
    on(L)
    L.set_idle("0")
    t.pass_awake(5)
    L.tick(touched=True)
    t.sleep(600)
    L.tick()
    assert L.locked


def test_screen_lock_is_checked_by_the_watcher_only(L):
    assert lk.screen_locked(run=lambda *a, **k: type("R", (), {"stdout": b'"IOConsoleLocked" = Yes'})())
    assert not lk.screen_locked(run=lambda *a, **k: type("R", (), {"stdout": b'"IOConsoleLocked" = No'})())


def test_changes_need_a_fresh_proof(L, t):
    on(L)
    L.lock_now()
    assert L.unlock_with_pin(PIN) == "ok"
    t.pass_awake(lk.PROOF_FOR + 1)
    assert "Confirm" in L.set_idle("60")
    assert "Confirm" in L.turn_off()
    assert L.prove_with_pin(PIN) == "ok"
    assert L.set_idle("60") == "" and L.idle_minutes() == 60


def test_reset_forgets_everything(L):
    on(L)
    L.reset()
    assert not L.enabled and L.store.get_setting(lk.PIN) == "" and L.credentials() == []


# ---- Touch ID: a real P-256 key standing in for the Mac's, signing the way a browser does ----------------------------------

ORIGIN = "http://localhost:8765"


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = b"cred-1" * 4

    @property
    def spki(self):
        return self.key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)

    @staticmethod
    def client(kind, challenge, origin=ORIGIN):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin}).encode()

    def sign(self, challenge, origin=ORIGIN, flags=0x05, rp="localhost"):
        client = self.client("webauthn.get", challenge, origin)
        auth = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + (1).to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return lk.b64e(auth), lk.b64e(client), lk.b64e(sig)


def enrol(L, a):
    token = L.challenge("register")
    return L.register(ORIGIN, lk.b64e(a.id), lk.b64e(a.spki), lk.b64e(a.client("webauthn.create", token)), "Safari")


def test_register_needs_proof_and_a_fresh_challenge(L, t):
    on(L)
    a = Authenticator()
    t.pass_awake(lk.PROOF_FOR + 1)
    assert "Confirm" in enrol(L, a)
    assert L.prove_with_pin(PIN) == "ok"
    assert enrol(L, a) == "" and [c["label"] for c in L.credentials()] == ["Safari"]
    assert "too long" in L.register(ORIGIN, lk.b64e(a.id), lk.b64e(a.spki), lk.b64e(a.client("webauthn.create", "stale")), "x")


def test_touch_id_unlocks(L):
    on(L)
    a = Authenticator()
    assert enrol(L, a) == ""
    L.lock_now()
    token = L.challenge("unlock")
    auth, client, sig = a.sign(token)
    assert L.unlock_with_key(ORIGIN, lk.b64e(a.id), auth, client, sig)
    assert not L.is_locked()


@pytest.mark.parametrize("bad", ["origin", "no touch", "wrong site", "replay", "other key"])
def test_touch_id_refuses_bad_answers(L, bad):
    on(L)
    a = Authenticator()
    enrol(L, a)
    L.lock_now()
    token = L.challenge("unlock")
    if bad == "origin":
        auth, client, sig = a.sign(token, origin="http://evil.example")
    elif bad == "no touch":
        auth, client, sig = a.sign(token, flags=0x01)  # present but no Touch ID check
    elif bad == "wrong site":
        auth, client, sig = a.sign(token, rp="example.com")
    elif bad == "other key":
        auth, client, sig = Authenticator().sign(token)
    else:
        auth, client, sig = a.sign(token)
        assert L.unlock_with_key(ORIGIN, lk.b64e(a.id), auth, client, sig)
        L.lock_now()
    assert not L.unlock_with_key(ORIGIN, lk.b64e(a.id), auth, client, sig)
    assert L.is_locked()


def test_a_confirm_challenge_cannot_unlock(L):
    on(L)
    a = Authenticator()
    enrol(L, a)
    L.lock_now()
    auth, client, sig = a.sign(L.challenge("confirm"))
    assert not L.unlock_with_key(ORIGIN, lk.b64e(a.id), auth, client, sig)


# ---- the hub over HTTP ------------------------------------------------------------------------------------------------

def hub(mac):
    return mac.server.hub


def locked_hub(mac):
    post(mac, "/hub/lock/on", pin=PIN, again=PIN)
    hub(mac).lock.lock_now()


def test_hub_is_open_while_the_lock_is_off(mac):
    status, _, body = page(mac, "/")
    assert status == 200 and "lockbtn" not in body
    status, _, data = request(mac, "GET", "/lock.json")
    assert json.loads(data) == {"on": False, "locked": False, "wait": 0, "ids": [], "proven": False}


def test_turning_it_on_from_settings_adds_the_header_button(mac):
    assert post(mac, "/hub/lock/on", pin=PIN, again=PIN)[0] == 303
    assert hub(mac).lock.enabled
    status, _, body = page(mac, "/")
    assert status == 200 and "lockbtn" in body


def test_locked_hub_redirects_pages_and_blocks_the_rest(mac):
    locked_hub(mac)
    status, headers, _ = request(mac, "GET", "/settings/ai?x=1")
    assert status == 303 and headers["Location"] == "/lock?next=%2Fsettings%2Fai%3Fx%3D1"
    assert request(mac, "GET", "/activity.json")[0] == 423
    assert request(mac, "GET", "/media/1/thumbnail.jpg")[0] == 423
    assert request(mac, "GET", "/item/1?frag=1")[0] == 423
    assert request(mac, "POST", "/hub/add", {"csrf": hub(mac).csrf, "url": "https://x.com/a/status/1"})[0] == 423
    assert request(mac, "GET", "/static/lock.js")[0] == 200  # the page's own scripts still load
    status, _, body = page(mac, "/lock")
    assert status == 200 and "Magpiary is locked" in body
    assert "Zebra" not in body


def test_phone_endpoints_stay_open_while_locked(mac):
    locked_hub(mac)
    assert request(mac, "GET", "/v1/ping")[0] == 200
    assert request(mac, "POST", "/v1/items", {"x": "1"})[0] == 401  # still its own pairing key, not the lock


def test_the_pin_unlocks_over_http(mac):
    locked_hub(mac)
    status, _, data = post(mac, "/hub/lock/pin", pin="000000", json="1")
    assert status == 403 and json.loads(data)["error"] == "That PIN is not right."
    status, _, data = post(mac, "/hub/lock/pin", pin=PIN, json="1")
    assert status == 200 and json.loads(data)["ok"]
    assert page(mac, "/")[0] == 200


def test_the_wait_shows_on_the_card(mac):
    locked_hub(mac)
    for _ in range(lk.TRIES):
        post(mac, "/hub/lock/pin", pin="000000", json="1")
    _, _, data = post(mac, "/hub/lock/pin", pin=PIN, json="1")
    assert "Try again in" in json.loads(data)["error"]
    assert 'data-wait="' in page(mac, "/lock")[2] and 'data-wait="0"' not in page(mac, "/lock?frag=1")[2]


def test_plain_form_unlock_redirects_back(mac):
    locked_hub(mac)
    status, headers, _ = post(mac, "/hub/lock/pin", pin=PIN, next="/settings/phones")
    assert status == 303 and headers["Location"] == "/settings/phones"


def test_lock_now_covers_the_hub(mac):
    post(mac, "/hub/lock/on", pin=PIN, again=PIN)
    assert page(mac, "/")[0] == 200
    status, headers, _ = post(mac, "/hub/lock/now")
    assert status == 303 and headers["Location"] == "/lock"
    assert page(mac, "/")[0] == 303


def test_settings_changes_need_confirming(mac):
    post(mac, "/hub/lock/on", pin=PIN, again=PIN)
    hub(mac).lock.proof = 0.0
    status, headers, _ = post(mac, "/hub/lock/off")
    assert status == 303 and "error=Confirm" in headers["Location"] and hub(mac).lock.enabled
    assert 'data-proven="0"' in page(mac, "/settings/privacy")[2]  # the page asks in a dialog before sending
    status, _, data = post(mac, "/hub/lock/prove", pin="000000", json="1")
    assert status == 403 and not json.loads(data)["ok"]
    status, _, data = post(mac, "/hub/lock/prove", pin=PIN, json="1")
    assert status == 200 and json.loads(data)["ok"]
    assert 'data-proven="1"' in page(mac, "/settings/privacy")[2]
    assert post(mac, "/hub/lock/off")[1]["Location"].startswith("/settings/privacy?note=")
    assert not hub(mac).lock.enabled


def test_pin_dialogs_answer_in_json(mac):
    status, _, data = post(mac, "/hub/lock/on", pin=PIN, again="111111", json="1")
    assert status == 403 and "different" in json.loads(data)["error"]
    status, _, data = post(mac, "/hub/lock/on", pin=PIN, again=PIN, json="1")
    assert "offer=touch" in json.loads(data)["next"]
    status, _, data = post(mac, "/hub/lock/on", pin="135790", again="135790", json="1")  # changing it later: no Touch ID offer
    assert status == 200 and "offer" not in json.loads(data)["next"]


def test_privacy_page_offers_the_lock(mac):
    body = page(mac, "/settings/privacy")[2]
    assert "Hub lock" in body and "Set a PIN" in body and 'id="lkd-pin"' in body
    assert "Lock on" not in page(mac, "/settings")[2]
    post(mac, "/hub/lock/on", pin=PIN, again=PIN)
    assert "Lock on · no idle timer" in page(mac, "/settings")[2]
    body = page(mac, "/settings/privacy")[2]
    for want in ("Change PIN", "Set up Touch ID", "Lock after being idle", 'id="lkd-change"', 'id="lkd-guard"', 'value="0" checked'):
        assert want in body


def test_cli_reset(capsys):
    from magpiary import cli
    from magpiary.config import db_path

    store = Store(db_path())
    assert lk.Lock(store).turn_on(PIN, PIN) == ""
    store.close()
    assert cli.main(["lock", "status"]) == 0 and "is on" in capsys.readouterr().out
    assert cli.main(["lock", "reset"]) == 0
    assert cli.main(["lock", "status"]) == 0 and "is off" in capsys.readouterr().out.splitlines()[-1]
