"""Settings → AI agents: the master switch (off until turned on), the three permissions, daily limits, hiding saves,
the activity log and the key. Writes are enforced by the hub, reads by the commands and the MCP server."""

import json

import pytest

from magpiary import agent_log, mcp_agent
from magpiary.config import config_dir, db_path
from test_agent_notes import YT, agents, hub, post_json, run, saved_id  # noqa: F401
from test_hub import page, post

OTHER = "https://www.youtube.com/watch?v=bbbbbbbbbbb"


def seed(mac, code, title, tags=()):
    phone, _ = mac.store.add_phone(f"Seed {code}")
    url = f"https://www.youtube.com/watch?v={code * 11}"
    mac.store.receive(phone, [{"id": f"seed-{code}", "url": url}])
    with mac.store._lock:
        mac.store._db.execute("UPDATE items SET ai_title=?, summary='A summary.', ai_status='done', status='archived' "
                              "WHERE canonical_url=?", (title, url))
        for tag in tags:
            mac.store._db.execute("INSERT INTO tags VALUES (?,?)", (url, tag))
    mac.store._reindex(url)
    return mac.store.id_for(url)


def switch(mac, on=True):
    mac.store.set_setting("agents_on", "1" if on else "0")


# ---- the master switch ----------------------------------------------------------------------------------------

def test_agents_are_off_until_the_owner_turns_them_on(mac, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))                       # no switch set: the default
    item = seed(mac, "c", "Sourdough starter")
    before = db_path().read_bytes()
    for argv in (["search", "sourdough"], ["list"], ["show", str(item)], ["status"]):
        code, out, err = run(capsys, mac, *argv)
        assert code == 1 and out == "" and "turned off" in err and "Settings → AI agents" in err, argv
    assert db_path().read_bytes() == before
    for argv in (["add", YT], ["note", str(item), "hello"]):
        code, _, err = run(capsys, mac, *argv)
        assert code == 1 and "turned off" in err, argv
    assert mac.store.id_for(YT) is None and mac.store.item_by_id(item)["agent_note"] == ""
    text, bad = mcp_agent.call("magpiary_search", {"query": "sourdough"})
    assert bad and "turned off" in text


def test_the_settings_switch_turns_them_on_and_off(hub, capsys):
    item = seed(hub, "a", "Sourdough starter")
    switch(hub, False)
    assert run(capsys, hub, "search", "sourdough")[0] == 1
    assert post(hub, "/hub/agents/on", enabled="1", next="/settings/agents")[0] == 303
    assert run(capsys, hub, "search", "sourdough", "--words-only")[0] == 0
    post(hub, "/hub/agents/on", enabled="0", next="/settings/agents")
    assert run(capsys, hub, "show", str(item))[0] == 1
    assert run(capsys, hub, "add", YT)[0] == 1


# ---- the three permissions ------------------------------------------------------------------------------------

@pytest.mark.parametrize("which,blocked,allowed", [
    ("read", ["search", "sourdough"], ["add", YT]),
    ("add", ["add", YT], ["search", "sourdough", "--words-only"]),
    ("note", ["note", "{id}", "hi"], ["add", YT]),
])
def test_each_permission_blocks_only_its_own_action(hub, capsys, which, blocked, allowed):
    item = seed(hub, "a", "Sourdough starter")
    post(hub, "/hub/agents/perm", which=which, enabled="0", next="/settings/agents")
    code, _, err = run(capsys, hub, *[a.format(id=item) for a in blocked])
    assert code == 1 and "turned off for AI agents" in err
    assert run(capsys, hub, *allowed)[0] == 0
    post(hub, "/hub/agents/perm", which=which, enabled="1", next="/settings/agents")
    assert run(capsys, hub, *[a.format(id=item) for a in blocked] + (["--words-only"] if blocked[0] == "search" else []))[0] == 0


# ---- daily limits ---------------------------------------------------------------------------------------------

def test_daily_limits_stop_links_and_notes_and_ignore_odd_values(hub, capsys):
    item = seed(hub, "c", "Sourdough starter")
    post(hub, "/hub/agents/limits", add="7", note="abc", next="/settings/agents")          # not one of the choices
    assert hub.store.get_setting("agents_limit_add", "") == "" and hub.store.get_setting("agents_limit_note", "") == ""
    post(hub, "/hub/agents/limits", add="10", note="100", next="/settings/agents")
    assert hub.store.get_setting("agents_limit_add") == "10"
    hub.store.set_setting("agents_limit_add", "1")
    hub.store.set_setting("agents_limit_note", "2")
    assert run(capsys, hub, "add", YT)[0] == 0
    code, _, err = run(capsys, hub, "add", OTHER)
    assert code == 1 and "daily limit" in err and hub.store.id_for(OTHER) is None
    assert run(capsys, hub, "note", str(item), "one")[0] == 0 and run(capsys, hub, "note", str(item), "two")[0] == 0
    code, _, err = run(capsys, hub, "note", str(item), "three")
    assert code == 1 and "daily limit" in err
    assert run(capsys, hub, "note", str(item), "--undo")[0] == 0                          # undoing is never counted
    hub.store.set_setting("agents_limit_add", "0")                                          # no limit
    assert run(capsys, hub, "add", OTHER)[0] == 0


# ---- hiding saves ---------------------------------------------------------------------------------------------

def test_hidden_tags_do_not_exist_for_agents(hub, capsys):
    shown = seed(hub, "a", "Sourdough starter")
    tagged = seed(hub, "b", "Private diary entry", tags=("private",))
    post(hub, "/hub/agents/hide", tags=" Private , journal ,private", next="/settings/agents")
    assert hub.store.get_setting("agents_hide_tags") == "private,journal"
    _, out, _ = run(capsys, hub, "list", "--json")
    assert [r["id"] for r in json.loads(out)["results"]] == [shown]
    _, out, _ = run(capsys, hub, "search", "diary", "--words-only", "--json")
    assert json.loads(out)["results"] == []
    code, _, err = run(capsys, hub, "show", str(tagged))
    assert code == 1 and "no saved post" in err
    code, _, err = run(capsys, hub, "note", str(tagged), "snoop")
    assert code == 1 and "no such save" in err.lower() and hub.store.item_by_id(tagged)["agent_note"] == ""
    text, bad = mcp_agent.call("magpiary_show", {"id": tagged}, hub.port)
    assert bad and text == "There is no saved post with that id."
    assert json.loads(run(capsys, hub, "status", "--json")[1])["library"] == 1             # not even counted
    code, out, _ = run(capsys, hub, "add", hub.store.item_by_id(tagged)["canonical_url"])  # re-adding a hidden link reveals nothing
    assert code == 0 and "Already in Magpiary." in out and "#" not in out
    post(hub, "/hub/agents/hide", tags="", next="/settings/agents")                       # unhide
    assert json.loads(run(capsys, hub, "status", "--json")[1])["library"] == 2
    assert run(capsys, hub, "show", str(tagged))[0] == 0


# ---- the activity log -----------------------------------------------------------------------------------------

def test_the_activity_log_records_actions_and_refusals_and_can_be_cleared(hub, capsys):
    seed(hub, "a", "Sourdough starter")
    run(capsys, hub, "search", "sourdough", "--words-only")
    run(capsys, hub, "add", YT)
    switch(hub, False)
    run(capsys, hub, "search", "secret words")
    entries = agent_log.recent(10)
    assert [(e["tool"], e["ok"]) for e in entries] == [("search", False), ("add", True), ("search", True)]
    assert entries[0]["why"] and entries[2]["detail"] == "sourdough"
    body = page(hub, "/settings/agents")[2]
    assert "Searched" in body and "Saved a link" in body and "Refused" in body and "secret words" in body
    post(hub, "/hub/agents/clearlog", next="/settings/agents")
    assert agent_log.recent(10) == [] and "Nothing yet" in page(hub, "/settings/agents")[2]


def test_the_page_shows_ten_entries_and_folds_the_rest(hub):
    for n in range(14):
        agent_log.record("search", f"query {n}")
    body = page(hub, "/settings/agents")[2].split('id="sethelp"')[0]
    assert "query 13" in body and "Show earlier activity" in body and "4 more" in body and "query 0" in body
    shown = body[body.index('id="activity"'):body.index("Show earlier activity")]
    assert "query 4" in shown and "query 3" not in shown                                     # ten on top, the older four folded


def test_a_full_disk_never_stops_an_answer(hub, capsys, monkeypatch):
    monkeypatch.setattr(agent_log, "_path", lambda: config_dir() / "no" / "such" / "folder" / "x" / ".." / "\0bad")
    seed(hub, "a", "Sourdough starter")
    assert run(capsys, hub, "list")[0] == 0


# ---- the page and Help ----------------------------------------------------------------------------------------

def test_the_settings_page_holds_controls_and_the_how_to_lives_in_help(hub):
    switch(hub, False)
    off = page(hub, "/settings/agents")[2].split('id="sethelp"')[0]
    assert "/hub/agents/perm" not in off and "Read my saves" not in off and "Turn it on to choose what they may do" in off  # nothing below an off switch
    switch(hub, True)
    whole = page(hub, "/settings/agents")[2]
    body = whole.split('id="sethelp"')[0]                                                # the page itself, not its Help drawer
    master = body[body.index('id="agents-on"'):body.index('id="activity"')]
    assert all(t in master for t in ("Read my saves", "Save links for me", "Write notes on my saves"))   # nested in the master group
    for control in ("/hub/agents/on", "/hub/agents/perm", "Recent activity", "Hide from agents", "Daily limits",
                    "/hub/agents/limits", "/hub/agents/hide"):
        assert control in body, control
    for gone in ("Make a new key", "Full activity log", "Their key", "pile_"):                # one list, no key row, no pile list
        assert gone not in body, gone
    assert 'data-copycode="claude mcp add magpiary -- magpiary mcp"' in body and 'data-copycode="codex mcp add magpiary -- magpiary mcp"' in body  # one click to copy
    assert 'href="/help#t-agents"' in body                                               # the explanation stays in Help
    assert "claude mcp add magpiary -- magpiary mcp" in whole.split('id="sethelp"')[1]     # and is one tap away in the drawer
    assert "goes to the company behind that AI" not in body
    help_body = page(hub, "/help")[2]
    assert "claude mcp add magpiary -- magpiary mcp" in help_body and "Turn AI agents on or off" in help_body
    assert "Which commands are there?" in help_body and "What is the key?" in help_body
    nav = page(hub, "/settings/ai")[2]
    assert 'href="/settings/agents"' in nav
