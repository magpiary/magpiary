"""`magpiary add` and `magpiary note`: AI agents save links and write notes through the running hub, with their own key.
The agent's note is separate from the owner's own note, labelled, and every edit can be undone."""

import json
import re
import stat
import urllib.error
import urllib.request

import pytest

from magpiary import cli
from magpiary.config import config_dir

YT = "https://www.youtube.com/watch?v=aaaaaaaaaaa"


@pytest.fixture
def hub(mac, tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))  # db_path() is now the fake Mac's own database
    mac.store.set_setting("agents_on", "1")             # agents are off until the owner turns them on (tested apart)
    return mac


def run(capsys, mac, *argv, port=None):
    code = cli.main([*argv, "--port", str(port or mac.port)] if argv[0] in ("add", "note") else list(argv))
    out = capsys.readouterr()
    shown = "".join(line for line in out.out.splitlines(keepends=True) if not re.match(r"\d\d:\d\d:\d\d ", line))  # the in-process hub logs here
    return code, shown, out.err


def saved_id(mac, url=YT):
    return mac.store.id_for(url)


def agents(mac):
    return [p for p in mac.store.list_phones() if p["kind"] == "agent" and not p["revoked_at"]]


def post_json(mac, path, body, key=None):
    request = urllib.request.Request(f"http://127.0.0.1:{mac.port}{path}", json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(request) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


# ---- add ------------------------------------------------------------------------------------------------------

def test_add_saves_a_link_strips_tracking_and_pairs_one_agent_device(hub, capsys):
    code, out, _ = run(capsys, hub, "add", YT + "&si=TRACKINGID")
    assert code == 0 and "Saved" in out
    assert saved_id(hub) is not None and hub.store.id_for(YT + "&si=TRACKINGID") is None
    key_file = config_dir() / "agent.key"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert len(agents(hub)) == 1
    code, out, _ = run(capsys, hub, "add", YT)
    assert code == 0 and "Already" in out
    assert len(agents(hub)) == 1  # the same key is reused


def test_add_json_names_the_save(hub, capsys):
    _, out, _ = run(capsys, hub, "add", YT, "--json")
    data = json.loads(out)
    assert data["status"] == "new" and data["id"] == saved_id(hub) and "notice" in data


def test_add_refuses_a_link_it_cannot_save(hub, capsys):
    code, out, err = run(capsys, hub, "add", "not a link")
    assert code == 1 and "can't save" in err.lower() and out == ""


def test_add_says_so_when_the_hub_is_not_running(hub, capsys):
    code, _, err = run(capsys, hub, "add", YT, port=1)
    assert code == 1 and "hub" in err.lower() and "running" in err.lower()


def test_a_revoked_agent_key_gets_a_clear_message(hub, capsys):
    run(capsys, hub, "add", YT)
    hub.store.revoke_phone(agents(hub)[0]["name"])
    code, _, err = run(capsys, hub, "add", YT)
    assert code == 1 and "agent.key" in err


# ---- note -----------------------------------------------------------------------------------------------------

def test_note_is_separate_labelled_and_never_touches_the_owners_note(hub, capsys):
    run(capsys, hub, "add", YT)
    item = saved_id(hub)
    hub.store.set_note(item, "my own words")
    code, out, _ = run(capsys, hub, "note", str(item), "Looks like a recipe for the weekend", "--by", "Claude Code", "--json")
    data = json.loads(out)
    assert code == 0 and data["agent_note"]["text"] == "Looks like a recipe for the weekend"
    assert data["agent_note"]["by"] == "Claude Code" and data["agent_note"]["at"]
    stored = hub.store.item_by_id(item)
    assert stored["note"] == "my own words"
    assert stored["agent_note"] == "Looks like a recipe for the weekend"


def test_every_edit_keeps_the_old_version_and_undo_steps_back(hub, capsys):
    run(capsys, hub, "add", YT)
    item = str(saved_id(hub))
    run(capsys, hub, "note", item, "first")
    run(capsys, hub, "note", item, "second")
    run(capsys, hub, "note", item, "third", "--append")
    assert hub.store.item_by_id(int(item))["agent_note"] == "second\nthird"
    run(capsys, hub, "note", item, "--undo")
    assert hub.store.item_by_id(int(item))["agent_note"] == "second"
    run(capsys, hub, "note", item, "--undo")
    assert hub.store.item_by_id(int(item))["agent_note"] == "first"
    code, out, _ = run(capsys, hub, "note", item, "--clear")
    assert code == 0 and hub.store.item_by_id(int(item))["agent_note"] == ""
    run(capsys, hub, "note", item, "--undo")  # even a clear can be undone
    assert hub.store.item_by_id(int(item))["agent_note"] == "first"
    run(capsys, hub, "note", item, "--undo")
    code, _, err = run(capsys, hub, "note", item, "--undo")
    assert code == 1 and "nothing to undo" in err.lower()


def test_show_and_search_see_the_agent_note(hub, capsys):
    run(capsys, hub, "add", YT)
    item = str(saved_id(hub))
    run(capsys, hub, "note", item, "zebrafinch reminder", "--by", "Codex")
    _, out, _ = run(capsys, hub, "show", item, "--json")
    note = json.loads(out)["item"]["agent_note"]
    assert note["text"] == "zebrafinch reminder" and note["by"] == "Codex"
    _, text, _ = run(capsys, hub, "show", item)
    assert "Agent note" in text and "Codex" in text
    _, out, _ = run(capsys, hub, "search", "zebrafinch", "--words-only", "--json")
    assert [r["id"] for r in json.loads(out)["results"]] == [int(item)]


def test_note_rules_about_who_may_write_what(hub, capsys):
    run(capsys, hub, "add", YT)
    item = saved_id(hub)
    _, phone_key = hub.store.add_phone("Some iPhone")
    key = (config_dir() / "agent.key").read_text().strip()
    body = {"id": item, "text": "hello", "mode": "set"}
    assert post_json(hub, "/v1/agent/note", body)[0] == 401                     # no key
    assert post_json(hub, "/v1/agent/note", body, phone_key)[0] == 403          # a phone's key cannot write notes
    assert post_json(hub, "/v1/agent/note", {**body, "id": 9999}, key)[0] == 404
    assert post_json(hub, "/v1/agent/note", {**body, "text": "x" * 2001}, key)[0] == 400
    assert post_json(hub, "/v1/agent/note", {**body, "mode": "nonsense"}, key)[0] == 400
    hub.store.set_shelf(item, "trash")
    assert post_json(hub, "/v1/agent/note", body, key)[0] == 404                 # the trash is out of reach
    hub.store.set_shelf(item, "inbox")
    assert post_json(hub, "/v1/agent/note", body, key)[0] == 200


def test_note_needs_something_to_do(hub, capsys):
    run(capsys, hub, "add", YT)
    item = str(saved_id(hub))
    for argv in (["note", item], ["note", item, "text", "--undo"], ["note", item, "--undo", "--clear"]):
        with pytest.raises(SystemExit) as stop:
            run(capsys, hub, *argv)
        assert stop.value.code == 2
    assert hub.store.item_by_id(int(item))["agent_note"] == ""


def test_the_agent_device_is_not_listed_among_the_phones(hub, capsys):
    from test_hub import page

    _, _ = hub.store.add_phone("Some iPhone")
    run(capsys, hub, "add", YT)
    assert len(agents(hub)) == 1
    for path in ("/settings/phones", "/help"):
        body = page(hub, path)[2]
        assert "AI agents (command line)" not in body, path
    assert "Some iPhone" in page(hub, "/settings/phones")[2]


# ---- what the owner sees: Settings, Help and the post --------------------------------------------------------

def test_the_key_has_no_controls_on_the_page(hub, capsys):
    from test_hub import page

    run(capsys, hub, "add", YT)                                                      # the key now exists
    body = page(hub, "/settings/agents")[2].split('id="sethelp"')[0]
    for gone in ("Their key", "Cut off", "Make a new key", "No key yet", "/hub/agents/newkey", "/hub/agents/cutoff"):
        assert gone not in body, gone


def test_help_has_an_ai_agents_topic_and_settings_lists_the_page(hub):
    from test_hub import page

    body = page(hub, "/help")[2]
    assert "AI agents" in body and "magpiary help agents" in body and "Turn AI agents on or off" in body and "Connect Claude Code or Codex" in body
    assert 'href="/settings/agents"' in page(hub, "/settings/ai")[2]


def test_the_owner_sees_the_agent_note_apart_from_their_own_and_can_remove_it(hub, capsys):
    from test_hub import page, post

    run(capsys, hub, "add", YT)
    item = saved_id(hub)
    hub.store.set_note(item, "mine")
    run(capsys, hub, "note", str(item), "<b>from the agent</b>", "--by", "Claude Code")
    body = page(hub, f"/item/{item}")[2]
    assert "Note from Claude Code" in body and "&lt;b&gt;from the agent&lt;/b&gt;" in body and "<b>from the agent</b>" not in body
    assert "mine" in body and "/hub/agentnote/remove" in body
    post(hub, "/hub/agentnote/remove", id=str(item), next=f"/item/{item}")
    assert hub.store.item_by_id(item)["agent_note"] == "" and hub.store.item_by_id(item)["note"] == "mine"
    assert "Note from Claude Code" not in page(hub, f"/item/{item}")[2]
    run(capsys, hub, "note", str(item), "--undo")                              # removing from the page is undoable too
    assert hub.store.item_by_id(item)["agent_note"] == "<b>from the agent</b>"


# ---- Codex review findings (1 Nov 2026): permission boundary, atomic edits, short-link merges -------------------

def test_an_agent_key_can_only_save_links_not_use_phone_powers(hub):
    _, key = hub.store.add_phone("Agent for tests", kind="agent")
    phone, _ = hub.store.add_phone("Seeder")
    hub.store.receive(phone, [{"id": "s1", "url": YT}])
    item = saved_id(hub)
    hub.store.set_shelf(item, "inbox")
    other = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    for extra in ({"note": "pretending to be the owner"}, {"board": "some-board"}, {"attach": True, "board": "some-board"}, {"shared_at": "2020-01-01"}):
        code, _ = post_json(hub, "/v1/items", {"items": [{"id": "x1", "url": other, **extra}]}, key)
        assert code == 403, extra
    assert hub.store.id_for(other) is None                                   # nothing was saved by the refused requests
    assert hub.store.item_by_id(item)["shelf"] == "inbox" and hub.store.item_by_id(item)["note"] == ""
    code, reply = post_json(hub, "/v1/items", {"items": [{"id": "x2", "url": other}]}, key)
    assert code == 200 and hub.store.id_for(other) is not None
    assert hub.store.item_by_id(hub.store.id_for(other))["note"] == ""      # an agent save never fills the owner's note


def test_many_appends_at_once_lose_nothing(hub):
    import threading

    phone, _ = hub.store.add_phone("Seeder")
    hub.store.receive(phone, [{"id": "s1", "url": YT}])
    item = saved_id(hub)
    lines = [f"line {n}" for n in range(16)]
    threads = [threading.Thread(target=hub.store.set_agent_note, args=(item, "append", line, "Claude Code")) for line in lines]
    [t.start() for t in threads]
    [t.join() for t in threads]
    note = hub.store.item_by_id(item)["agent_note"]
    assert sorted(note.split("\n")) == sorted(lines)
    with hub.store._lock:
        kept = hub.store._db.execute("SELECT COUNT(*) FROM agent_note_history").fetchone()[0]
    assert kept == len(lines) - 1                                            # every earlier version is recoverable


def test_a_failed_edit_leaves_the_note_and_its_history_as_they_were(hub):
    phone, _ = hub.store.add_phone("Seeder")
    hub.store.receive(phone, [{"id": "s1", "url": YT}])
    item = saved_id(hub)
    store = hub.store
    store.set_agent_note(item, "set", "first", "A")
    store.set_agent_note(item, "set", "second", "A")

    def history():
        with store._lock:
            return [r[0] for r in store._db.execute("SELECT text FROM agent_note_history ORDER BY id")]

    class Failing:                                                           # the database refuses the final write
        def __init__(self, real):
            self.real = real

        def execute(self, sql, *args):
            if sql.lstrip().startswith("UPDATE items SET agent_note"):
                raise RuntimeError("disk full")
            return self.real.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.real, name)

    real = store._db
    store._db = Failing(real)
    try:
        with pytest.raises(RuntimeError):
            store.set_agent_note(item, "undo")
        with pytest.raises(RuntimeError):
            store.set_agent_note(item, "set", "third")
    finally:
        store._db = real
    assert store.item_by_id(item)["agent_note"] == "second" and history() == ["first"]
    store.set_agent_note(item, "set", "y" * 1500)
    before = history()
    with pytest.raises(ValueError):
        store.set_agent_note(item, "append", "z" * 600)                       # too long: refused before anything is kept
    assert history() == before and len(store.item_by_id(item)["agent_note"]) == 1500


def test_an_agent_note_survives_a_short_link_turning_into_a_post_already_saved(hub):
    from magpiary.cleaner import clean

    store = hub.store
    short, real = clean("https://redd.it/abc123"), clean(YT)
    assert short.needs_expansion
    for target_note, expected in (("", "from the short link"), ("already here", "already here\nfrom the short link")):
        with store._lock:
            store._db.execute("DELETE FROM items")
            store._db.execute("DELETE FROM agent_note_history")
        store.add_link(YT)
        store.add_link("https://redd.it/abc123")
        target = store.id_for(real.url)
        if target_note:
            store.set_agent_note(target, "set", target_note, "Codex")
        store.set_agent_note(store.id_for(short.url), "set", "from the short link", "Claude Code")
        store.expansion_succeeded(short.url, real)
        merged = store.item_by_id(store.id_for(real.url))
        assert merged["agent_note"] == expected
        if target_note:
            assert store.set_agent_note(merged["id"], "undo")["text"] == "already here"   # the earlier version is recoverable
        else:
            assert merged["agent_note_by"] == "Claude Code"
