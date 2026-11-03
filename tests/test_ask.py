import json
import time
from pathlib import Path
from types import SimpleNamespace

from magpiary import ask as asking
from test_hub import lib, page, post  # noqa: F401  (the library fixture and helpers)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def ask_is_on(mac):
    mac.store.set_setting("ask_on", "1")  # new installs start with Ask off; these tests are about using it


def test_the_prompt_holds_only_the_saves_text_and_marks_each_post(mac, lib):
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({"title": "Cedar Panels", "summary": "An invented panel toolkit.",
                                                    "key_points": [{"at": "0:08", "text": "Modules"}], "entities": {}}))
    (folder / "transcript.json").write_text(json.dumps({"segments": [{"start": 8, "text": "install the package with npm"}]}))
    item = mac.store.item_by_id(lib["ig"])
    text = asking.post_text(item, "how do I install it", 1)
    assert text.startswith("[P1] Cedar Panels") and "Summary: An invented panel toolkit." in text and "0:08 install the package with npm" in text
    prompt = asking.build_prompt("how do I install it", [text], [("user", "hi")], "Cedar Panels")
    assert "Answer ONLY from the posts" in prompt and "untrusted" in prompt and "QUESTION: how do I install it" in prompt


def test_answers_point_at_posts_and_a_reply_that_is_not_json_is_still_used():
    assert asking.parse('```json\n{"found": true, "answer": "Use npm [P1@0:08]."}\n```') == (True, "Use npm [P1@0:08].")
    assert asking.parse('{"found": false, "answer": "The saves do not say."}')[0] is False
    assert asking.parse("plain words")[1] == "plain words"
    posts = [{"id": 11}, {"id": 12}]
    assert asking.cites("A [P2@1:05] and B [P1] and a ghost [P9].", posts) == [
        {"n": 2, "id": 12, "at": "1:05"}, {"n": 1, "id": 11, "at": ""}]


def test_asking_from_a_post_keeps_the_chat_cites_the_moment_and_can_save_a_note(mac, lib, monkeypatch):
    hub = mac.server.hub
    monkeypatch.setattr(type(hub), "ask_engine", lambda self: {"id": "key", "name": "Gemini", "short": "Gemini", "other": "", "write": None,
                                                              "key": SimpleNamespace(provider="gemini", model="m", secret="s", name="k")})
    sent = {}

    def fake_gemini(key, prompt, history, web, on_event, system=None):
        sent.update(prompt=prompt, web=web, system=system)
        on_event({"step": "Searching the web: eggs", "kind": "search", "arg": "eggs"})
        return f"Cooks the egg off the heat [[save:{lib['ig']}@0:05]].", {"in": 1200, "out": 80}

    from magpiary import ask_keys

    monkeypatch.setitem(ask_keys.ASKERS, "gemini", fake_gemini)
    scope = f"post:{lib['ig']}"
    status, _, body = post(mac, "/hub/ask/send", scope=scope, q="when do the eggs go in?")
    job = json.loads(body)["job"]
    for _ in range(100):
        done = json.loads(page(mac, f"/ask/poll?job={job}&after=0")[2])
        if done["done"]:
            break
        time.sleep(0.05)
    html = done["html"]
    assert status == 200 and 'class="askcite"' in html and "0:05" in html and f'href="/item/{lib["ig"]}"' in html
    assert sent["web"] is True and "when do the eggs go in?" in sent["prompt"] and done["events"][0]["kind"] == "search"
    assert "Answer the question properly" in sent["system"]  # Normal depth is the default
    panel = page(mac, f"/ask/panel?scope={scope}")[2]
    assert "when do the eggs go in?" in panel and "Save as note" in panel and "What can Ask Magpiary do?" not in panel
    assert 'data-enable-grammarly="false"' in panel and 'data-gramm="false"' in panel and 'class="askgrip"' in panel
    message = [m for m in mac.store.ask_thread(scope) if m["role"] == "assistant"][0]
    status, _, body = post(mac, "/hub/ask/note", scope=scope, message=str(message["id"]))
    assert status == 200
    assert "Cooks the egg off the heat" in (mac.store.item_by_id(lib["ig"]).get("note") or "")  # saved onto the post's own note
    assert body.decode() == mac.store.item_by_id(lib["ig"])["note"]  # the page shows the kept note at once


def test_the_empty_chat_has_a_calm_hello_and_three_plain_starters(mac, lib):
    panel = page(mac, f"/ask/panel?scope=post:{lib['ig']}")[2]
    assert 'class="askorb"' in panel and "What do you want to know?" in panel and panel.count('class="askstart"') == 3 and "data-asktype" in panel and "<i aria-hidden=\"true\">→</i>" not in panel and 'data-askmic' in panel
    assert "askclear" not in panel and 'class="askchip"' not in panel  # no New chat until there is a chat; no boxed starter buttons


def test_without_a_key_the_panel_says_so_and_nothing_is_sent(mac, lib, monkeypatch):
    monkeypatch.setattr(asking, "claude_available", lambda: False)
    panel = page(mac, f"/ask/panel?scope=post:{lib['ig']}")[2]
    assert "Ask Magpiary needs an AI" in panel
    assert post(mac, "/hub/ask/send", scope=f"post:{lib['ig']}", q="hello")[0] == 400


def test_a_pile_has_an_ask_button_and_shows_saved_notes(mac, lib):
    urls = [mac.store.item_by_id(lib[k])["canonical_url"] for k in ("ig", "yt")]
    pid = mac.store.save_auto_pile(None, urls, "Pasta", keep_name=True)
    assert f'data-askscope="pile:{pid}"' in page(mac, f"/pile/{pid}")[2] and "data-askdock" in page(mac, f"/pile/{pid}")[2]
    mac.store.ask_note_add(f"pile:{pid}", "Both use eggs.")
    assert "Both use eggs." in page(mac, f"/pile/{pid}")[2]


def test_a_post_asks_through_the_side_sheet_with_the_post_as_the_subject(mac, lib):
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({"title": "Cedar Panels", "summary": "x", "type": "tool", "key_points": [{"at": "0:08", "text": "Modules"}],
                                                    "extras": {"tool_name": "Cedar Panels"}, "entities": {"tools": ["Cedar Panels"]}}))
    body = page(mac, f"/item/{lib['ig']}")[2]
    assert 'data-tab="ask"' not in body  # Ask is not a tab any more
    assert f'class="pvask" data-askpost="{lib["ig"]}"' in body and body.index('class="pvask"') < body.index('class="pvprimary')
    assert f'data-askscope="post:{lib["ig"]}"' in body and "data-askdock" in body  # the bar at the bottom right is on a post, set to this post
    panel = page(mac, f"/ask/panel?scope=post:{lib['ig']}")[2]
    assert "Research Cedar Panels more deeply" in panel and "Walk me through getting started with Cedar Panels." in panel
    assert "What happens at" not in panel  # no questions quoting a moment of the video
    context = mac.server.hub.ask_place(f"post:{lib['ig']}", "Cedar Panels", [mac.store.item_by_id(lib["ig"])])["context"]
    assert "saved post open" in context and "about this post" in context and "web search" in context  # the post is the default subject


def test_a_post_has_one_conversation_kept_in_its_own_section_and_cleared_on_request(mac, lib):
    scope = f"post:{lib['ig']}"
    mac.store.ask_add(scope, "user", "what is it?")
    mac.store.ask_add(scope, "assistant", "A tool.", {})
    mac.store.ask_add("library:all", "user", "hello")
    listing = page(mac, f"/ask/sessions?scope={scope}")[2]
    assert listing.index(">Posts<") < listing.index(">Now<") and scope in listing and listing.count(f'data-scope="{scope}"') == 1
    assert "what is it?" in page(mac, f"/ask/panel?scope={scope}")[2] and "data-askclearpost" in page(mac, f"/ask/panel?scope={scope}")[2]
    assert "data-askclear>" not in page(mac, f"/ask/panel?scope={scope}")[2]  # no 'new chat' on a post: one conversation only
    assert post(mac, "/hub/ask/live-delete", scope=scope)[0] == 200
    assert mac.store.ask_thread(scope) == []


def test_cited_links_get_preview_cards_fetched_by_the_mac(tmp_path, monkeypatch):
    from magpiary import ask_cards

    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))
    html = b'<html><head><title>Plain</title><meta property="og:title" content="Pebble Desk Pricing"><meta property="og:image" content="https://cdn.example.com/p.png"></head></html>'
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50

    def get(url, headers=None, limit=0):
        return (200, url, png) if url.endswith(".png") else (200, url, html)
    text = "See [Pebble Desk](https://pebbledesk.example.com/pricing) and [again](https://pebbledesk.example.com/pricing/) and [x](https://other.example/a)"
    assert ask_cards.links_in(text) == ["https://pebbledesk.example.com/pricing", "https://other.example/a"]
    cards = ask_cards.cards_for(text, get, public=lambda host: True)
    assert cards[0]["title"] == "Pebble Desk Pricing" and cards[0]["host"] == "pebbledesk.example.com" and ask_cards.image_path(cards[0]["img"]).suffix == ".png"
    assert ask_cards.card("http://127.0.0.1/x", get) is None  # a private address gets no card


def test_the_claude_code_writer_returns_the_json_asked_for():
    out = asking.write_with_claude(None, "p", run=lambda *a, **k: SimpleNamespace(
        stdout=json.dumps({"structured_output": {"found": True, "answer": "Yes [P1]."}}), stderr="", returncode=0))
    assert asking.parse(out) == (True, "Yes [P1].")


# ---- the open version: Claude Code with the web and the library --------------------------------------------

from magpiary import ask_open, askconfig, mcp_library  # noqa: E402


def test_the_open_prompt_makes_the_saves_background_and_allows_only_the_web_and_the_library():
    assert "not a limit" in ask_open.SYSTEM and "untrusted" in ask_open.SYSTEM and "Answer ONLY" not in ask_open.SYSTEM
    cmd = ask_open.command("claude")
    assert cmd[cmd.index("--model") + 1] == "haiku" and cmd[cmd.index("--effort") + 1] == "medium"  # the cheap default
    assert cmd[cmd.index("--tools") + 1] == "WebSearch,WebFetch"
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--mcp-config")]
    assert allowed == ["WebSearch", "WebFetch", "mcp__magpiary__search_saves", "mcp__magpiary__read_save"]
    assert "Bash" not in " ".join(cmd) and "stream-json" in cmd and "--strict-mcp-config" in cmd
    prompt = ask_open.build_prompt("how is Example Finch different?", ["[save:5] Example Finch desktop"], [("user", "hi")], "Example Finch")
    assert "QUESTION: how is Example Finch different?" in prompt and "[save:5] Example Finch desktop" in prompt and "EARLIER IN THIS CHAT" in prompt
    assert "whole library" in ask_open.build_prompt("q", [], [], "your whole library")


def test_the_stream_becomes_steps_text_and_a_final_answer():
    events = []
    lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "example finch agent"}}]}}),
             json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Example Finch is"}}}),
             "not json at all",
             json.dumps({"type": "result", "is_error": False, "result": "Example Finch is an agent."})]
    final = None
    for line in lines:
        final = ask_open.handle(line, {}, events.append) or final
    assert events[:2] == [{"step": "Searching the web: example finch agent", "kind": "search", "arg": "example finch agent"}, {"text": "Example Finch is"}] and final == "Example Finch is an agent."
    assert events[2]["usage"] == {"in": 0, "out": 0, "cached": 0, "cost": 0.0}
    answer, saves = ask_open.split_saves("Try it.\nSAVE: https://finch.example.com/work | Example Finch Work\nSAVE: https://x.test/a")
    assert answer == "Try it." and saves == [{"url": "https://finch.example.com/work", "title": "Example Finch Work"}, {"url": "https://x.test/a", "title": ""}]


def test_answers_render_as_safe_html_with_chips_links_and_lists(mac, lib):
    hub = mac.server.hub
    html = hub.render_answer(f'Intro with **bold** and `code` <script>x</script>\n\n- one [[save:{lib["ig"]}@0:05]]\n- two [site](https://a.test/x?y=1&z=2) [bad](javascript:alert(1))\n\n1. first')
    assert "<script>" not in html and "<b>bold</b>" in html and "<code>code</code>" in html
    assert "<ul><li>one" in html and 'class="askcite"' in html and "0:05" in html and "<ol><li>first</li></ol>" in html
    assert 'href="https://a.test/x?y=1&amp;z=2"' in html and 'rel="noopener noreferrer"' in html and 'href="javascript' not in html


def test_the_library_tools_search_and_read_saves_and_refuse_the_rest(mac, lib):
    found = mcp_library.call(mac.store, "search_saves", {"query": "carbonara"})
    assert f"id {lib['ig']}:" in found
    assert "Pasta carbonara" in mcp_library.call(mac.store, "read_save", {"id": lib["ig"]}) or "Chef Alex Example" in mcp_library.call(mac.store, "read_save", {"id": lib["ig"]})
    assert "no saved post" in mcp_library.call(mac.store, "read_save", {"id": 9999})
    assert mcp_library.reply({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, mac.store)["result"]["tools"][0]["name"] == "search_saves"
    assert mcp_library.reply({"jsonrpc": "2.0", "method": "notifications/initialized"}, mac.store) is None


def test_an_open_question_runs_as_a_job_that_shows_steps_and_ends_in_a_saved_message(mac, lib, monkeypatch):
    hub = mac.server.hub
    monkeypatch.setattr(type(hub), "ask_engine", lambda self: {"id": "claude", "name": "Claude Code", "short": "Claude Code", "other": "",
                                                              "write": None, "key": None})

    def fake_run(question, items, history, scope, on_event, cancelled=lambda: False, **kw):
        on_event({"step": "Searching the web: example finch"})
        on_event({"text": "Example Finch works"})
        return "Example Finch works differently [[save:%d]].\nSAVE: https://finch.example.com | Example Finch" % items[0]["id"]

    monkeypatch.setattr(ask_open, "run", fake_run)
    scope = f"post:{lib['ig']}"
    status, headers, body = post(mac, "/hub/ask/send", scope=scope, q="How is Example Finch different from other agents?")
    job = json.loads(body)["job"]
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    for _ in range(50):
        done = json.loads(page(mac, f"/ask/poll?job={job}&after=0")[2])
        if done["done"]:
            break
        time.sleep(0.05)
    assert done["events"][0] == {"step": "Searching the web: example finch"} and 'class="askm ai open"' in done["html"]
    assert "data-asklink" not in done["html"] and "1 step" in done["html"] and "SAVE:" not in done["html"]
    assert page(mac, "/ask/poll?job=nope")[0] == 404
    assert "Ask anything about this post" in page(mac, f"/ask/panel?scope={scope}")[2]
    lib_panel = page(mac, "/ask/panel?scope=library:all")[2]
    assert "Ask anything: your saves and the web" in lib_panel and 'data-askscope="library:auto"' in page(mac, "/")[2] and "data-askdock" in page(mac, "/")[2]


# ---- Settings → Ask Magpiary ------------------------------------------------------------------------------------

def test_with_ask_off_no_ask_button_tab_or_panel_shows_anywhere(mac, lib):
    mac.store.set_setting("ask_on", "0")
    urls = [mac.store.item_by_id(lib[k])["canonical_url"] for k in ("ig", "yt")]
    pid = mac.store.save_auto_pile(None, urls, "Pasta", keep_name=True)
    folder = Path(mac.store.item_by_id(lib["ig"])["archive_dir"])
    (folder / "record.json").write_text(json.dumps({"title": "T", "summary": "x", "type": "tool", "key_points": [], "entities": {}}))
    for path in ("/", f"/item/{lib['ig']}", f"/pile/{pid}", "/?view=boards"):
        body = page(mac, path)[2]
        assert "data-ask=" not in body and "data-askdock" not in body and "data-askscope" not in body and 'data-tab="ask"' not in body and 'class="pvask"' not in body, path
    assert page(mac, "/ask/panel?scope=library:all")[0] == 404
    assert post(mac, "/hub/ask/send", scope="library:all", q="hi")[0] == 404
    settings = page(mac, "/settings/ask")[2]
    assert 'id="onoff"' in settings and 'id="engine"' not in settings
    post(mac, "/hub/askset", on="1", next="/settings/ask")
    on = page(mac, "/settings/ask")[2]
    assert 'id="engine"' in on and 'id="model"' in on and 'id="usage"' in on and 'data-askscope="library:auto"' in page(mac, "/")[2] and "data-askdock" in page(mac, "/")[2]


def test_the_settings_tab_saves_engine_model_effort_web_and_limits(mac, lib, monkeypatch):
    monkeypatch.setattr(asking, "claude_available", lambda: True)
    from magpiary import ask_codex

    monkeypatch.setattr(ask_codex, "available", lambda: False)
    monkeypatch.setattr("magpiary.ask_setup.installed", lambda engine: engine == "claude")  # not this Mac's real tools
    monkeypatch.setattr(type(mac.server.hub), "_claude_state", lambda self: {"installed": True, "signed_in": True})
    body = page(mac, "/settings/ask")[2]
    assert "Haiku 5.5" in body and "Active" in body and "Codex" in body and "Not set up" in body
    post(mac, "/hub/askset", model="sonnet", effort="high", next="/settings/ask")
    post(mac, "/hub/askset", web="0", tokens="0", limit="medium", period="day", next="/settings/ask")
    from magpiary import askconfig
    s = mac.store
    assert (askconfig.claude_model(s), askconfig.claude_effort(s), askconfig.web_allowed(s), askconfig.show_tokens(s)) == ("sonnet", "high", False, False)
    assert askconfig.limit(s) == 25 * askconfig.TOKENS_PER_QUESTION and "about 25 questions a day" in askconfig.limit_words(s)
    post(mac, "/hub/askset", period="month", next="/settings/ask")
    assert askconfig.limit(s) == 25 * 30 * askconfig.TOKENS_PER_QUESTION and "about 750 questions a month" in askconfig.limit_words(s)
    post(mac, "/hub/askset", effort="bogus", model="bad name; rm -rf", limit="huge", next="/settings/ask")  # nonsense is ignored
    assert askconfig.limit_preset(s) == "medium"
    page_html = page(mac, "/settings/ask")[2]
    assert "A different model" not in page_html and 'name="limit_day"' not in page_html and "Extra high" in page_html and "Per month" in page_html
    assert askconfig.claude_effort(s) == "high" and askconfig.claude_model(s) == "sonnet"
    cmd = ask_open.command("claude", "sonnet", "high", web=False)
    assert cmd[cmd.index("--tools") + 1] == "" and "WebSearch" not in cmd


def test_tokens_are_recorded_shown_under_the_answer_and_a_limit_warns_before_sending(mac, lib, monkeypatch):
    hub = mac.server.hub
    monkeypatch.setattr(asking, "claude_available", lambda: True)

    def fake_run(question, items, history, scope, on_event, cancelled=lambda: False, **kw):
        assert kw["model"] == "haiku" and kw["effort"] == "medium" and kw["web"] is True
        on_event({"usage": {"in": 2100, "out": 340, "cost": 0.004}})
        return "Fine."

    monkeypatch.setattr(ask_open, "run", fake_run)
    scope = f"post:{lib['ig']}"
    job = json.loads(post(mac, "/hub/ask/send", scope=scope, q="one?")[2])["job"]
    for _ in range(50):
        done = json.loads(page(mac, f"/ask/poll?job={job}&after=0")[2])
        if done["done"]:
            break
        time.sleep(0.05)
    assert "2.1k in · 340 out · Haiku 5.5" in done["html"] and not any("usage" in e for e in done["events"])
    from magpiary import askconfig
    assert mac.store.ask_usage_since(askconfig.periods(mac.store._now())["day"])[0]["tokens_in"] == 2100
    assert "2.1k in" in page(mac, "/settings/ask")[2]
    mac.store.set_setting("ask_limit", "low")
    mac.store.ask_usage_add(scope, "claude", "Haiku 5.5", 140_000, 20_000)  # over Low (about 10 questions, 150k tokens)
    assert 'class="askmeter' not in page(mac, "/ask/panel?scope=library:all")[2]  # no meter in the panel; the limit only warns
    warn = json.loads(post(mac, "/hub/ask/send", scope=scope, q="two?")[2])
    assert "past your Low limit" in warn["warn"] and len([m for m in mac.store.ask_thread(scope) if m["role"] == "user"]) == 1
    assert "job" in json.loads(post(mac, "/hub/ask/send", scope=scope, q="two?", over="1")[2])
    mac.store.set_setting("ask_show_tokens", "0")
    assert "2.1k in" not in hub._ask_message(mac.store.ask_message(done_id(mac, scope)), [], scope)


def done_id(mac, scope):
    return [m for m in mac.store.ask_thread(scope) if m["role"] == "assistant"][0]["id"]


def test_turning_ask_on_needs_examplecreator_to_answer_and_turning_it_off_stops_running_answers(mac, lib, monkeypatch):
    hub = mac.server.hub
    mac.store.set_setting("ask_on", "0")
    monkeypatch.setattr(asking, "claude_available", lambda: False)
    monkeypatch.setattr("magpiary.keys.usable", lambda *a, **k: [])
    monkeypatch.setattr("magpiary.ask_codex.available", lambda: False)
    status, headers, _ = post(mac, "/hub/askset", on="1", next="/settings/ask")
    assert status == 303 and "error=" in headers["Location"] and mac.store.get_setting("ask_on", "0") == "0"
    assert "needs an AI" in page(mac, headers["Location"])[2]
    monkeypatch.setattr(asking, "claude_available", lambda: True)
    monkeypatch.setattr(type(hub), "_claude_state", lambda self: {"installed": True, "signed_in": True})
    assert post(mac, "/hub/askset", on="1", next="/settings/ask")[1]["Location"] == "/settings/ask"
    assert mac.store.get_setting("ask_on", "0") == "1" and json.loads(page(mac, "/activity.json")[2])["ask"] is True
    # an answer being written is stopped when Ask is switched off, and the off switch asks first
    assert 'data-confirm="Turn off Ask Magpiary?' in page(mac, "/settings/ask")[2]
    hub.__dict__["_ask_jobs"] = {"j1": {"events": [], "done": False, "html": "", "at": 0, "stop": False}}
    post(mac, "/hub/askset", on="0", next="/settings/ask")
    assert hub._ask_jobs["j1"]["stop"] is True and json.loads(page(mac, "/activity.json")[2])["ask"] is False
    assert post(mac, "/hub/ask/stop", job="j1")[0] == 404  # Ask is off: even this answers nothing


def test_a_spoken_question_is_turned_into_text_on_this_mac(mac, lib, monkeypatch):
    import base64
    from types import SimpleNamespace

    from magpiary import transcribe

    seen = {}
    monkeypatch.setattr("magpiary.tools.find", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(transcribe, "transcribe", lambda wav, out, *a, **k: seen.setdefault("n", 1) and {"segments": [{"text": " How is Example Finch "}, {"text": "different?"}]})
    audio = base64.b64encode(b"x" * 5000).decode()
    assert json.loads(post(mac, "/hub/ask/voice", audio=audio)[2]) == {"text": "How is Example Finch different?"}
    assert "error" in json.loads(post(mac, "/hub/ask/voice", audio="")[2])
    assert "error" in json.loads(post(mac, "/hub/ask/voice", audio=base64.b64encode(b"x" * 515_000).decode())[2])
    mac.store.set_setting("ask_on", "0")
    assert post(mac, "/hub/ask/voice", audio=audio)[0] == 404


def test_spoken_words_drops_notes_about_sound():
    from magpiary.hub_ask import spoken_words
    assert spoken_words("[BLANK_AUDIO]") == ""
    assert spoken_words(" (silence) ") == ""
    assert spoken_words("*music* ♪ How does it work? [Silence]") == "How does it work?"


def test_poll_sends_the_text_so_far_formatted(tmp_path):
    from magpiary.hub_ask import AskPages
    page = AskPages.__new__(AskPages)
    page.__dict__["_ask_jobs"] = {"j": {"events": [{"text": "Hello **bo"}, {"text": "ld** world [[sav"}], "done": False, "html": ""}}
    page.render_answer = lambda t: f"<p>{t}</p>"
    body = __import__("json").loads(page.ask_poll({"job": "j", "after": "0"}).body)
    assert body["live"] == "<p>Hello **bold** world </p>"


def test_a_chat_with_an_answer_becomes_a_past_chat_you_can_read_but_not_continue(mac, lib):
    store = mac.store
    store.ask_add("library:all", "user", "What is new in Claude?")
    store.ask_add("library:all", "assistant", "Opus 5.5 came out.", {"open": True, "steps": [], "usage": {}, "seconds": 3})
    assert page(mac, "/ask/panel?scope=library:all")[2].count('data-askhist') == 1
    post(mac, "/hub/ask/clear", scope="library:all")
    assert store.ask_thread("library:all") == []
    listing = page(mac, "/ask/sessions")[2]
    assert "Recent" in listing and "What is new in Claude?" in listing and "Whole library" in listing
    sid = store.ask_sessions()[0]["id"]
    read = page(mac, f"/ask/session?id={sid}")[2]
    assert "Opus 5.5 came out." in read and "<textarea" not in read and "data-asksave" not in read and f'data-askhistdel="{sid}"' in read
    # a chat nobody answered is dropped, not kept
    store.ask_add("library:all", "user", "Hello?")
    post(mac, "/hub/ask/clear", scope="library:all")
    assert len(store.ask_sessions()) == 1
    post(mac, "/hub/ask/session-delete", id=str(sid))
    assert store.ask_sessions() == [] and "No chats yet" in page(mac, "/ask/sessions")[2]
    assert page(mac, "/ask/session?id=999")[0] == 404


# ---- Codex and keys, the open way ---------------------------------------------------------------------------

CODEX_RUN = [
    '{"type":"thread.started","thread_id":"t"}', '{"type":"turn.started"}',
    '{"type":"item.started","item":{"id":"item_0","type":"mcp_tool_call","server":"magpiary","tool":"search_saves","arguments":{"query":"claude"},"result":null,"error":null,"status":"in_progress"}}',
    '{"type":"item.completed","item":{"id":"item_0","type":"mcp_tool_call","server":"magpiary","tool":"search_saves","arguments":{"query":"claude"},"status":"completed"}}',
    '{"type":"item.started","item":{"id":"item_1","type":"web_search","query":""}}',
    '{"type":"item.completed","item":{"id":"item_1","type":"web_search","query":"example finch work","action":{"type":"search","query":"example finch work"}}}',
    '{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Example Finch Work is an agent."}}',
    '{"type":"turn.completed","usage":{"input_tokens":70806,"cached_input_tokens":59008,"output_tokens":88,"reasoning_output_tokens":12}}']


def test_codex_runs_under_the_permissions_profile_in_an_empty_folder_and_its_stream_becomes_steps_text_and_usage():
    from magpiary import ask_codex

    cmd = ask_codex.command("codex", "gpt-6-luna", "medium", True, python="py")
    assert cmd[:2] == ["codex", "exec"] and "-s" not in cmd and 'default_permissions="magpiary_ask"' in cmd and "--ephemeral" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-6-luna" and "model_reasoning_effort=medium" in cmd and 'web_search="live"' in cmd
    assert 'mcp_servers.magpiary.default_tools_approval_mode="approve"' in cmd
    assert 'web_search="disabled"' in ask_codex.command("codex", "m", "low", False)
    events, state, last = [], {}, None
    for line in CODEX_RUN:
        last = ask_codex.handle(line, events.append, state) or last
    assert last == "done"
    assert [e["kind"] for e in events if "step" in e] == ["saves", "search"] and events[1]["arg"] == "example finch work"
    assert {"text": "Example Finch Work is an agent."} in events and events[-1] == {"usage": {"in": 11798, "cached": 59008, "out": 100, "cost": 0.0}}


def test_the_codex_runner_collects_the_answer_and_reports_a_silent_failure(monkeypatch, tmp_path):
    from magpiary import ask_codex

    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))
    monkeypatch.setattr(ask_codex, "binary", lambda: "codex")
    monkeypatch.setattr(ask_codex, "confined", lambda: True)

    class Proc:
        def __init__(self, lines):
            self.stdin = SimpleNamespace(write=lambda t: None, close=lambda: None)
            self.stdout, self.stderr = iter(lines), SimpleNamespace(read=lambda: "")
        def wait(self): return 0
        def kill(self): pass

    got = []
    text = ask_codex.run("q", [], [], "your whole library", got.append, popen=lambda *a, **k: Proc([l + "\n" for l in CODEX_RUN]))
    assert text == "Example Finch Work is an agent."
    with pytest.raises(Exception, match="no answer"):
        ask_codex.run("q", [], [], "x", got.append, popen=lambda *a, **k: Proc(["{}\n"]))


def test_codex_can_be_chosen_with_its_model_and_effort_never_above_medium(mac, lib, monkeypatch):
    from magpiary import ask_codex, askconfig

    monkeypatch.setattr(ask_codex, "available", lambda: True)
    assert 'aria-label="Use Codex' in page(mac, "/settings/ask")[2]
    post(mac, "/hub/askset", engine="codex", cmodel="gpt-6-sol", ceffort="high", next="/settings/ask")
    assert mac.store.get_setting(askconfig.ENGINE) == "codex" and mac.store.get_setting(askconfig.CODEX_MODEL) == "gpt-6-sol"
    assert askconfig.codex_effort(mac.store) == "medium"  # "high" is refused
    engine = mac.server.hub.ask_engine()
    assert engine["id"] == "codex" and engine["model"] == "GPT-6 Sol"
    panel = page(mac, "/ask/panel?scope=library:all")[2]
    assert "Codex · GPT-6 Sol · Medium" in panel and 'class="enginelogo"' in panel


def test_each_keys_provider_answers_with_its_own_web_search(monkeypatch):
    from magpiary import ask_keys, providers

    steps, key = [], SimpleNamespace(provider="gemini", model="gemini-x", secret="s")
    seen = {}

    def fake_call(method, url, secret, body, timeout):
        seen["body"] = body
        return 200, {"candidates": [{"content": {"parts": [{"text": "Answer."}]}, "groundingMetadata": {
            "webSearchQueries": ["example finch"], "groundingChunks": [{"web": {"uri": "https://a.test/x", "title": "A"}}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}
    monkeypatch.setattr(ask_keys, "http_call", fake_call)
    text, used = ask_keys.gemini(key, "p", [], True, steps.append)
    assert seen["body"]["tools"] == [{"google_search": {}}] and steps[0]["arg"] == "example finch" and "[A](https://a.test/x)" in text and used == {"in": 10, "out": 5}
    ask_keys.gemini(key, "p", [], False, steps.append)
    assert "tools" not in seen["body"]
    bodies = {}

    def fake_request(method, url, headers, body, timeout):
        bodies[url] = body
        if url.endswith("/responses"):
            return 200, {"output": [{"type": "web_search_call", "action": {"query": "q1"}}, {"type": "message", "content": [
                {"type": "output_text", "text": "Hi", "annotations": [{"type": "url_citation", "url": "https://b.test", "title": "B"}]}]}],
                "usage": {"input_tokens": 7, "output_tokens": 3}}
        return 200, {"choices": [{"message": {"content": "Yo", "annotations": [{"type": "url_citation", "url_citation": {"url": "https://c.test", "title": "C"}}]}}],
                     "usage": {"prompt_tokens": 4, "completion_tokens": 2}}
    monkeypatch.setattr(providers, "http_request", fake_request)
    t, u = ask_keys.openai(SimpleNamespace(model="gpt", secret="s"), "p", [], True, steps.append)
    assert bodies[providers.OPENAI + "/responses"]["tools"] == [{"type": "web_search"}] and "https://b.test" in t and u == {"in": 7, "out": 3}
    t, u = ask_keys.openrouter(SimpleNamespace(model="m", secret="s"), "p", [], True, steps.append)
    assert bodies[providers.OPENROUTER + "/chat/completions"]["plugins"][0]["id"] == "web" and "https://c.test" in t and u == {"in": 4, "out": 2}


def test_asking_from_a_tab_knows_the_place_and_asks_questions_that_fit_it(mac, lib):
    mac.store.save_auto_pile(None, [mac.store.item_by_id(lib[k])["canonical_url"] for k in ("ig", "yt")], "Pasta", keep_name=True)
    piles = page(mac, "/ask/panel?scope=library:piles")[2]
    assert "Asking about your piles · 1 pile" in piles and "What is in Pasta and why did I save it?" in piles and "your piles" in piles
    boards = page(mac, "/ask/panel?scope=library:boards")[2]
    assert "Asking about your boards" in boards and 'data-scope="library:boards"' in boards
    ev = page(mac, "/ask/panel?scope=library:everything")[2]
    assert "Asking about everything you saved" in ev and "What have I saved this week?" in ev
    place = mac.server.hub.ask_place("library:piles", "your piles", [])
    assert "Pasta (2)" in place["context"]
    assert "This post · " in page(mac, f"/ask/panel?scope=post:{lib['ig']}")[2]
    assert "library:auto" in page(mac, "/")[2]


def test_ask_has_a_page_of_its_own_with_chats_on_the_left_and_a_place_picker(mac, lib):
    store = mac.store
    store.ask_add("library:all", "user", "What is new in Claude?")
    store.ask_add("library:all", "assistant", "Opus 5.5.", {"open": True, "steps": [], "usage": {}, "seconds": 1})
    store.ask_add(f"post:{lib['ig']}", "user", "Explain this post")
    body = page(mac, "/ask")[2]
    assert "data-asknewchat" in body and "What is new in Claude?" in body and "Explain this post" in body and 'data-askplace' in body
    assert 'class="askp askfull" data-scope="library:all"' in body and "Whole library" in body
    assert 'class="askp askfull" data-scope="library:piles"' in page(mac, "/ask?scope=library:piles")[2]
    assert 'data-scope="library:all"' in page(mac, "/ask?scope=nonsense")[2]  # an unknown place falls back to the library
    post(mac, "/hub/ask/clear", scope="library:all")
    sid = store.ask_sessions()[0]["id"]
    assert f'data-askopen="{sid}"' in page(mac, "/ask")[2]
    plain = page(mac, f"/ask/session?id={sid}&plain=1")[2]
    assert "Opus 5.5." in plain and "askplain" in plain and "<textarea" not in plain
    panel = page(mac, "/ask/panel?scope=library:all")[2]
    assert "data-askmin" in panel and 'href="/ask?scope=library:all"' in panel
    mac.store.set_setting("ask_on", "0")
    assert page(mac, "/ask")[0] == 303


def test_the_page_scripts_have_no_syntax_errors():
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    for name in ("hub.js", "settings.js", "lock.js"):
        done = subprocess.run([node, "--check", str(Path(__file__).parent.parent / "src" / "magpiary" / "static" / name)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr[:300]


def test_a_past_chat_can_be_continued_pinned_and_deleted_and_the_sheet_lists_live_chats_too(mac, lib):
    store = mac.store
    store.ask_add("library:all", "user", "First question")
    store.ask_add("library:all", "assistant", "First answer.", {"open": True, "steps": [], "usage": {}, "seconds": 1})
    store.ask_add(f"post:{lib['ig']}", "user", "About this post")  # a chat still going somewhere else
    listing = page(mac, "/ask/sessions")[2]
    assert "About this post" in listing and "data-asklive" in listing and "Now" in listing  # the sheet shows live chats too
    post(mac, "/hub/ask/clear", scope="library:all")
    sid = store.ask_sessions()[0]["id"]
    assert 'data-askmenu' in page(mac, "/ask/sessions")[2]
    post(mac, "/hub/ask/session-pin", id=str(sid), on="1")
    assert store.ask_sessions()[0]["pinned"] == 1 and "Pinned" in page(mac, "/ask/sessions")[2]
    store.ask_add("library:all", "user", "A newer chat")
    store.ask_add("library:all", "assistant", "Newer answer.", {"open": True, "steps": [], "usage": {}, "seconds": 1})
    status, _, body = post(mac, "/hub/ask/session-resume", id=str(sid))
    assert json.loads(body)["scope"] == "library:all"
    assert [m["text"] for m in store.ask_thread("library:all")] == ["First question", "First answer."]  # carried on where it stopped
    assert [s["title"] for s in store.ask_sessions()] == ["A newer chat"]  # the live one that was there is kept as a past chat
    post(mac, "/hub/ask/live-delete", scope=f"post:{lib['ig']}")
    assert store.ask_thread(f"post:{lib['ig']}") == []
    post(mac, "/hub/ask/session-delete", id=str(store.ask_sessions()[0]["id"]))
    assert store.ask_sessions() == []


def test_the_full_page_has_a_controls_column_whose_changes_come_back_to_the_page(mac, lib, monkeypatch):
    monkeypatch.setattr(asking, "claude_available", lambda: True)
    body = page(mac, "/ask?scope=library:piles")[2]
    assert "data-askctlcol" in body and "data-askctl" in body and "Tokens used" in body and "All Ask settings" in body
    assert 'name="next" value="/ask?scope=library:piles"' in body or "/ask?scope=library:piles" in body
    status, headers, _ = post(mac, "/hub/askset", web="0", next="/ask?scope=library:piles")
    assert status == 303 and headers["Location"] == "/ask?scope=library:piles"
    assert post(mac, "/hub/askset", web="1", next="https://evil.test/")[1]["Location"] == "/settings/ask"  # only Ask's own page is allowed back
    assert 'data-askdockstate' in page(mac, "/")[2]


def test_answer_depth_is_remembered_changes_the_prompt_and_the_run_limits(mac):
    assert 'data-askdepth="short"' in page(mac, "/ask/panel?scope=library:all")[2] and askconfig.depth(mac.store) == "normal"
    post(mac, "/hub/ask/depth", depth="deep")
    assert askconfig.depth(mac.store) == "deep" and 'data-askdepth="deep" class="on"' in page(mac, "/ask/panel?scope=library:all")[2]
    post(mac, "/hub/ask/depth", depth="nonsense")
    assert askconfig.depth(mac.store) == "deep"
    assert "Go deep" in ask_open.system("deep") and "Be economical" in ask_open.system("short") and "Be economical" not in ask_open.system("normal")
    cmd = lambda depth: ask_open.command("claude", depth=depth)
    assert cmd("short")[cmd("short").index("--max-turns") + 1] == "8" and cmd("deep")[cmd("deep").index("--max-turns") + 1] == "24"
    post(mac, "/hub/askset", depth="short", next="/settings/ask")
    assert askconfig.depth(mac.store) == "short"


def test_a_failed_answer_says_what_to_do():
    from magpiary.brain import BrainFailed
    from magpiary.hub_ask import AskPages  # noqa
    text = AskPages._ask_failure("Gemini", BrainFailed("bad_key", "Gemini refused the key (HTTP 400)"))
    assert "Settings" in text and "kept" in text and "HTTP" not in text
    assert "limit" in AskPages._ask_failure("Gemini", BrainFailed("rate_limited", "x"))
