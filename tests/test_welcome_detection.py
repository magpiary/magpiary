"""The Welcome guide ticks only what the Mac has really seen: the extension's hello, a device's first contact, the Shortcut download."""

import json

from test_browser_pairing import _post, add_browser, redeem
from test_setup import Env, A, env  # noqa: F401  (env is the fixture)


def test_a_phone_is_not_contacted_until_it_uses_its_key(env):
    phone, key = env.mac.store.add_phone("Test iPhone")
    assert env.mac.store.list_phones()[0]["first_seen_at"] is None  # a QR code alone proves nothing
    assert env.mac.store.phone_for_key(key).id == phone.id
    first = env.mac.store.list_phones()[0]["first_seen_at"]
    assert first and env.mac.store.list_phones()[0]["last_seen_at"] == first
    state = env.mac.server.hub._welcome_state()
    assert state["contact"] is True and state["phone_saved"] is False


def test_the_extension_hello_marks_it_added_and_pinned_without_a_key(env):
    status = env.mac.store.extension_status()
    assert status == {"added": False, "pinned": None, "paired": False, "used": False}
    assert _post(env, "/v1/hello", json.dumps({"v": "0.1.4", "pinned": False}))[0] == 200
    assert env.mac.store.extension_status()["added"] is True and env.mac.store.extension_status()["pinned"] is False
    assert _post(env, "/v1/hello", json.dumps({"v": "0.1.4", "pinned": True}))[0] == 200
    assert env.mac.store.extension_status()["pinned"] is True
    assert _post(env, "/v1/hello", json.dumps({"v": "0.1.4"}))[0] == 200            # older Chrome: pinned not known
    assert env.mac.store.extension_status()["pinned"] is None


def test_the_extension_hello_rejects_bad_bodies(env):
    assert _post(env, "/v1/hello", "not json")[0] == 400
    assert _post(env, "/v1/hello", json.dumps({"v": 5}))[0] == 400
    assert _post(env, "/v1/hello", json.dumps({"v": "0.1.4", "pinned": "yes"}))[0] == 400
    assert _post(env, "/v1/hello", json.dumps({"v": "x" * 600}))[0] == 400
    assert env.mac.store.extension_status()["added"] is False


def test_pairing_chrome_counts_as_added_and_connected_and_its_first_save_as_saved(env):
    _, code = add_browser(env)
    key = json.loads(redeem(env, code)[1])["key"]
    ext = env.mac.store.extension_status()
    assert ext["added"] is True and ext["paired"] is True and ext["pinned"] is None  # a 0.1.3 extension never says if it is pinned
    assert env.mac.server.hub._welcome_state()["chrome_saved"] is False
    _post(env, "/v1/items", json.dumps({"items": [{"id": "20261103101500-123456", "url": "https://example.com/a-page",
                                                   "shared_at": "2026-11-03T10:15:00+00:00", "v": 1}]}), key)
    assert env.mac.server.hub._welcome_state()["chrome_saved"] is True
    assert env.mac.store.delivered_kinds() == {"browser"}


def test_the_pinned_button_stands_in_for_an_extension_that_cannot_say(env):
    hub = env.mac.server.hub
    assert hub._welcome_state()["ext"]["pinned"] in (None, False)
    env.post("/hub/welcome/pinned", next="/welcome/browser")
    assert hub._welcome_state()["ext"]["pinned"] is True


def test_the_page_signature_changes_when_a_step_ticks(env):
    hub = env.mac.server.hub
    before = hub._sig(hub._welcome_state())
    _post(env, "/v1/hello", json.dumps({"v": "0.1.4", "pinned": True}))
    assert hub._sig(hub._welcome_state()) != before
