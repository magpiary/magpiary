"""Popularity numbers (likes, comments, views) kept per post, and the very careful queue that refreshes them.

Refreshes are paced one post at a time, with a random gap of minutes between posts, a small daily cap per site and
only while the Mac is awake. A login-only post is skipped; two login walls in a row or one rate limit pause the site
for a day. The owner may route supported refreshes through an optional proxy. Refreshing reads the post's details
only: no download, no AI.
The numbers saved when a post was archived (meta.json) seed the table without any request.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from magpiary.sources import FetchFailed, describe
from magpiary.tools import YtDlp

GAP_SECONDS = (45, 120)        # a chosen refresh: a random wait of 45 to 120 seconds between two posts
DAILY_CAP = 40                 # ... and at most this many posts per site per day
AUTO_GAP_SECONDS = (240, 600)  # the weekly automatic refresh is slower still: 4 to 10 minutes
AUTO_DAILY_CAP = 15
STRIKES_TO_STOP = 2            # login walls in a row (no post read fine between) that stop a whole site
BLOCK_HOURS = 24               # a warning sign (login wall, rate limit) pauses that site this long
UNAVAILABLE_DAYS = 30          # a deleted or private post is not asked again for this long
AUTO_DAYS = 30                 # the weekly automatic refresh covers posts saved or shared this recently
AUTO_EVERY_DAYS = 7
STOP_REASONS = {"login_wall", "rate_limited"}   # reasons that stop a whole site, not just one post
KEYS = ("like_count", "comment_count", "view_count")
EXTRA_KEYS = ("repost_count", "share_count")  # kept with the post (meta.json), not in the stats table; Threads has them

STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS stats (
    canonical_url TEXT PRIMARY KEY, likes INTEGER, comments INTEGER, views INTEGER, fetched_at TEXT,
    prev_likes INTEGER, prev_comments INTEGER, prev_views INTEGER, prev_at TEXT,
    state TEXT NOT NULL DEFAULT 'ok', retry_after TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS stats_queue (
    canonical_url TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'manual', added_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opens (canonical_url TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS opens_url ON opens (canonical_url);
CREATE TABLE IF NOT EXISTS stats_log (day TEXT NOT NULL, source TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, source));
"""


def _now() -> datetime:
    return datetime.now().astimezone()


def _stamp(when: datetime | None = None) -> str:
    return (when or _now()).isoformat(timespec="seconds")


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class StatsStore:
    """Methods mixed into Store, on its connection and lock."""

    # ---- reading ------------------------------------------------------------------------------------

    def stats_for(self, url: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM stats WHERE canonical_url=?", (url,)).fetchone()
        return dict(row) if row else None

    def stats_all(self) -> dict[str, dict]:
        with self._lock:
            return {r["canonical_url"]: dict(r) for r in self._db.execute("SELECT * FROM stats")}

    # ---- writing ------------------------------------------------------------------------------------

    def stats_save(self, url: str, likes, comments, views, when: str | None = None) -> None:
        """Keep the new numbers and, if there were numbers before, the previous ones (one earlier snapshot)."""
        likes, comments, views = _int(likes), _int(comments), _int(views)
        when = when or _stamp()
        with self._lock:
            old = self._db.execute("SELECT * FROM stats WHERE canonical_url=?", (url,)).fetchone()
            if old and any(old[k] is not None for k in ("likes", "comments", "views")):
                self._db.execute(
                    "UPDATE stats SET prev_likes=likes, prev_comments=comments, prev_views=views, prev_at=fetched_at "
                    "WHERE canonical_url=?", (url,))
            self._db.execute(
                "INSERT INTO stats (canonical_url, likes, comments, views, fetched_at, state, retry_after, detail) "
                "VALUES (?, ?, ?, ?, ?, 'ok', '', '') ON CONFLICT(canonical_url) DO UPDATE SET likes=excluded.likes, "
                "comments=excluded.comments, views=excluded.views, fetched_at=excluded.fetched_at, state='ok', "
                "retry_after='', detail=''", (url, likes, comments, views, when))
            self._db.commit()

    def stats_unavailable(self, url: str, detail: str, days: int = UNAVAILABLE_DAYS) -> None:
        retry = _stamp(_now() + timedelta(days=days))
        with self._lock:
            self._db.execute(
                "INSERT INTO stats (canonical_url, state, retry_after, detail) VALUES (?, 'unavailable', ?, ?) "
                "ON CONFLICT(canonical_url) DO UPDATE SET state='unavailable', retry_after=excluded.retry_after, detail=excluded.detail",
                (url, retry, detail[:200]))
            self._db.commit()

    def stats_backfill(self) -> int:
        """Seed the table from what was saved with each post (meta.json): reads files on this Mac, makes no request."""
        done = 0
        with self._lock:
            have = {r[0] for r in self._db.execute("SELECT canonical_url FROM stats")}
            rows = self._db.execute(
                "SELECT canonical_url, archive_dir FROM items WHERE archive_dir IS NOT NULL AND status='archived'").fetchall()
        for row in rows:
            if row["canonical_url"] in have:
                continue
            try:
                meta = json.loads((Path(row["archive_dir"]) / "meta.json").read_text())
            except (OSError, ValueError):
                continue
            values = [_int(meta.get(k)) for k in KEYS]
            if all(v is None for v in values):
                continue
            self.stats_save(row["canonical_url"], *values, when=meta.get("stats_at") or meta.get("fetched_at") or _stamp())
            done += 1
        return done

    # ---- which posts get opened (a signal of interest; local only, never leaves this Mac) ------------------

    def open_record(self, url: str) -> None:
        """One open of a post's page or card. Re-draws and tab switches right after an open do not count again."""
        now = _now()
        with self._lock:
            last = self._db.execute("SELECT MAX(at) FROM opens WHERE canonical_url=?", (url,)).fetchone()[0]
            if last:
                try:
                    if now - datetime.fromisoformat(last) < timedelta(minutes=30):
                        return
                except ValueError:
                    pass
            self._db.execute("INSERT INTO opens (canonical_url, at) VALUES (?, ?)", (url, _stamp(now)))
            self._db.commit()

    def opens_weighted(self, half_life_days: float = 60.0) -> dict[str, float]:
        """Each post's opens, recent ones counting more (they halve every `half_life_days`)."""
        now = _now()
        out: dict[str, float] = {}
        with self._lock:
            rows = self._db.execute("SELECT canonical_url, at FROM opens").fetchall()
        for url, at in rows:
            try:
                age = (now - datetime.fromisoformat(at)).total_seconds() / 86400
            except ValueError:
                continue
            out[url] = out.get(url, 0.0) + 0.5 ** (max(age, 0) / half_life_days)
        return out

    # ---- the queue ----------------------------------------------------------------------------------

    def stats_enqueue(self, urls: list[str], kind: str = "manual") -> int:
        """Queue posts for a refresh. Posts marked unavailable stay out until their wait is over; a post already queued stays."""
        now, added = _stamp(), 0
        with self._lock:
            for url in urls:
                item = self._db.execute("SELECT source, shelf, login_only FROM items WHERE canonical_url=?", (url,)).fetchone()
                if not item or item["shelf"] == "trash" or item["login_only"]:
                    continue  # Instagram shows login-only posts to logged-in people only: they are never refreshed
                row = self._db.execute("SELECT state, retry_after FROM stats WHERE canonical_url=?", (url,)).fetchone()
                if row and row["state"] == "unavailable" and row["retry_after"] > now:
                    continue
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO stats_queue (canonical_url, source, kind, added_at) VALUES (?, ?, ?, ?)",
                    (url, item["source"], kind, now))
                added += cur.rowcount
            self._db.commit()
        return added

    def stats_queue_counts(self) -> dict[str, int]:
        with self._lock:
            return {r["source"]: r["n"] for r in self._db.execute("SELECT source, COUNT(*) AS n FROM stats_queue GROUP BY source")}

    def stats_next(self, source: str) -> tuple[str, str] | None:
        """The next queued post of a site and its kind: chosen posts first, then the newest saves."""
        with self._lock:
            self._db.execute("DELETE FROM stats_queue WHERE canonical_url IN "
                             "(SELECT canonical_url FROM items WHERE login_only!=0 OR shelf='trash')")
            row = self._db.execute(
                "SELECT q.canonical_url, q.kind FROM stats_queue q JOIN items i ON i.canonical_url=q.canonical_url "
                "WHERE q.source=? AND i.login_only=0 AND i.shelf!='trash' "
                "ORDER BY (q.kind='manual') DESC, i.created_at DESC LIMIT 1", (source,)).fetchone()
        return (row[0], row[1]) if row else None

    def stats_dequeue(self, url: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM stats_queue WHERE canonical_url=?", (url,))
            self._db.commit()

    def stats_clear_queue(self) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM stats_queue").rowcount
            self._db.commit()
        return n

    def stats_done_today(self, source: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT n FROM stats_log WHERE day=? AND source=?", (_now().date().isoformat(), source)).fetchone()
        return row[0] if row else 0

    def stats_count_today(self, source: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO stats_log (day, source, n) VALUES (?, ?, 1) ON CONFLICT(day, source) DO UPDATE SET n=n+1",
                             (_now().date().isoformat(), source))
            self._db.commit()

    def stats_recent_urls(self, days: int = AUTO_DAYS) -> list[str]:
        """Posts for the weekly refresh: those saved or shared in the last `days`, newest first."""
        since = _stamp(_now() - timedelta(days=days))
        with self._lock:
            return [r[0] for r in self._db.execute(
                "SELECT canonical_url FROM items WHERE shelf != 'trash' AND status='archived' "
                "AND COALESCE(last_shared_at, created_at) >= ? ORDER BY created_at DESC", (since,))]


# ---- estimates, for the confirmation box ----------------------------------------------------------------

def estimate(per_source: dict[str, int]) -> dict:
    """How long a refresh of chosen posts would take at the pace for chosen posts: sites run side by side, each one post
    at a time, with the daily cap spreading a long list over several days."""
    mean_gap = sum(GAP_SECONDS) / 2
    longest = 0.0
    for n in per_source.values():
        days = max(0, (n - 1) // DAILY_CAP)
        longest = max(longest, days * 86400 + min(n, DAILY_CAP) * mean_gap)
    return {"seconds": int(longest), "posts": sum(per_source.values()), "per_source": per_source}


def human(seconds: int) -> str:
    if seconds < 90:
        return "about a minute"
    if seconds < 5400:
        return f"about {round(seconds / 60)} minutes"
    if seconds < 86400 * 1.5:
        return f"about {round(seconds / 3600)} hours"
    return f"about {round(seconds / 86400)} days"


# ---- the loop's one step ----------------------------------------------------------------------------------

def describe_via_proxy(source: str, url: str):
    """The normal logged-out read, through the owner's proxy when one is set (never with a login)."""
    from magpiary import proxy
    address = proxy.get()
    try:
        return describe(source, url, ytdlp=YtDlp(proxy=address) if address else None)
    except FetchFailed as err:
        if not address:
            raise
        # Downloader diagnostics may echo proxy userinfo; never retain them in the library.
        detail = "empty media response" if "empty media response" in err.detail.lower() else "Refresh through the configured proxy failed."
        raise FetchFailed(err.reason, detail) from None


def refresh_one(store, url: str, source: str, library_write: Callable[[str, dict], None] | None = None,
                get_details: Callable = describe) -> str:
    """Read one post's numbers again. Returns 'ok', 'unavailable' or the reason that should stop the site."""
    try:
        fresh = get_details(source, url).meta
    except FetchFailed as err:
        if err.reason == "rate_limited" and "empty media response" in err.detail.lower():
            return "login_wall"  # Instagram says this for a post it will not show logged-out (age limit, restricted account) as well as for a real limit
        if err.reason in STOP_REASONS:
            return err.reason
        store.stats_unavailable(url, f"{err.reason}: {err.detail}")
        return "unavailable"
    except Exception as err:  # a refresh must never crash its lane
        return f"unknown:{type(err).__name__}"
    store.stats_save(url, *(fresh.get(k) for k in KEYS))
    store.set_setting(f"stats_strikes_{source}", "0")  # a post that reads fine clears the count of login walls in a row
    if library_write:
        library_write(url, fresh)
    return "ok"


def write_meta(store, url: str, fresh: dict) -> None:
    """Keep the post page's own copy (meta.json) in step, as the single-post refresh always did."""
    item = store.item_by_url(url)
    folder = item and item.get("archive_dir")
    if not folder:
        return
    path = Path(folder) / "meta.json"
    try:
        meta = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    for key in KEYS + EXTRA_KEYS:
        if fresh.get(key) is not None:
            meta[key] = fresh[key]
    meta["stats_at"] = _stamp()
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def step(store, now: Callable[[], float] = time.time, gap: Callable[[], float] | None = None,
         details: Callable = describe, state: dict | None = None) -> str:
    """One pass over the queue. Each site has its own clock: a post is taken only when that site's wait is over,
    its daily cap is not used up, and it is not stopped. Returns a short word for the log ('' when nothing was due)."""
    gap_given = gap is not None
    state = state if state is not None else store.__dict__.setdefault("_stats_state", {"next": {}, "stopped": {}})
    if store.paused("stats"):
        return ""
    did = ""
    for source in sorted(store.stats_queue_counts()):
        if state["stopped"].get(source, 0) > now() or _stopped_until(store, source) > now():  # a stop survives a restart
            continue
        if state["next"].get(source, 0) > now():
            continue
        nxt = store.stats_next(source)
        if not nxt:
            continue
        url, kind = nxt
        if store.stats_done_today(source) >= (DAILY_CAP if kind == "manual" else AUTO_DAILY_CAP):
            continue
        store.stats_count_today(source)
        state["next"][source] = now() + (gap() if gap_given else random.uniform(*(GAP_SECONDS if kind == "manual" else AUTO_GAP_SECONDS)))
        result = refresh_one(store, url, source, library_write=lambda u, f: write_meta(store, u, f),
                             get_details=lambda s, u: (describe_via_proxy if details is describe else details)(s, u))
        if result in ("ok", "unavailable"):
            store.stats_dequeue(url)
            did = result
        elif result == "login_wall" and _strike(store, source) < STRIKES_TO_STOP:
            # one post asking for a login is usually that post (age limit, restricted account): skip it, keep going
            store.mark_login_only(url)  # for good: it will not be asked again, and its tile gets the lock
            store.stats_dequeue(url)
            did = "restricted"
        elif result in STOP_REASONS:
            state["stopped"][source] = now() + BLOCK_HOURS * 3600  # leave the post queued; try again after a day
            store.set_setting(f"stats_stop_{source}", f"{state['stopped'][source]:.0f}|{result}")
            did = f"stopped:{source}:{result}"
        else:
            store.stats_dequeue(url)
            did = "failed"
        break  # one post per pass, whichever site: a calm pace across all sites too
    return did


def _strike(store, source: str) -> int:
    """Count one more login wall in a row for this site and return the new count."""
    try:
        n = int(store.get_setting(f"stats_strikes_{source}", "0")) + 1
    except ValueError:
        n = 1
    store.set_setting(f"stats_strikes_{source}", str(n))
    return n


def _stopped_until(store, source: str) -> float:
    """When a site that showed a warning sign may be tried again (0 when it is not stopped)."""
    try:
        return float(store.get_setting(f"stats_stop_{source}", "0|").split("|")[0] or 0)
    except ValueError:
        return 0.0


def weekly_due(store) -> bool:
    last = store.get_setting("stats_auto_at", "")
    if not last:  # the very first start only begins the clock: nothing is requested until a week has passed
        store.set_setting("stats_auto_at", _stamp())
        return False
    try:
        return _now() - datetime.fromisoformat(last) >= timedelta(days=AUTO_EVERY_DAYS)
    except ValueError:
        return True


def weekly_queue(store) -> int:
    """Queue the newest month of posts for the slow automatic refresh. Off when the owner turned it off."""
    if store.get_setting("stats_auto", "1") != "1" or not weekly_due(store):
        return 0
    store.set_setting("stats_auto_at", _stamp())
    return store.stats_enqueue(store.stats_recent_urls(), kind="auto")
