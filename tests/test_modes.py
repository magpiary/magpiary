"""Smart and Private: who may write the next summary."""

import pytest

from magpiary import modes
from magpiary.store import Store
from test_hub import page, post


class Keys:
    def __init__(self, usable=(), saved=()):
        self._usable, self._saved = list(usable), list(saved or usable)

    def usable(self):
        return self._usable

    def load(self):
        return self._saved


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


@pytest.mark.parametrize("saved, expected", [
    ({}, "smart"), ({"ai_mode": "private"}, "private"), ({"ai_mode": "none"}, "private"),
    ({"no_ai_for_now": "1"}, "private"), ({"ai_mode": "balanced"}, "smart"),  # earlier choices carry over
])
def test_the_mode_and_earlier_choices(store, saved, expected):
    for key, value in saved.items():
        store.set_setting(key, value)
    assert modes.current(store) == expected


def test_smart_uses_the_keys_and_says_why_it_waits(store):
    assert modes.summarisers(store, Keys(["gemini", "openrouter"])) == ["gemini", "openrouter"]
    assert "reached its limit" in modes.waiting_reason(store, Keys([], ["gemini"]))
    assert "Add an AI key" in modes.waiting_reason(store, Keys())
    assert modes.waiting_reason(store, Keys(["gemini"])) == ""


def test_private_sends_nothing_to_any_ai(store, tmp_path):
    from magpiary.worker import brain_due

    store.set_setting(modes.SETTING, "private")
    assert modes.summarisers(store, Keys(["gemini"])) == [] and "Private" in modes.waiting_reason(store, Keys(["gemini"]))
    url = "https://www.instagram.com/reel/MODE1/"
    folder = tmp_path / "f"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.senses_done(url, "")
    used = []
    brain_due(store, tmp_path, pause=lambda t: None, process=lambda item, key, p: used.append(key), key_source=Keys(["gemini"]))
    assert used == []


def test_settings_shows_two_modes_and_saves_the_choice(mac, monkeypatch):
    from magpiary import engines
    from magpiary import keys as keyring
    from magpiary.keys import Key

    body = page(mac, "/settings/ai")[2]
    assert "Enable Smart Summaries" in body and "Balanced" not in body and "local model" not in body.lower()
    assert "modestat private" in body and "Add a key" in body  # no key: reads Private, and the switch says why
    status, headers, _ = post(mac, "/hub/settings/mode", mode="smart", next="/settings/ai")
    assert "#keys" in headers["Location"]
    monkeypatch.setattr(keyring, "load", lambda: [Key("g1", "gemini", "free", "s", "", "m", "")])
    body = page(mac, "/settings/ai")[2]
    assert "modestat smart" in body and "Switch to Private" in body  # a key: Smart by itself
    post(mac, "/hub/settings/mode", mode="private")
    assert mac.store.get_setting(modes.SETTING) == "private"
    post(mac, "/hub/settings/mode", mode="balanced")
    assert mac.store.get_setting(modes.SETTING) == "private"
    assert "modestat private" in page(mac, "/settings/ai")[2] and modes.effective(mac.store) == "private"
