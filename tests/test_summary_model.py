"""The regular summary on Claude Code takes the owner's model and effort (AI keys), falls back to Haiku/low when that fails,
and the post records what ran. Recorded fixtures only: no live Claude calls."""

import json

import pytest

from magpiary import askconfig, brain, deepdive, engines
from magpiary.brain import BrainFailed
from magpiary.store import Store
from test_hub import page, post

RECORD = json.dumps({"title": "T", "summary": "S.", "key_points": [], "type": "other", "entities": {}, "suggested_tags": []})


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(engines, "installed", lambda kind: True)
    return Store(tmp_path / "m.db")


def test_defaults_are_sonnet_low_and_junk_values_are_ignored(store):
    assert (askconfig.summary_model(store), askconfig.summary_effort(store)) == ("sonnet", "low")
    store.set_setting(askconfig.SUMMARY_MODEL, "gpt-9")
    store.set_setting(askconfig.SUMMARY_EFFORT, "max")  # the CLI takes it, the owner's list does not offer it
    assert (askconfig.summary_model(store), askconfig.summary_effort(store)) == ("sonnet", "low")


def test_the_engine_carries_the_chosen_model_and_effort(store):
    engines.allow(store, "claude_code", test=lambda kind: (True, ""))
    store.set_setting(askconfig.SUMMARY_MODEL, "opus")
    store.set_setting(askconfig.SUMMARY_EFFORT, "high")
    eng = engines.summarisers(store, [])[0]
    assert (eng.model, eng.effort) == ("opus", "high")


def test_chosen_model_is_passed_and_recorded(monkeypatch):
    seen, used = [], {}
    monkeypatch.setattr(deepdive, "claude_code_asker", lambda m, e: (seen.append((m, e)), lambda *a: RECORD)[1])
    brain.summarise([{"text": "x"}], "local", "opus", provider="claude_code", ask=brain.local_asker("claude_code", "opus", "high", used))
    assert seen == [("opus", "high")] and used["model"] == "opus" and used["effort"] == "high" and not used["fell_back"]


def test_an_unavailable_model_falls_back_to_haiku_low_and_says_so(monkeypatch):
    seen, used = [], {}

    def fake(model, effort):
        def ask(*a):
            seen.append((model, effort))
            if model == "opus":
                raise BrainFailed("unknown", "Claude Code stopped without a usable answer")
            return RECORD
        return ask
    monkeypatch.setattr(deepdive, "claude_code_asker", fake)
    record = brain.summarise([{"text": "x"}], "local", "opus", provider="claude_code",
                             ask=brain.local_asker("claude_code", "opus", "high", used))
    assert record["title"] == "T" and seen == [("opus", "high"), ("haiku", "low")]
    assert used["fell_back"] and (used["model"], used["effort"]) == ("haiku", "low") and used["why"]


def test_the_default_failing_is_not_retried(monkeypatch):
    calls = []

    def fake(model, effort):
        def ask(*a):
            calls.append(model)
            raise BrainFailed("unknown", "nope")
        return ask
    monkeypatch.setattr(deepdive, "claude_code_asker", fake)
    with pytest.raises(BrainFailed):
        brain.local_asker("claude_code", "haiku", "low")([{"text": "x"}], [])
    assert calls == ["haiku"]


def test_settings_shows_the_pick_only_when_allowed_and_saves_it(mac, monkeypatch):
    monkeypatch.setattr(engines, "installed", lambda kind: True)
    assert 'name="effort"' not in page(mac, "/settings/ai")[2] or "Summary model" not in page(mac, "/settings/ai")[2]
    engines.allow(mac.store, "claude_code", test=lambda kind: (True, ""))
    body = page(mac, "/settings/ai")[2]
    assert "Summary model" in body and "uses the most of your plan" in body and "Haiku at low effort" in body
    post(mac, "/hub/summary-pick", model="opus", effort="medium")
    assert (askconfig.summary_model(mac.store), askconfig.summary_effort(mac.store)) == ("opus", "medium")
    post(mac, "/hub/summary-pick", model="bogus", effort="max")
    assert (askconfig.summary_model(mac.store), askconfig.summary_effort(mac.store)) == ("opus", "medium")
