"""The settings redesign: Advanced blocks, search, the Claude Code controls, the health check as it runs."""

import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import unquote

from magpiary import claude_code, doctor
from magpiary import digest as dg
from magpiary.web import e
from test_digest import now_of, stocked, story
from test_hub import page, post, request


def fake_run(answers):
    """A stand-in for subprocess.run: answers by the claude sub-command."""
    def run(cmd, **kw):
        key = "version" if "--version" in cmd else "auth" if "auth" in cmd else "prompt"
        out = answers[key]
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(returncode=out[0], stdout=out[1], stderr=out[2] if len(out) > 2 else "")
    return run


def test_every_page_with_technical_settings_ends_in_a_folded_advanced_block(mac):
    for path in ("ai", "storage", "boards", "profile", "privacy"):  # (Phones keeps its Advanced inside each phone)
        body = page(mac, f"/settings/{path}")[2]
        assert 'class="adv" id="advanced" data-adv' in body, path
        assert body.index("Advanced settings") > body.index("sgroup"), path
    assert 'class="adv"' not in page(mac, "/settings/appearance")[2]  # everything there stays visible


def test_what_moved_into_advanced_is_inside_it_and_the_rest_is_outside(mac):
    for path, inside, outside in (("storage", "Removing Magpiary", "Your library"),
                                  ("boards", "Where boards sync", "Your boards"), ("profile", "Your identity", "Your public face"),
                                  ("privacy", "Where your data lives", "What leaves this Mac"),
                                  ("ai", "Pause summaries", "AI keys")):
        body = page(mac, f"/settings/{path}")[2].split('id="setpane"')[1]  # (the page list's search box carries every title)
        cut = body.index('class="adv"')
        assert inside in body[cut:] and inside not in body[:cut].replace("Advanced settings", ""), (path, inside)
        assert outside in body[:cut], (path, outside)


def test_the_links_page_is_gone_and_its_settings_moved(mac):
    status, headers, _ = page(mac, "/settings/links")
    assert status == 303 and headers["Location"] == "/settings/ai#search"
    assert "Add a search key" in page(mac, "/settings/ai")[2].split('id="search"')[1]
    assert 'id="instagram"' in page(mac, "/settings/phones")[2] and 'href="/settings/links"' not in page(mac, "/settings/ai")[2]


def test_the_list_is_grouped_in_the_agreed_order_and_opens_where_a_look_is_needed(mac):
    body = page(mac, "/settings/ai")[2]
    nav = body[body.index('class="setnav"'):body.index('class="setpane"')]
    order = [nav.index(f'href="/settings/{k}"') for k in ("profile", "phones", "ai", "ask", "agents", "boards", "appearance", "storage", "privacy")]
    assert order == sorted(order)
    assert nav.index(">You<") < order[0] < nav.index(">Using Magpiary<") < order[1] and order[5] < nav.index(">This hub<") < order[6]
    assert "Your phones" in page(mac, "/settings")[2]  # no phone yet: Settings opens there
    mac.store.add_phone("Work iPhone")
    mac.store.set_setting("ai_mode", "private")
    assert "How summaries are made" in page(mac, "/settings")[2]  # nothing needs a look: AI & digest


def test_goals_live_in_the_profile_marked_private_and_every_ai_can_read_them(mac):
    from magpiary import ask_open, library

    body = page(mac, "/settings/profile")[2]
    assert 'id="goals"' in body and "never shared with friends" in body and "never go to a board" in body
    post(mac, "/hub/digest/goals", goals="Learn to bake", next="/settings/profile#goals")
    assert "Learn to bake" in page(mac, "/settings/ai")[2].split('id="digest"')[1]
    assert "Learn to bake" in ask_open.build_prompt("q", [], [], "your library", goals="Learn to bake")
    assert "data, not instructions" in ask_open.goals_note("Learn to bake") and ask_open.goals_note("  ") == ""
    assert library.status(mac.store)["goals"] == "Learn to bake"
    from magpiary import identity
    assert "Learn to bake" not in str(identity.profile(mac.store))


def test_the_profile_says_when_nobody_can_see_the_card(mac):
    assert "so nobody sees it" in page(mac, "/settings/profile")[2]


def test_goals_sit_just_above_topics_and_the_proxy_field_is_our_own(mac):
    body = page(mac, "/settings/profile")[2].split('id="setpane"')[1]
    assert body.index('id="links"') < body.index('id="goals"') < body.index('id="topics"')
    assert 'class="proxyline"' in page(mac, "/settings/storage")[2]


def test_the_digest_can_be_turned_off(mac, tmp_path):
    stocked(mac, tmp_path)
    post(mac, "/hub/digest/when", every="off", next="/settings/ai#digest")
    assert 'value="off" checked' in page(mac, "/settings/ai")[2]
    later = now_of(mac.store) + timedelta(days=60)
    assert dg.weekly_due(mac.store, later, None, alert=lambda *a: None) is None


def test_back_up_now_makes_a_whole_private_copy(mac):
    import sqlite3

    status, headers, _ = post(mac, "/hub/backup")
    assert status == 303 and "Backed+up" in headers["Location"].replace("%20", "+")
    copies = list(mac.server.hub._folders()["backups"].glob("magpiary-*.db"))
    assert len(copies) == 1 and copies[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(copies[0]) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "Last one:" in page(mac, "/settings/storage")[2]


def test_check_now_says_what_it_found_even_with_the_daily_check_off(mac, monkeypatch):
    from urllib.parse import unquote

    from magpiary import update

    post(mac, "/hub/versioncheck", enabled="0", next="/settings/storage")
    for answer, words in (((200, b'{"tag_name": "v99.0.0"}'), "Version 99.0.0 is available."), ((200, b'{"tag_name": "v0.0.1"}'), "up to date"),
                          ((404, b""), "Couldn't get an answer")):
        monkeypatch.setattr(update, "_get", lambda url, a=answer: a)
        status, headers, _ = post(mac, "/hub/versioncheck/now")
        assert status == 303 and words in unquote(headers["Location"]), words
    assert mac.store.get_setting(update.LATEST_SETTING) == "0.0.1"


def test_the_version_check_can_be_turned_off(mac):
    from magpiary import update

    asked = []
    def get(url):
        asked.append(url)
        return 200, b'{"tag_name": "v99.0"}'
    post(mac, "/hub/versioncheck", enabled="0", next="/settings/storage")
    update.check_daily(mac.store, get, "2026-11-01")
    assert not asked
    check = page(mac, "/settings/privacy")[2].split("Version check")[1].split("</div></div>")[0]
    assert ">Off<" in check
    post(mac, "/hub/versioncheck", enabled="1", next="/settings/storage")
    update.check_daily(mac.store, get, "2026-11-01")
    assert len(asked) == 1


def test_digest_schedule_uses_pills_and_goals_a_full_width_box(mac):
    body = page(mac, "/settings/ai")[2]
    assert 'class="pillbar"' in body and 'name="every" value="monthly" checked' in body and 'data-autosubmit' in body
    assert body.count('name="day"') == 7 and '<select name="hour"' in body
    assert 'class="goalform"' in page(mac, "/settings/profile")[2] and "<textarea" in page(mac, "/settings/profile")[2]


def test_the_profile_keeps_links_and_topics_outside_and_the_key_has_copy_and_finder(mac):
    body = page(mac, "/settings/profile")[2].split('id="setpane"')[1]
    cut = body.index('class="adv"')
    assert 'id="links"' in body[:cut] and 'id="topics"' in body[:cut] and 'id="identity"' in body[cut:]
    assert 'data-copy="' in body[cut:] and "Show in Finder" in body[cut:]


def test_keep_awake_and_health_check_and_the_digest_stay_visible(mac):
    here = page(mac, "/settings/storage")[2].split('class="adv"')[0]
    assert "Keep awake while plugged in" in here and "data-health" in here and 'id="trash"' in here
    assert 'id="versioncheck"' in here and "/hub/versioncheck/now" in here
    assert "Digest" in page(mac, "/settings/ai")[2].split('class="adv"')[0]


def test_the_privacy_page_shows_the_journey_and_everything_else_that_can_leave(mac):
    body = page(mac, "/settings/privacy")[2]
    leaves = body[body.index('id="leaves"'):body.index('class="adv"')]
    assert leaves.index("Stays on this Mac") < leaves.index("Opening a post") and "Never leaves" in leaves
    for word in ("Finding links", "Summaries", "Ask Magpiary", "Your digest", "your goals", "Shared boards", "AI agents", "Version check"):
        assert word in leaves, word
    assert 'id="extras"' not in body and "journey" not in leaves
    assert 'id="notes"' not in body and "Privacy notes" not in body.split('id="setpane"')[1]


def test_the_search_index_covers_every_page_and_every_anchor_exists(mac):
    from magpiary.hub_settings import SEARCH_INDEX
    pages = {}
    mac.store.set_setting("ask_state", "on")  # the Ask page shows all its groups only when Ask is on
    for _, _, p, a in SEARCH_INDEX:
        body = pages.setdefault(p, page(mac, f"/settings/{p}")[2])
        assert f'id="{a}"' in body, (p, a)
    assert set(pages) == {"profile", "ai", "ask", "agents", "phones", "storage", "boards", "appearance", "privacy"}
    assert "data-setsearch" in page(mac, "/settings/ai")[2]


def test_a_phone_keeps_its_wifi_mode_and_wait_inside_its_own_advanced(mac):
    mac.store.add_phone("Work iPhone", "Example Net")
    body = page(mac, "/settings/phones")[2]
    row = body[body.index("Work iPhone"):]
    assert "padv" in row and "After a failed try, wait" in row and "Where it sends" in row and "Example Net" in row
    status, headers, _ = post(mac, "/hub/phones/wait", name="Work iPhone", retry_wait="30")
    assert status == 303 and mac.store.get_phone("Work iPhone")["retry_wait"] == 30 and "install+code" in headers["Location"].replace("%20", "+")
    status, headers, _ = post(mac, "/hub/phones/wait", name="Work iPhone", retry_wait="7")
    assert mac.store.get_phone("Work iPhone")["retry_wait"] == 30  # not one of the allowed waits


# ---- Claude Code ----------------------------------------------------------------------------------------------

def test_the_free_checks_read_installed_signed_in_and_the_plan(monkeypatch):
    ok = fake_run({"version": (0, "2.1.299 (Claude Code)\n"), "auth": (0, json.dumps({"loggedIn": True, "subscriptionType": "pro"}))})
    assert claude_code.check(ok) == {"installed": True, "version": "2.1.299", "signed_in": True, "plan": "pro", "why": ""}
    out = fake_run({"version": (0, "2.1.299 (Claude Code)"), "auth": (0, json.dumps({"loggedIn": False}))})
    st = claude_code.check(out)
    assert st["signed_in"] is False and "sign in" in st["why"]
    missing = claude_code.check(fake_run({"version": FileNotFoundError()}))
    assert missing["installed"] is False and "isn't installed" in missing["why"]
    odd = claude_code.check(fake_run({"version": (0, "2.1 (Claude Code)"), "auth": (0, "not json")}))
    assert odd["signed_in"] is None and odd["why"]


def test_the_tiny_test_is_remembered_and_never_runs_by_itself(mac, tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path / "home"))
    assert claude_code.last_test(mac.store) is None
    result = claude_code.tiny_test(mac.store, fake_run({"prompt": (0, "ok")}))
    assert result["ok"] and claude_code.last_test(mac.store)["ok"]
    failed = claude_code.tiny_test(mac.store, fake_run({"prompt": (1, "", "Not logged in")}))
    assert not failed["ok"] and "Check that it is signed in" in failed["text"]


def test_use_mode_changes_who_writes_the_digest(mac, tmp_path):
    stocked(mac, tmp_path)
    mac.store.set_setting("ai_mode", "smart")
    now = now_of(mac.store)

    class Keys:
        @staticmethod
        def usable():
            return [SimpleNamespace(name="Gemini key")]
    calls = []
    claude = lambda p: calls.append("claude") or story("C")
    writer = lambda p, key: calls.append("key") or story("K")
    mac.store.set_setting(claude_code.USE, "key")
    d = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    assert dg.story_due(mac.store, now, Keys, claude, writer) == 1 and calls == ["key"]  # at once, Claude Code is not asked
    assert mac.store.digest(d)["data"]["story_by"] == "Gemini key"

    calls.clear()
    mac.store.set_setting(claude_code.USE, "only")
    down = lambda p: calls.append("claude") or (_ for _ in ()).throw(ValueError("down"))
    dg.make(mac.store, now - timedelta(days=8), now + timedelta(seconds=2), "manual")
    assert dg.story_due(mac.store, now + timedelta(days=5), Keys, down, writer) == 0 and "key" not in calls  # never the key

    calls.clear()
    mac.store.set_setting(claude_code.USE, "first")
    mac.store.set_setting(claude_code.WAIT, "6")
    assert dg.story_due(mac.store, now + timedelta(hours=7), Keys, down, writer) == 1 and calls == ["claude", "key"]  # the owner's 6 hours


def test_a_digest_written_by_claude_code_records_when(mac, tmp_path):
    stocked(mac, tmp_path)
    mac.store.set_setting("ai_mode", "smart")
    now = now_of(mac.store)
    d = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    dg.story_due(mac.store, now, None, lambda p: story(), None)
    assert mac.store.digest(d)["data"]["story_at"] == now.isoformat(timespec="seconds")
    assert claude_code.last_run(mac.store)["ok"] == now.isoformat(timespec="seconds")


def test_settings_shows_the_group_saves_the_mode_and_disconnects(mac, tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(claude_code, "check", lambda run=None: {"installed": True, "version": "2.1.299", "signed_in": True, "plan": "pro", "why": ""})
    body = page(mac, "/settings/ai")[2]
    assert "Who writes it" in body and 'id="claude"' in body and "What uses it" not in body and "Version 2.1.299" in body and "Send a tiny test" in body
    assert "Claude Code first, then my key" in body and "My key only" in body
    status, headers, _ = post(mac, "/hub/claude/mode", use="only", wait="48")
    assert status == 303 and mac.store.get_setting(claude_code.USE, "") == "only" and mac.store.get_setting(claude_code.WAIT, "") == "48"
    post(mac, "/hub/claude/mode", use="nonsense", wait="5")
    assert claude_code.mode(mac.store) == "only" and claude_code.wait_hours(mac.store) == 48  # not allowed: ignored
    claude_code.folder().mkdir(parents=True)
    (claude_code.folder() / "x").write_text("1")
    status, headers, _ = post(mac, "/hub/claude/remove")
    assert claude_code.mode(mac.store) == "key" and not claude_code.folder().exists()
    assert "AI key writes the digest" in page(mac, "/settings/ai?saved=claudeoff")[2]


def test_the_digest_group_says_how_claude_code_stands(mac, monkeypatch):
    mac.store.set_setting("ai_mode", "smart")
    for state, text in (({"installed": False, "version": "", "signed_in": None, "plan": "", "why": "x"}, "isn't installed"),
                        ({"installed": True, "version": "1", "signed_in": False, "plan": "", "why": "x"}, "isn't signed in"),
                        ({"installed": True, "version": "1", "signed_in": True, "plan": "max", "why": ""}, "Written by Claude Code")):
        monkeypatch.setattr(claude_code, "check", lambda run=None, s=state: s)
        mac.server.hub._claude_cache = None
        assert text in page(mac, "/settings/ai")[2]


# ---- the health check as it runs ------------------------------------------------------------------------------

def test_the_health_check_streams_its_results_and_ends_with_a_summary(mac, monkeypatch):
    monkeypatch.setattr(claude_code, "check", lambda run=None: {"installed": False, "version": "", "signed_in": None, "plan": "", "why": "x"})
    assert request(mac, "GET", "/doctor.json")[0] == 404  # nothing run yet
    status, _, data = request(mac, "POST", "/hub/doctor", {"csrf": mac.server.hub.csrf})
    assert status == 200
    seen, since, last = [], 0, {}
    for _ in range(100):
        last = json.loads(request(mac, "GET", f"/doctor.json?since={since}")[2])
        seen += last["items"]
        since = last["next"]
        if last["done"]:
            break
        time.sleep(0.05)
    assert last["done"] and last["phase"] == "offline" and "problems" in last and "warnings" in last
    assert any(c["name"] == "Digest writer" and c["state"] == doctor.WARN for c in seen)
    assert {c["area"] for c in seen} >= {"Claude Code"}


def test_a_live_health_check_reports_each_site_as_it_finishes(mac, monkeypatch):
    monkeypatch.setattr(doctor, "live", lambda store, emit=None, **kw: [emit(doctor.Check("Sites", "Instagram", doctor.OK, "fine")) for _ in [0]])
    request(mac, "POST", "/hub/doctor", {"csrf": mac.server.hub.csrf, "live": "1"})
    for _ in range(100):
        j = json.loads(request(mac, "GET", "/doctor.json?since=0")[2])
        if j["done"]:
            break
        time.sleep(0.05)
    assert j["live"] and any(c["area"] == "Sites" for c in j["items"])


def test_round_three_menu_order_flat_folds_and_privacy_tags(mac):
    body = page(mac, "/settings/ai")[2]
    assert 'class="setnav"' in body
    form = body.split('class="addform"')[1].split('</form>')[0]
    assert form.index('id="provider"') < form.index("Get your") < form.index('id="key"') < form.index('id="addkey-adv"') < form.index("Check and save")
    assert '<details class="advmini" id="addkey-adv"><summary><span class="amt"><b>More options</b>' in form and "advpill" not in form
    phones = page(mac, "/settings/phones")[2]
    assert 'class="padv"' not in phones or '<summary><span class="amt"><b>More options</b>' in phones
    priv = page(mac, "/settings/privacy")[2]
    assert "Never leaves" in priv and 'class="seticon" style="--c:#5b5b66"' in priv
    assert 'class="srow dgrow"' not in page(mac, "/settings/ai")[2]


def test_switch_script_posts_form_encoded_because_the_hub_reads_no_multipart():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "src/magpiary/static/settings.js").read_text()
    assert "new URLSearchParams(data)" in js and "body: data," not in js


def test_settings_lists_what_magpiary_downloads_from_the_catalog(mac, monkeypatch):
    from magpiary import downloads

    monkeypatch.delenv("MAGPIARY_PROGRAM", raising=False)
    here = page(mac, "/settings/storage")[2].split('class="adv"')[0]
    assert 'id="downloads"' in here
    for entry in downloads.catalog():
        assert e(entry.name) in here and e(entry.source) in here and e(entry.url) in here
    assert downloads.human_size(downloads.total_bytes(downloads.catalog())) in here
    assert "Already inside the app" not in here and "checksum" not in here


def test_the_mac_app_also_says_what_is_already_inside_it(mac, monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/MacOS/magpiary")
    here = page(mac, "/settings/storage")[2]
    assert "Already inside the app" in here and "yt-dlp" in here and "checksum" in here


def test_the_ai_key_form_and_the_search_key_form_each_have_their_own_provider_menu_and_guides(mac):
    body = page(mac, "/settings/ai")[2]
    assert body.count('id="provider"') == 1 and body.count('id="search-provider"') == 1
    for provider in ("gemini", "openrouter", "claude", "openai", "tavily", "brave"):
        assert f'class="guide2" data-provider="{provider}"' in body
    assert "app.tavily.com" in body and "api-dashboard.search.brave.com" in body


def test_interface_size_defaults_to_automatic_and_can_be_chosen(mac):
    assert 'data-scale="auto"' in page(mac, "/settings/appearance")[2]
    assert 'id="scale"' in page(mac, "/settings/appearance")[2]
    post(mac, "/hub/ui", scale="85", next="/settings/appearance")
    assert 'data-scale="85"' in page(mac, "/")[2]
    post(mac, "/hub/ui", scale="999", next="/settings/appearance")  # not a choice: ignored
    assert 'data-scale="85"' in page(mac, "/")[2]


def test_restore_from_a_backup_puts_the_library_back_and_keeps_a_safety_copy(mac):
    mac.store.add_link("https://example.com/kept")
    post(mac, "/hub/backup")
    folder = mac.server.hub._folders()["backups"]
    backup = next(folder.glob("magpiary-*.db"))
    mac.store.add_link("https://example.com/added-later")
    assert mac.store.get_item("https://example.com/added-later")
    assert b"Restore from a backup" in page(mac, "/settings/storage")[2].encode() and backup.name in page(mac, "/settings/storage")[2]
    status, headers, _ = post(mac, "/hub/restore", file=backup.name)
    assert status == 303 and "Restored" in unquote(headers["Location"])
    assert mac.store.get_item("https://example.com/kept") and not mac.store.get_item("https://example.com/added-later")
    safety = next(folder.glob("before-restore-*.db"))  # what was there before, so the restore can be undone
    post(mac, "/hub/restore", file=safety.name)
    assert mac.store.get_item("https://example.com/added-later")


def test_restore_refuses_anything_that_is_not_a_sound_backup(mac):
    folder = mac.server.hub._folders()["backups"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "junk.db").write_text("this is not a database")
    mac.store.add_link("https://example.com/stays")
    status, headers, _ = post(mac, "/hub/restore", file="junk.db")
    assert status == 303 and "error=" in headers["Location"] and mac.store.get_item("https://example.com/stays")
    for bad in ("../magpiary.db", "/etc/passwd", "nope.db", ""):
        assert "error=" in post(mac, "/hub/restore", file=bad)[1]["Location"]
    assert mac.store.get_item("https://example.com/stays")


def test_deeper_dive_needs_a_local_engine_or_a_paid_key(mac, monkeypatch):
    from magpiary import engines

    body = page(mac, "/settings/ai")[2]
    assert 'id="deepdive"' in body and "Allow Claude Code or Codex" in body and 'action="/hub/deep/on"' not in body
    monkeypatch.setattr(engines, "installed", lambda kind: True)
    mac.store.set_setting(engines.ALLOWED, json.dumps(["claude_code"]))
    body = page(mac, "/settings/ai")[2]
    assert 'action="/hub/settings/long-video"' in body and 'action="/hub/deep/engine"' in body  # on by itself
    post(mac, "/hub/deep/on", enabled="0", next="/settings/ai")
    assert not engines.is_on(mac.store, "deep")


def test_long_videos_get_a_deeper_dive_suggested_after_the_minutes_set(mac):
    post(mac, "/hub/settings/long-video", minutes="45")
    assert mac.store.get_setting("long_video_minutes") == "45"
    post(mac, "/hub/settings/long-video", minutes="0")  # 0 reads every video straight away
    assert mac.store.get_setting("long_video_minutes") == "0"
    post(mac, "/hub/settings/long-video", minutes="-5")
    post(mac, "/hub/settings/long-video", minutes="9999")
    assert mac.store.get_setting("long_video_minutes") == "0"  # nonsense is ignored
