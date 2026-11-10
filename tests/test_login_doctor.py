"""The opt-in Instagram login and `magpiary doctor`: recorded runs, no browser, no network."""

import stat
import subprocess
from pathlib import Path

import pytest

from magpiary import doctor, login
from magpiary.sources import FetchFailed
from magpiary.store import Store
from magpiary.tools import YtDlp
from magpiary.worker import _plain_failure, with_login
from test_hub import page, post, request

COOKIES = ("# Netscape HTTP Cookie File\n"
           ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tSECRET-IG\n"
           "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t2000000000\tcsrftoken\tCSRF\n"
           ".bank.example\tTRUE\t/\tTRUE\t2000000000\tsession\tSECRET-BANK\n")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


def fake_ytdlp(cookies_text=COOKIES, code=0, stderr=""):
    seen = []

    def run(command, timeout):
        seen.append(command)
        Path(command[command.index("--cookies") + 1]).write_text(cookies_text)
        return subprocess.CompletedProcess(command, code, "", stderr)
    return run, seen


def test_connect_keeps_only_the_instagram_login_in_a_private_file(store, monkeypatch):
    monkeypatch.setattr(login, "find", lambda name: "/bin/yt-dlp")
    run, seen = fake_ytdlp()
    assert login.connect(store, run=run) is None
    saved = login.login_path().read_text()
    assert "SECRET-IG" in saved and "csrftoken" in saved and "SECRET-BANK" not in saved
    assert stat.S_IMODE(login.login_path().stat().st_mode) == 0o600
    assert not (login.login_path().parent / "browser-cookies.tmp").exists()  # every site's cookies: gone
    assert "--use-extractors" in seen[0] and "chrome" in seen[0]  # no site is contacted
    assert login.connected(store)
    login.disconnect(store)
    assert not login.login_path().exists() and not login.connected(store)


def test_connect_explains_a_missing_login_or_a_refused_keychain(store, monkeypatch):
    monkeypatch.setattr(login, "find", lambda name: "/bin/yt-dlp")
    assert "Log in to instagram.com in Chrome" in login.connect(store, run=fake_ytdlp("# Netscape HTTP Cookie File\n")[0])
    refused = fake_ytdlp("# Netscape HTTP Cookie File\n", 1, "ERROR: cannot read keychain")[0]
    assert "choose Allow" in login.connect(store, run=refused)
    assert not login.login_path().exists()


def test_the_login_is_used_only_for_items_the_owner_allowed(store, monkeypatch):
    plain = YtDlp(run=lambda c, t: None, binary="/bin/yt-dlp")
    assert with_login(plain) is plain  # not connected: nothing changes
    monkeypatch.setattr(login, "find", lambda name: "/bin/yt-dlp")
    login.connect(store, run=fake_ytdlp()[0])
    used = with_login(plain)
    assert "--cookies" in used._base() and "--cookies" not in plain._base()

    url = "https://www.instagram.com/reel/AGE1/"
    store.add_link(url)
    store.fetch_failed(url, "login_wall", "x", retry=False)
    assert store.try_with_login(store.id_for(url))
    item = store.get_item(url)
    assert item["use_login"] == 1 and item["status"] == "queued"


def test_an_empty_answer_three_times_means_the_post_needs_a_login():
    err = FetchFailed("rate_limited", "Instagram sent an empty media response. Check if this post is accessible")
    assert _plain_failure(err, {"attempts": 0}, False)[0] == "rate_limited"  # often short-lived (S1)
    reason, detail, retry = _plain_failure(err, {"attempts": 2}, False)
    assert reason == "login_wall" and "age limit" in detail and retry is False
    assert "connect Instagram again" in _plain_failure(err, {"attempts": 0}, True)[1]


def test_the_doctor_checks_offline_and_live_without_secrets(store):
    url = "https://www.instagram.com/reel/OK1/"
    store.add_link(url)
    store.fetch_succeeded(url, "/tmp/nowhere")
    checks = doctor.offline(store, ping=lambda port: False)
    service = next(c for c in checks if c.name == "Background service")
    assert service.state == doctor.FAIL and "service install" in service.fix
    assert next(c for c in checks if c.name == "Database").detail.startswith("1 saves")

    def describe(source, link):
        if source == "instagram":
            raise FetchFailed("login_wall", "login required")
    results = doctor.live(store, describe=describe, call=lambda *a: (200, {}), pause=lambda s: None)
    ig = next(c for c in results if c.name == "Instagram")
    assert ig.state == doctor.FAIL and "wants a login" in ig.detail
    assert next(c for c in results if c.name == "YouTube").detail.startswith("No saved post")
    text = doctor.report(checks + results)
    assert "✗ Instagram" in text and "problem(s)" in text


def test_the_hub_has_the_login_panel_the_item_button_and_the_doctor_page(mac):
    body = page(mac, "/settings/ai")[2] + page(mac, "/settings/storage")[2]
    assert "Instagram login" in body and "data-login-connect" in body and "Connect Instagram" in body and "login connect" in body and "/doctor" in body
    url = "https://www.instagram.com/reel/AGE2/"
    mac.store.add_link(url)
    mac.store.fetch_failed(url, "login_wall", "x", retry=False)
    item = page(mac, f"/item/{mac.store.id_for(url)}")[2]
    assert "Connect Instagram to try with your login" in item
    status, _, data = request(mac, "GET", "/doctor")
    assert status == 200 and b"Health check" in data and b"Also test each site" in data
    status, headers, _ = post(mac, "/hub/login/disconnect", next="/settings#instagram")
    assert status == 303


def test_a_login_only_failure_offers_three_choices_and_keeping_it_leaves_needs_attention(mac):
    url = "https://www.instagram.com/reel/AGE3/"
    mac.store.add_link(url)
    mac.store.fetch_failed(url, "login_wall", "x", retry=False)
    item_id = mac.store.id_for(url)
    body = page(mac, f"/item/{item_id}")[2]
    assert "Keep it as a link" in body and "Archive it" in body and "shows this post only to logged-in people" in body
    assert mac.store.problems() and post(mac, "/hub/keep-link", id=str(item_id), next="/")[0] == 303
    assert not any(p["canonical_url"] == url for p in mac.store.problems())
    assert "Kept as a link" in page(mac, f"/item/{item_id}")[2]


def test_a_login_can_be_kept_per_site_and_is_used_only_for_that_site(store, monkeypatch):
    monkeypatch.setattr(login, "find", lambda name: "/bin/yt-dlp")
    cookies = ("# Netscape HTTP Cookie File\n.behance.net\tTRUE\t/\tTRUE\t2000000000\tsid\tSECRET-BE\n"
               ".bank.example\tTRUE\t/\tTRUE\t2000000000\tsession\tSECRET-BANK\n")
    run, seen = fake_ytdlp(cookies)
    assert login.connect(store, run=run, domain="behance.net") is None
    path = login.login_path("behance.net")
    assert path.parent.name == "logins" and "SECRET-BE" in path.read_text() and "SECRET-BANK" not in path.read_text()
    assert login.connected(store, "behance.net") and not login.connected(store)  # Instagram is not connected
    assert login.cookie_header("behance.net") == "sid=SECRET-BE" and login.cookie_header("instagram.com") == ""
    assert seen[0][-1] == "https://www.behance.net/"
    assert "No example.org login" in login.connect(store, run=fake_ytdlp(cookies)[0], domain="example.org")
    assert "not a site name" in login.connect(store, run=run, domain="../etc")
    login.disconnect(store, "behance.net")
    assert not path.exists() and not login.connected(store, "behance.net")


def test_site_of_cuts_a_link_to_the_site_a_login_belongs_to():
    assert login.site_of("https://www.behance.net/gallery/1/x") == "behance.net"
    assert login.site_of("https://news.bbc.co.uk/a") == "bbc.co.uk" and login.site_of("https://m.example.com/") == "example.com"


def test_the_retry_with_my_login_button_is_offered_on_any_site_that_refuses(mac, monkeypatch):
    url = "https://www.behance.net/gallery/1/Thing"
    mac.store.add_link(url)
    mac.store.fetch_failed(url, "login_wall", "HTTP 403", retry=False)
    item_id = mac.store.id_for(url)
    body = page(mac, f"/item/{item_id}")[2]
    assert "Retry with my login" in body and "data-login-connect" in body and "login connect behance.net" in body and "behance.net refused a visit without a login" in body
    assert "Instagram" not in body.split("Couldn")[1].split("</div></div>")[0]  # nothing Instagram-specific on a Behance post
    monkeypatch.setattr(login, "connected", lambda s, d=login.DEFAULT: "2026-11-02")
    body = page(mac, f"/item/{item_id}")[2]
    assert 'action="/hub/try-login"' in body and "Retry with my login" in body and "login connect behance.net" not in body


def test_terminal_command_names_the_bundled_program_by_full_path(monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    assert login.terminal_command() == "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary login connect"
    assert login.terminal_command("behance.net").endswith("login connect behance.net")
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Apps/x y/Magpiary.app/magpiary")  # a space in the path must stay one word
    assert login.terminal_command().startswith("'/Apps/x y/Magpiary.app/magpiary' login connect")


def test_connect_button_route_copies_the_login_and_never_returns_cookies(mac, monkeypatch):
    run, _ = fake_ytdlp()
    monkeypatch.setattr(login, "find", lambda name: "/bin/yt-dlp")
    real = login.connect
    monkeypatch.setattr(login, "connect", lambda store, domain="instagram.com": real(store, run=run, domain=domain))
    status, _, data = post(mac, "/hub/login/connect")
    assert status == 200 and b"SECRET" not in data
    import json
    assert json.loads(data) == {"ok": True, "error": "", "terminal": False}
    assert login.connected(mac.store)


def test_connect_button_route_offers_terminal_when_macos_refuses(mac, monkeypatch):
    monkeypatch.setattr(login, "connect", lambda store, domain="instagram.com": "macOS did not allow Magpiary to read Chrome's data. Press “Open Terminal for me”.")
    import json
    body = json.loads(post(mac, "/hub/login/connect")[2])
    assert body["ok"] is False and body["terminal"] is True and "Open Terminal" in body["error"]
    assert json.loads(post(mac, "/hub/login/connect", site="not a site")[2])["ok"] is False


def test_open_in_terminal_writes_a_command_script_with_no_secrets(store, tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    opened = []
    err = login.open_in_terminal(run=lambda c, t: opened.append(c) or subprocess.CompletedProcess(c, 0, "", ""))
    assert err is None and opened[0][:3] == ["/usr/bin/open", "-a", "Terminal"]
    script = Path(opened[0][3])
    assert script.read_text().count("login connect") >= 1 and stat.S_IMODE(script.stat().st_mode) == 0o700
    assert login.open_in_terminal(run=lambda c, t: subprocess.CompletedProcess(c, 1, "", "")) == "Could not open Terminal."


def test_terminal_script_keeps_custom_folders(store, monkeypatch, tmp_path):
    monkeypatch.setenv("MAGPIARY_HOME", "/tmp/my lib")
    ran = []
    monkeypatch.setattr(login, "config_dir", lambda: tmp_path)
    assert login.open_in_terminal(run=lambda a, t=0: ran.append(a) or subprocess.CompletedProcess(a, 0, "", "")) is None
    assert "export MAGPIARY_HOME='/tmp/my lib'" in (tmp_path / "connect-login.command").read_text()
