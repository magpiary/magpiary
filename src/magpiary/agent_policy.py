"""What AI agents may do, as set in Settings → AI agents. The master switch is off until the owner turns it on.
Writes are checked by the hub (so it holds for any client); reads by the commands and the MCP server before they answer."""

from datetime import datetime

ON = "agents_on"
PERMS = {"read": "agents_read", "add": "agents_add", "note": "agents_note"}
LIMITS = {"add": "agents_limit_add", "note": "agents_limit_note"}
DEFAULT_LIMITS = {"add": 30, "note": 60}
LIMIT_CHOICES = (10, 30, 100, 0)  # 0 = no limit
HIDE_TAGS = "agents_hide_tags"

WHAT = {"read": "Reading your saves", "add": "Saving links", "note": "Writing notes"}


def enabled(store) -> bool:
    return store.get_setting(ON, "0") == "1"


def permitted(store, what: str) -> bool:
    return store.get_setting(PERMS[what], "1") == "1"


def refusal(store, what: str) -> str | None:
    """Why an agent may not do `what` (read, add or note) right now, in plain words; None when it may."""
    if not enabled(store):
        return "AI agents are turned off in Magpiary. The owner can turn them on in Settings → AI agents."
    if not permitted(store, what):
        return f"{WHAT[what]} is turned off for AI agents. The owner can allow it in Settings → AI agents."
    return None


def limit(store, what: str) -> int:
    raw = store.get_setting(LIMITS[what], "")
    return int(raw) if raw.isdigit() else DEFAULT_LIMITS[what]


def over_limit(store, what: str, extra: int = 1) -> str | None:
    cap = limit(store, what)
    if cap and store.agent_used(what) + extra > cap:
        return f"The daily limit for AI agents is reached ({cap} {'links' if what == 'add' else 'notes'} a day). The owner can change it in Settings → AI agents."
    return None


def hidden_tags(store) -> list[str]:
    return [t.strip().lower() for t in store.get_setting(HIDE_TAGS, "").split(",") if t.strip()]


def hidden_urls(store) -> set[str]:
    """Saves agents must never see: those carrying a hidden tag."""
    tags = hidden_tags(store)
    if not tags:
        return set()
    with store._lock:
        return {r[0] for r in store._db.execute(
            f"SELECT canonical_url FROM tags WHERE tag IN ({','.join('?' for _ in tags)})", tags)}


def today() -> str:
    return datetime.now().astimezone().date().isoformat()
