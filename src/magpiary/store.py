"""SQLite storage for the delivery queue, library, boards and settings.

ChatStore supplies chat history, notes and usage on this same connection and lock.

Item identity is the canonical URL. A phone's own item ids only acknowledge delivery:
the (phone, id) ledger makes a resent batch a no-op. Pairing keys are stored as a
SHA-256 hash (keys are long random strings), so they cannot be read back.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from magpiary.protocol import DEFAULT_RETRY_WAIT
from magpiary.stats import STATS_SCHEMA, StatsStore
from magpiary.store_chat import ChatStore
from magpiary.cleaner import CleanLink, UnsupportedLink, clean
from magpiary.expand import FAILURE_REASON, retry_delay

log = logging.getLogger(__name__)

MAX_ID_LEN = 64
MAX_NOTE_LEN = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS phones (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL,
    home_wifi TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, revoked_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS phones_active_name ON phones(name) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS digests (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    made_at TEXT NOT NULL, intro TEXT NOT NULL DEFAULT '', data TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT NOT NULL UNIQUE, source TEXT NOT NULL, kind TEXT,
    first_phone_id INTEGER REFERENCES phones(id), last_phone_id INTEGER REFERENCES phones(id),
    first_shared_at TEXT, last_shared_at TEXT, saved_count INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, reason TEXT, reason_detail TEXT,
    attempts INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (
    phone_id INTEGER NOT NULL, delivery_id TEXT NOT NULL, canonical_url TEXT NOT NULL,
    received_at TEXT NOT NULL, PRIMARY KEY (phone_id, delivery_id));
"""

# item statuses: queued (clean link, waiting to be fetched), expanding (short link, first try pending),
# archived (fetched; archive_dir holds it), needs_attention (see reason; retried on a schedule
# when next_retry_at is set, otherwise it waits for the Retry button)

MIGRATIONS = ["ALTER TABLE items ADD COLUMN archive_dir TEXT", "ALTER TABLE items ADD COLUMN archived_at TEXT",
              # the hub: shelf is inbox, archive (done) or trash; the rest is copied from meta.json for listing
              "ALTER TABLE items ADD COLUMN shelf TEXT NOT NULL DEFAULT 'inbox'",
              "ALTER TABLE items ADD COLUMN trashed_at TEXT",
              "ALTER TABLE items ADD COLUMN title TEXT", "ALTER TABLE items ADD COLUMN author TEXT",
              "ALTER TABLE items ADD COLUMN caption TEXT", "ALTER TABLE items ADD COLUMN thumb TEXT",
              "ALTER TABLE items ADD COLUMN media_kind TEXT", "ALTER TABLE items ADD COLUMN published_at TEXT",
              # M3: ai_status is NULL (not yet), done, or needs_attention (ai_reason, retried at ai_next_at)
              "ALTER TABLE items ADD COLUMN ai_status TEXT", "ALTER TABLE items ADD COLUMN ai_reason TEXT",
              "ALTER TABLE items ADD COLUMN ai_detail TEXT", "ALTER TABLE items ADD COLUMN ai_attempts INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE items ADD COLUMN ai_next_at TEXT", "ALTER TABLE items ADD COLUMN ai_title TEXT",
              "ALTER TABLE items ADD COLUMN summary TEXT", "ALTER TABLE items ADD COLUMN ai_type TEXT",
              "ALTER TABLE items ADD COLUMN suggested_tags TEXT", "ALTER TABLE items ADD COLUMN entities_text TEXT",
              "ALTER TABLE items ADD COLUMN transcript_text TEXT", "ALTER TABLE items ADD COLUMN screen_text TEXT", "ALTER TABLE items ADD COLUMN processed_at TEXT",
              # senses_status: NULL (not yet) or done; ai_force: the owner pressed "Try again" (goes first, even when paused)
              "ALTER TABLE items ADD COLUMN senses_status TEXT", "ALTER TABLE items ADD COLUMN ai_force INTEGER NOT NULL DEFAULT 0",
              # M3.5 links: links_status NULL (to do); save_found_links records the resolver's status
              "ALTER TABLE items ADD COLUMN links_status TEXT", "ALTER TABLE items ADD COLUMN links_force INTEGER NOT NULL DEFAULT 0",
              # the owner pressed "Try with my Instagram login" on this item
              "ALTER TABLE items ADD COLUMN use_login INTEGER NOT NULL DEFAULT 0",
              # the board whose "Also add to my library" switch brought this post into the library (it leaves again
              # when the switch goes off, unless it was also saved on its own)
              "ALTER TABLE items ADD COLUMN via_board TEXT",
              # a friend's post on a shared board, fetched only so its card can play: no transcript, no AI
              "ALTER TABLE items ADD COLUMN media_only INTEGER NOT NULL DEFAULT 0",
              # the note an AI agent wrote (the owner's own note stays in `note`); older versions are in agent_note_history
              "ALTER TABLE items ADD COLUMN agent_note TEXT NOT NULL DEFAULT ''",
              "ALTER TABLE items ADD COLUMN agent_note_by TEXT NOT NULL DEFAULT ''",
              "ALTER TABLE items ADD COLUMN agent_note_at TEXT NOT NULL DEFAULT ''",
              # Instagram shows this post only to logged-in people: 1 = flagged (no automatic refresh, never in the background
              # with a login), 2 = the owner chose to keep it as it is (leaves Needs attention, no more tries)
              "ALTER TABLE items ADD COLUMN login_only INTEGER NOT NULL DEFAULT 0"]

HUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_usage (day TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, kind));
CREATE TABLE IF NOT EXISTS agent_note_history (id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_url TEXT NOT NULL,
    text TEXT NOT NULL, by TEXT NOT NULL DEFAULT '', at TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS agent_note_history_url ON agent_note_history(canonical_url, id);
CREATE TABLE IF NOT EXISTS tags (canonical_url TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (canonical_url, tag));
CREATE TABLE IF NOT EXISTS links (canonical_url TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', rank TEXT NOT NULL DEFAULT 'best',
    checked TEXT NOT NULL DEFAULT 'yes', origin TEXT NOT NULL DEFAULT 'auto', removed INTEGER NOT NULL DEFAULT 0,
    found_at TEXT NOT NULL, PRIMARY KEY (canonical_url, name, url));
CREATE TABLE IF NOT EXISTS timings (canonical_url TEXT NOT NULL, step TEXT NOT NULL, started_at TEXT NOT NULL,
    seconds REAL NOT NULL, PRIMARY KEY (canonical_url, step));
CREATE TABLE IF NOT EXISTS vectors (canonical_url TEXT NOT NULL, model TEXT NOT NULL, text_hash TEXT NOT NULL,
    vector BLOB NOT NULL, PRIMARY KEY (canonical_url, model));
CREATE TABLE IF NOT EXISTS not_related (a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS piles (id INTEGER PRIMARY KEY, name TEXT NOT NULL, auto_name TEXT NOT NULL DEFAULT '',
    owner_named INTEGER NOT NULL DEFAULT 0, owner_made INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, seen_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pile_items (pile_id INTEGER NOT NULL, canonical_url TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'auto', removed INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (pile_id, canonical_url));
"""
SEARCH_COLUMNS = ("title", "author", "caption", "tags", "note", "summary", "transcript", "entities", "screen")
ASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS ask_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, role TEXT NOT NULL,
    text TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ask_messages_scope_id ON ask_messages(scope, id);
CREATE TABLE IF NOT EXISTS ask_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, scope TEXT NOT NULL, engine TEXT NOT NULL,
    model TEXT NOT NULL, tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, cost REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ask_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, label TEXT NOT NULL, title TEXT NOT NULL,
    started TEXT NOT NULL, ended TEXT NOT NULL, count INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ask_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity (day TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, kind));
"""
BOARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS boards (id TEXT PRIMARY KEY, name TEXT NOT NULL, creator TEXT NOT NULL, via TEXT NOT NULL,
    created_at TEXT NOT NULL, joined_at TEXT NOT NULL, synced_at TEXT NOT NULL DEFAULT '',
    sync_error TEXT NOT NULL DEFAULT '', since INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS board_events (board_id TEXT NOT NULL, member TEXT NOT NULL, seq INTEGER NOT NULL,
    at INTEGER NOT NULL, type TEXT NOT NULL, body TEXT NOT NULL, signed TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
    published INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (board_id, member, seq));
CREATE TABLE IF NOT EXISTS board_pending (board_id TEXT NOT NULL, canonical_url TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, PRIMARY KEY (board_id, canonical_url));
CREATE TABLE IF NOT EXISTS board_offers (invite TEXT PRIMARY KEY, board_id TEXT NOT NULL, name TEXT NOT NULL,
    sender TEXT NOT NULL, created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS relay_notes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS board_slugs (slug TEXT PRIMARY KEY, board_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS board_invites (id TEXT PRIMARY KEY, board_id TEXT NOT NULL, created_at TEXT NOT NULL,
    expires INTEGER NOT NULL, used_by TEXT NOT NULL DEFAULT '', bucket_key_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open');
"""
SEARCH_SCHEMA = (f"CREATE VIRTUAL TABLE search USING fts5(url UNINDEXED, {', '.join(SEARCH_COLUMNS)}, "
                 "tokenize='unicode61 remove_diacritics 2')")
SHELVES = ("inbox", "archive", "trash", "board")  # board: shared from the phone only for a board, not the library
MAX_TAGS, MAX_TAG_LEN = 30, 40
TRASH_DAYS = 30


@dataclass(frozen=True)
class Phone:
    id: int
    name: str


@dataclass(frozen=True)
class ItemResult:
    id: str
    status: str  # new, again, replay, empty, rejected, board (a board choice for a post sent with it)
    reason: str | None = None  # for rejected
    saved_count: int = 0
    needs_expansion: bool = False


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _local_now() -> datetime:
    return datetime.now().astimezone()


class Store(ChatStore, StatsStore):
    def __init__(
        self,
        path: Path | str,
        now: Callable[[], datetime] = _local_now,
        *,
        read_only: bool = False,
    ) -> None:
        self._now = now
        self._lock = threading.RLock()
        if read_only:
            # An AI library reader must never initialize, migrate or create a database.
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self._db = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA query_only=ON")
            return
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._prepare()
        if str(path) != ":memory:":
            Path(path).chmod(0o600)  # key hashes live here

    def _prepare(self) -> None:
        """Create what is missing and bring an older database up to date. Run when the store opens and again after a restore."""
        self._db.executescript(SCHEMA)
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}
        for statement in MIGRATIONS:
            if statement.split()[5] not in columns:
                self._db.execute(statement)
        self._db.execute("UPDATE items SET login_only=1 WHERE use_login=1 AND login_only=0")  # fetched with the owner's login at first
        if sum(r["pk"] > 0 for r in self._db.execute("PRAGMA table_info(vectors)")) == 1:
            self._db.execute("DROP TABLE vectors")  # one reading per item before; vectors are made again
        self._db.executescript(HUB_SCHEMA)
        self._db.executescript(BOARD_SCHEMA)
        self._db.executescript(ASK_SCHEMA)
        self._db.executescript(STATS_SCHEMA)
        self._migrate_item_ids()
        if "pinned" not in {r["name"] for r in self._db.execute("PRAGMA table_info(ask_sessions)")}:
            self._db.execute("ALTER TABLE ask_sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "to_library" not in {r["name"] for r in self._db.execute("PRAGMA table_info(boards)")}:
            # my phone shares to this board also go into my library (owner, 25 Oct: off by default)
            self._db.execute("ALTER TABLE boards ADD COLUMN to_library INTEGER NOT NULL DEFAULT 0")
        if "wifi_mode" not in {r["name"] for r in self._db.execute("PRAGMA table_info(phones)")}:
            # where this phone sends: "home" (only on its home Wi-Fi, the default) or "any" (any Wi-Fi it is on)
            self._db.execute("ALTER TABLE phones ADD COLUMN wifi_mode TEXT NOT NULL DEFAULT 'home'")
        if "retry_wait" not in {r["name"] for r in self._db.execute("PRAGMA table_info(phones)")}:
            # minutes a phone waits before trying a Wi-Fi again after a try the Mac never answered (an advanced setting)
            self._db.execute("ALTER TABLE phones ADD COLUMN retry_wait INTEGER NOT NULL DEFAULT 15")
        if "kind" not in {r["name"] for r in self._db.execute("PRAGMA table_info(phones)")}:
            # what this device is: "phone" (the Shortcut), "browser" (the Chrome extension on this Mac) or "agent" (`magpiary add` / `note` for AI agents)
            self._db.execute("ALTER TABLE phones ADD COLUMN kind TEXT NOT NULL DEFAULT 'phone'")
        for column in ("first_seen_at", "last_seen_at"):
            # when this device first and last reached the Mac with its key (the Welcome guide ticks "paired" from the first)
            if column not in {r["name"] for r in self._db.execute("PRAGMA table_info(phones)")}:
                self._db.execute(f"ALTER TABLE phones ADD COLUMN {column} TEXT")
        for column, ddl in (("shared", "INTEGER NOT NULL DEFAULT 1"), ("archived_at", "TEXT NOT NULL DEFAULT ''"),
                            ("ended", "INTEGER NOT NULL DEFAULT 0")):
            # a board is solo (local only) until its owner shares it; deleted boards wait 30 days archived; ended = its
            # creator deleted a shared board (owner, 26 Oct). Boards from before this are shared until sorted by members
            if column not in {r["name"] for r in self._db.execute("PRAGMA table_info(boards)")}:
                self._db.execute(f"ALTER TABLE boards ADD COLUMN {column} {ddl}")
        for table, column in (("piles", "seen_at"), ("pile_items", "added_at")):  # first M4 build lacked these
            if column not in {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        # Links v2: main link or badge, central or passing (behind "Show more"), named or an alternative
        for column, default in (("role", "'main'"), ("central", "1"), ("section", "'named'")):
            if column not in {r["name"] for r in self._db.execute("PRAGMA table_info(links)")}:
                self._db.execute(f"ALTER TABLE links ADD COLUMN {column} {'INTEGER' if column == 'central' else 'TEXT'} "
                                 f"NOT NULL DEFAULT {default}")
        # post types before 24 Oct: "media" and "entertainment" become design or other (brain.type_of)
        self._db.execute("UPDATE items SET ai_type = CASE WHEN lower(COALESCE(ai_title, '') || ' ' || COALESCE(suggested_tags, '')) "
                         "LIKE '%design%' THEN 'design' ELSE 'other' END WHERE ai_type IN ('media', 'entertainment')")
        found = [r["name"] for r in self._db.execute("PRAGMA table_info(search)")]
        if found != ["url", *SEARCH_COLUMNS]:  # new searchable fields: rebuild the index
            self._db.execute("DROP TABLE IF EXISTS search")
            self._db.execute(SEARCH_SCHEMA)
            for row in self._db.execute("SELECT canonical_url FROM items").fetchall():
                self._reindex(row[0])

    def close(self) -> None:
        self._db.close()

    def restore_from(self, source: Path, safety_copy: Path) -> None:
        """Replace everything in this database with a backup. The current one is first copied to `safety_copy`, so a restore can be
        undone. Raises ValueError for a file that is not a sound Magpiary backup; nothing is changed then."""
        try:
            backup = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as err:
            raise ValueError("That file could not be opened.") from err
        try:
            try:
                sound = backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                tables = {r[0] for r in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.Error as err:
                raise ValueError("That file is not a Magpiary backup.") from err
            if not sound or not {"items", "settings", "phones"} <= tables:
                raise ValueError("That file is not a sound Magpiary backup.")
            self.backup_to(safety_copy)
            with self._lock:
                backup.backup(self._db)
        finally:
            backup.close()
        with self._lock:
            self._prepare()  # a backup from an older version gets the newer tables and columns

    def _migrate_item_ids(self) -> None:
        """Keep legacy rowids, then never reuse one (including ids in retained chats and digests)."""
        if "id" in {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}:
            return
        self._db.execute("BEGIN IMMEDIATE")
        try:
            # Another connection may have migrated while this one waited for the write lock.
            if "id" not in {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}:
                sql = self._db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='items'").fetchone()[0]
                sql = sql.replace("CREATE TABLE items", "CREATE TABLE items_with_ids", 1).replace(
                    "canonical_url TEXT PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_url TEXT NOT NULL UNIQUE", 1)
                indexes = [r[0] for r in self._db.execute(
                    "SELECT sql FROM sqlite_master WHERE tbl_name='items' AND type IN ('index','trigger') AND sql IS NOT NULL")]
                self._db.execute(sql)
                self._db.execute("INSERT INTO items_with_ids SELECT rowid, * FROM items")
                self._db.execute("DROP TABLE items")
                self._db.execute("ALTER TABLE items_with_ids RENAME TO items")
                for statement in indexes:
                    self._db.execute(statement)
                high = self._db.execute("SELECT COALESCE(MAX(id),0) FROM items").fetchone()[0]
                for row in self._db.execute("SELECT scope FROM ask_messages UNION SELECT scope FROM ask_sessions "
                                            "UNION SELECT scope FROM ask_notes UNION SELECT scope FROM ask_usage"):
                    if re.fullmatch(r"post:[0-9]+", row[0]):
                        high = max(high, int(row[0][5:]))
                # Stories cite 'saves'; live and saved chats cite 'posts' in their metadata.
                pending = [json.loads(r[0]) for r in self._db.execute(
                    "SELECT data FROM digests UNION ALL SELECT meta FROM ask_messages UNION ALL SELECT data FROM ask_sessions")]
                while pending:
                    value = pending.pop()
                    if isinstance(value, dict):
                        for field in ("saves", "posts"):
                            for item_id in value.get(field, []) if isinstance(value.get(field), list) else []:
                                if re.fullmatch(r"[0-9]{1,19}", str(item_id)) and int(item_id) <= 2**63 - 1:
                                    high = max(high, int(item_id))
                        pending.extend(v for k, v in value.items() if k not in ("saves", "posts"))
                    elif isinstance(value, list):
                        pending.extend(value)
                self._db.execute("DELETE FROM sqlite_sequence WHERE name='items'")
                self._db.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('items', ?)", (high,))
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    # ---- shared boards (M9) -------------------------------------------------------------------
    # A board's events, one log per member, as checked and opened on this Mac; the board keys live in
    # ~/.config/magpiary/boards.json, never here.

    def save_board(self, board_id: str, name: str, creator: str, via: str, shared: bool = True) -> None:
        stamp = self._stamp()
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO boards (id, name, creator, via, created_at, joined_at, shared) "
                             "VALUES (?,?,?,?,?,?,?)", (board_id, name, creator, via, stamp, stamp, int(shared)))

    def boards(self, archived: bool = False) -> list[dict]:
        """The boards on show, or (archived=True) the deleted ones waiting out their 30 days."""
        with self._lock:
            return [dict(r) for r in self._db.execute(
                f"SELECT * FROM boards WHERE archived_at {'!=' if archived else '='} '' ORDER BY joined_at DESC").fetchall()]

    def boards_to_sync(self) -> list[dict]:
        """Shared boards that still sync: not solo, not ended by their creator; an archived one only until its last
        event (the 'deleted' notice) has gone out."""
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM boards WHERE shared=1 AND ended=0 ORDER BY joined_at DESC").fetchall()]

    def purge_archived_boards(self, days: int = 30) -> list[str]:
        cutoff = (self._now() - timedelta(days=days)).isoformat(timespec="seconds")
        old = [b["id"] for b in self.boards(archived=True) if b["archived_at"] <= cutoff]
        for board_id in old:
            self.delete_board(board_id)
        return old

    def board(self, board_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        return dict(row) if row else None

    def update_board(self, board_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "via", "synced_at", "sync_error", "since", "to_library", "shared", "archived_at", "ended")}
        if allowed:
            with self._lock, self._db:
                self._db.execute(f"UPDATE boards SET {', '.join(f'{k}=?' for k in allowed)} WHERE id=?",
                                 (*allowed.values(), board_id))

    def delete_board(self, board_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM board_events WHERE board_id=?", (board_id,))
            self._db.execute("DELETE FROM board_invites WHERE board_id=?", (board_id,))
            self._db.execute("DELETE FROM board_pending WHERE board_id=?", (board_id,))
            self._db.execute("DELETE FROM board_slugs WHERE board_id=?", (board_id,))
            self._db.execute("DELETE FROM boards WHERE id=?", (board_id,))

    def remember_slugs(self, slugs: dict) -> None:
        """A board's address by name ({slug: board id}); earlier names stay, so old links still lead to the board."""
        with self._lock, self._db:
            self._db.executemany("INSERT OR REPLACE INTO board_slugs (slug, board_id) VALUES (?,?)", slugs.items())

    def board_by_slug(self, slug: str) -> str:
        with self._lock:
            row = self._db.execute("SELECT board_id FROM board_slugs WHERE slug=?", (slug,)).fetchone()
        return row[0] if row else ""

    def add_board_event(self, board_id: str, member: str, seq: int, at: int, kind: str, body: dict, signed: str,
                        ref: str = "", published: bool = True) -> bool:
        """False when this member's event with this number is already here."""
        with self._lock, self._db:
            return self._db.execute(
                "INSERT OR IGNORE INTO board_events (board_id, member, seq, at, type, body, signed, ref, published) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (board_id, member, seq, at, kind, json.dumps(body), signed, ref, int(published))).rowcount == 1

    def board_events(self, board_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT member, seq, at, type, body FROM board_events WHERE board_id=? "
                                    "ORDER BY at, member, seq", (board_id,)).fetchall()
        return [{**dict(r), "body": json.loads(r["body"])} for r in rows]

    def next_board_seq(self, board_id: str, member: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(seq) FROM board_events WHERE board_id=? AND member=?",
                                   (board_id, member)).fetchone()
        return (row[0] or 0) + 1

    def append_board_event(self, board_id: str, member: str, at: int, kind: str, body: dict,
                           sign: Callable[[int], str]) -> int:
        """Allocate, sign and insert together, across threads and database connections."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                seq = self.next_board_seq(board_id, member)
                signed = sign(seq)
                self._db.execute(
                    "INSERT INTO board_events (board_id, member, seq, at, type, body, signed, published) VALUES (?,?,?,?,?,?,?,0)",
                    (board_id, member, seq, at, kind, json.dumps(body), signed))
                self._db.execute("COMMIT")
                return seq
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def unpublished_board_events(self, board_id: str, member: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT seq, signed FROM board_events WHERE board_id=? AND member=? AND published=0 ORDER BY seq",
                (board_id, member)).fetchall()]

    def board_event_published(self, board_id: str, member: str, seq: int, ref: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE board_events SET published=1, ref=? WHERE board_id=? AND member=? AND seq=?",
                             (ref, board_id, member, seq))

    def save_invite(self, invite_id: str, board_id: str, expires: int, bucket_key_id: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO board_invites (id, board_id, created_at, expires, bucket_key_id) VALUES (?,?,?,?,?)",
                             (invite_id, board_id, self._stamp(), expires, bucket_key_id))

    def invites(self, board_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM board_invites WHERE board_id=? ORDER BY created_at",
                                                      (board_id,)).fetchall()]

    def update_invite(self, invite_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("used_by", "state")}
        if allowed:
            with self._lock, self._db:
                self._db.execute(f"UPDATE board_invites SET {', '.join(f'{k}=?' for k in allowed)} WHERE id=?",
                                 (*allowed.values(), invite_id))

    def board_refs(self, board_id: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT ref FROM board_events WHERE board_id=? AND ref != ''",
                                                   (board_id,)).fetchall()}

    # ---- digests (M7c) ------------------------------------------------------------------------

    def save_digest(self, kind: str, start: str, end: str, data: dict, intro: str = "") -> int:
        with self._lock, self._db:
            return self._db.execute("INSERT INTO digests (kind, start, end, made_at, intro, data) VALUES (?,?,?,?,?,?)",
                                    (kind, start, end, self._stamp(), intro, json.dumps(data))).lastrowid

    def digests(self, limit: int = 60) -> list[dict]:
        """Newest first, without their contents."""
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT id, kind, start, end, made_at, seen FROM digests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def digest(self, digest_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM digests WHERE id=?", (digest_id,)).fetchone()
        if row is None:
            return None
        found = dict(row)
        found["data"] = json.loads(found["data"])
        return found

    def last_digest_end(self, kind: str) -> str:
        with self._lock:
            row = self._db.execute("SELECT MAX(end) FROM digests WHERE kind=?", (kind,)).fetchone()
        return row[0] or ""

    def update_digest(self, digest_id: int, data: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE digests SET data=? WHERE id=?", (json.dumps(data), digest_id))

    def digest_seen(self, digest_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE digests SET seen=1 WHERE id=?", (digest_id,))

    def unseen_digest(self) -> dict | None:
        """The newest digest not opened yet (the top bar's dot, the wall's banner)."""
        with self._lock:
            row = self._db.execute("SELECT id, kind, start, end, made_at FROM digests WHERE seen=0 ORDER BY id DESC "
                                   "LIMIT 1").fetchone()
        return dict(row) if row else None

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _aware(self, stamp: str, fallback: str) -> str:
        """A share time always carries its offset (the phone sends one; a browser may not): without one it is this Mac's local time.
        Mixed forms broke date maths on the post page."""
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return fallback
        if when.tzinfo is None:
            when = when.replace(tzinfo=self._now().tzinfo)
        return when.isoformat(timespec="seconds")

    def now(self) -> str:
        """The store's clock, as a stamp (tests move it)."""
        return self._stamp()

    # ---- phones -------------------------------------------------------------------------

    RETRY_WAITS = (5, 15, 30, 60)

    def add_phone(self, name: str, home_wifi: str = "", retry_wait: int = DEFAULT_RETRY_WAIT,
                  kind: str = "phone") -> tuple[Phone, str]:
        """Create a phone (or, with kind="browser", the Chrome extension) and its key. The key is returned once and never stored in clear."""
        name = name.strip()
        if not name:
            raise ValueError("a phone needs a name")
        if len(name) > 60 or len(home_wifi) > 64:
            raise ValueError("name too long")
        if retry_wait not in self.RETRY_WAITS:
            retry_wait = DEFAULT_RETRY_WAIT
        if kind not in ("phone", "browser", "agent"):
            raise ValueError("unknown device kind")
        key = secrets.token_urlsafe(32)
        with self._lock:
            try:
                cur = self._db.execute(
                    "INSERT INTO phones (name, key_hash, home_wifi, wifi_mode, retry_wait, kind, created_at) VALUES (?,?,?,?,?,?,?)",
                    (name, _hash(key), home_wifi.strip(), "home" if home_wifi.strip() else "any", retry_wait, kind, self._stamp()))
            except sqlite3.IntegrityError:
                raise ValueError(f"a phone called {name!r} already exists") from None
        return Phone(cur.lastrowid, name), key

    def phone_for_key(self, key: str) -> Phone | None:
        """The active phone this key belongs to, or None (wrong, empty or revoked)."""
        if not key:
            return None
        digest = _hash(key)
        with self._lock:
            rows = self._db.execute(
                "SELECT id, name, key_hash FROM phones WHERE revoked_at IS NULL").fetchall()
        found = None
        for row in rows:  # compare every row so timing does not reveal a near match
            if hmac.compare_digest(row["key_hash"], digest):
                found = Phone(row["id"], row["name"])
        if found:
            self._touch_phone(found.id)
        return found

    def _touch_phone(self, phone_id: int) -> None:
        """Note that this device reached the Mac with its key. Written at most about once a minute."""
        now = self._stamp()
        with self._lock:
            self._db.execute(
                "UPDATE phones SET first_seen_at=COALESCE(first_seen_at, ?), last_seen_at=? WHERE id=? "
                "AND (last_seen_at IS NULL OR last_seen_at < ?)",
                (now, now, phone_id, (datetime.fromisoformat(now) - timedelta(seconds=60)).isoformat(timespec="seconds")))

    def agent_used(self, kind: str) -> int:
        """How many links or notes AI agents have added today (for their daily limit)."""
        with self._lock:
            row = self._db.execute("SELECT n FROM agent_usage WHERE day=? AND kind=?", (self._stamp()[:10], kind)).fetchone()
        return row["n"] if row else 0

    def agent_use(self, kind: str, n: int = 1) -> None:
        day = self._stamp()[:10]
        with self._lock:
            self._db.execute("INSERT INTO agent_usage (day, kind, n) VALUES (?,?,?) "
                             "ON CONFLICT(day, kind) DO UPDATE SET n=n+excluded.n", (day, kind, n))
            self._db.execute("DELETE FROM agent_usage WHERE day < date(?, '-30 day')", (day,))

    def backup_to(self, path: Path) -> None:
        """A whole, consistent copy of the database, finished under another name so a half-made copy never looks like a backup."""
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        copy = sqlite3.connect(part)
        try:
            with self._lock:
                self._db.backup(copy)
        finally:
            copy.close()
        part.chmod(0o600)
        part.replace(path)

    def phone_kind(self, phone_id: int) -> str:
        with self._lock:
            row = self._db.execute("SELECT kind FROM phones WHERE id=?", (phone_id,)).fetchone()
        return row["kind"] if row else ""

    def new_key(self, name: str) -> tuple[Phone, str] | None:
        """Replace an active phone's key (a lost install code). The old Shortcut stops working."""
        key = secrets.token_urlsafe(32)
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM phones WHERE name=? AND revoked_at IS NULL", (name,)).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE phones SET key_hash=? WHERE id=?", (_hash(key), row["id"]))
        return Phone(row["id"], name), key

    def save_offer(self, invite: str, board_id: str, name: str, sender: str) -> bool:
        """An invite a friend sent straight to this Mac. False if it was seen before."""
        with self._lock, self._db:
            return self._db.execute("INSERT OR IGNORE INTO board_offers (invite, board_id, name, sender, created_at) "
                                    "VALUES (?,?,?,?,?)", (invite, board_id, name, sender, self._stamp())).rowcount == 1

    def offers(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM board_offers WHERE state='new' ORDER BY created_at DESC").fetchall()]

    def offer(self, invite: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM board_offers WHERE invite=?", (invite,)).fetchone()
        return dict(row) if row else None

    def set_offer(self, invite: str, state: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE board_offers SET state=? WHERE invite=?", (state, invite))

    def save_relay_note(self, event_id: str, kind: str) -> None:
        """A note this Mac left on the relays (an invite code, an invite for one friend, a member's key)."""
        import time as _time

        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO relay_notes (id, kind, created) VALUES (?,?,?)",
                             (event_id, kind, int(_time.time())))

    def relay_note_age(self, event_id: str, now: float) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT created FROM relay_notes WHERE id=?", (event_id,)).fetchone()
        return now - row[0] if row else None

    def relay_note_kind(self, event_id: str) -> str:
        with self._lock:
            row = self._db.execute("SELECT kind FROM relay_notes WHERE id=?", (event_id,)).fetchone()
        return row[0] if row else ""

    def relay_notes_deleted(self, event_ids: list[str]) -> None:
        with self._lock, self._db:
            self._db.executemany("UPDATE relay_notes SET deleted=1 WHERE id=?", [(i,) for i in event_ids])

    def add_board_pending(self, board_id: str, url: str, note: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO board_pending (board_id, canonical_url, note, created_at) VALUES (?,?,?,?)",
                             (board_id, url, note, self._stamp()))

    def board_pending(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM board_pending ORDER BY created_at").fetchall()]

    def to_library(self, board_id: str, urls: set, dry: bool = False) -> int:
        """Posts kept only for a board go into the library (remembering why). Returns how many (would) move."""
        with self._lock, self._db:
            if dry:
                return sum(self._db.execute("SELECT COUNT(*) FROM items WHERE canonical_url=? AND shelf='board'",
                                            (u,)).fetchone()[0] for u in urls)
            return sum(self._db.execute("UPDATE items SET shelf='inbox', via_board=? WHERE canonical_url=? AND "
                                        "shelf='board'", (board_id, u)).rowcount for u in urls)

    def from_library(self, board_id: str, dry: bool = False) -> int:
        """Posts this board's switch brought into the library go back to the board only. Returns how many (would)."""
        with self._lock, self._db:
            if dry:
                return self._db.execute("SELECT COUNT(*) FROM items WHERE via_board=? AND shelf='inbox'",
                                        (board_id,)).fetchone()[0]
            return self._db.execute("UPDATE items SET shelf='board', via_board=NULL WHERE via_board=? AND shelf='inbox'",
                                    (board_id,)).rowcount

    def board_pending_done(self, board_id: str, url: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM board_pending WHERE board_id=? AND canonical_url=?", (board_id, url))

    def list_phones(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT name, home_wifi, wifi_mode, retry_wait, kind, created_at, revoked_at, first_seen_at, last_seen_at FROM phones ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_phone(self, name: str) -> dict | None:
        """An active phone by name (never its key)."""
        with self._lock:
            row = self._db.execute(
                "SELECT name, home_wifi, wifi_mode, retry_wait, created_at FROM phones WHERE name=? AND revoked_at IS NULL",
                (name,)).fetchone()
        return dict(row) if row else None

    WIFI_MODES = ("home", "any")

    def set_retry_wait(self, name: str, minutes: int) -> bool:
        """How long an active phone waits after a failed try. It is built into the phone's Shortcut, so it takes a new install code."""
        if minutes not in self.RETRY_WAITS:
            return False
        with self._lock:
            return self._db.execute("UPDATE phones SET retry_wait=? WHERE name=? AND revoked_at IS NULL",
                                    (minutes, name)).rowcount > 0

    def set_wifi_mode(self, name: str, mode: str) -> bool:
        """Where an active phone sends: only on its home Wi-Fi, or on any Wi-Fi (the phone learns it from the next reply)."""
        if mode not in self.WIFI_MODES:
            return False
        if mode == "home" and not (self.get_phone(name) or {}).get("home_wifi"):
            return False  # Home only needs the name of a home Wi-Fi
        with self._lock:
            return self._db.execute("UPDATE phones SET wifi_mode=? WHERE name=? AND revoked_at IS NULL",
                                    (mode, name)).rowcount > 0

    def wifi_mode_of(self, phone_id: int) -> str:
        """Where a phone may send. A phone paired without a home Wi-Fi name always sends on any Wi-Fi: Home only
        needs a name to mean anything."""
        with self._lock:
            row = self._db.execute("SELECT wifi_mode, home_wifi FROM phones WHERE id=?", (phone_id,)).fetchone()
        if not row or not row["home_wifi"]:
            return "any"
        return row["wifi_mode"] if row["wifi_mode"] in self.WIFI_MODES else "home"

    def phone_shared_since(self, name: str, since: str) -> bool:
        """Whether an active phone delivered anything at or after `since` (a store stamp): its install works."""
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM deliveries d JOIN phones p ON p.id = d.phone_id WHERE p.name=? AND p.revoked_at IS NULL "
                "AND d.received_at >= ? LIMIT 1", (name, since)).fetchone() is not None

    def last_home_wifi(self) -> str:
        with self._lock:
            row = self._db.execute(
                "SELECT home_wifi FROM phones WHERE home_wifi != '' ORDER BY id DESC LIMIT 1").fetchone()
        return row["home_wifi"] if row else ""

    # ---- settings -----------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def extension_hello(self, version: str, pinned: bool | None) -> None:
        """The Chrome extension said hello (installed or Chrome started): its version and whether its button is on the toolbar."""
        self.set_setting("ext_hello_at", self._stamp())
        self.set_setting("ext_version", version[:20])
        self.set_setting("ext_pinned", "" if pinned is None else "1" if pinned else "0")

    def extension_status(self) -> dict:
        """What the Mac knows about Chrome: added (a hello arrived or it paired), pinned (True/False/None when never reported)."""
        browser = next((p for p in self.list_phones() if not p["revoked_at"] and p.get("kind") == "browser"), None)
        pinned = self.get_setting("ext_pinned")
        return {"added": bool(self.get_setting("ext_hello_at")) or browser is not None,
                "pinned": None if pinned == "" else pinned == "1", "paired": browser is not None,
                "used": bool(browser and browser.get("first_seen_at"))}

    def revoke_phone(self, name: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE phones SET revoked_at=? WHERE name=? AND revoked_at IS NULL",
                (self._stamp(), name))
        return cur.rowcount > 0

    # ---- receiving ----------------------------------------------------------------------

    def receive(self, phone: Phone, items: list) -> list[ItemResult]:
        """Store a batch. Everything is committed before this returns, so a reply means stored."""
        results = []
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for item in items:
                    results.append(self._receive_one(phone, item))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return results

    def _receive_one(self, phone: Phone, item) -> ItemResult:
        if not isinstance(item, dict):
            return ItemResult("", "rejected", "bad_item")
        item_id, url = item.get("id"), item.get("url")
        if not isinstance(item_id, str) or not item_id or len(item_id) > MAX_ID_LEN:
            return ItemResult("", "rejected", "bad_id")
        if not isinstance(url, str):
            return ItemResult(item_id, "rejected", "bad_url")
        if not url.strip():  # a run with nothing shared (the Wi-Fi automation): acknowledge only
            return ItemResult(item_id, "empty")
        try:
            link = clean(url)
        except UnsupportedLink:
            return ItemResult(item_id, "rejected", "unsupported_link")

        seen = self._db.execute(
            "SELECT canonical_url FROM deliveries WHERE phone_id=? AND delivery_id=?",
            (phone.id, item_id)).fetchone()
        if seen:
            return ItemResult(item_id, "replay", saved_count=self._count(seen["canonical_url"]),
                              needs_expansion=link.needs_expansion)

        now = self._stamp()
        board = item.get("board")
        if item.get("attach"):  # the phone's board choice for a post it queued just before: not a new save
            self._db.execute("INSERT INTO deliveries VALUES (?,?,?,?)", (phone.id, item_id, link.url, now))
            found = self._db.execute("SELECT to_library FROM boards WHERE id=?", (board,)).fetchone() \
                if isinstance(board, str) and re.fullmatch(r"[0-9a-f]{16}", board) else None
            if found:
                self._db.execute("INSERT OR IGNORE INTO board_pending (board_id, canonical_url, note, created_at) "
                                 "VALUES (?,?,?,?)", (board, link.url, "", now))
                if not found["to_library"]:  # a post saved just now only for this board stays out of the library
                    self._db.execute("UPDATE items SET shelf='board' WHERE canonical_url=? AND saved_count=1 AND "
                                     "shelf='inbox'", (link.url,))
                else:  # in the library because of this board's switch: remembered, so switching off takes it out
                    self._db.execute("UPDATE items SET via_board=? WHERE canonical_url=? AND saved_count=1 AND "
                                     "shelf='inbox' AND via_board IS NULL", (board, link.url))
            return ItemResult(item_id, "board")
        shared_at = self._aware(str(item.get("shared_at") or now)[:40], now)
        note = str(item.get("note") or "")[:MAX_NOTE_LEN]
        if isinstance(board, str) and re.fullmatch(r"[0-9a-f]{16}", board) and \
                self._db.execute("SELECT 1 FROM boards WHERE id=?", (board,)).fetchone():
            # the first board Shortcut (25 Oct) put the choice on the post itself
            self._db.execute("INSERT OR IGNORE INTO board_pending (board_id, canonical_url, note, created_at) "
                             "VALUES (?,?,?,?)", (board, link.url, "", now))
        self._db.execute("INSERT INTO deliveries VALUES (?,?,?,?)", (phone.id, item_id, link.url, now))
        row = self._db.execute("SELECT saved_count FROM items WHERE canonical_url=?", (link.url,)).fetchone()
        if row:
            if self.phone_kind(phone.id) == "agent":
                # Agents may add links, not restore trash, move board-only saves or change hidden saves.
                return ItemResult(item_id, "again", saved_count=row["saved_count"],
                                  needs_expansion=link.needs_expansion)
            self._db.execute(
                "UPDATE items SET saved_count=saved_count+1, last_shared_at=?, last_phone_id=?, updated_at=?, "
                "shelf=CASE WHEN shelf IN ('trash', 'board') THEN 'inbox' ELSE shelf END, via_board=NULL, media_only=0, "
                "trashed_at=CASE WHEN shelf='trash' THEN NULL ELSE trashed_at END "
                "WHERE canonical_url=?", (shared_at, phone.id, now, link.url))
            return ItemResult(item_id, "again", saved_count=row["saved_count"] + 1,
                              needs_expansion=link.needs_expansion)
        self._db.execute(
            "INSERT INTO items (canonical_url, source, kind, first_phone_id, last_phone_id, first_shared_at, "
            "last_shared_at, saved_count, note, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,?,?,?,?)",
            (link.url, link.source, link.kind, phone.id, phone.id, shared_at, shared_at, note,
             "expanding" if link.needs_expansion else "queued", now, now))
        return ItemResult(item_id, "new", saved_count=1, needs_expansion=link.needs_expansion)

    def _count(self, url: str) -> int:
        row = self._db.execute("SELECT saved_count FROM items WHERE canonical_url=?", (url,)).fetchone()
        return row["saved_count"] if row else 0

    # ---- reading ------------------------------------------------------------------------

    def items(self) -> list[dict]:
        """Every item, newest share first, with the sending phone's name."""
        with self._lock:
            rows = self._db.execute(
                "SELECT i.*, p.name AS phone FROM items i LEFT JOIN phones p ON p.id = i.last_phone_id "
                "ORDER BY i.last_shared_at DESC, i.created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_item(self, url: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM items WHERE canonical_url=?", (url,)).fetchone()
        return dict(row) if row else None

    # ---- short links: expansion bookkeeping ---------------------------------------------

    def due_for_expansion(self) -> list[CleanLink]:
        """Short links waiting for a first try, or whose retry time has come."""
        now = self._stamp()
        with self._lock:
            rows = self._db.execute(
                "SELECT canonical_url FROM items WHERE status='expanding' "
                "OR (status='needs_attention' AND next_retry_at IS NOT NULL AND next_retry_at <= ?) "
                "ORDER BY created_at", (now,)).fetchall()
        due = []
        for row in rows:
            try:
                link = clean(row["canonical_url"])
            except UnsupportedLink:
                continue
            if link.needs_expansion:
                due.append(link)
        return due

    def expansion_succeeded(self, short_url: str, link: CleanLink) -> None:
        """Replace the short link by the clean one; merge if that post is already stored."""
        now = self._stamp()
        merged_note = False
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                short = self._db.execute("SELECT * FROM items WHERE canonical_url=?", (short_url,)).fetchone()
                if short is not None:
                    target = self._db.execute(
                        "SELECT canonical_url FROM items WHERE canonical_url=?", (link.url,)).fetchone()
                    if target:
                        self._db.execute(
                            "UPDATE items SET saved_count=saved_count+?, updated_at=?, "
                            "last_shared_at=MAX(COALESCE(last_shared_at,''), COALESCE(?,'')), "
                            "last_phone_id=? WHERE canonical_url=?",
                            (short["saved_count"], now, short["last_shared_at"], short["last_phone_id"], link.url))
                        self._merge_agent_note(short, link.url)
                        merged_note = bool(short["agent_note"])
                        self._db.execute("DELETE FROM items WHERE canonical_url=?", (short_url,))
                    else:
                        self._db.execute(
                            "UPDATE items SET canonical_url=?, source=?, kind=?, status='queued', reason=NULL, "
                            "reason_detail=NULL, next_retry_at=NULL, attempts=0, updated_at=? WHERE canonical_url=?",
                            (link.url, link.source, link.kind, now, short_url))
                    for table, column in (("deliveries", "canonical_url"), ("tags", "canonical_url"), ("search", "url"),
                                          ("timings", "canonical_url"), ("links", "canonical_url"),
                                          ("agent_note_history", "canonical_url")):
                        self._db.execute(f"UPDATE OR IGNORE {table} SET {column}=? WHERE {column}=?", (link.url, short_url))
                    if link.url != short_url:
                        self._db.execute("UPDATE OR IGNORE board_pending SET canonical_url=? WHERE canonical_url=?", (link.url, short_url))
                        self._db.execute("DELETE FROM board_pending WHERE canonical_url=?", (short_url,))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        if merged_note:
            self._reindex(link.url)

    def _merge_agent_note(self, short, target_url: str) -> None:
        """A short link that turns out to be a post already saved: its agent note must not vanish with its row. An empty
        target takes it; otherwise it is added under the target's note, and when that would be too long it goes into
        the target's history, where undo can bring it back. Runs inside expansion_succeeded's transaction."""
        note = short["agent_note"] or ""
        if not note:
            return
        target = self._db.execute("SELECT agent_note, agent_note_by, agent_note_at FROM items WHERE canonical_url=?",
                                  (target_url,)).fetchone()
        if not target["agent_note"]:
            self._db.execute("UPDATE items SET agent_note=?, agent_note_by=?, agent_note_at=? WHERE canonical_url=?",
                             (note, short["agent_note_by"], short["agent_note_at"], target_url))
        elif len(target["agent_note"]) + 1 + len(note) <= MAX_NOTE_LEN:
            self._db.execute("INSERT INTO agent_note_history (canonical_url, text, by, at) VALUES (?,?,?,?)",
                             (target_url, target["agent_note"], target["agent_note_by"], target["agent_note_at"]))
            self._db.execute("UPDATE items SET agent_note=? WHERE canonical_url=?",
                             (f'{target["agent_note"]}\n{note}', target_url))
        else:
            self._db.execute("INSERT INTO agent_note_history (canonical_url, text, by, at) VALUES (?,?,?,?)",
                             (target_url, note, short["agent_note_by"], short["agent_note_at"]))

    def expansion_failed(self, short_url: str, detail: str) -> None:
        """Flag the item and schedule the next try; once the schedule runs out it just stays flagged."""
        with self._lock:
            row = self._db.execute("SELECT attempts FROM items WHERE canonical_url=?", (short_url,)).fetchone()
            if row is None:
                return
            attempts = row["attempts"] + 1
            delay = retry_delay(attempts - 1)
            retry_at = None if delay is None else (self._now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self._db.execute(
                "UPDATE items SET status='needs_attention', reason=?, reason_detail=?, attempts=?, "
                "next_retry_at=?, updated_at=? WHERE canonical_url=?",
                (FAILURE_REASON, detail[:200], attempts, retry_at, self._stamp(), short_url))


    # ---- fetching: archive bookkeeping --------------------------------------------------

    def due_for_fetch(self) -> list[dict]:
        """Clean links waiting to be fetched, or whose fetch retry time has come (oldest first)."""
        now = self._stamp()
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM items WHERE status='queued' "
                "OR (status='needs_attention' AND next_retry_at IS NOT NULL AND next_retry_at <= ?) "
                "ORDER BY created_at", (now,)).fetchall()
        due = []
        for row in rows:
            try:
                if clean(row["canonical_url"]).needs_expansion:
                    continue  # the short-link worker owns these
            except UnsupportedLink:
                continue
            due.append(dict(row))
        return due

    def fetch_succeeded(self, url: str, archive_dir: str) -> None:
        now = self._stamp()
        with self._lock:
            self._db.execute(
                "UPDATE items SET status='archived', archive_dir=?, archived_at=?, reason=NULL, reason_detail=NULL, "
                "attempts=0, next_retry_at=NULL, updated_at=? WHERE canonical_url=?", (archive_dir, now, now, url))

    def fetch_failed(self, url: str, reason: str, detail: str, retry: bool) -> None:
        """Flag the item; `retry` schedules the next try on the usual schedule, else it waits for Retry."""
        with self._lock:
            row = self._db.execute("SELECT attempts FROM items WHERE canonical_url=?", (url,)).fetchone()
            if row is None:
                return
            attempts = row["attempts"] + 1
            delay = retry_delay(attempts - 1) if retry else None
            retry_at = None if delay is None else (self._now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self._db.execute(
                "UPDATE items SET status='needs_attention', reason=?, reason_detail=?, attempts=?, "
                "next_retry_at=?, updated_at=? WHERE canonical_url=?",
                (reason, detail[:200], attempts, retry_at, self._stamp(), url))

    def retry(self, url: str) -> bool:
        """The Retry button: start over (a short link is expanded again, a post is fetched again)."""
        try:
            status = "expanding" if clean(url).needs_expansion else "queued"
        except UnsupportedLink:
            return False
        with self._lock:
            cur = self._db.execute(
                "UPDATE items SET status=?, reason=NULL, reason_detail=NULL, attempts=0, next_retry_at=NULL, "
                "updated_at=? WHERE canonical_url=? AND status='needs_attention'", (status, self._stamp(), url))
        return cur.rowcount > 0

    # ---- the doctor ---------------------------------------------------------------------

    def integrity(self) -> str:
        with self._lock:
            return self._db.execute("PRAGMA quick_check").fetchone()[0]

    def count_items(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def last_delivery(self) -> str:
        with self._lock:
            return self._db.execute("SELECT MAX(received_at) FROM deliveries").fetchone()[0] or ""

    def delivered_kinds(self) -> set[str]:
        """Which kinds of device have ever delivered a save: "phone", "browser" (the Chrome extension) or "agent"."""
        with self._lock:
            rows = self._db.execute("SELECT DISTINCT p.kind FROM deliveries d JOIN phones p ON p.id=d.phone_id").fetchall()
        return {r[0] for r in rows}

    def newest_by_source(self) -> dict[str, str]:
        """The newest saved (archived) post from each site, to test the site with."""
        with self._lock:
            rows = self._db.execute(
                "SELECT source, canonical_url FROM items WHERE status='archived' AND shelf != 'trash' "
                "ORDER BY archived_at").fetchall()
        return {r["source"]: r["canonical_url"] for r in rows}

    def mark_login_only(self, url: str) -> None:
        """Instagram shows this post only to logged-in people: it is left out of every refresh from now on."""
        with self._lock:
            self._db.execute("UPDATE items SET login_only=MAX(login_only, 1) WHERE canonical_url=?", (url,))
            self._db.commit()

    def keep_as_link(self, item_id: int, archive: bool = False) -> bool:
        """The owner leaves a post Instagram will not show as it is: no more tries, out of Needs attention. Optionally
        on the Archive shelf too."""
        item = self.item_by_id(item_id)
        if not item:
            return False
        with self._lock:
            self._db.execute("UPDATE items SET login_only=2, next_retry_at=NULL WHERE rowid=?", (item_id,))
            self._db.commit()
        if archive:
            self.set_shelf(item_id, "archive")
        return True

    def try_with_login(self, item_id: int) -> bool:
        """The owner allows their saved login to this post's site for this one item, and it is fetched again."""
        item = self.item_by_id(item_id)
        if not item:
            return False
        with self._lock:
            self._db.execute("UPDATE items SET use_login=1 WHERE rowid=?", (item_id,))
        return self.retry(item["canonical_url"])

    # ---- the hub ------------------------------------------------------------------------

    def add_link(self, url: str) -> ItemResult:
        """A link typed into the hub: cleaned and queued exactly like a phone share (no phone)."""
        link = clean(url)  # raises UnsupportedLink
        now = self._stamp()
        with self._lock:
            row = self._db.execute("SELECT saved_count FROM items WHERE canonical_url=?", (link.url,)).fetchone()
            if row:
                self._db.execute(
                    "UPDATE items SET saved_count=saved_count+1, last_shared_at=?, updated_at=?, "
                    "shelf=CASE WHEN shelf IN ('trash', 'board') THEN 'inbox' ELSE shelf END, via_board=NULL, media_only=0 WHERE canonical_url=?",
                    (now, now, link.url))
                return ItemResult(link.url, "again", saved_count=row["saved_count"] + 1)
            self._db.execute(
                "INSERT INTO items (canonical_url, source, kind, first_shared_at, last_shared_at, saved_count, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?,?)",
                (link.url, link.source, link.kind, now, now, "expanding" if link.needs_expansion else "queued", now, now))
        return ItemResult(link.url, "new", saved_count=1, needs_expansion=link.needs_expansion)

    def set_details(self, url: str, details: dict) -> None:
        """What the hub lists, copied from the archive's meta.json."""
        with self._lock:
            self._db.execute(
                "UPDATE items SET title=?, author=?, caption=?, thumb=?, media_kind=?, published_at=? WHERE canonical_url=?",
                (details.get("title") or "", details.get("author") or "", details.get("caption") or "",
                 details.get("thumb"), details.get("media_kind"), details.get("published_at") or "", url))
        self._reindex(url)

    def _reindex(self, url: str) -> None:
        with self._lock:
            row = self._db.execute(
                "SELECT title, ai_title, author, caption, note, agent_note, summary, transcript_text, entities_text, screen_text "
                "FROM items WHERE canonical_url=?", (url,)).fetchone()
            self._db.execute("DELETE FROM search WHERE url=?", (url,))
            if row:
                self._db.execute(
                    f"INSERT INTO search (url, {', '.join(SEARCH_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (url, " ".join(filter(None, (row["ai_title"], row["title"]))), row["author"] or "",
                     row["caption"] or "", " ".join(self.tags_for(url)), " ".join(filter(None, (row["note"], row["agent_note"]))), row["summary"] or "",
                     row["transcript_text"] or "", " ".join(filter(None, [row["entities_text"] or "", *(
                         r[0] for r in self._db.execute("SELECT DISTINCT name FROM links WHERE canonical_url=? AND removed=0",
                                                        (url,)).fetchall())])),
                     row["screen_text"] or ""))

    def id_for(self, url: str) -> int | None:
        with self._lock:
            row = self._db.execute("SELECT rowid FROM items WHERE canonical_url=?", (url,)).fetchone()
        return row[0] if row else None

    def item_by_id(self, item_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT rowid AS id, * FROM items WHERE rowid=?", (item_id,)).fetchone()
        if not row:
            return None
        found = dict(row)
        found["tags"] = self.tags_for(found["canonical_url"])
        return found

    def items_by_urls(self, urls: list[str]) -> list[dict]:
        """Full saves in input order (including repeats), skipping missing URLs."""
        return self._items_by("canonical_url", urls)

    def items_by_ids(self, ids: list[int]) -> list[dict]:
        """Full saves in input order (including repeats), skipping missing IDs."""
        return self._items_by("id", ids)

    def _items_by(self, column: str, values: list) -> list[dict]:
        found = {}
        for start in range(0, len(values), 400):
            batch = values[start:start + 400]
            with self._lock:
                rows = [dict(r) for r in self._db.execute(
                    f"SELECT rowid AS id, * FROM items WHERE {column} IN ({','.join('?' for _ in batch)})", batch)]
                self._attach_tags(rows)
            found.update((r[column], r) for r in rows)
        return [found[v] for v in values if v in found]

    def fetch_for_board(self, cards) -> int:
        """Friends' posts on a board, queued to be downloaded on this Mac (logged-out, like any save) and read only
        on the Mac: the summary, title, type, tags and links come from the friend's card, the transcript and frames
        are made here, and no AI runs unless the owner presses Summarise again. Kept off the library. Returns how
        many were queued."""
        now, added = self._stamp(), 0
        with self._lock, self._db:
            for card in cards:
                try:
                    link = clean(card["url"])
                except UnsupportedLink:
                    continue
                row = self._db.execute("SELECT media_only, ai_status FROM items WHERE canonical_url=?", (link.url,)).fetchone()
                if row and not (row["media_only"] and row["ai_status"] is None):
                    continue
                if not row:
                    self._db.execute(
                        "INSERT INTO items (canonical_url, source, kind, first_shared_at, last_shared_at, saved_count, "
                        "status, shelf, media_only, created_at, updated_at) VALUES (?,?,?,?,?,0,?, 'board', 1, ?,?)",
                        (link.url, link.source, link.kind, now, now, "expanding" if link.needs_expansion else "queued",
                         now, now))
                    added += 1
                # what the friend's Mac sent stands in for the summary: marked done, so no AI runs on it
                self._db.execute("UPDATE items SET ai_status='done', ai_title=?, summary=?, ai_type=?, suggested_tags=? "
                                 "WHERE canonical_url=?",
                                 (card.get("title") or None, card.get("summary") or "", card.get("kind") or None,
                                  json.dumps(list(card.get("tags") or [])[:12]), link.url))
                links = [x for x in card.get("links") or [] if str(x.get("url", "")).startswith(("https://", "http://"))]
                for rank, x in enumerate(links[:8]):
                    self._db.execute(
                        "INSERT OR IGNORE INTO links (canonical_url, name, kind, url, title, source, rank, checked, origin, "
                        "found_at, role, central, section) VALUES (?,?,'links',?,?,'board','best','yes','auto',?, 'main', 1, 'named')",
                        (link.url, str(x.get("name") or "")[:80], x["url"], str(x.get("name") or "")[:80], now))
                if links:
                    self._db.execute("UPDATE items SET links_status='done' WHERE canonical_url=?", (link.url,))
        return added

    def item_by_url(self, url: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT rowid FROM items WHERE canonical_url=?", (url,)).fetchone()
        return self.item_by_id(row[0]) if row else None

    def did_you_mean(self, query: str) -> str:
        """The search with misspelt words put right, using words that really occur in the library; "" when nothing needs
        fixing. A word counts as misspelt when no word in the library starts with it."""
        import difflib

        words = re.findall(r"\w+", query, flags=re.UNICODE)[:12]
        if not words:
            return ""
        try:
            with self._lock:
                self._db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.search_vocab USING fts5vocab(main, search, 'row')")
                vocab = {r[0]: r[1] for r in self._db.execute("SELECT term, doc FROM temp.search_vocab").fetchall()}
        except Exception as err:  # spelling suggestions must not block search
            log.debug("Search vocabulary unavailable (%s)", type(err).__name__)
            return ""
        fixed, changed = [], False
        for w in words:
            low = w.lower()
            if len(low) < 4 or any(t.startswith(low) for t in vocab):
                fixed.append(w)
                continue
            near = [t for t in difflib.get_close_matches(low, [t for t in vocab if abs(len(t) - len(low)) <= 2], n=5, cutoff=0.75)]
            if near:
                fixed.append(max(near, key=lambda t: vocab[t]))
                changed = True
            else:
                fixed.append(w)
        return " ".join(fixed) if changed else ""

    def hub_items(self, shelf: str = "inbox", query: str = "", source: str = "", tag: str = "",
                  attention: bool = False, limit: int = 300, compact: bool = False) -> list[dict]:
        # Ranking and filtering the wall need only descriptors. Full records are fetched for visible tiles.
        columns = ("id, canonical_url, source, status, shelf, created_at, last_shared_at, published_at, "
                   "archive_dir, thumb, ai_status, ai_type, author") if compact else "rowid AS id, *"
        if shelf == "kept":  # search: the library and the archive together
            sql, args = [f"SELECT {columns} FROM items WHERE shelf IN ('inbox', 'archive')"], []
        else:
            sql = [f"SELECT {columns} FROM items WHERE shelf=?"]
            args: list = [shelf if shelf in SHELVES else "inbox"]
        if source:
            sql.append("AND source=?")
            args.append(source)
        if tag:
            sql.append("AND canonical_url IN (SELECT canonical_url FROM tags WHERE tag=?)")
            args.append(tag)
        if attention:
            sql.append("AND status='needs_attention' AND login_only!=2")
        words = re.findall(r"\w+", query, flags=re.UNICODE)
        if words:
            match = " ".join(f'"{w}"*' for w in words[:12])
            sql.append("AND canonical_url IN (SELECT url FROM search WHERE search MATCH ?)")
            args.append(match)
        sql.append("ORDER BY COALESCE(last_shared_at, created_at) DESC LIMIT ?")
        args.append(limit)
        with self._lock:
            rows = [dict(r) for r in self._db.execute(" ".join(sql), args).fetchall()]
            self._attach_tags(rows)
        return rows

    def _attach_tags(self, rows: list[dict]) -> None:
        with self._lock:
            tag_rows = []
            # Small requests (including the checklist's single save) need only their own tags.
            # Batches stay below SQLite's variable limit even for a large or unlimited result.
            for start in range(0, len(rows), 400):
                urls = [r["canonical_url"] for r in rows[start:start + 400]]
                tag_rows.extend(self._db.execute(
                    f"SELECT canonical_url, tag FROM tags WHERE canonical_url IN ({','.join('?' for _ in urls)}) ORDER BY tag",
                    urls).fetchall())
        by_url: dict[str, list[str]] = {}
        for r in tag_rows:
            by_url.setdefault(r["canonical_url"], []).append(r["tag"])
        for r in rows:
            r["tags"] = by_url.get(r["canonical_url"], [])

    def progress_signature(self) -> str:
        """Changes whenever the wall would look different (a new save, a step finished, a problem): the hub
        reloads its page content when it does."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*), SUM(status='archived'), SUM(ai_status='done'), SUM(status='needs_attention'), "
                "SUM(ai_status='needs_attention'), SUM(senses_status='done'), SUM(links_status IS NOT NULL), "
                "MAX(created_at), MAX(processed_at), (SELECT COUNT(*) FROM board_events), "
                "(SELECT COUNT(*) || '-' || IFNULL(MAX(created_at), '') FROM board_pending) FROM items").fetchone()
        return ":".join(str(v or 0) for v in row)

    def item_signature(self, item_id: int) -> str:
        """Changes when this one post would look different (its steps, shelf, tags, summary, or a board vote): an open post
        reloads on this, not on every save elsewhere."""
        with self._lock:
            row = self._db.execute(
                "SELECT status, ai_status, senses_status, links_status, screen_text IS NULL, processed_at, shelf, updated_at, "
                "(SELECT COUNT(*) FROM board_events) FROM items WHERE rowid=?", (item_id,)).fetchone()
            tags = self._db.execute("SELECT COUNT(*) FROM tags t JOIN items i ON i.canonical_url=t.canonical_url WHERE i.rowid=?",
                                    (item_id,)).fetchone()[0]
        return ":".join(str(v or 0) for v in (*(row or ()), tags))

    def panel_counts(self) -> tuple[int, int, int]:
        """The library, what is waiting to be read, and what needs the owner, cheap enough for the menu bar to ask often."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(status IN ('queued', 'expanding')), 0), "
                "COALESCE(SUM(status='needs_attention' AND login_only!=2), 0) FROM items WHERE shelf='inbox'").fetchone()
        return row[0], row[1], row[2]

    def hub_counts(self) -> dict:
        """Counts for the hub's tabs and filters."""
        with self._lock:
            shelves = dict(self._db.execute("SELECT shelf, COUNT(*) FROM items GROUP BY shelf").fetchall())
            sources = dict(self._db.execute(
                "SELECT source, COUNT(*) FROM items WHERE shelf='inbox' GROUP BY source").fetchall())
            tags = dict(self._db.execute(
                "SELECT t.tag, COUNT(*) FROM tags t JOIN items i ON i.canonical_url=t.canonical_url "
                "WHERE i.shelf != 'trash' GROUP BY t.tag ORDER BY t.tag").fetchall())
            attention = self._db.execute(
                "SELECT COUNT(*) FROM items WHERE shelf='inbox' AND status='needs_attention' AND login_only!=2").fetchone()[0]
        return {"shelves": shelves, "sources": sources, "tags": tags, "attention": attention}

    def known_words(self, limit: int = 60) -> dict:
        """The owner's most used tags and the topics of their posts, for the summary to reuse."""
        with self._lock:
            tags = [r[0] for r in self._db.execute(
                "SELECT t.tag FROM tags t JOIN items i ON i.canonical_url=t.canonical_url WHERE i.shelf != 'trash' "
                "GROUP BY t.tag ORDER BY COUNT(*) DESC, t.tag LIMIT ?", (limit,)).fetchall()]
        topics: dict[str, int] = {}
        for folder in self._recent_folders(200):
            try:
                topic = json.loads((Path(folder) / "record.json").read_text()).get("topic")
            except (OSError, ValueError):
                continue
            if topic:
                topics[topic] = topics.get(topic, 0) + 1
        return {"tags": tags, "topics": sorted(topics, key=lambda t: -topics[t])[:30]}

    def _recent_folders(self, limit: int) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute(
                "SELECT archive_dir FROM items WHERE ai_status='done' AND archive_dir IS NOT NULL AND shelf != 'trash' "
                "ORDER BY processed_at DESC LIMIT ?", (limit,)).fetchall()]

    def tags_for(self, url: str) -> list[str]:
        with self._lock:
            return [r["tag"] for r in self._db.execute(
                "SELECT tag FROM tags WHERE canonical_url=? ORDER BY tag", (url,)).fetchall()]

    def set_tags(self, item_id: int, text: str) -> None:
        """Tags typed as 'cooking, ai tools' (comma separated); lower case, de-duplicated."""
        tags = []
        for part in text.split(","):
            tag = re.sub(r"\s+", " ", part).strip().lower()[:MAX_TAG_LEN]
            if tag and tag not in tags:
                tags.append(tag)
        item = self.item_by_id(item_id)
        if not item:
            return
        with self._lock:
            self._db.execute("DELETE FROM tags WHERE canonical_url=?", (item["canonical_url"],))
            self._db.executemany("INSERT INTO tags VALUES (?,?)", [(item["canonical_url"], t) for t in tags[:MAX_TAGS]])
        self._reindex(item["canonical_url"])

    def set_note(self, item_id: int, note: str) -> None:
        item = self.item_by_id(item_id)
        if not item:
            return
        with self._lock:
            self._db.execute("UPDATE items SET note=? WHERE rowid=?", (note[:MAX_NOTE_LEN], item_id))
        self._reindex(item["canonical_url"])

    def set_agent_note(self, item_id: int, mode: str, text: str = "", by: str = "") -> dict | None:
        """The AI agents' note on a save, kept apart from the owner's own note. Modes: set, append, clear, undo.
        Every change keeps the version it replaced, so `undo` steps back (even over a clear). None when the save is
        not in the library or archive; ValueError for text that is too long or has nothing to undo. One write
        transaction covers reading the note, its history and the new note, so two edits at once (the hub and a
        command) cannot lose each other's text, and a failure part-way changes nothing."""
        if mode not in ("set", "append", "clear", "undo"):
            raise ValueError("unknown mode")
        if len(text) > MAX_NOTE_LEN:
            raise ValueError(f"a note can be at most {MAX_NOTE_LEN} characters")
        now = self._stamp()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                item = self._db.execute(
                    "SELECT canonical_url, shelf, agent_note, agent_note_by, agent_note_at FROM items WHERE rowid=?",
                    (item_id,)).fetchone()
                if not item or item["shelf"] not in ("inbox", "archive"):
                    self._db.execute("ROLLBACK")
                    return None
                url, old = item["canonical_url"], item["agent_note"] or ""
                if mode == "undo":
                    last = self._db.execute("SELECT id, text, by, at FROM agent_note_history WHERE canonical_url=? "
                                            "ORDER BY id DESC LIMIT 1", (url,)).fetchone()
                    if not last:
                        raise ValueError("nothing to undo")
                    new, who, when = last["text"], last["by"], last["at"]
                else:
                    new = "" if mode == "clear" else (f"{old}\n{text}" if mode == "append" and old else text)
                    if len(new) > MAX_NOTE_LEN:
                        raise ValueError(f"a note can be at most {MAX_NOTE_LEN} characters")
                    who, when = (by[:40], now) if new else ("", "")
                if mode == "undo":
                    self._db.execute("DELETE FROM agent_note_history WHERE id=?", (last["id"],))
                elif old:
                    self._db.execute("INSERT INTO agent_note_history (canonical_url, text, by, at) VALUES (?,?,?,?)",
                                     (url, old, item["agent_note_by"] or "", item["agent_note_at"] or ""))
                self._db.execute("UPDATE items SET agent_note=?, agent_note_by=?, agent_note_at=? WHERE rowid=?",
                                 (new, who, when, item_id))
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        self._reindex(url)
        return {"text": new, "by": who, "at": when}

    def set_shelf(self, item_id: int, shelf: str) -> bool:
        if shelf not in SHELVES:
            return False
        with self._lock:
            cur = self._db.execute(
                "UPDATE items SET shelf=?, trashed_at=?, updated_at=?, "
                "media_only=CASE WHEN ? IN ('inbox', 'archive') THEN 0 ELSE media_only END WHERE rowid=?",
                (shelf, self._stamp() if shelf == "trash" else None, self._stamp(), shelf, item_id))
        return cur.rowcount > 0

    def purge_trash(self, everything: bool = False) -> list[str]:
        """Delete trashed items (all, or those older than TRASH_DAYS). Returns their archive folders."""
        cutoff = (self._now() - timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._db.execute(
                "SELECT canonical_url, archive_dir FROM items WHERE shelf='trash'" + ("" if everything else " AND trashed_at <= ?"),
                () if everything else (cutoff,)).fetchall()
            for r in rows:
                for table, column in (("items", "canonical_url"), ("tags", "canonical_url"), ("search", "url"),
                                      ("timings", "canonical_url"), ("links", "canonical_url"),
                                      ("agent_note_history", "canonical_url")):
                    self._db.execute(f"DELETE FROM {table} WHERE {column}=?", (r["canonical_url"],))
        return [r["archive_dir"] for r in rows if r["archive_dir"]]

    # ---- the brain (M3) -----------------------------------------------------------------

    def due_for_brain(self) -> list[dict]:
        """Archived items that still need a transcript or a summary (or whose summary retry time has come).
        "Try again" items go first, then the newest shares."""
        now = self._stamp()
        with self._lock:
            rows = self._db.execute(
                "SELECT rowid AS id, * FROM items WHERE status='archived' AND shelf != 'trash' AND "
                "(senses_status IS NULL OR ai_force=1 OR ai_status IS NULL OR "
                "(ai_status='needs_attention' AND ai_next_at IS NOT NULL AND ai_next_at <= ?)) "
                "ORDER BY ai_force DESC, created_at DESC", (now,)).fetchall()
        return [dict(r) for r in rows]

    def screen_done(self, url: str, text: str) -> None:
        """The text read off the screen for a post ("" when there was none): searchable from now on."""
        with self._lock:
            self._db.execute("UPDATE items SET screen_text=? WHERE canonical_url=?", (text, url))
        self._reindex(url)

    def due_for_screen(self, limit: int = 20) -> list[dict]:
        """Archived posts whose on-screen text has not been read yet, oldest first (reset to NULL to read again)."""
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT rowid AS id, * FROM items WHERE status='archived' AND screen_text IS NULL AND archive_dir IS NOT NULL "
                "AND shelf != 'trash' ORDER BY created_at LIMIT ?", (limit,)).fetchall()]

    def reset_screen(self, url: str | None = None) -> int:
        """Read the on-screen text again: for one post, or for every post."""
        with self._lock:
            cur = self._db.execute("UPDATE items SET screen_text=NULL" + (" WHERE canonical_url=?" if url else ""), (url,) if url else ())
            return cur.rowcount

    # ---- private activity counts ---------------------------------------------------------

    def activity_add(self, kind: str, n: int = 1) -> None:
        """One more of something done in the hub today (counted on this Mac only); a negative `n` takes one back, never below zero."""
        day = self._now().date().isoformat()
        with self._lock, self._db:
            self._db.execute("INSERT INTO activity (day, kind, n) VALUES (?,?,MAX(0, ?)) ON CONFLICT(day, kind) DO UPDATE SET n = MAX(0, n + ?)",
                             (day, kind, n, n))

    def activity_days(self, days: int = 30) -> dict[str, dict[str, int]]:
        """{kind: {day: count}} for the last `days` days, today included."""
        since = (self._now().date() - timedelta(days=days - 1)).isoformat()
        with self._lock:
            rows = self._db.execute("SELECT day, kind, n FROM activity WHERE day >= ?", (since,)).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["kind"], {})[r["day"]] = r["n"]
        return out

    def activity_clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM activity")

    def senses_done(self, url: str, transcript_text: str) -> None:
        """The transcript is saved and searchable as soon as it exists, whatever happens to the summary."""
        with self._lock:
            self._db.execute("UPDATE items SET senses_status='done', transcript_text=? WHERE canonical_url=?",
                             (transcript_text, url))
        self._reindex(url)

    def paused(self, part: str) -> bool:
        """part: transcribe, summary or links."""
        return self.get_setting(f"pause_{part}") == "1"

    def set_paused(self, part: str, value: bool) -> None:
        self.set_setting(f"pause_{part}", "1" if value else "")

    def brain_succeeded(self, url: str, record: dict, transcript_text: str, apply_tags: bool) -> None:
        entities = " ".join(v for values in record["entities"].values() for v in values)
        with self._lock:
            self._db.execute(
                "UPDATE items SET ai_status='done', ai_reason=NULL, ai_detail=NULL, ai_attempts=0, ai_next_at=NULL, ai_force=0, "
                "links_status=NULL, "  # a new record names new things: find their links again
                "ai_title=?, summary=?, ai_type=?, suggested_tags=?, entities_text=?, transcript_text=?, processed_at=? "
                "WHERE canonical_url=?",
                (record["title"], record["summary"], record["type"], json.dumps(record["suggested_tags"]),
                 entities, transcript_text, self._stamp(), url))
            if apply_tags:
                self._db.executemany("INSERT OR IGNORE INTO tags VALUES (?,?)",
                                     [(url, t) for t in record["suggested_tags"]])
        self._reindex(url)

    def brain_failed(self, url: str, reason: str, detail: str, retry: bool) -> None:
        with self._lock:
            row = self._db.execute("SELECT ai_attempts FROM items WHERE canonical_url=?", (url,)).fetchone()
            if row is None:
                return
            attempts = row["ai_attempts"] + 1
            delay = retry_delay(attempts - 1) if retry else None
            retry_at = None if delay is None else (self._now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self._db.execute(
                "UPDATE items SET ai_status='needs_attention', ai_reason=?, ai_detail=?, ai_attempts=?, ai_next_at=?, "
                "ai_force=0 WHERE canonical_url=?", (reason, detail[:200], attempts, retry_at, url))

    def summarise_again(self, item_id: int | None = None) -> int:
        """Queue one item (or all with a problem, when item_id is None) to be summarised again."""
        with self._lock:
            if item_id is None:
                cur = self._db.execute("UPDATE items SET ai_status=NULL, ai_attempts=0, ai_next_at=NULL "
                                       "WHERE ai_status='needs_attention'")
            else:  # the owner's own "Try again": first in line, even while summaries are paused
                cur = self._db.execute("UPDATE items SET ai_status=NULL, ai_attempts=0, ai_next_at=NULL, ai_force=1 "
                                       "WHERE rowid=?", (item_id,))
        return cur.rowcount

    def accept_tags(self, item_id: int) -> None:
        item = self.item_by_id(item_id)
        if not item or not item.get("suggested_tags"):
            return
        with self._lock:
            self._db.executemany("INSERT OR IGNORE INTO tags VALUES (?,?)",
                                 [(item["canonical_url"], t) for t in json.loads(item["suggested_tags"])])
        self._reindex(item["canonical_url"])

    # ---- timing and activity ------------------------------------------------------------

    def record_timing(self, url: str, step: str, started: float, ended: float) -> None:
        stamp = datetime.fromtimestamp(started).astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO timings VALUES (?,?,?,?)", (url, step, stamp, round(ended - started, 2)))

    def avg_step_seconds(self, step: str, default: float) -> float:
        """How long a step usually takes here: the average of the last 30 times, or `default` when there is no history."""
        with self._lock:
            row = self._db.execute("SELECT AVG(seconds) FROM (SELECT seconds FROM timings WHERE step=? ORDER BY started_at DESC LIMIT 30)", (step,)).fetchone()
        return float(row[0]) if row and row[0] else default

    def timings_for(self, url: str) -> dict[str, float]:
        with self._lock:
            return {r["step"]: r["seconds"] for r in self._db.execute(
                "SELECT step, seconds FROM timings WHERE canonical_url=?", (url,)).fetchall()}

    def waiting_counts(self) -> dict[str, int]:
        with self._lock:
            fetch = self._db.execute("SELECT COUNT(*) FROM items WHERE status IN ('queued','expanding')").fetchone()[0]
            process = self._db.execute("SELECT COUNT(*) FROM items WHERE status='archived' AND shelf != 'trash' "
                                       "AND media_only=0 AND (ai_status IS NULL OR senses_status IS NULL)").fetchone()[0]
        return {"fetch": fetch, "process": process}

    def waiting_items(self, limit: int = 20) -> dict[str, list[dict]]:
        with self._lock:
            fetch = self._db.execute("SELECT rowid AS id, * FROM items WHERE status IN ('queued','expanding') "
                                     "ORDER BY created_at LIMIT ?", (limit,)).fetchall()
            process = self._db.execute("SELECT rowid AS id, * FROM items WHERE status='archived' AND shelf != 'trash' "
                                       "AND media_only=0 AND (ai_status IS NULL OR senses_status IS NULL) "
                                       "ORDER BY ai_force DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"fetch": [dict(r) for r in fetch], "process": [dict(r) for r in process]}

    def recent_finished(self, limit: int = 50) -> list[dict]:
        """Items that went all the way to a summary, newest first, with their step times."""
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT rowid AS id, * FROM items WHERE ai_status='done' ORDER BY processed_at DESC LIMIT ?",
                (limit,)).fetchall()]
        for r in rows:
            r["timings"] = self.timings_for(r["canonical_url"])
        return rows

    def problems(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT rowid AS id, * FROM items WHERE shelf != 'trash' AND media_only=0 AND ((status='needs_attention' AND login_only!=2) "
                "OR ai_status='needs_attention') ORDER BY updated_at DESC LIMIT 50").fetchall()]

    # ---- summary budget: paused, the next N items, or all --------------------------------

    def summary_budget(self) -> str:
        """'all', or a number of summaries still allowed ('0' = paused)."""
        return self.get_setting("ai_budget", "all")

    def take_summary_turn(self) -> bool:
        with self._lock:
            budget = self.summary_budget()
            if budget == "all":
                return True
            left = int(budget) if budget.isdigit() else 0
            if left <= 0:
                return False
            self.set_setting("ai_budget", str(left - 1))
            return True

    def allow_one_more_summary(self) -> None:
        """A "Try again" click is the owner's say-so for one more request."""
        with self._lock:
            budget = self.summary_budget()
            if budget != "all":
                self.set_setting("ai_budget", str((int(budget) if budget.isdigit() else 0) + 1))

    # ---- links (M3.5) -------------------------------------------------------------------

    def due_for_links(self) -> list[dict]:
        """Summarised items whose links are not found yet ("Find more links" first, then the newest)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT rowid AS id, * FROM items WHERE ai_status='done' AND shelf != 'trash' AND "
                "(links_status IS NULL OR links_force=1) ORDER BY links_force DESC, created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def save_found_links(self, url: str, found: list, status: str = "done") -> None:
        """Replace the automatic links (the owner's own links and removals stay)."""
        now = self._stamp()
        with self._lock:
            removed = {r[0] for r in self._db.execute(
                "SELECT url FROM links WHERE canonical_url=? AND removed=1", (url,)).fetchall()}
            self._db.execute("DELETE FROM links WHERE canonical_url=? AND origin='auto' AND removed=0", (url,))
            for f in found:
                if f.url in removed:
                    continue
                self._db.execute(
                    "INSERT OR IGNORE INTO links (canonical_url, name, kind, url, title, source, rank, checked, origin, "
                    "found_at, role, central, section) VALUES (?,?,?,?,?,?,?,?, 'auto', ?,?,?,?)",
                    (url, f.name, f.kind, f.url, f.title, f.source, "possible" if f.possible else "best", f.checked,
                     now, f.role, int(f.central), f.section))
            self._db.execute("UPDATE items SET links_status=?, links_force=0 WHERE canonical_url=?", (status, url))
        self._reindex(url)

    def links_for(self, url: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT rowid AS id, * FROM links WHERE canonical_url=? AND removed=0 ORDER BY section != 'named', "
                "central DESC, CASE origin WHEN 'user' THEN 0 ELSE 1 END, rowid",
                (url,)).fetchall()]

    def removed_links(self, url: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute(
                "SELECT url FROM links WHERE canonical_url=? AND removed=1", (url,)).fetchall()}

    def remove_link(self, link_id: int) -> str | None:
        """The owner removes a link: kept as a tombstone so a later search never brings it back."""
        with self._lock:
            row = self._db.execute("SELECT canonical_url FROM links WHERE rowid=?", (link_id,)).fetchone()
            if row:
                self._db.execute("UPDATE links SET removed=1 WHERE rowid=?", (link_id,))
        if row:
            self._reindex(row[0])
        return row[0] if row else None

    def add_link_by_owner(self, item_id: int, name: str, url: str, kind: str = "links") -> bool:
        item = self.item_by_id(item_id)
        if not item or not name.strip() or urlsplit(url).scheme not in ("http", "https"):
            return False
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO links (canonical_url, name, kind, url, title, source, rank, checked, origin, "
                "removed, found_at) VALUES (?,?,?,?, '', 'added by you', 'best', 'yes', 'user', 0, ?)",
                (item["canonical_url"], name.strip()[:80], kind, url.strip()[:500], self._stamp()))
        self._reindex(item["canonical_url"])
        return True

    def find_links_again(self, item_id: int) -> None:
        with self._lock:
            self._db.execute("UPDATE items SET links_force=1 WHERE rowid=?", (item_id,))

    def link_urls(self) -> list[str]:
        """Every link address kept for any post (for site icons), newest first."""
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT url FROM links WHERE removed=0 ORDER BY rowid DESC").fetchall()]

    def urls_with_links(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT DISTINCT canonical_url FROM links WHERE removed=0")}

    def has_links(self, url: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM links WHERE canonical_url=? AND removed=0 LIMIT 1", (url,)).fetchone() is not None

    # ---- related content and piles (M4) -----------------------------------------------------

    def related_rows(self) -> list[dict]:
        """Everything Related and Piles look at: archived items outside the Trash, with tags and link names."""
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT rowid AS id, canonical_url, source, archive_dir, title, ai_title, caption, summary, suggested_tags, "
                "transcript_text, author, first_shared_at, created_at, published_at, thumb, media_kind, shelf "
                "FROM items WHERE status='archived' AND shelf IN ('inbox', 'archive') "
                "ORDER BY created_at").fetchall()]
            tags = self._db.execute("SELECT canonical_url, tag FROM tags").fetchall()
            names = self._db.execute("SELECT DISTINCT canonical_url, name FROM links WHERE removed=0").fetchall()
        by_tag: dict[str, list[str]] = {}
        for r in tags:
            by_tag.setdefault(r[0], []).append(r[1])
        by_name: dict[str, list[str]] = {}
        for r in names:
            by_name.setdefault(r[0], []).append(r[1])
        for r in rows:
            r["tags"] = by_tag.get(r["canonical_url"], [])
            r["link_names"] = by_name.get(r["canonical_url"], [])
        return rows

    def related_signature(self) -> tuple:
        """Changes whenever what Related and Piles look at changes."""
        with self._lock:
            return tuple(self._db.execute(
                "SELECT (SELECT COUNT(*) || '.' || IFNULL(SUM(rowid), 0) FROM vectors), (SELECT COUNT(*) FROM not_related), "
                "(SELECT COUNT(*) FROM items WHERE shelf='trash'), (SELECT COUNT(*) FROM items WHERE status='archived')"
            ).fetchone())

    def vectors(self, model: str) -> dict[str, tuple[str, bytes]]:
        with self._lock:
            return {r[0]: (r[1], r[2]) for r in self._db.execute(
                "SELECT canonical_url, text_hash, vector FROM vectors WHERE model=?", (model,)).fetchall()}

    def save_vector(self, url: str, model: str, text_hash: str, vector: bytes) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)", (url, model, text_hash, vector))

    def not_related_pairs(self) -> set[tuple[str, str]]:
        with self._lock:
            return {(r[0], r[1]) for r in self._db.execute("SELECT a, b FROM not_related").fetchall()}

    def mark_not_related(self, a: str, b: str) -> None:
        """The owner says two items are not related: never suggested together again."""
        if a != b:
            with self._lock:
                self._db.execute("INSERT OR IGNORE INTO not_related VALUES (?,?)", tuple(sorted((a, b))))

    def piles(self, deleted: bool = False) -> list[dict]:
        """Piles with their members (urls, oldest first); `removed` lists items the owner took out."""
        with self._lock:
            piles = [dict(r) for r in self._db.execute(
                "SELECT * FROM piles WHERE deleted=? ORDER BY id", (1 if deleted else 0,)).fetchall()]
            rows = self._db.execute("SELECT pile_id, canonical_url, origin, removed FROM pile_items ORDER BY rowid").fetchall()
        by_pile: dict[int, dict] = {p["id"]: p for p in piles}
        for p in piles:
            p["members"], p["removed"], p["owner_members"] = [], [], []
        for r in rows:
            p = by_pile.get(r["pile_id"])
            if p is None:
                continue
            if r["removed"]:
                p["removed"].append(r["canonical_url"])
            else:
                p["members"].append(r["canonical_url"])
                if r["origin"] == "owner":
                    p["owner_members"].append(r["canonical_url"])
        return piles

    def pile(self, pile_id: int) -> dict | None:
        return next((p for p in self.piles() if p["id"] == pile_id), None)

    def piles_for(self, url: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT p.id, p.name FROM piles p JOIN pile_items i ON i.pile_id=p.id "
                "WHERE i.canonical_url=? AND i.removed=0 AND p.deleted=0 ORDER BY p.name", (url,)).fetchall()]

    def save_auto_pile(self, pile_id: int | None, urls: list[str], auto_name: str, keep_name: bool = False,
                       mark_new: bool = False) -> int:
        """Create a pile, or set the automatic members of one (the owner's own members and removals stay).
        A save that joins an existing pile counts as new there until the owner opens the pile."""
        now = self._now().isoformat()  # to the microsecond: "new since the owner looked" needs it
        with self._lock:
            if pile_id is None:
                pile_id = self._db.execute("INSERT INTO piles (name, auto_name, created_at, seen_at) VALUES (?,?,?,?)",
                                           (auto_name, auto_name, now, now)).lastrowid
                added = ""
            else:
                if not keep_name:
                    self._db.execute("UPDATE piles SET auto_name=?, name=CASE owner_named WHEN 1 THEN name ELSE ? END "
                                     "WHERE id=?", (auto_name, auto_name, pile_id))
                added = now if mark_new else ""
                marks = ",".join("?" * len(urls)) or "''"
                self._db.execute(f"DELETE FROM pile_items WHERE pile_id=? AND origin='auto' AND removed=0 "
                                 f"AND canonical_url NOT IN ({marks})", (pile_id, *urls))
            self._db.executemany("INSERT OR IGNORE INTO pile_items (pile_id, canonical_url, added_at) VALUES (?,?,?)",
                                 [(pile_id, u, added) for u in urls])
        return pile_id

    def new_in_pile(self, pile_id: int) -> int:
        """Saves that joined the pile since the owner last opened it."""
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) FROM pile_items i JOIN piles p ON p.id=i.pile_id WHERE i.pile_id=? AND i.removed=0 "
                "AND i.added_at != '' AND i.added_at > p.seen_at", (pile_id,)).fetchone()[0]

    def pile_seen(self, pile_id: int) -> None:
        with self._lock:
            self._db.execute("UPDATE piles SET seen_at=? WHERE id=?", (self._now().isoformat(), pile_id))

    def drop_pile(self, pile_id: int) -> None:
        """An automatic pile the owner never touched, whose topic has gone."""
        with self._lock:
            self._db.execute("DELETE FROM pile_items WHERE pile_id=?", (pile_id,))
            self._db.execute("DELETE FROM piles WHERE id=?", (pile_id,))

    def rename_pile(self, pile_id: int, name: str) -> bool:
        name = " ".join(name.split())[:60]
        if not name:
            return False
        with self._lock:
            return self._db.execute("UPDATE piles SET name=?, owner_named=1 WHERE id=? AND deleted=0",
                                    (name, pile_id)).rowcount == 1

    def delete_pile(self, pile_id: int) -> None:
        """Kept as a tombstone so the same pile is not made again."""
        with self._lock:
            self._db.execute("UPDATE piles SET deleted=1 WHERE id=?", (pile_id,))

    def remove_from_pile(self, pile_id: int, url: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO pile_items (pile_id, canonical_url, origin, removed) "
                             "VALUES (?,?, 'owner', 1)", (pile_id, url))

    def move_to_pile(self, url: str, pile_id: int) -> bool:
        """The owner puts a save in a pile by hand: it joins that pile and leaves any other. Regrouping keeps it
        there (an owner member is never moved by Magpiary)."""
        if not self.pile(pile_id):
            return False
        with self._lock:
            self._db.execute("UPDATE pile_items SET removed=1, origin='owner' WHERE canonical_url=? AND pile_id != ? "
                             "AND removed=0", (url, pile_id))
            self._db.execute("INSERT OR REPLACE INTO pile_items (pile_id, canonical_url, origin, removed, added_at) "
                             "VALUES (?,?, 'owner', 0, '')", (pile_id, url))
        return True

    def new_pile(self, name: str) -> int:
        name = " ".join(name.split())[:60] or "New pile"
        with self._lock:
            return self._db.execute("INSERT INTO piles (name, auto_name, owner_named, owner_made, created_at, seen_at) "
                                    "VALUES (?, '', 1, 1, ?, ?)", (name, self._stamp(), self._now().isoformat())).lastrowid

    def merge_piles(self, source: int, target: int) -> bool:
        """Everything in `source` moves to `target`; `source` stays as a tombstone."""
        first, second = self.pile(source), self.pile(target)
        if not first or not second or source == target:
            return False
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO pile_items (pile_id, canonical_url, origin, removed) "
                                 "VALUES (?,?, 'owner', 0)", [(target, u) for u in first["members"]])
            self._db.execute("UPDATE piles SET owner_made=1 WHERE id=?", (target,))
        self.delete_pile(source)
        return True

    def split_pile(self, pile_id: int, urls: list[str], name: str) -> int | None:
        """The chosen items leave the pile and become a new pile of their own."""
        pile = self.pile(pile_id)
        urls = [u for u in urls if pile and u in pile["members"]]
        if not urls or len(urls) == len(pile["members"]):
            return None
        name = " ".join(name.split())[:60] or f"Part of {pile['name']}"
        with self._lock:
            new_id = self._db.execute("INSERT INTO piles (name, auto_name, owner_named, owner_made, created_at) "
                                      "VALUES (?, '', 1, 1, ?)", (name, self._stamp())).lastrowid
            self._db.executemany("INSERT INTO pile_items (pile_id, canonical_url, origin) VALUES (?,?, 'owner')",
                                 [(new_id, u) for u in urls])
        for u in urls:
            self.remove_from_pile(pile_id, u)
        return new_id

