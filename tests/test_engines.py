"""Claude Code and Codex are used only once allowed (dialog, then a test run); the Digest, Ask and Deeper dive follow one
rule: on by themselves with a local engine or a paid key, off with only free-tier keys (Deeper dive never uses those)."""

import json

import pytest

from magpiary import engines
from magpiary.keys import Key
from magpiary.store import Store
from test_hub import page, post

FREE = Key("f1", "gemini", "free", "s", "", "gemini-3.5-flash-lite", "")
PAID = Key("p1", "claude", "paid", "s", "", "claude-haiku-5-5", "")


@pytest.fixture
def store(tmp_path, monkeypatch):
    from magpiary import keys as keyring

    monkeypatch.setattr(engines, "installed", lambda kind: True)
    monkeypatch.setattr(keyring, "load", lambda: [FREE, PAID])
    return Store(tmp_path / "m.db")


def test_found_on_the_mac_is_not_allowed(store):
    assert engines.allowed(store) == [] and not engines.strong(store, [FREE])
    assert [o["id"] for o in engines.options(store, [FREE])] == ["key:f1"]


def test_only_a_passing_test_allows_it_and_the_owners_order_decides(store):
    ok, why = engines.allow(store, "codex", test=lambda kind: (False, "Codex did not answer the test."))
    assert not ok and "did not answer" in why and engines.allowed(store) == []
    assert engines.allow(store, "codex", test=lambda kind: (True, ""))[0]
    assert engines.allow(store, "claude_code", test=lambda kind: (True, ""))[0]
    keys = [FREE, PAID]
    assert [o["id"] for o in engines.options(store, keys)] == ["key:f1", "key:p1", "codex", "claude_code"]  # each joins the end when allowed
    assert engines.choice(store, "digest", keys)["id"] == "key:p1"  # the first that is not a free key
    assert [getattr(s, "id") for s in engines.summarisers(store, [FREE, PAID], today="2026-11-04")] == ["f1", "p1", "codex", "claude_code"]


def test_dragging_claude_code_to_the_top_makes_it_write_summaries(store, monkeypatch):
    from magpiary import keys as keyring

    monkeypatch.setattr(keyring, "reorder", lambda ids: None)
    keys = [FREE, PAID]
    assert [s.id for s in engines.summarisers(store, keys, today="2026-11-04")] == ["f1", "p1"]  # not allowed: skipped
    engines.allow(store, "claude_code", test=lambda kind: (True, ""))
    assert engines.summarisers(store, keys, today="2026-11-04")[-1].id == "claude_code"  # allowed: last until dragged up
    assert not engines.set_order(store, ["claude_code", "key:f1"], keys)  # every one must be in the new order
    assert engines.set_order(store, ["claude_code", "key:f1", "key:p1", "codex"], keys)
    first = engines.summarisers(store, keys, today="2026-11-04")[0]
    assert first.id == "claude_code" and first.provider == "claude_code" and first.model == "sonnet" and first.effort == "low"
    assert engines.choice(store, "ask", keys)["id"] == "claude_code"

def test_free_keys_only_everything_off_digest_and_ask_can_be_turned_on_deeper_dive_never(store):
    keys = [FREE]
    assert not any(engines.is_on(store, f, keys) for f in engines.FEATURES) and engines.only_free(store, keys)
    engines.set_on(store, "digest", True)
    engines.set_on(store, "deep", True)
    assert engines.is_on(store, "digest", keys) and not engines.is_on(store, "deep", keys)
    assert engines.choice(store, "deep", keys) is None
    assert "free key" in engines.warning("digest")


def test_a_paid_key_or_an_allowed_engine_turns_them_on_and_stopping_falls_back(store):
    assert all(engines.is_on(store, f, [PAID]) for f in engines.FEATURES)
    engines.allow(store, "claude_code", test=lambda kind: (True, ""))
    engines.set_on(store, "ask", False)
    assert not engines.is_on(store, "ask", [FREE])  # the owner's off is kept
    engines.allow(store, "codex", test=lambda kind: (True, ""))
    assert engines.is_on(store, "ask", [FREE])  # allowing again turns the three back on
    engines.choose(store, "deep", "codex", [FREE])
    engines.disallow(store, "codex", [FREE])
    assert engines.choice(store, "deep", [FREE])["id"] == "claude_code"  # moved to the next
    engines.disallow(store, "claude_code", [FREE])
    assert not engines.is_on(store, "digest", [FREE]) and not engines.is_on(store, "deep", [FREE])


def test_allowing_in_settings_runs_the_test_and_explains_a_failure(mac, monkeypatch):
    monkeypatch.setattr(engines, "installed", lambda kind: True)
    monkeypatch.setattr(engines, "test_run", lambda kind, run=None: (False, "Claude Code did not answer the test. Run claude in Terminal once and sign in."))
    body = page(mac, "/settings/ai")[2]
    assert "Claude Code on this Mac" in body and "Codex on this Mac" in body and "Allow Claude Code on this Mac?" in body
    status, headers, _ = post(mac, "/hub/engine/allow", kind="claude_code", enabled="1", next="/settings/ai")
    assert "error=" in headers["Location"] and engines.allowed(mac.store) == []
    monkeypatch.setattr(engines, "test_run", lambda kind, run=None: (True, ""))
    post(mac, "/hub/engine/allow", kind="claude_code", enabled="1", next="/settings/ai")
    assert engines.allowed(mac.store) == ["claude_code"]
    post(mac, "/hub/engine/allow", kind="claude_code", enabled="0", next="/settings/ai")
    assert engines.allowed(mac.store) == []


def test_keys_take_the_order_they_are_dragged_into(mac, monkeypatch):
    from magpiary import keys as keyring

    saved = [Key("aaaa0001", "gemini", "free", "s", "", "m", ""), Key("bbbb0002", "tavily", "free", "s", "", "", ""),
             Key("cccc0003", "openrouter", "free", "s", "", "m", "")]
    store_keys = {"list": saved}
    monkeypatch.setattr(keyring, "load", lambda: list(store_keys["list"]))
    monkeypatch.setattr(keyring, "_save", lambda keys: store_keys.update(list=keys))
    post(mac, "/hub/keys/order", ids="key:cccc0003,claude_code,key:aaaa0001,codex", next="/settings/ai")
    assert [k.id for k in store_keys["list"]] == ["cccc0003", "bbbb0002", "aaaa0001"]  # the search key keeps its place
    post(mac, "/hub/keys/order", ids="key:cccc0003,key:cccc0003,codex", next="/settings/ai")  # nonsense changes nothing
    assert [k.id for k in store_keys["list"]] == ["cccc0003", "bbbb0002", "aaaa0001"]
    body = page(mac, "/settings/ai")[2]
    assert "data-keylist" in body and body.count("data-keyhandle") == 4  # two keys, Claude Code and Codex, in one list
    assert body.index('id="key-cccc0003"') < body.index('id="key-aaaa0001"') < body.index('id="local-claude_code"')  # not in use: below
    assert body.count("data-keyhandle disabled") == 2


def test_a_summary_by_claude_code_gets_the_pictures_as_files_and_the_summary_rules(monkeypatch):
    import base64

    from magpiary import brain, deepdive

    seen = {}

    def fake(model, effort):
        def ask(system, schema, parts, images):
            seen.update(model=model, system=system, schema=schema, text=parts[0]["text"], images=[p.read_bytes() for p in images])
            return json.dumps({"title": "T", "summary": "S.", "key_points": [], "type": "other", "entities": {}, "suggested_tags": []})
        return ask
    monkeypatch.setattr(deepdive, "claude_code_asker", fake)
    parts = [{"text": "CAPTION: hello"}, {"text": "FRAME at 0:01"},
             {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b"\xff\xd8pic").decode()}}]
    record = brain.summarise(parts, "local", "haiku", provider="claude_code")
    assert record["title"] == "T" and seen["model"] == "haiku" and seen["system"] is brain.PROMPT and seen["schema"] is brain.SCHEMA
    assert seen["images"] == [b"\xff\xd8pic"] and "CAPTION: hello" in seen["text"]
