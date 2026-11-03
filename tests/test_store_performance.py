"""Behaviour preserved by the measured query optimisations, including existing libraries."""

import sqlite3

from magpiary.store import Store


def test_existing_chats_keep_first_question_latest_order_and_scoped_history(tmp_path):
    path = tmp_path / "existing.db"
    # An existing chat table without the new index must upgrade without losing history.
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE ask_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, "
                   "role TEXT NOT NULL, text TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', at TEXT NOT NULL)")
        db.executemany("INSERT INTO ask_messages(scope, role, text, at) VALUES (?,?,?,?)", [
            ("post:1", "assistant", "Before a question", "2026-10-28T10:00:00"),
            ("post:2", "user", "Second place", "2026-10-28T10:01:00"),
            ("post:1", "user", "First question", "2026-10-28T10:02:00"),
            ("post:1", "user", "Later question", "2026-10-28T10:03:00"),
            ("library:all", "assistant", "No question", "2026-10-28T10:04:00"),
        ])
    store = Store(path)
    try:
        expected = [
            {"scope": "library:all", "title": "A chat", "at": "2026-10-28T10:04:00"},
            {"scope": "post:1", "title": "First question", "at": "2026-10-28T10:03:00"},
            {"scope": "post:2", "title": "Second place", "at": "2026-10-28T10:01:00"},
        ]
        assert store.ask_live_chats() == expected
        assert [m["text"] for m in store.ask_thread("post:1", limit=2)] == ["First question", "Later question"]
        assert store.ask_thread("missing") == []
        store.ask_clear("post:1")
        assert store.ask_live_chats() == [expected[0], expected[2]]
    finally:
        store.close()
    # Opening a second time is idempotent, and the other scopes still exist.
    store = Store(path)
    try:
        assert store.ask_live_chats() == [expected[0], expected[2]]
    finally:
        store.close()


def test_hub_results_keep_sorted_tags_across_batches_and_filters(tmp_path):
    store = Store(tmp_path / "library.db")
    try:
        with store._db:
            for i in range(405):
                url = f"https://example.invalid/post/{i}"
                shelf = "inbox" if i < 403 else "archive" if i == 403 else "trash"
                store._db.execute(
                    "INSERT INTO items(canonical_url, source, status, shelf, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (url, "youtube" if i == 402 else "other", "needs_attention" if i == 402 else "archived",
                     shelf, f"2026-10-28T10:{i // 60:02d}:{i % 60:02d}", "2026-10-28T10:00:00"))
                if i != 401:  # an untagged save must still have an empty tags list
                    store._db.executemany("INSERT INTO tags VALUES (?,?)", [(url, "zebra"), (url, "alpha")])
            store._db.execute("INSERT INTO search(url, title) VALUES (?,?)", ("https://example.invalid/post/403", "needle"))
        rows = store.hub_items(limit=500)
        assert [r["canonical_url"] for r in rows] == [f"https://example.invalid/post/{i}" for i in reversed(range(403))]
        assert all(r["tags"] == ([] if r["canonical_url"].endswith("/401") else ["alpha", "zebra"]) for r in rows)
        assert store.hub_items(limit=1) == rows[:1]
        assert store.hub_items(limit=0) == []
        assert store.hub_items(query="missing") == []
        assert store.hub_items(source="youtube", tag="alpha", attention=True) == rows[:1]
        kept = store.hub_items("kept", query="needle")
        assert len(kept) == 1 and kept[0]["shelf"] == "archive" and kept[0]["tags"] == ["alpha", "zebra"]
        assert store.hub_items("trash")[0]["canonical_url"].endswith("/404")
    finally:
        store.close()
