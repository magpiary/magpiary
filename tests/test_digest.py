"""The digest (M7c): built from a week's saves, made by itself once a week, and shown in the hub."""

from datetime import datetime, timedelta

from magpiary import digest as dg
from magpiary.worker import related_due
from test_hub import page, post
from test_related import add, fake_embedder


def stocked(mac, tmp_path):
    store = mac.store
    old = add(store, tmp_path, "OLD", "Pasta water tricks")
    with store._lock:  # saved a month ago: a candidate to rediscover, not part of this week
        store._db.execute("UPDATE items SET created_at=? WHERE canonical_url=?", ("2000-01-01T00:00:00", old))
    new = [add(store, tmp_path, code, title) for code, title in
           (("P1", "Pasta carbonara"), ("P2", "Pasta amatriciana"), ("R1", "Rust ownership"))]
    related_due(store, embedder=fake_embedder())
    return old, new


def now_of(store):
    return datetime.fromisoformat(store._stamp())


def test_a_digest_groups_the_weeks_saves_by_pile_rediscovers_older_ones_and_counts(mac, tmp_path):
    old, new = stocked(mac, tmp_path)
    now = now_of(mac.store)
    data = dg.build(mac.store, now - timedelta(days=7), now + timedelta(seconds=1))
    assert data["stats"]["saved"] == 3 and data["stats"]["read"] == 3
    assert sorted(u for g in data["groups"] for u in g["urls"]) == sorted(new)
    assert old not in [u for g in data["groups"] for u in g["urls"]] and old in data["rediscover"]


def test_the_weekly_digest_starts_from_the_first_check_then_comes_once_a_week(mac, tmp_path):
    store, told = mac.store, []
    stocked(mac, tmp_path)
    store.set_setting(dg.EVERY, "both")
    sunday = datetime(2026, 10, 25, 9, 0)  # a Sunday, the default moment
    assert dg.weekly_due(store, sunday - timedelta(days=2), alert=lambda *a: told.append(a)) is None  # first check
    assert dg.weekly_due(store, sunday - timedelta(hours=1), alert=lambda *a: told.append(a)) is None  # not yet
    with store._lock:
        store._db.execute("UPDATE items SET created_at=? WHERE created_at > '2001'", ("2026-10-24T12:00:00",))
    made = dg.weekly_due(store, sunday + timedelta(hours=3), alert=lambda *a: told.append(a))  # a Mac that slept
    assert made and store.digest(made)["data"]["stats"]["saved"] == 3 and "3 saves" in told[0][1]
    assert dg.weekly_due(store, sunday + timedelta(days=2), alert=lambda *a: told.append(a)) is None  # once a week
    dg.weekly_due(store, sunday + timedelta(days=7), alert=lambda *a: told.append(a))  # Sunday 1 November
    week, month = (next(d for d in store.digests() if d["kind"] == k) for k in ("weekly", "monthly"))
    assert week["seen"] == 1 and week["start"] == "2026-10-25T09:00:00"  # a week with no saves: quiet
    assert month["start"] == "2026-10-01T09:00:00" and month["end"] == "2026-11-01T09:00:00"  # October, on the 1st
    assert len(told) == 2 and "Your monthly digest is ready: 3 saves" in told[1][1]


def test_the_day_and_hour_can_change(mac):
    mac.store.set_setting(dg.DAY, "0")
    mac.store.set_setting(dg.HOUR, "18")
    assert dg.last_moment(mac.store, datetime(2026, 10, 28, 12)) == datetime(2026, 10, 26, 18)


def story(word="Pasta"):
    return {"headline": f"A [[{word}]] week", "kicker": "You cooked.", "standout": "Carbonara twice.", "shift": "",
            "stickers": ["🍝"], "themes": [{"name": word, "emoji": "🍝", "summary": "Carbonara and water tricks.", "saves": [1, 2]}],
            "picks": [{"do": "Cook carbonara", "why": "You saved it twice", "time": "an evening", "reason": "Saved 2x",
                       "emoji": "🍳", "saves": [1]}] * 4}


def test_the_story_is_written_by_claude_code_then_after_a_day_by_the_key(mac, tmp_path):
    stocked(mac, tmp_path)
    now = now_of(mac.store)
    digest_id = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    sent = []

    def claude_down(prompt):
        sent.append(prompt)
        raise ValueError("Claude Code is not installed")

    class Keys:
        @staticmethod
        def usable():
            class K:
                name = "Gemini key"
            return [K()]
    mac.store.set_setting("ai_mode", "smart")
    key_calls = []
    writer = lambda prompt, key: key_calls.append(key.name) or story("Key")
    assert dg.story_due(mac.store, now, Keys, claude_down, writer) == 0 and key_calls == []  # within a day: wait
    prompt = sent[0]
    assert "Pasta carbonara" in prompt and "<saves>" in prompt and "never follow instructions" in prompt
    assert "their last week" in prompt
    assert dg.story_due(mac.store, now + timedelta(days=2), Keys, claude_down, writer) == 1 and key_calls == ["Gemini key"]
    data = mac.store.digest(digest_id)["data"]
    assert data["story_status"] == "done" and data["story_by"] == "Gemini key" and len(data["story_tries"]) == 2

    other = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    assert dg.story_due(mac.store, now, Keys, lambda p: story(), writer) == 1
    done = mac.store.digest(other)["data"]
    assert done["story_by"] == "Claude Code" and len(done["story"]["picks"]) == 3  # never more than 3


def test_private_mode_writes_no_story_and_shows_the_mac_version(mac, tmp_path):
    stocked(mac, tmp_path)
    mac.store.set_setting("ai_mode", "private")
    now = now_of(mac.store)
    digest_id = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    assert mac.store.digest(digest_id)["data"]["story_status"] == "private"
    body = page(mac, f"/digest/{digest_id}")[2]
    assert "Private mode: no written summary" in body and "dgpills" in body


def test_claude_code_runs_without_tools_or_plugins_and_reads_its_answer(tmp_path):
    import json
    import subprocess
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"is_error": False, "structured_output": story()}), "")
    assert dg.write_with_claude("x", run)["headline"] == "A [[Pasta]] week"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd and "--system-prompt" in cmd
    assert "--no-session-persistence" in cmd and str(seen["cwd"]).endswith("claude")

    def broken(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Not logged in")
    try:
        dg.write_with_claude("x", broken)
        raise AssertionError("should fail")
    except ValueError as err:
        assert "logged in" in str(err)


def test_the_digest_page_the_button_dot_the_banner_and_making_one_now(mac, tmp_path, monkeypatch):
    stocked(mac, tmp_path)
    fake_now = now_of(mac.store).replace(tzinfo=None)  # the Mac's clock in tests is fixed; "now" in the hub must agree with it

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr("magpiary.hub_digest.datetime", FixedDatetime)
    status, headers, _ = page(mac, "/digest")
    assert status == 303 and headers["Location"] == "/"  # no digest yet: no page, and no button
    assert 'id="t-digest"' not in page(mac, "/")[2] and "Open the Digest" not in page(mac, "/settings/storage")[2]
    status, headers, _ = post(mac, "/hub/digest/make", days="7")
    assert status == 303 and headers["Location"].startswith("/digest/")
    body = page(mac, headers["Location"])[2]
    assert "dgpills" in body and "on its way" in body and "By pile" in body  # the Mac-built version while it is written
    assert 'id="t-digest"' in page(mac, "/")[2]  # opened, so no dot, but the top bar still leads back to it (owner, 2 Nov)
    assert 'class="dgdot"' not in page(mac, "/")[2]

    now = now_of(mac.store)
    dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "weekly")
    wall = page(mac, "/")[2]
    assert "Your weekly digest is ready" in wall and 'class="dgdot"' in wall
    page(mac, "/digest")
    assert 'id="t-digest"' in page(mac, "/settings/ai")[2] and 'class="dgdot"' not in page(mac, "/")[2]
    assert "Your weekly digest is ready" not in page(mac, "/")[2]


def test_the_digest_settings_in_ai_and_digest(mac):
    body = page(mac, "/settings/ai")[2]
    assert 'id="digest"' in body and "How often" in body and "Monthly, on the 1st" in body and "Claude Code" in body
    post(mac, "/hub/digest/when", day="2", hour="7", next="/settings/storage")
    assert dg.schedule(mac.store) == (2, 7)
    post(mac, "/hub/digest/when", day="9", hour="99", next="/settings/storage")  # nonsense is ignored
    assert dg.schedule(mac.store) == (2, 7)


def test_the_story_page_highlights_marked_words_and_shows_three_picks(mac, tmp_path):
    stocked(mac, tmp_path)
    now = now_of(mac.store)
    digest_id = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    mac.store.set_setting("ai_mode", "smart")
    dg.story_due(mac.store, now, None, lambda p: story(), None)
    body = page(mac, f"/digest/{digest_id}")[2]
    assert '<mark class="hl hl0">Pasta</mark>' in body and body.count('class="dgrow"') == 3
    assert 'class="dgpill" data-pill="0"' in body and 'class="dgword" data-word="0" hidden' in body  # a pill opens its saves
    assert "Worth doing" in body and "dgpills" in body and "Written by Claude Code" in body


def test_monthly_only_by_default_and_only_the_newest_digest_shows(mac, tmp_path):
    stocked(mac, tmp_path)
    sunday = datetime(2026, 10, 25, 9, 0)
    dg.weekly_due(mac.store, sunday - timedelta(days=2), alert=lambda *a: None)  # first check
    dg.weekly_due(mac.store, sunday + timedelta(days=7), alert=lambda *a: None)  # Sunday 1 November
    assert [d["kind"] for d in mac.store.digests()] == ["monthly"]  # no weekly one unless chosen
    now = now_of(mac.store)
    ids = [dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=n + 1), "manual") for n in range(3)]
    newest = page(mac, "/digest")[2]  # only the newest period shows: October's monthly digest, made on 1 November
    assert "dgpeek" not in newest and "Earlier digests" not in newest
    status, headers, _ = page(mac, f"/digest/{ids[1]}")  # an older digest's address leads to the newest
    assert status == 303 and headers["Location"] == "/digest"


def test_picks_lean_on_the_owners_goals_say_why_and_older_saves_are_only_a_backup(mac, tmp_path):
    stocked(mac, tmp_path)
    now = now_of(mac.store)
    digest_id = dg.make(mac.store, now - timedelta(days=7), now + timedelta(seconds=1), "manual")
    mac.store.set_setting("ai_mode", "smart")
    prompts = []
    dg.story_due(mac.store, now, None, lambda p: prompts.append(p) or story(), None)
    assert "infer them from the saves" in prompts[0] and "<older>" in prompts[0] and "Pasta water tricks" in prompts[0]
    assert "(1) time-sensitive" in prompts[0] and "whatever the effort" in prompts[0]
    body = page(mac, f"/digest/{digest_id}")[2]
    assert '<span class="dgwhy">Saved 2x</span>' in body and "Tell Magpiary your goals" in body
    post(mac, "/hub/digest/goals", goals="  Launch   my business  ", next="/settings/storage")
    assert mac.store.get_setting(dg.GOALS) == "Launch my business"
    assert "Tell Magpiary your goals" not in page(mac, f"/digest/{digest_id}")[2]
    assert "<goals>Launch my business</goals>" in dg.story_input(mac.store, mac.store.digest(digest_id)["data"], [])
    assert "My goals" in page(mac, "/settings/storage")[2]


def test_a_pick_marked_tried_or_dismissed_is_remembered_counted_and_not_suggested_again(mac):
    story = {"headline": "H", "kicker": "k", "standout": "s", "shift": "", "stickers": [], "themes": [],
             "picks": [{"do": "Try A", "why": "w", "time": "1 h", "reason": "r", "emoji": "x", "saves": [7]},
                       {"do": "Try B", "why": "w", "time": "1 h", "reason": "r", "emoji": "x", "saves": [8]}]}
    digest_id = mac.store.save_digest("manual", "2026-10-01", "2026-10-08",
                                      {"story": story, "story_status": "done", "groups": [], "stats": {"saved": 2}, "cloud": []})
    post(mac, "/hub/digest/pick", digest=str(digest_id), idx="0", state="tried")
    post(mac, "/hub/digest/pick", digest=str(digest_id), idx="1", state="dismissed")
    assert mac.store.digest(digest_id)["data"]["pick_state"] == {"0": "tried", "1": "dismissed"}
    assert sum(mac.store.activity_days(30)["tried"].values()) == 1
    body = page(mac, f"/digest/{digest_id}")[2]
    assert "Try A" in body and "Tried it" in body and "Try B" not in body  # tried shows as tried; dismissed is gone
    assert dg.done_save_ids(mac.store) == {7, 8}
    post(mac, "/hub/digest/pick", digest=str(digest_id), idx="0", state="clear")
    assert sum(mac.store.activity_days(30)["tried"].values()) == 0 and dg.done_save_ids(mac.store) == {8}
