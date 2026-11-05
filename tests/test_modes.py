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


def test_the_next_n_allowance_is_kept_while_nobody_can_write_a_summary(store, tmp_path):
    """Review 4 Nov 2026: "next 1" was used up in Private mode, so turning Smart on later found summaries paused."""
    from magpiary.worker import brain_due

    store.set_setting(modes.SETTING, "private")
    store.set_setting("ai_budget", "1")
    url = "https://www.instagram.com/reel/MODE2/"
    folder = tmp_path / "g"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.senses_done(url, "")
    brain_due(store, tmp_path, pause=lambda t: None, process=lambda item, key, p: None, key_source=Keys(["gemini"]))
    assert store.summary_budget() == "1"


def test_a_failed_transcript_is_not_marked_done_and_is_tried_again_the_next_day(store, tmp_path):
    """Review 4 Nov 2026: a transcription that raised was marked done, so it never came back."""
    from magpiary.worker import brain_due

    url = "https://www.instagram.com/reel/MODE3/"
    folder = tmp_path / "h"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    tries = []

    def broken(item, progress):
        tries.append(1)
        raise RuntimeError("whisper fell over")
    run = lambda: brain_due(store, tmp_path, pause=lambda t: None, process=lambda i, k, p: None,  # noqa: E731
                            prepare=broken, key_source=Keys([]))
    run()
    run()
    assert len(tries) == 1 and store.get_item(url)["senses_status"].startswith("failed:")
    store._db.execute("UPDATE items SET senses_status='failed:2000-01-01' WHERE canonical_url=?", (url,))
    run()
    assert len(tries) == 2


def test_a_transcript_whisper_could_not_make_is_failed_not_done(store, tmp_path):
    """Review 2, 4 Nov 2026: senses() catches Whisper's failure and returns it as a problem; that is a failure too."""
    from magpiary.worker import brain_due

    url = "https://www.instagram.com/reel/MODE4/"
    folder = tmp_path / "w"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    brain_due(store, tmp_path, pause=lambda t: None, process=lambda i, k, p: None,
              prepare=lambda item, progress: ([], [], "whisper exited 1"), key_source=Keys([]))
    assert store.get_item(url)["senses_status"].startswith("failed:")


def test_the_real_transcriber_is_called_not_shadowed(store, tmp_path, monkeypatch):
    """Found by pyflakes in review 7, 4 Nov 2026: a local variable named `senses` hid process.senses, so the default
    prepare() called a string and every transcript failed. The default path is used here, with senses() stubbed."""
    from magpiary import process
    from magpiary.worker import brain_due

    called = []
    monkeypatch.setattr(process, "senses", lambda folder, meta, progress=None: called.append(folder) or ([], [], ""))
    url = "https://www.instagram.com/reel/MODE5/"
    folder = tmp_path / "s"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    brain_due(store, tmp_path, pause=lambda t: None, process=lambda i, k, p: None, key_source=Keys([]))
    assert called and store.get_item(url)["senses_status"] == "done"


def test_a_summary_of_a_page_captured_again_meanwhile_is_dropped(tmp_path):
    """The owner saves the page again (Save what I see) while its old summary is being written: that summary must not
    mark the new copy as summarised (review, 5 Nov 2026)."""
    from datetime import datetime, timedelta

    from magpiary.worker import brain_due

    t = [datetime(2026, 11, 5, 10, 0).astimezone()]
    store = Store(tmp_path / "m.db", now=lambda: t[0])
    url = "https://writers.example.org/paper-gardens"
    folder = tmp_path / "f"
    folder.mkdir()
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.senses_done(url, "")

    def process(item, key, progress):  # the capture lands and is archived while the AI is writing
        store.recaptured(url)
        t[0] += timedelta(seconds=30)
        store.fetch_succeeded(url, str(folder))
        return {"title": "Old page", "summary": "about the old page", "entities": {}}

    from types import SimpleNamespace

    key = SimpleNamespace(id="k1", name="Gemini", tier="free", provider="gemini", model="m")
    brain_due(store, tmp_path, pause=lambda t_: None, process=process, key_source=Keys([key]))
    assert store.get_item(url)["ai_status"] is None   # still to be summarised, from the new copy
    store.close()
