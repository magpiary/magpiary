"""Review regressions replay saved inputs; no downloader, model or provider is contacted."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from magpiary import archive, askconfig, boards, digest, identity
from magpiary.hub import Hub
from magpiary.store import ASK_SCHEMA, Store
from magpiary.worker import brain_due
from test_fetch import FakeYtDlp, IG_INFO, pages
from test_modes import Keys


@pytest.fixture
def recorded():
    return json.loads((Path(__file__).parent / "fixtures" / "review_regressions.json").read_text())


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "review.db")
    yield s
    s.close()


@pytest.mark.parametrize("mode,available", [("private", True), ("smart", False), ("smart", True)])
def test_all_items_transcribe_without_a_summariser(store, tmp_path, recorded, mode, available):
    from magpiary.brain import BrainFailed

    store.set_setting("ai_mode", mode)
    urls = recorded["urls"][:2]
    for n, url in enumerate(urls):
        folder = tmp_path / str(n)
        folder.mkdir()
        (folder / "meta.json").write_text(json.dumps(recorded["meta"]))
        store.add_link(url)
        store.fetch_succeeded(url, str(folder))
    prepared, used = [], []
    keys = Keys([SimpleNamespace(id="fixture", name="Fixture", tier="free")] if available else [])

    def prepare(item, progress):
        prepared.append(item["canonical_url"])
        (Path(item["archive_dir"]) / "transcript.json").write_text(json.dumps(recorded["transcript"]))

    def refused(item, key, progress):
        used.append(key.id)
        raise BrainFailed("bad_key", "recorded refusal")

    keys.mark = lambda *a, **k: keys._usable.clear()
    assert brain_due(store, tmp_path / "notes", prepare=prepare, process=refused,
                     key_source=keys, pause=lambda tier: None) == 0
    assert set(prepared) == set(urls)
    assert all(store.get_item(url)["senses_status"] == "done" for url in urls)
    assert all("paper wing" in store.get_item(url)["transcript_text"] for url in urls)
    assert used == (["fixture"] if mode == "smart" and available else [])


@pytest.mark.parametrize("chosen,wanted", [("key", "selected"), ("key", ""), ("claude", "selected"), ("codex", "selected")])
def test_ask_never_substitutes_an_unselected_key(store, recorded, monkeypatch, chosen, wanted):
    hub = Hub(store)
    store.set_setting("ask_state", "on")
    store.set_setting(askconfig.ENGINE, chosen)
    store.set_setting(askconfig.KEY, wanted)
    selected, other = [SimpleNamespace(**k) for k in recorded["keys"]]
    monkeypatch.setattr("magpiary.keys.usable", lambda: [other])
    monkeypatch.setattr("magpiary.ask.claude_available", lambda: False)
    monkeypatch.setattr("magpiary.ask_codex.available", lambda: False)
    assert hub.ask_engine() is None
    store.set_setting(askconfig.ENGINE, "key")
    store.set_setting(askconfig.KEY, selected.id)
    monkeypatch.setattr("magpiary.keys.usable", lambda: [other, selected])
    assert hub.ask_engine()["key"] is selected


def test_purged_item_ids_cannot_be_inherited_after_reopen(tmp_path, recorded):
    path = tmp_path / "ids.db"
    s = Store(path)
    url, new = recorded["urls"][:2]
    s.add_link(url)
    old_id = s.id_for(url)
    scope = f"post:{old_id}"
    for msg in recorded["chat"]:
        s.ask_add(scope, msg["role"], msg["text"])
    session = s.ask_end(scope, "Pasta")
    s.ask_add(scope, "user", recorded["chat"][0]["text"])
    s.save_digest("weekly", recorded["made_at"], recorded["made_at"],
                  {"story": {"picks": [{"saves": [old_id]}]}})
    s.set_shelf(old_id, "trash")
    s.purge_trash(everything=True)
    s.close()
    s = Store(path)
    try:
        s.add_link(new)
        assert s.id_for(new) > old_id
        assert s.item_by_id(old_id) is None
        assert s.ask_thread(f"post:{s.id_for(new)}") == []
        assert s.ask_session(session)["scope"] == scope
    finally:
        s.close()


def test_legacy_id_migration_preserves_rows_and_reserves_historical_references(tmp_path, recorded):
    path = tmp_path / "legacy.db"
    # Recorded pre-fix schema, with a gap in the rowids and a deleted digest pick (47).
    db = sqlite3.connect(path)
    db.executescript((Path(__file__).parent / "fixtures" / "legacy_queue.sql").read_text())
    db.executescript(ASK_SCHEMA)
    for rowid, url in zip((3, 12), recorded["urls"]):
        db.execute("INSERT INTO items (rowid, canonical_url, source, status, created_at, updated_at) VALUES (?,?,?,'queued',?,?)",
                   (rowid, url, "instagram", recorded["made_at"], recorded["made_at"]))
    db.execute("INSERT INTO digests (kind,start,end,made_at,data) VALUES ('weekly',?,?,?,?)",
               (recorded["made_at"], recorded["made_at"], recorded["made_at"], json.dumps({"story": recorded["story"]})))
    db.execute("CREATE INDEX recorded_items_source ON items(source)")
    db.execute("INSERT INTO ask_notes (scope,text,at) VALUES ('post:64',?,?)",
               (recorded["chat"][1]["text"], recorded["made_at"]))
    db.execute("INSERT INTO ask_messages (scope,role,text,meta,at) VALUES ('library:all','assistant',?,?,?)",
               (recorded["chat"][1]["text"], json.dumps({"posts": [80]}), recorded["made_at"]))
    db.commit()
    db.close()
    s = Store(path)
    try:
        assert [s.id_for(u) for u in recorded["urls"][:2]] == [3, 12]
        s.add_link(recorded["urls"][2])
        assert s.id_for(recorded["urls"][2]) > 80
        assert s.integrity() == "ok"
        assert s._db.execute("SELECT name FROM sqlite_master WHERE name='recorded_items_source'").fetchone()
    finally:
        s.close()
    s = Store(path)
    try:
        assert [s.id_for(u) for u in recorded["urls"][:2]] == [3, 12]
        assert s.integrity() == "ok"
    finally:
        s.close()


def test_item_id_migration_rolls_back_on_failure(tmp_path, recorded):
    db = sqlite3.connect(tmp_path / "rollback.db", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript((Path(__file__).parent / "fixtures" / "legacy_queue.sql").read_text())
    db.executescript(ASK_SCHEMA)
    db.execute("INSERT INTO items (rowid,canonical_url,source,status,created_at,updated_at) VALUES (12,?,'instagram','queued',?,?)",
               (recorded["urls"][0], recorded["made_at"], recorded["made_at"]))
    s = Store.__new__(Store)
    s._db = db
    db.set_authorizer(lambda op, name, *rest: sqlite3.SQLITE_DENY if op == sqlite3.SQLITE_DROP_TABLE and name == "items"
                      else sqlite3.SQLITE_OK)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            s._migrate_item_ids()
        assert not db.in_transaction
        assert db.execute("SELECT rowid FROM items").fetchone()[0] == 12
        assert "id" not in {r["name"] for r in db.execute("PRAGMA table_info(items)")}
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='items_with_ids'").fetchone()
        db.set_authorizer(None)
        s._migrate_item_ids()
        assert db.execute("SELECT id FROM items").fetchone()[0] == 12
    finally:
        db.close()


def test_archive_folders_are_unique_and_keep_matching_legacy_archives(tmp_path, recorded):
    reel, post = recorded["urls"][:2]
    assert archive.slug(reel, "instagram") != archive.slug(post, "instagram")
    legacy = tmp_path / "instagram-Example0020"
    legacy.mkdir()
    (legacy / "meta.json").write_text(json.dumps({"url": reel, **recorded["meta"]}))
    (legacy / "record.json").write_text(json.dumps(recorded["story"]))
    fake = FakeYtDlp(infos={reel: IG_INFO, post: IG_INFO})
    first = archive.fetch_item({"canonical_url": reel, "source": "instagram", "archive_dir": str(legacy)},
                               tmp_path, pages({}), fake)
    second = archive.fetch_item({"canonical_url": post, "source": "instagram"}, tmp_path, pages({}), fake)
    assert first == legacy and second != first
    assert json.loads((first / "meta.json").read_text())["url"] == reel
    assert json.loads((second / "meta.json").read_text())["url"] == post


@pytest.mark.parametrize("separate_connections", [False, True])
def test_board_sequence_allocation_and_insert_are_atomic(tmp_path, recorded, monkeypatch, separate_connections):
    path = tmp_path / "events.db"
    stores = [Store(path) for _ in recorded["board_events"]] if separate_connections else [Store(path)]
    member = identity.public_key()
    monkeypatch.setattr(boards, "board_key", lambda board_id: bytes(32))
    original = Store.next_board_seq

    def slow_allocation(self, board_id, who):
        seq = original(self, board_id, who)
        time.sleep(0.02)  # expose the former gap between allocating and inserting
        return seq

    monkeypatch.setattr(Store, "next_board_seq", slow_allocation)
    start = Barrier(len(recorded["board_events"]))

    def write(n):
        start.wait(timeout=5)
        return boards.write(stores[n] if separate_connections else stores[0], recorded["board"],
                            "add", **recorded["board_events"][n])

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            seqs = list(pool.map(write, range(4)))
        assert sorted(seqs) == [1, 2, 3, 4]
        rows = stores[0].unpublished_board_events(recorded["board"], member)
        assert len(rows) == 4
        for row in rows:
            envelope = json.loads(row["signed"])
            event = json.loads(envelope["e"])
            assert event["seq"] == row["seq"]
            assert identity.verify(member, envelope["e"].encode(), envelope["s"])
        assert {ev["body"]["note"] for ev in stores[0].board_events(recorded["board"])} == {
            ev["note"] for ev in recorded["board_events"]}
    finally:
        for s in stores:
            s.close()


def test_board_signing_failure_rolls_back_the_allocation(store, recorded, monkeypatch):
    monkeypatch.setattr(boards, "board_key", lambda board_id: bytes(32))
    envelope = boards._envelope

    def failed(event):
        raise ValueError("Recorded signing failure")

    monkeypatch.setattr(boards, "_envelope", failed)
    with pytest.raises(ValueError, match="signing failure"):
        boards.write(store, recorded["board"], "add", **recorded["board_events"][0])
    assert store.board_events(recorded["board"]) == [] and not store._db.in_transaction
    monkeypatch.setattr(boards, "_envelope", envelope)
    assert boards.write(store, recorded["board"], "add", **recorded["board_events"][0]) == 1


@pytest.mark.parametrize("existing_target", [False, True])
def test_expansion_migrates_and_deduplicates_board_pending(store, recorded, existing_target):
    from magpiary.cleaner import clean

    short, url, board = recorded["short"], recorded["urls"][0], recorded["board"]
    store.add_link(short)
    if existing_target:
        store.add_link(url)
        store.add_board_pending(board, url, "Existing canonical note")
    store.add_board_pending(board, short, "Short link note")
    store.add_board_pending("other-board", short, "Another board")
    store.expansion_succeeded(short, clean(url))
    rows = store.board_pending()
    assert len(rows) == 2 and {r["canonical_url"] for r in rows} == {url}
    assert next(r for r in rows if r["board_id"] == board)["note"] == (
        "Existing canonical note" if existing_target else "Short link note")
    assert next(r for r in rows if r["board_id"] == "other-board")["note"] == "Another board"
    store.expansion_succeeded(short, clean(url))
    assert store.board_pending() == rows


def test_profile_events_keep_only_sanitized_extras(store, recorded):
    body = boards._clean(recorded["profile"])
    for k, value in recorded["clean_profile"].items():
        assert body[k] == value
    assert "ignored" not in body
    store.save_board(recorded["board"], "Cooking", "friend", "nostr")
    store.add_board_event(recorded["board"], "friend", 1, 1, "profile", body, "")
    shown = boards.view(store, recorded["board"])["members"]["friend"]
    assert all(shown[k] == v for k, v in recorded["clean_profile"].items())
    # Card links still use the card list format, and missing profile extras clear old values.
    assert boards._clean({"type": "add", "links": [{"name": "Pasta", "url": "https://example.com"}]})["links"]
    assert boards._clean({"type": "profile"})["links"] == {}


@pytest.mark.parametrize("expiry", [False, True])
def test_purge_removes_generated_notes_with_media(store, tmp_path, recorded, expiry):
    library = tmp_path / "library"
    folder = library / "instagram-Example0020"
    folder.mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / f"{folder.name}.md"
    note.write_text(recorded["meta"]["text"])
    keep = notes / "unrelated.md"
    keep.write_text("Keep")
    url = recorded["urls"][0]
    store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.set_shelf(store.id_for(url), "trash")
    hub = Hub(store, library)
    if expiry:
        store._db.execute("UPDATE items SET trashed_at='2000-01-01T00:00:00'")
        assert hub.purge_old_trash() == 1
    else:
        hub._delete_folders(store.purge_trash(everything=True))
    assert not folder.exists() and not note.exists() and keep.exists()


def test_independent_hub_save_clears_board_provenance(store, recorded):
    url, board = recorded["urls"][0], recorded["board"]
    store.add_link(url)
    store.set_shelf(store.id_for(url), "board")
    assert store.to_library(board, {url}) == 1
    assert store.get_item(url)["via_board"] == board
    assert store.add_link(url).status == "again"
    assert store.get_item(url)["via_board"] is None
    assert store.from_library(board) == 0
    assert store.get_item(url)["shelf"] == "inbox"


def test_a_short_link_for_a_trashed_post_brings_it_back_with_its_note(store, recorded):
    """Review 4 Nov 2026: the merge left the post in the Trash and dropped the owner's note on the short link."""
    from magpiary.cleaner import clean

    short, url = recorded["short"], recorded["urls"][0]
    store.add_link(url)
    store.set_shelf(store.id_for(url), "trash")
    store.add_link(short)
    store.set_note(store.id_for(short), "Watch the second half")
    store.expansion_succeeded(short, clean(url))
    item = store.get_item(url)
    assert item["shelf"] == "inbox" and item["note"] == "Watch the second half"


def test_a_new_database_and_its_side_files_are_private(tmp_path):
    """Review 4, 4 Nov 2026: under a 022 umask the -wal and -shm files could be readable by other accounts."""
    import os
    import stat

    from magpiary.store import Store

    old = os.umask(0o022)
    try:
        s = Store(tmp_path / "fresh.db")
        s.set_setting("x", "1")
    finally:
        os.umask(old)
    for name in ("fresh.db", "fresh.db-wal", "fresh.db-shm"):
        p = tmp_path / name
        if p.exists():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600, name
