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

SETTINGS_PAGES = ["/settings", "/settings/ai", "/settings/privacy", "/settings/phones", "/ask", "/ask/poll", "/ask/panel",
                  "/ask/sessions", "/doctor", "/doctor.json", "/welcome", "/pair.json?qr=x"]


@pytest.mark.parametrize("path", SETTINGS_PAGES)
def test_phone_cannot_open_settings_or_ask_pages(door, path):
    door.pair()
    status, body, _ = door.request("GET", path)
    assert status == 403, path


SETTINGS_POSTS = ["/hub/keys/add", "/hub/keys/remove", "/hub/keys/remove-all", "/hub/keys/order", "/hub/keys/model",
                  "/hub/settings/mode", "/hub/settings/budget", "/hub/lock/on", "/hub/lock/off", "/hub/lock/idle",
                  "/hub/lock/forget", "/hub/lock/register", "/hub/lock/prove", "/hub/askset", "/hub/ask/send",
                  "/hub/ask/engine", "/hub/ask/voice", "/hub/phones/add", "/hub/phones/remove", "/hub/engine/allow",
                  "/hub/backup", "/hub/restore", "/hub/update", "/hub/login/disconnect", "/hub/try-login",
                  "/hub/digest/engine", "/hub/digest/on", "/hub/deep/engine", "/hub/deep/on", "/hub/boards/b2",
                  "/hub/profile", "/hub/reveal", "/hub/awake", "/hub/agents/on", "/hub/welcome/done",
                  "/hub/browsers/add", "/hub/ui", "/hub/doctor", "/hub/made-up-path"]


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
