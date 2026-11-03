-- Recorded queue schema before permanent numeric item ids.
CREATE TABLE phones (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL,
    home_wifi TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE digests (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    made_at TEXT NOT NULL, intro TEXT NOT NULL DEFAULT '', data TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE items (
    canonical_url TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT,
    first_phone_id INTEGER REFERENCES phones(id), last_phone_id INTEGER REFERENCES phones(id),
    first_shared_at TEXT, last_shared_at TEXT, saved_count INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, reason TEXT, reason_detail TEXT,
    attempts INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE deliveries (
    phone_id INTEGER NOT NULL, delivery_id TEXT NOT NULL, canonical_url TEXT NOT NULL,
    received_at TEXT NOT NULL, PRIMARY KEY (phone_id, delivery_id));
