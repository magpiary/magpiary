"""Chat persistence on the Store's existing connection, clock and lock.

The Store still owns initialization and migrations. Keeping chat operations together
leaves the delivery queue independent of the chat's history, notes and usage queries.
"""

from __future__ import annotations

import json
import sqlite3
from _thread import RLock
from collections.abc import Callable

CHAT_HISTORY_LIMIT = 60
CHAT_ARCHIVE_LIMIT = 500
CHAT_SESSION_LIMIT = 300
CHAT_TITLE_LIMIT = 90


def _message(row: sqlite3.Row) -> dict:
    return {**dict(row), "meta": json.loads(row["meta"] or "{}")}


class ChatStore:
    """Ask methods inherited by Store; no second connection or transaction layer."""

    _db: sqlite3.Connection
    _lock: RLock
    _stamp: Callable[[], str]

    def ask_add(
        self, scope: str, role: str, text: str, meta: dict | None = None
    ) -> int:
        with self._lock, self._db:
            return self._db.execute(
                "INSERT INTO ask_messages (scope, role, text, meta, at) VALUES (?,?,?,?,?)",
                (scope, role, text, json.dumps(meta or {}), self._stamp()),
            ).lastrowid

    def ask_thread(self, scope: str, limit: int = CHAT_HISTORY_LIMIT) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, role, text, meta, at FROM ask_messages WHERE scope=? ORDER BY id DESC LIMIT ?",
                (scope, limit),
            ).fetchall()
        return [_message(r) for r in reversed(rows)]

    def ask_message(self, message_id: int) -> dict | None:
        with self._lock:
            r = self._db.execute(
                "SELECT id, scope, role, text, meta, at FROM ask_messages WHERE id=?",
                (message_id,),
            ).fetchone()
        return _message(r) if r else None

    def ask_usage_add(
        self,
        scope: str,
        engine: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float = 0.0,
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO ask_usage (at, scope, engine, model, tokens_in, tokens_out, cost) VALUES (?,?,?,?,?,?,?)",
                (self._stamp(), scope, engine, model, tokens_in, tokens_out, cost),
            )

    def ask_usage_since(self, since: str) -> list[dict]:
        """Tokens used since a moment, per engine: [{"engine", "questions", "tokens_in", "tokens_out", "cost"}]."""
        with self._lock:
            rows = self._db.execute(
                "SELECT engine, COUNT(*) AS questions, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out, "
                "SUM(cost) AS cost FROM ask_usage WHERE at >= ? GROUP BY engine ORDER BY engine",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def ask_clear(self, scope: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM ask_messages WHERE scope=?", (scope,))

    def ask_end(self, scope: str, label: str) -> int | None:
        """End the chat in this place. One with an answer is kept as a past chat and its id returned;
        one without is just dropped."""
        thread = self.ask_thread(scope, limit=CHAT_ARCHIVE_LIMIT)
        with self._lock, self._db:
            self._db.execute("DELETE FROM ask_messages WHERE scope=?", (scope,))
            if not any(m["role"] == "assistant" for m in thread):
                return None
            first = next((m["text"] for m in thread if m["role"] == "user"), "A chat")
            title = " ".join(first.split())[:CHAT_TITLE_LIMIT]
            data = json.dumps(
                [
                    {
                        "role": m["role"],
                        "text": m["text"],
                        "meta": m["meta"],
                        "at": m["at"],
                    }
                    for m in thread
                ]
            )
            return self._db.execute(
                "INSERT INTO ask_sessions (scope, label, title, started, ended, count, data) VALUES (?,?,?,?,?,?,?)",
                (
                    scope,
                    label,
                    title,
                    thread[0]["at"],
                    self._stamp(),
                    len(thread),
                    data,
                ),
            ).lastrowid

    def ask_live_chats(self) -> list[dict]:
        """Chats still going, one per place that has messages: [{"scope", "title" (first question), "at" (last message)}], newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT scope, MAX(id) AS last, MAX(at) AS at, (SELECT text FROM ask_messages m2 WHERE m2.scope=m.scope AND m2.role='user' "
                "ORDER BY id LIMIT 1) AS title FROM ask_messages m GROUP BY scope ORDER BY last DESC"
            ).fetchall()
        return [
            {"scope": r["scope"], "title": r["title"] or "A chat", "at": r["at"]}
            for r in rows
        ]

    def ask_sessions(self) -> list[dict]:
        """Past chats, newest first: [{"id", "scope", "label", "title", "ended", "count"}]."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, scope, label, title, started, ended, count, pinned FROM ask_sessions ORDER BY id DESC LIMIT ?",
                (CHAT_SESSION_LIMIT,),
            ).fetchall()
        return [dict(r) for r in rows]

    def ask_session(self, session_id: int) -> dict | None:
        with self._lock:
            r = self._db.execute(
                "SELECT id, scope, label, title, started, ended, count, data FROM ask_sessions WHERE id=?",
                (session_id,),
            ).fetchone()
        return (
            {
                **{k: v for k, v in dict(r).items() if k != "data"},
                "messages": json.loads(r["data"]),
            }
            if r
            else None
        )

    def ask_session_pin(self, session_id: int, pinned: bool) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE ask_sessions SET pinned=? WHERE id=?",
                (1 if pinned else 0, session_id),
            )

    def ask_session_resume(self, session_id: int, label: str = "") -> str | None:
        """Carry on in a past chat: it becomes the live chat of its place again (the one that was there is kept as a past chat first).
        Returns the place, or None when there is no such chat."""
        session = self.ask_session(session_id)
        if not session:
            return None
        self.ask_end(session["scope"], label or session["label"])
        with self._lock, self._db:
            for m in session["messages"]:
                self._db.execute(
                    "INSERT INTO ask_messages (scope, role, text, meta, at) VALUES (?,?,?,?,?)",
                    (
                        session["scope"],
                        m["role"],
                        m["text"],
                        json.dumps(m["meta"]),
                        m["at"],
                    ),
                )
            self._db.execute("DELETE FROM ask_sessions WHERE id=?", (session_id,))
        return session["scope"]

    def ask_session_delete(self, session_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM ask_sessions WHERE id=?", (session_id,))

    def ask_note_add(self, scope: str, text: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO ask_notes (scope, text, at) VALUES (?,?,?)",
                (scope, text, self._stamp()),
            )

    def ask_notes(self, scope: str) -> list[dict]:
        with self._lock:
            return [
                dict(r)
                for r in self._db.execute(
                    "SELECT id, text, at FROM ask_notes WHERE scope=? ORDER BY id DESC",
                    (scope,),
                ).fetchall()
            ]

    def ask_note_delete(self, note_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM ask_notes WHERE id=?", (note_id,))
