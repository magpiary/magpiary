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
    monkeypatch.setattr(engines, "installed", lambda kind: True)
    return Store(tmp_path / "m.db")


def test_found_on_the_mac_is_not_allowed(store):
    assert engines.allowed(store) == [] and not engines.strong(store, [FREE])
    assert [o["id"] for o in engines.options(store, [FREE])] == ["key:f1"]


def test_only_a_passing_test_allows_it_and_the_first_allowed_comes_first(store):
    ok, why = engines.allow(store, "codex", test=lambda kind: (False, "Codex did not answer the test."))
    assert not ok and "did not answer" in why and engines.allowed(store) == []
    assert engines.allow(store, "codex", test=lambda kind: (True, ""))[0]
    assert engines.allow(store, "claude_code", test=lambda kind: (True, ""))[0]
    assert [o["id"] for o in engines.options(store, [FREE, PAID])] == ["codex", "claude_code", "key:p1", "key:f1"]
    assert engines.choice(store, "digest", [FREE])["id"] == "codex"


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
