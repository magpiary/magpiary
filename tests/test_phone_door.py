"""The HTTPS phone door end to end, with a real TLS client that trusts only our own CA."""

import http.client
import socket
import ssl
import threading
from urllib.parse import urlencode

import pytest

from magpiary import access, phone_gate
from magpiary.receiver import make_server
from magpiary.secure_door import SecureServer
from magpiary.store import Store

HOST = "magpiary.local"


class Conn(http.client.HTTPSConnection):
    """Connects to 127.0.0.1 but checks the certificate for magpiary.local, like a phone resolving the name."""

    def connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=5)
        self.sock = self._context.wrap_socket(sock, server_hostname=HOST)


class Door:
    def __init__(self, tmp_path):
        self.store = Store(tmp_path / "door.db")
        self.store.set_setting("setup_done", "1")
        self.primary = make_server(self.store, "127.0.0.1", 0)
        cert, key = access.server_files([HOST, "test-mac.local"])
        self.secure = SecureServer(("127.0.0.1", 0), self.primary, [HOST, "test-mac.local"], str(cert), str(key),
                                   announce=lambda name: self.announced.append(name))
        self.announced: list[str] = []
        for s in (self.primary, self.secure):
            threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.devices = self.primary.hub.devices
        self.ctx = ssl.create_default_context(cadata=access.ca_pem().decode())
        self.key = ""

    def request(self, method, path, body=None, host=HOST, key=None, headers=None):
        c = Conn("127.0.0.1", self.secure.server_port, context=self.ctx, timeout=5)
        h = {"Host": host, **(headers or {})}
        use = self.key if key is None else key
        if use:
            h["Cookie"] = f"{access.COOKIE}={use}"
        data = urlencode(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, r.read().decode("utf-8", "replace"), dict(r.getheaders())
        c.close()
        return out

    def pair(self, name="Test iPhone"):
        token = self.devices.new_pair_token()
        status, _, _ = self.request("GET", access.PAIR_PATH if False else f"/phone/pair/{token}")
        assert status == 200
        status, _, headers = self.request("POST", f"/phone/pair/{token}", {"name": name})
        assert status == 303
        cookie = headers["Set-Cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
        self.key = cookie.split(";")[0].split("=", 1)[1]
        return self.key

    def stop(self):
        for s in (self.primary, self.secure):
            s.shutdown()
            s.server_close()
        self.store.close()


@pytest.fixture
def door(tmp_path):
    d = Door(tmp_path)
    d.store.set_setting(access.SETTING, "1")
    yield d
    d.stop()


def test_unpaired_phone_is_refused_and_logged(door):
    status, _, _ = door.request("GET", "/")
    assert status == 401
    assert door.devices.recent()[0]["kind"] == "refused"


def test_access_off_refuses_even_a_paired_phone(door):
    door.pair()
    assert door.request("GET", "/")[0] == 200
    door.store.set_setting(access.SETTING, "")
    assert door.request("GET", "/")[0] == 403


def test_pairing_is_one_use_and_gives_a_working_key(door):
    token = door.devices.new_pair_token()
    assert door.request("POST", f"/phone/pair/{token}", {"name": "A"})[0] == 303
    assert door.request("POST", f"/phone/pair/{token}", {"name": "B"}, key="")[0] == 410  # same code again
    assert len(door.devices.active()) == 1


def test_expired_or_made_up_pair_code_refused(door):
    assert door.request("GET", "/phone/pair/not-a-real-code")[0] == 410
    assert door.devices.active() == []


def test_paired_phone_opens_the_library_and_the_mac_is_told_once(door):
    door.pair("Maya's iPhone")
    assert door.request("GET", "/")[0] == 200
    door.request("GET", "/")
    assert door.announced == ["Maya's iPhone"]
    assert door.devices.active()[0]["last_seen"]


def test_revoked_phone_is_refused_at_once(door):
    door.pair()
    assert door.request("GET", "/")[0] == 200
    door.devices.revoke(door.devices.active()[0]["id"])
    status, _, _ = door.request("GET", "/")
    assert status == 401


def test_wrong_cookie_is_refused(door):
    door.pair()
    assert door.request("GET", "/", key="x" * 43)[0] == 401


def test_wrong_host_name_is_refused(door):
    door.pair()
    assert door.request("GET", "/", host="evil.example")[0] == 421
    assert door.request("GET", "/", host="test-mac.local")[0] == 200


def test_phone_cannot_reach_the_send_api_or_unknown_paths(door):
    door.pair()
    assert door.request("GET", "/v1/ping")[0] == 404
    assert door.request("POST", "/v1/items", {"x": "1"})[0] == 404
    assert door.request("GET", "/install")[0] == 404


def test_untrusting_client_cannot_connect(door):
    ctx = ssl.create_default_context()  # system roots only: our CA is not installed
    c = Conn("127.0.0.1", door.secure.server_port, context=ctx, timeout=5)
    with pytest.raises(ssl.SSLError):
        c.request("GET", "/")
        c.getresponse()


def test_plain_http_to_the_secure_port_gets_nothing(door):
    s = socket.create_connection(("127.0.0.1", door.secure.server_port), timeout=3)
    s.sendall(b"GET / HTTP/1.1\r\nHost: magpiary.local\r\n\r\n")
    try:
        got = s.recv(200)
    except (ConnectionResetError, TimeoutError):
        got = b""
    s.close()
    assert b"200 OK" not in got and b"<html" not in got


# ---- the limits (docs/specs.md): refused by the server, not just hidden ----

SETTINGS_PAGES = ["/ask", "/ask/poll", "/ask/panel", "/ask/sessions", "/doctor.json?start=1", "/doctor.json?live=1", "/welcome",
                  "/pair.json?qr=x"]


@pytest.mark.parametrize("path", SETTINGS_PAGES)
def test_phone_cannot_open_settings_or_ask_pages(door, path):
    door.pair()
    status, body, _ = door.request("GET", path)
    assert status == 403, path


SETTINGS_POSTS = ["/hub/keys/add", "/hub/keys/remove", "/hub/keys/remove-all", "/hub/keys/order", "/hub/keys/model",
                  "/hub/settings/budget", "/hub/phones/new-code", "/hub/boards/b2-env", "/hub/boards/s3", "/hub/boards/via", "/hub/lock/on", "/hub/lock/off", "/hub/lock/idle",
                  "/hub/lock/forget", "/hub/lock/register", "/hub/lock/prove", "/hub/ask/send",
                  "/hub/ask/engine", "/hub/ask/voice", "/hub/agents/limits", "/hub/agents/hide", "/hub/agents/clearlog", "/hub/versioncheck", "/hub/extension/get", "/hub/phones/add", "/hub/phones/remove", 
                  "/hub/backup", "/hub/restore", "/hub/update", "/hub/login/disconnect", "/hub/try-login",
                  "/hub/boards/b2",
                  "/hub/reveal",  "/hub/welcome/done",
                  "/hub/browsers/add", "/hub/doctor", "/hub/made-up-path"]


@pytest.mark.parametrize("path", SETTINGS_POSTS)
def test_phone_cannot_post_settings_keys_lock_or_ask(door, path):
    door.pair()
    csrf = door.primary.hub._csrf  # even holding a valid page token
    status, body, _ = door.request("POST", path, {"csrf": csrf, "key": "sk-test", "pin": "123456", "text": "hi"})
    assert status == 403, path
    assert door.store.get_setting("lock_on") != "1" and door.store.get_setting("lock_pin") == ""


def test_ai_action_needs_the_confirm_tap(door):
    door.pair()
    csrf = door.primary.hub._csrf
    status, body, _ = door.request("POST", "/hub/again", {"csrf": csrf, "id": "1", "next": "/"})
    assert status == 200 and "Use your AI?" in body and phone_gate.CONFIRM in body
    for path, form in [("/hub/deep", {"id": "1"}), ("/hub/digest/make", {}), ("/hub/screen-again", {"id": "1"}),
                       ("/hub/links/again", {"id": "1"}), ("/hub/bulk", {"action": "again", "ids": "1"})]:
        status, body, _ = door.request("POST", path, {"csrf": csrf, **form})
        assert "Use your AI?" in body, path
    status, body, _ = door.request("POST", "/hub/again", {"csrf": csrf, "id": "1", phone_gate.CONFIRM: "1"})
    assert "Use your AI?" not in body and status in (200, 303)


def test_plain_actions_work_from_the_phone(door):
    door.pair()
    csrf = door.primary.hub._csrf
    status, _, _ = door.request("POST", "/hub/add", {"csrf": csrf, "url": "https://example.com/p/abc"})
    assert status in (200, 303)


def test_post_from_another_site_is_refused(door):
    door.pair()
    csrf = door.primary.hub._csrf
    status, _, _ = door.request("POST", "/hub/add", {"csrf": csrf, "url": "https://example.com/x"},
                                headers={"Origin": "https://evil.example"})
    assert status == 403


# ---- the hub lock on a phone ----

def test_phone_has_its_own_lock_state_under_the_same_pin(door):
    lock = door.primary.hub._main_lock
    assert lock.turn_on("135790", "135790") == ""
    lock.unlock_with_pin("135790")  # the Mac is unlocked
    door.pair()
    status, _, headers = door.request("GET", "/")
    assert status == 303 and headers["Location"].startswith("/lock")  # the phone still asks for the PIN
    csrf = door.primary.hub._csrf
    bad = door.request("POST", "/hub/lock/pin", {"csrf": csrf, "pin": "000000", "json": "1"})
    assert bad[0] == 403
    ok = door.request("POST", "/hub/lock/pin", {"csrf": csrf, "pin": "135790", "json": "1"})
    assert ok[0] == 200
    assert door.request("GET", "/")[0] == 200
    lock.lock_now()  # the Mac locking does not need the phone and the phone unlocking did not unlock the Mac
    assert door.primary.hub._main_lock.is_locked()
    assert door.request("GET", "/")[0] == 200


def test_phone_unlock_does_not_unlock_the_mac(door):
    lock = door.primary.hub._main_lock
    lock.turn_on("135790", "135790")
    lock.lock_now()
    door.pair()
    csrf = door.primary.hub._csrf
    door.request("POST", "/hub/lock/pin", {"csrf": csrf, "pin": "135790", "json": "1"})
    assert door.request("GET", "/")[0] == 200
    assert lock.is_locked()


def test_phone_cannot_turn_the_lock_off(door):
    lock = door.primary.hub._main_lock
    lock.turn_on("135790", "135790")
    door.pair()
    csrf = door.primary.hub._csrf
    assert door.request("POST", "/hub/lock/off", {"csrf": csrf})[0] == 403
    assert lock.enabled


# ---- the Mac's Settings block and the pairing guide ----

def mac_post(door, path, **form):
    return door.primary.hub.post(path, {"csrf": door.primary.hub._csrf, **form}, "127.0.0.1", "localhost:8765", None)


def mac_get(door, path):
    return door.primary.hub.get(path, {}, "127.0.0.1", "localhost:8765")


def test_switch_is_off_by_default_and_toggles_from_the_mac(tmp_path):
    d = Door(tmp_path)
    try:
        assert not access.enabled(d.store)
        page = mac_get(d, "/settings/phones").body.decode()
        assert "Phone access" in page and "Off until you turn it on" in page and "Pair a phone" not in page
        mac_post(d, "/hub/access/toggle", enabled="1")
        assert access.enabled(d.store)
        assert "Pair a phone" in mac_get(d, "/settings/phones").body.decode()
        mac_post(d, "/hub/access/toggle", enabled="0")
        assert not access.enabled(d.store)
    finally:
        d.stop()


def test_pairing_guide_serves_only_the_public_certificate_with_a_good_code(door):
    mac_post(door, "/hub/access/pair")
    page = mac_get(door, "/settings/phones").body.decode()
    assert "fingerprint" in page and " ".join(access.ca_fingerprint().split(" ")[:8]) in page and "data-access" in page
    token = door.primary.hub._pairing[0]
    hub = door.primary.hub
    guide = hub.access_guide(f"/phone-access/{token}", "192.168.1.20")
    assert guide.status == 200 and access.ca_fingerprint().encode() not in guide.body and b"SHA-256" in guide.body  # the fingerprint is NOT on the plain-HTTP page
    crt = hub.access_guide(f"/phone-access/{token}/ca.crt", "192.168.1.20")
    assert crt.status == 200 and b"BEGIN CERTIFICATE" in crt.body and b"PRIVATE" not in crt.body
    assert hub.access_guide("/phone-access/wrong/ca.crt", "192.168.1.20").status == 410
    assert hub.access_guide(f"/phone-access/{token}/ca.crt", "8.8.8.8").status == 410  # not a home-network address
    door.store.set_setting(access.SETTING, "")
    assert hub.access_guide(f"/phone-access/{token}/ca.crt", "192.168.1.20").status == 410


def test_revoke_and_reset_from_the_mac_close_the_door_on_phones(door):
    door.pair()
    did = door.devices.active()[0]["id"]
    mac_post(door, "/hub/access/revoke", id=str(did))
    assert door.request("GET", "/")[0] == 401
    door.pair("Second")
    mac_post(door, "/hub/access/reset")
    assert door.devices.active() == []


def test_a_phone_cannot_use_the_access_settings(door):
    door.pair()
    csrf = door.primary.hub._csrf
    for path in ("/hub/access/toggle", "/hub/access/pair", "/hub/access/revoke", "/hub/access/reset"):
        assert door.request("POST", path, {"csrf": csrf, "id": "1", "enabled": "0"})[0] == 403
    assert access.enabled(door.store) and len(door.devices.active()) == 1


def test_mac_hub_still_refuses_other_addresses(door):
    refused = door.primary.hub.get("/", {}, "192.168.1.20", "magpiary.local")
    assert refused.status == 403


def test_nav_phone_icon_only_while_access_is_on_and_only_for_the_mac(tmp_path):
    d = Door(tmp_path)
    try:
        assert "phacc" not in mac_get(d, "/").body.decode()
        mac_post(d, "/hub/access/toggle", enabled="1")
        assert 'class="ubtn phacc"' in mac_get(d, "/").body.decode()
        d.pair()
        assert "phacc" not in d.request("GET", "/")[1]  # not shown on the phone itself
    finally:
        d.stop()


def test_door_opens_and_closes_with_the_switch_and_starts_helpers(tmp_path):
    from magpiary.secure_door import Door as OpenDoor

    d = Door(tmp_path)
    try:
        events = []

        class FakeBonjour:
            def sync(self, ip): events.append("bonjour")
            def stop(self): events.append("bonjour-stop")

        door = OpenDoor(d.primary, lambda: "test-mac.local", bonjour=FakeBonjour(), port=0)
        door.poll()
        assert door.server is None  # off by default: nothing listens
        d.store.set_setting(access.SETTING, "1")
        door.poll()
        assert door.server is not None and "bonjour" in events
        d.store.set_setting(access.SETTING, "")
        door.poll()
        assert door.server is None and "bonjour-stop" in events
    finally:
        d.stop()


# ---- the Home Screen app: iOS keeps its cookies apart from Safari's ----

def test_pairing_ends_on_the_add_to_home_screen_page(door):
    token = door.devices.new_pair_token()
    status, _, headers = door.request("POST", f"/phone/pair/{token}", {"name": "Maya"}, key="")
    assert status == 303 and headers["Location"] == "/phone/app"


def test_home_screen_icon_is_public_and_the_head_links_it(door):
    status, body, headers = door.request("GET", "/static/apple-touch-icon.png", key="")
    assert status == 200 and headers["Content-Type"] == "image/png"
    door.pair()
    assert 'rel="apple-touch-icon"' in door.request("GET", "/")[1]
    assert door.request("GET", "/static/hub.css", key="")[0] == 401  # only the icon is public


def test_home_screen_app_claims_its_own_key_once(door):
    door.pair("Maya")
    status, body, _ = door.request("GET", "/phone/app")
    assert status == 200 and "replaceState" in body
    token = body.split('replaceState(null,"",')[1].split(")")[0].strip("'\"").rsplit("/", 1)[1]
    # the icon starts with no cookie of its own
    status, page, _ = door.request("GET", f"/phone/app/{token}", key="")
    assert status == 200 and "navigator.standalone" in page and door.devices.app_token_device(token)  # looking does not spend it
    status, _, headers = door.request("POST", f"/phone/app/{token}", {}, key="")
    assert status == 303 and "Secure" in headers["Set-Cookie"]
    app_key = headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    assert door.request("GET", "/", key=app_key)[0] == 200
    assert [d["name"] for d in door.devices.active()] == ["Maya", "Maya app"]
    assert door.request("POST", f"/phone/app/{token}", {}, key="")[0] == 410  # once only
    assert door.request("GET", f"/phone/app/{token}", key=app_key)[0] == 303  # later launches simply go in


def test_home_screen_link_dies_with_the_phone_or_the_clock(door):
    door.pair("Maya")
    did = door.devices.active()[0]["id"]
    token = door.devices.new_app_token(did)
    assert door.devices.app_token_device(token, wall=access.APP_FOR + 10**10) is None  # expired
    door.devices.revoke(did)
    assert door.request("POST", f"/phone/app/{token}", {}, key="")[0] == 410
    assert door.request("GET", "/phone/app", key="")[0] == 401  # unpaired cannot make links


def test_turning_the_lock_on_locks_every_phone_again(door):
    door.pair()
    assert door.request("GET", "/")[0] == 200  # lock off: the phone is open
    csrf = door.primary.hub._csrf
    door.primary.hub.post("/hub/lock/on", {"csrf": csrf, "pin": "135790", "again": "135790"}, "127.0.0.1", "localhost", None)
    assert door.primary.hub._main_lock.enabled
    status, _, headers = door.request("GET", "/")
    assert status == 303 and headers["Location"].startswith("/lock")


def test_add_to_home_screen_page_names_the_icon_magpiary(door):
    door.pair()
    body = door.request("GET", "/phone/app")[1]
    assert 'rel="apple-touch-icon" href="/static/apple-touch-icon.png"' in body
    assert 'name="apple-mobile-web-app-title" content="Magpiary"' in body


def test_home_screen_manifest_opens_full_screen_and_starts_at_the_one_time_link(door):
    import json as j

    door.pair("Maya")
    body = door.request("GET", "/phone/app")[1]
    assert 'rel="manifest"' in body
    token = body.split('replaceState(null,"",')[1].split(")")[0].strip("'\"").rsplit("/", 1)[1]
    status, text, headers = door.request("GET", f"/phone/app/{token}/manifest.webmanifest", key="")
    m = j.loads(text)
    assert status == 200 and m["display"] == "standalone" and m["start_url"] == f"/phone/app/{token}" and m["name"] == "Magpiary"
    assert door.request("GET", "/phone/app/not-a-token/manifest.webmanifest", key="")[0] == 404


# ---- fixes from the first Codex review (7 Nov) ----

def test_control_cannot_set_the_proxy_and_resume_needs_a_confirm(door):
    door.pair()
    csrf = door.primary.hub._csrf
    status, _, _ = door.request("POST", "/hub/control", {"csrf": csrf, "part": "statsproxy", "action": "save", "address": "http://10.0.0.9:8080"})
    assert status == 403
    status, body, _ = door.request("POST", "/hub/control", {"csrf": csrf, "part": "summary", "action": "resume"})
    assert "Use your AI?" in body
    assert door.request("POST", "/hub/control", {"csrf": csrf, "part": "summary", "action": "pause"})[0] in (200, 303)
    assert door.request("POST", "/hub/control", {"csrf": csrf, "part": "bogus", "action": "pause"})[0] == 403


def test_refusals_and_confirm_leak_nothing_while_the_phone_is_locked(door):
    lock = door.primary.hub._main_lock
    lock.turn_on("135790", "135790")
    door.pair()
    for path, form in (("/settings", None), ("/hub/again", {"csrf": door.primary.hub._csrf, "id": "1"})):
        status, body, headers = door.request("GET" if form is None else "POST", path, form)
        assert "id=\"ticker\"" not in body and "data-count" not in body and "phone_confirm" not in body
    wrong_csrf = door.request("POST", "/hub/again", {"csrf": "nope", "id": "1"})
    assert "phone_confirm" not in wrong_csrf[1] and wrong_csrf[0] == 403
    other_site = door.request("POST", "/hub/again", {"csrf": door.primary.hub._csrf, "id": "1"}, headers={"Origin": "https://evil.example"})
    assert other_site[0] == 403


def test_mac_screen_lock_locks_every_phone_and_turning_the_lock_on_does_too(door):
    hub = door.primary.hub
    hub._main_lock.turn_on("135790", "135790")
    door.pair()
    door.request("POST", "/hub/lock/pin", {"csrf": hub._csrf, "pin": "135790", "json": "1"})
    assert door.request("GET", "/")[0] == 200
    hub.lock_phones_if_screen_locked(screen=lambda: True)
    assert door.request("GET", "/")[0] == 303


def test_two_phones_guessing_at_once_share_one_wait(door):
    hub = door.primary.hub
    hub._main_lock.turn_on("135790", "135790")
    from magpiary.lock import Lock

    locks = [Lock(door.store) for _ in range(2)]
    results = []

    def guess(lock):
        for i in range(8):
            results.append(lock.check_pin(f"00000{i}"))

    threads = [threading.Thread(target=guess, args=(lk,)) for lk in locks]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("wrong") == 5 and results.count("wait") == 11  # five tries in all, however many phones


def test_certificate_reset_is_served_to_new_connections(door):
    from magpiary import access as acc

    names = [HOST, "test-mac.local"]
    acc.forget_authority()
    cert, key = acc.server_files(names)
    assert door.secure.reload_certificate(str(cert), str(key)) is True
    ctx = ssl.create_default_context(cadata=acc.ca_pem().decode())  # a phone that now trusts only the NEW authority
    door.ctx = ctx
    door.pair()
    assert door.request("GET", "/")[0] == 200


def test_the_phone_door_clears_any_old_hsts_rule(door):
    door.pair()
    assert door.request("GET", "/")[2]["Strict-Transport-Security"] == "max-age=0"
    assert door.request("GET", "/", key="")[2]["Strict-Transport-Security"] == "max-age=0"  # even a refusal wipes it


def test_the_pairing_qr_uses_the_network_address_not_the_name(door, monkeypatch):
    import re

    from magpiary import secure_door

    monkeypatch.setattr(secure_door, "lan_ip", lambda: "192.168.9.9")
    mac_post(door, "/hub/access/pair")
    page = mac_get(door, "/settings/phones").body.decode()
    assert "data-access" in page  # the card is drawn; its QR encodes http://192.168.9.9:<port>/phone-access/<code>
    import segno

    token = door.primary.hub._pairing[0]
    want = segno.make(f"http://192.168.9.9:{door.primary.server_port}/phone-access/{token}", error="m").svg_inline(
        border=2, omitsize=True, dark="#000", light="#fff")
    assert want in page


# ---- the phone setup pages ----

def test_certificate_guide_has_the_exact_ios_words_and_a_live_trust_check(door):
    mac_post(door, "/hub/access/pair")
    token = door.primary.hub._pairing[0]
    page = door.primary.hub.access_guide(f"/phone-access/{token}", "192.168.1.20").body.decode()
    for words in ("Profile Downloaded", "Certificate Trust Settings", "Magpiary local network CA", "General → About",
                  "VPN &amp; Device Management", "Enable full trust for root certificates"):
        assert words in page, words
    assert f"https://magpiary.local:{access.https_port(door.primary.server_port)}/static/apple-touch-icon.png" in page  # the live check
    assert f"/phone/pair/{token}" in page and "viewport-fit=cover" in page


def test_pair_and_home_screen_pages_are_phone_sized(door):
    token = door.devices.new_pair_token()
    page = door.request("GET", f"/phone/pair/{token}", key="")[1]
    assert 'maxlength="40"' in page and "min-height:52px" in page and "font:16px" in page  # no iOS zoom, big tap targets
    door.pair()
    home = door.request("GET", "/phone/app")[1]
    assert "Open as Web App" in home and "Add to Home Screen" in home


# ---- Settings on the phone: the owner's list (7 Nov): look, switch, small choices; never keys, lock, pairing, files ----

@pytest.mark.parametrize("path", ["/settings", "/settings/profile", "/settings/phones", "/settings/ai", "/settings/ask", "/settings/agents",
                                  "/settings/boards", "/settings/appearance", "/settings/storage", "/settings/privacy", "/doctor"])
def test_phone_can_open_the_settings_pages(door, path):
    door.pair()
    assert door.request("GET", path)[0] == 200, path


def test_phone_settings_hide_pairing_and_phone_access(door):
    mac_post(door, "/hub/access/pair")
    door.pair()
    page = door.request("GET", "/settings/phones?qr=http://x")[1]
    assert "Phone access" not in page and "Pair a phone" not in page and "fingerprint" not in page


@pytest.mark.parametrize("path,form", [("/hub/settings/mode", {"mode": "private"}), ("/hub/awake", {"enabled": "1"}),
                                       ("/hub/ui", {"theme": "dark"}), ("/hub/digest/on", {"enabled": "1"}),
                                       ("/hub/deep/on", {"enabled": "1"}), ("/hub/agents/on", {"enabled": "1"}),
                                       ("/hub/askset", {"enabled": "1"}), ("/hub/phones/wifi", {"name": "x", "mode": "any"}),
                                       ("/hub/profile", {"name": "Maya"})])
def test_phone_can_change_the_listed_settings(door, path, form):
    door.pair()
    status, body, _ = door.request("POST", path, {"csrf": door.primary.hub._csrf, **form})
    assert status in (200, 303) and "Not on the phone" not in body, path


def test_phone_still_cannot_touch_keys_the_lock_pairing_or_files(door):
    door.pair()
    csrf = door.primary.hub._csrf
    for path in ("/hub/keys/add", "/hub/keys/remove", "/hub/lock/on", "/hub/lock/off", "/hub/phones/add", "/hub/phones/remove",
                 "/hub/backup", "/hub/restore", "/hub/boards/b2", "/hub/login/disconnect", "/hub/reveal"):
        assert door.request("POST", path, {"csrf": csrf})[0] == 403, path


def test_certificate_guide_lets_the_phone_say_the_install_is_done(door):
    mac_post(door, "/hub/access/pair")
    token = door.primary.hub._pairing[0]
    page = door.primary.hub.access_guide(f"/phone-access/{token}", "192.168.1.20").body.decode()
    assert 'id="inst"' in page and "I've installed the profile" in page and "mark(3)" in page


# ---- the phone's More menu, and the phone's hide-list for Mac-only settings ----

def test_more_menu_offers_add_to_home_screen_to_a_paired_phone_only(door):
    assert "data-homescreen" not in mac_get(door, "/").body.decode()
    door.pair()
    page = door.request("GET", "/")[1]
    assert 'href="/phone/app" data-homescreen' in page and "Add to Home Screen" in page
    assert door.request("GET", "/phone/app")[0] == 200


def test_phone_css_hide_list_ids_still_exist_on_the_settings_pages(door):
    import re
    from pathlib import Path

    css = (Path(__file__).parent.parent / "src/magpiary/static/phone.css").read_text()
    hidden = set(re.findall(r"#(instagram|home|chrome)\b", css))
    assert hidden == {"instagram", "home", "chrome"}  # the hide list still names them
    door.store.add_phone("Work iPhone", "")  # "home" is inside the phones card once a phone is paired
    pages = {p: mac_get(door, f"/settings/{p}").body.decode() for p in ("ai", "phones", "storage")}
    assert 'id="instagram"' in pages["ai"] and 'id="home"' in pages["phones"]
    src = (Path(__file__).parent.parent / "src/magpiary/hub_settings.py").read_text()
    assert 'gid="chrome"' in src  # shown only with the pairing service, on Library & this Mac
