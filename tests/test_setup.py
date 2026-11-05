"""Pairing a phone, seen from outside over HTTP: Settings → Phones makes the code, the phone installs the Shortcut."""

import http.client
import json
import plistlib
import re
from urllib.parse import urlencode

import pytest

from fakephone import Clock, Mac, Phone
from magpiary.power import KeepAwake
from magpiary.setup import TOKEN_DOWNLOADS, TOKEN_TTL_SECONDS, Setup
from test_power import FakeProcess

A = "https://www.instagram.com/reel/AAAA111/"


class Env:
    def __init__(self, tmp_path):
        self.clock = Clock()
        self.signer_fails = False
        self.awake_fails = False
        self.suggested = "Suggested Net"

        def signer(workflow):
            if self.signer_fails:
                raise RuntimeError("Failed to modify some records")
            return plistlib.dumps(workflow)  # unsigned, but readable by the tests

        def spawn():
            if self.awake_fails:
                raise FileNotFoundError("caffeinate")
            return FakeProcess()
        self.awake = KeepAwake(spawn=spawn)
        self.mac = Mac(tmp_path / "magpiary.db", self.clock, lambda store: Setup(
            store, host_name="test-mac.local", signer=signer, keep_awake=self.awake,
            wifi_suggestion=lambda: self.suggested, now=lambda: self.clock.now().timestamp()))
        self.setup = self.mac.setup
        self.csrf = self.mac.server.hub.csrf

    def request(self, method, path, form=None, host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.mac.port, timeout=10)
        h = {"Host": host or f"localhost:{self.mac.port}", **(headers or {})}
        body = None
        if form is not None:
            body = urlencode(form)
            h["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), data

    def post(self, path, **form):
        return self.request("POST", path, {"csrf": self.csrf, **form})

    def add_phone(self, name="Test iPhone", home_wifi="Example Net"):
        """(status, where Settings sends you: the QR address, or an error)."""
        status, headers, _ = self.post("/hub/phones/add", name=name, home_wifi=home_wifi, next="/settings/phones")
        return status, headers.get("Location", "")

    def token_from(self, location):
        return re.search(r"t%3D([A-Za-z0-9_-]+)", location).group(1)

    def shortcut_for(self, token):
        status, headers, data = self.request("GET", f"/s/{token}/Magpiary.shortcut", host="test-mac.local:8765")
        return status, headers, data

    def baked_in_key(self, data):
        """What the Shortcut holds to sign with: sha256 of the phone's key (the key itself is never in it)."""
        wf = plistlib.loads(data)
        text = next(a["WFWorkflowActionParameters"]["WFTextActionText"]["Value"]["string"] for a in wf["WFWorkflowActions"]
                    if a["WFWorkflowActionIdentifier"].endswith("gettext") and isinstance(a["WFWorkflowActionParameters"]["WFTextActionText"], dict)
                    and "|POST /v1/items|" in a["WFWorkflowActionParameters"]["WFTextActionText"]["Value"]["string"])
        return text.split("|", 1)[0]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.mac.stop()
    e.mac.store.close()


# ---- the whole journey ----------------------------------------------------------------------

def test_add_a_phone_scan_install_and_send_a_share(env):
    status, page = env.add_phone("Alex Example iPhone", "Example Net")
    assert status == 303 and "qr=" in page
    assert b"<svg" in env.request("GET", page)[2]
    token = env.token_from(page)

    status, _, install = env.request("GET", f"/install?t={token}", host="test-mac.local:8765")
    assert status == 200 and f"/s/{token}/Magpiary.shortcut" in install.decode()

    status, headers, data = env.shortcut_for(token)
    assert status == 200 and headers["Content-Type"] == "application/vnd.apple.shortcut"
    assert 'filename="Magpiary.shortcut"' in headers["Content-Disposition"]
    wf = plistlib.loads(data)
    post = next(a for a in wf["WFWorkflowActions"] if a["WFWorkflowActionIdentifier"].endswith("downloadurl")
                and a["WFWorkflowActionParameters"]["WFHTTPMethod"] == "POST")
    assert post["WFWorkflowActionParameters"]["WFURL"] == f"http://test-mac.local:{env.mac.port}/v1/items"
    gate = next(a for a in wf["WFWorkflowActions"] if a["WFWorkflowActionParameters"].get("WFReplaceTextReplace") == "@@go@@")
    assert re.search(gate["WFWorkflowActionParameters"]["WFReplaceTextFind"], "Example Net\u00a7home\u00a7https://x.test/p\u00a7\u00a7Example Net\u00a6202610272214a\u00a7")

    key = env.baked_in_key(data)
    assert key not in page and key not in install.decode()   # a key is never shown on a page
    Phone(env.mac, secret=key).run(A + "?igsh=x")
    assert env.mac.counts() == {A: 1}
    assert [i["phone"] for i in env.mac.store.items()] == ["Alex Example iPhone"]


# ---- install codes --------------------------------------------------------------------------

def test_a_code_expires_after_fifteen_minutes(env):
    token = env.token_from(env.add_phone()[1])
    env.clock.advance(TOKEN_TTL_SECONDS - 5)
    assert env.shortcut_for(token)[0] == 200
    env.clock.advance(10)
    assert env.shortcut_for(token)[0] == 404
    assert env.request("GET", f"/install?t={token}")[0] == 403


def test_a_code_works_only_a_few_times(env):
    token = env.token_from(env.add_phone()[1])
    assert [env.shortcut_for(token)[0] for _ in range(TOKEN_DOWNLOADS + 1)] == [200] * TOKEN_DOWNLOADS + [404]


def test_an_unknown_code_gets_nothing(env):
    assert env.shortcut_for("not-a-token")[0] == 404
    assert env.request("GET", "/install?t=nope")[0] == 403
    assert env.request("GET", "/install")[0] == 403


def test_when_apple_signing_fails_the_page_says_so_and_the_code_survives(env, capsys):
    token = env.token_from(env.add_phone()[1])
    env.signer_fails = True
    status, _, body = env.shortcut_for(token)
    assert status == 503 and b"signed by Apple" in body and b"iCloud" in body and b"Failed to modify" not in body
    assert "shortcut signing failed" in capsys.readouterr().out  # the reason reaches the log
    env.signer_fails = False
    assert env.shortcut_for(token)[0] == 200


def test_a_new_install_code_replaces_the_phones_key(env):
    token = env.token_from(env.add_phone()[1])
    old_key = env.baked_in_key(env.shortcut_for(token)[2])
    status, headers, _ = env.post("/hub/phones/new-code", name="Test iPhone")
    new_key = env.baked_in_key(env.shortcut_for(env.token_from(headers["Location"]))[2])
    assert status == 303 and new_key != old_key
    assert "didn't accept" in Phone(env.mac, secret=old_key).run(A)
    assert "Saved to Magpiary" in Phone(env.mac, secret=new_key).run(A)


def test_removing_a_phone_cuts_it_off_and_frees_the_name(env):
    key = env.baked_in_key(env.shortcut_for(env.token_from(env.add_phone()[1]))[2])
    status, headers, _ = env.post("/hub/phones/remove", name="Test iPhone")
    assert status == 303 and headers["Location"].startswith("/settings/phones")
    assert "didn't accept" in Phone(env.mac, secret=key).run(A)
    assert env.mac.store.get_phone("Test iPhone") is None
    assert "qr=" in env.add_phone("Test iPhone")[1]


def test_a_duplicate_or_empty_name_shows_an_error(env):
    env.add_phone("Test iPhone")
    status, page = env.add_phone("Test iPhone")
    assert "error=" in page and "already%20exists" in page
    assert "error=" in env.add_phone("   ")[1]


def test_names_are_escaped_on_the_page(env):
    env.add_phone("<script>alert(1)</script>", "<b>wifi</b>")
    page = env.request("GET", "/settings/phones")[2].decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


# ---- this Mac only, and safe from other websites --------------------------------------------

def test_pairing_is_refused_to_other_devices(env):
    hub = env.mac.server.hub
    assert hub.post("/hub/phones/add", {"csrf": env.csrf, "name": "x"}, "192.168.1.50", "localhost:8765", None).status == 403
    assert env.mac.store.list_phones() == []


def test_dns_rebinding_is_refused(env):
    assert env.request("GET", "/settings/phones", host="evil.example:8765")[0] == 403
    status, _, _ = env.request("POST", "/hub/phones/add", {"csrf": env.csrf, "name": "x"}, host="evil.example")
    assert status == 403 and env.mac.store.list_phones() == []


def test_forms_without_the_secret_field_are_refused(env):
    for form in ({"name": "x"}, {"name": "x", "csrf": "wrong"}):
        assert env.request("POST", "/hub/phones/add", form)[0] == 403
    assert env.mac.store.list_phones() == []


def test_a_form_posted_from_another_website_is_refused(env):
    status, _, _ = env.request("POST", "/hub/phones/add", {"csrf": env.csrf, "name": "x"},
                               headers={"Origin": "https://evil.example"})
    assert status == 403 and env.mac.store.list_phones() == []


def test_the_same_website_origin_is_accepted(env):
    status, _, _ = env.request("POST", "/hub/phones/add", {"csrf": env.csrf, "name": "x"},
                               headers={"Origin": f"http://localhost:{env.mac.port}"})
    assert status == 303 and env.mac.store.get_phone("x")


def test_the_old_setup_page_is_gone(env):
    assert env.request("GET", "/setup")[0] == 404
    assert env.request("POST", "/setup/phones", {"csrf": env.csrf, "name": "x"})[0] == 404


# ---- stay awake -----------------------------------------------------------------------------

def test_stay_awake_is_off_by_default(env):
    env.setup.apply_saved_settings()
    assert not env.awake.running


def test_the_saved_choice_is_honoured_at_startup_and_only_then(env):
    env.mac.store.set_setting("stay_awake", "1")
    env.setup.apply_saved_settings()
    assert env.awake.running


def test_if_the_macos_tool_is_missing_nothing_is_saved_as_on(env):
    env.awake_fails = True
    env.post("/hub/awake", enabled="1", next="/nest")
    assert env.mac.store.get_setting("stay_awake") == "" and not env.awake.running


def test_the_retry_button_starts_a_flagged_item_over_and_wakes_the_worker(env):
    from magpiary.queuepage import table
    url = "https://www.instagram.com/reel/Private1/"
    phone, _ = env.mac.store.add_phone("Retry phone")
    env.mac.store.receive(phone, [{"id": "r1", "url": url}])
    env.mac.store.fetch_failed(url, "private", "Private video", retry=False)
    woken = []
    env.mac.server.hub.wake = lambda: woken.append(1)
    body = table(env.mac.store, env.csrf)[1]
    assert "Needs attention: The post is private" in body and "Retry now" in body and env.csrf in body
    assert env.request("POST", "/hub/retry", {"url": url})[0] == 403  # no secret field: refused
    status, headers, _ = env.post("/hub/retry", url=url, next="/nest?tab=phones")
    assert status == 303 and env.mac.store.get_item(url)["status"] == "queued" and woken == [1]


def test_an_archived_item_shows_where_it_is(env):
    from magpiary.queuepage import table
    url = "https://www.instagram.com/reel/Done1/"
    phone, _ = env.mac.store.add_phone("Archive phone")
    env.mac.store.receive(phone, [{"id": "a1", "url": url}])
    env.mac.store.fetch_succeeded(url, "/path/to/Magpiary/library/instagram-Done1")
    body = table(env.mac.store, env.csrf)[1]
    assert "Archived" in body and "library/instagram-Done1" in body and "Retry now" not in body


# ---- pairing from the hub (M7a: Settings → Phones and the first-run guide) ------------------------

def test_the_hub_pairs_a_phone_with_a_qr_code_and_can_renew_or_remove_it(env):
    hub = env.mac.server.hub
    form = {"csrf": hub.csrf, "name": "Hub iPhone", "home_wifi": "Example Net", "next": "/welcome/phone"}
    status, headers, _ = env.request("POST", "/hub/phones/add", form)
    assert status == 303 and headers["Location"].startswith("/welcome/phone?qr=http%3A%2F%2Ftest-mac.local%3A")
    status, _, body = env.request("GET", headers["Location"])
    assert status == 200 and b'class="qr"' in body and b"<svg" in body and b"Paired: Hub iPhone" not in body
    assert env.mac.store.get_phone("Hub iPhone")["home_wifi"] == "Example Net"
    token = re.search(r"t%3D([\w-]+)", headers["Location"]).group(1)
    assert env.request("GET", f"/install?t={token}")[0] == 200          # the code in the QR works
    status, headers, _ = env.request("POST", "/hub/phones/add", form)   # the same name again
    assert "error=" in headers["Location"]
    status, headers, _ = env.request("POST", "/hub/phones/new-code", {"csrf": hub.csrf, "name": "Hub iPhone"})
    assert headers["Location"].startswith("/settings/phones?qr=")
    status, headers, _ = env.request("POST", "/hub/phones/remove", {"csrf": hub.csrf, "name": "Hub iPhone"})
    assert env.mac.store.get_phone("Hub iPhone") is None
    assert env.request("POST", "/hub/phones/add", {**form, "csrf": "wrong"})[0] == 403


def test_a_qr_for_another_host_is_never_drawn(env):
    _, _, body = env.request("GET", "/settings/phones?qr=http%3A%2F%2Fevil.example%2Finstall&phone=x")
    assert b"Scan with the iPhone camera" not in body and b"evil.example" not in body


def test_keep_awake_from_the_nest(env):
    hub = env.mac.server.hub
    env.request("POST", "/hub/awake", {"csrf": hub.csrf, "enabled": "1", "next": "/nest"})
    assert env.awake.running and env.mac.store.get_setting("stay_awake") == "1"
    env.request("POST", "/hub/awake", {"csrf": hub.csrf, "enabled": "0", "next": "/nest"})
    assert not env.awake.running


# ---- the pairing window's live steps ----------------------------------------------------------

def test_the_pairing_window_ticks_off_page_download_and_first_share(env):
    status, location = env.add_phone("Tick iPhone", "Example Net")
    qr = location.split("qr=")[1].split("&")[0]
    state = lambda: json.loads(env.request("GET", f"/pair.json?qr={qr}")[2])
    assert state() == {"phone": "Tick iPhone", "left": TOKEN_TTL_SECONDS, "opened": False, "downloaded": False,
                       "shared": False}
    token = env.token_from(location)
    env.request("GET", f"/install?t={token}", host="test-mac.local:8765")
    assert state()["opened"] and not state()["downloaded"]
    _, _, data = env.shortcut_for(token)
    assert state()["downloaded"] and not state()["shared"]
    Phone(env.mac, secret=env.baked_in_key(data)).run(A)
    assert state()["shared"]
    page = env.request("GET", location)[2].decode()
    assert 'class="dlg pairdlg paired"' in page and "First share arrived" in page


def test_the_pairing_status_is_for_this_mac_only_and_known_codes_only(env):
    _, location = env.add_phone()
    qr = location.split("qr=")[1].split("&")[0]
    assert env.request("GET", f"/pair.json?qr={qr}", host="test-mac.local:8765")[0] == 403
    assert env.request("GET", "/pair.json?qr=http%3A%2F%2Ftest-mac.local%3A1%2Finstall%3Ft%3Dnope")[0] == 404


def test_an_expired_code_offers_a_new_one(env):
    _, location = env.add_phone("Late iPhone")
    env.clock.advance(TOKEN_TTL_SECONDS + 1)
    page = env.request("GET", location)[2].decode()
    assert 'pairdlg dead' in page and "/hub/phones/new-code" in page
    status, _, body = env.request("GET", f"/install?t={env.token_from(location)}", host="test-mac.local:8765")
    assert status == 403 and b"run out" in body


def test_the_phone_page_gets_the_hubs_fonts_and_nothing_else(env):
    status, headers, data = env.request("GET", "/install/fonts/dm-sans.woff2", host="test-mac.local:8765")
    assert status == 200 and headers["Content-Type"] == "font/woff2" and data[:4] == b"wOF2"
    assert env.request("GET", "/install/fonts/..%2Fhub.css", host="test-mac.local:8765")[0] == 404
    assert env.request("GET", "/install/fonts/hub.css", host="test-mac.local:8765")[0] == 404


def test_the_install_page_learns_when_its_shortcut_went_out(env):
    token = env.token_from(env.add_phone("Spin iPhone")[1])
    state = lambda t: env.request("GET", f"/install/state?t={t}", host="test-mac.local:8765")
    assert json.loads(state(token)[2]) == {"ready": False}
    env.shortcut_for(token)
    assert json.loads(state(token)[2]) == {"ready": True}
    assert state("nope")[0] == 404


def test_add_forms_fold_back_with_cancel(env):
    page = env.request("GET", "/settings/phones")[2].decode()
    assert "data-closedetails" in page


# ---- where a phone may send: Home only (default) or Any Wi-Fi ------------------------------

REELS = [f"https://www.instagram.com/reel/Wifi{n}/" for n in range(6)]


def test_a_phone_paired_without_a_home_wifi_sends_on_any_wifi(env):
    _, key = env.mac.store.add_phone("P")
    assert env.mac.store.get_phone("P")["wifi_mode"] == "any"
    phone = Phone(env.mac, key)
    phone.no_home = True
    assert phone.run(REELS[0], network="other") == "Saved to Magpiary ✅"  # no learning step: it just sends
    assert phone.wifi_file == "any"
    assert phone.run(REELS[1], network="mobile") == "Saved. It will send when you're home."  # (the fake's one message)


def test_a_phone_paired_with_a_home_wifi_sends_from_home_only_and_the_replies_say_so(env):
    _, key = env.mac.store.add_phone("P", "Example Net")
    assert env.mac.store.get_phone("P")["wifi_mode"] == "home"
    phone = Phone(env.mac, key)
    phone.run(REELS[0])
    assert phone.wifi_file == "home"


def test_home_only_needs_a_home_wifi_name(env):
    env.mac.store.add_phone("P")
    assert not env.mac.store.set_wifi_mode("P", "home")
    assert env.mac.store.wifi_mode_of(env.mac.store.phone_for_key(env.mac.store.add_phone("Q")[1]).id) == "any"


def test_the_mode_only_changes_for_the_two_known_values(env):
    env.mac.store.add_phone("P", "Example Net")
    assert env.mac.store.set_wifi_mode("P", "any") and env.mac.store.get_phone("P")["wifi_mode"] == "any"
    assert not env.mac.store.set_wifi_mode("P", "everywhere") and env.mac.store.get_phone("P")["wifi_mode"] == "any"
    assert not env.mac.store.set_wifi_mode("Nobody", "home")


def test_any_wifi_lets_a_phone_with_a_home_wifi_send_away_once_it_has_learned_it(env):
    _, key = env.mac.store.add_phone("P", "Example Net")
    phone = Phone(env.mac, key)
    saved = lambda: len(env.mac.store.items())
    assert phone.run(REELS[0], network="other") == "Saved. It will send when you're home."  # Home only: waits
    env.mac.store.set_wifi_mode("P", "any")
    phone.run(REELS[1], network="other")
    assert saved() == 0                      # the phone has not heard about the change yet
    phone.run(REELS[2], network="home")      # the next time it reaches the Mac, it learns "any" (and sends the queue)
    assert phone.wifi_file == "any" and saved() == 3
    phone.run(REELS[3], network="other")     # another Wi-Fi: sends now
    assert saved() == 4
    assert phone.run(REELS[4], network="mobile") == "Saved. It will send when you're home."  # no Wi-Fi: queue
    assert saved() == 4 and phone.waiting() == 1
    phone.run("", network="mobile")          # Magpiary run by hand: Send now, from anywhere
    assert saved() == 5 and phone.waiting() == 0


def test_switching_back_to_home_only_takes_effect_the_next_time_the_phone_reaches_the_mac(env):
    _, key = env.mac.store.add_phone("P", "Example Net")
    env.mac.store.set_wifi_mode("P", "any")
    phone = Phone(env.mac, key)
    phone.run(REELS[0], network="home")
    env.mac.store.set_wifi_mode("P", "home")
    phone.run(REELS[1], network="other")     # still believes "any": sends, and hears "home" in the reply
    assert phone.wifi_file == "home"
    assert phone.run(REELS[2], network="other") == "Saved. It will send when you're home."


def test_settings_phones_has_the_switch_and_it_saves(env):
    env.add_phone("Test iPhone")
    page = env.request("GET", "/settings/phones")[2].decode()
    assert "Home only" in page and "Any Wi-Fi" in page and 'value="home" checked' in page
    status, headers, _ = env.post("/hub/phones/wifi", name="Test iPhone", mode="any", next="/settings/phones")
    assert status == 303 and headers["Location"] == "/settings/phones"
    assert env.mac.store.get_phone("Test iPhone")["wifi_mode"] == "any"
    assert 'value="any" checked' in env.request("GET", "/settings/phones")[2].decode()


# ---- a Wi-Fi without the Mac: the first try waits, the rest of that 15-minute slot do not ------------------------------

def test_an_unanswered_try_blocks_that_network_until_the_slot_is_over(env):
    from fakephone import CouldNotConnect

    _, key = env.mac.store.add_phone("P")
    phone = Phone(env.mac, key)
    phone.no_home = True
    phone.reachable = False
    with pytest.raises(CouldNotConnect):
        phone.run(REELS[0], network="other")             # the one slow failure: iOS times out, the share is queued
    assert phone.waiting() == 1 and phone.try_file.startswith("Cafe")
    msg = phone.run(REELS[1], network="other")           # the same Wi-Fi, a moment later: no request, a clear message
    assert "wasn't reachable on this Wi-Fi" in msg and phone.waiting() == 2
    phone.reachable = True                               # the Mac arrives on that Wi-Fi, but the phone cannot know
    assert "wasn't reachable" in phone.run(REELS[2], network="other") and len(env.mac.store.items()) == 0
    assert phone.run(REELS[3], network="home") == "Saved 4 items to Magpiary ✅"  # another network: it tries, everything goes
    assert len(env.mac.store.items()) == 4


def test_the_block_ends_with_its_15_minute_slot_and_send_now_ignores_it(env):
    from fakephone import CouldNotConnect

    _, key = env.mac.store.add_phone("P")
    phone = Phone(env.mac, key)
    phone.no_home = True
    phone.reachable = False
    env.clock.t = env.clock.t.replace(minute=1)
    with pytest.raises(CouldNotConnect):
        phone.run(REELS[0], network="other")
    phone.reachable = True
    assert "wasn't reachable" in phone.run(REELS[1], network="other")
    assert "Saved 2 items" in phone.run("", network="other")          # Send now: tries whatever the note says, and succeeds
    assert len(env.mac.store.items()) == 2 and phone.try_file == " "
    phone.reachable = False
    env.clock.t = env.clock.t.replace(minute=2)
    with pytest.raises(CouldNotConnect):
        phone.run(REELS[2], network="other")
    env.clock.advance(900)                                           # the next slot
    phone.reachable = True
    assert phone.run(REELS[3], network="other") == "Saved 2 items to Magpiary ✅"   # the waiting one and this one


def test_a_phone_is_paired_with_its_retry_wait_and_the_shortcut_carries_it(env):
    status, headers, _ = env.post("/hub/phones/add", name="Slow iPhone", retry_wait="30", next="/settings/phones")
    assert status == 303 and env.mac.store.get_phone("Slow iPhone")["retry_wait"] == 30
    token = env.token_from(headers["Location"])
    wf = plistlib.loads(env.shortcut_for(token)[2])
    finds = [a["WFWorkflowActionParameters"]["WFReplaceTextFind"] for a in wf["WFWorkflowActions"]
             if a["WFWorkflowActionIdentifier"].endswith("text.replace")]  # (some are token strings, which never equal these)
    assert "[0-2][0-9]$" in finds and "[3-5][0-9]$" in finds       # 30-minute slots
    page = env.request("GET", "/settings/phones")[2].decode()
    assert '<option value="30" selected>30 minutes</option>' in page and "Advanced" in page
    # a new install code keeps the choice
    renewed = env.setup.renew("Slow iPhone")
    wf2 = plistlib.loads(env.shortcut_for(re.search(r"t=([A-Za-z0-9_-]+)", renewed).group(1))[2])
    assert any(a["WFWorkflowActionParameters"].get("WFReplaceTextFind") == "[3-5][0-9]$" for a in wf2["WFWorkflowActions"])


def test_the_default_wait_is_fifteen_minutes_and_odd_values_are_ignored(env):
    env.post("/hub/phones/add", name="A", next="/settings/phones")
    env.post("/hub/phones/add", name="B", retry_wait="7", next="/settings/phones")
    assert env.mac.store.get_phone("A")["retry_wait"] == 15 and env.mac.store.get_phone("B")["retry_wait"] == 15


def test_the_welcome_pairing_step_warns_before_the_phone_does_when_signing_will_fail(env, capsys):
    env.signer_fails = True
    env.mac.setup.check_signing(wait=True)
    assert env.mac.setup.signing_state() == "error"
    assert b"isn&#x27;t answering" in env.request("GET", "/welcome/phone")[2] or b"isn't answering" in env.request("GET", "/welcome/phone")[2]
    env.clock.advance(300)
    env.signer_fails = False
    env.mac.setup.check_signing(wait=True)
    assert env.mac.setup.signing_state() == "ok"
    assert b"answering" not in env.request("GET", "/welcome/phone")[2]


def test_an_icloud_reason_from_the_signer_gets_its_own_wording(env):
    env.mac.setup.signer = lambda workflow: (_ for _ in ()).throw(RuntimeError("shortcuts sign failed: you must be signed into iCloud"))
    env.mac.setup.check_signing(wait=True)
    assert env.mac.setup.signing_state() == "icloud"
    assert b"iCloud Drive" in env.request("GET", "/welcome/phone")[2]
    token = env.token_from(env.add_phone()[1])
    status, _, body = env.shortcut_for(token)
    assert status == 503 and b"iCloud Drive" in body



def test_the_welcome_key_form_has_a_guide_for_every_provider_and_shows_only_the_first(env):
    from magpiary import keys as keyring

    env.request("POST", "/hub/settings/mode", {"csrf": env.mac.server.hub.csrf, "mode": "smart", "next": "/welcome/reading"})
    body = env.request("GET", "/welcome/reading")[2].decode()
    for provider, info in keyring.PROVIDERS.items():
        if info["kind"] == "ai":
            assert f'class="guide2" data-provider="{provider}"' in body
    assert body.count('class="guide2"') == body.count('data-provider=') and "Get a free Gemini key" not in body
    assert 'data-provider="gemini">' in body.replace(' hidden', 'X') or 'data-provider="gemini"' in body
    assert 'data-provider="openrouter" hidden' in body


def test_settings_can_put_the_bundled_chrome_extension_in_a_folder_and_open_it(env, monkeypatch, tmp_path):
    import subprocess

    from magpiary import chrome_ext

    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path / "home"))
    opened = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: opened.append(cmd))
    assert b"Get the extension" in env.request("GET", "/settings/phones")[2]
    assert env.post("/hub/extension/get", next="/settings/phones")[0] == 303
    folder = chrome_ext.target()
    assert (folder / "manifest.json").exists() and (folder / "popup.html").exists()
    assert ["open", str(folder)] in opened and any("chrome://extensions" in c for c in opened)

