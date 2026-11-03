"""What the Chrome extension may ask the hub: is this link already saved, and which board fits it. Both answer only about the
links asked, never a list of the library, and both need a paired browser's key."""

from datetime import datetime
from urllib.parse import urlsplit

from magpiary import boards, identity
from magpiary.cleaner import UnsupportedLink, clean

MAX_URLS = 40
RECENT_SECONDS = 45 * 60  # a board you saved to this recently is the likeliest next one


def _variants(url: str) -> list[str]:
    """The canonical address, and for Instagram its /p/ or /reel/ twin (the same post may have been saved either way)."""
    try:
        link = clean(url).url
    except UnsupportedLink:
        return []
    out = [link]
    if "instagram.com" in link:
        twin = link.replace("/p/", "/reel/") if "/p/" in link else link.replace("/reel/", "/p/") if "/reel/" in link else ""
        if twin:
            out.append(twin)
    elif "?" in link and "youtube.com/watch" not in link:
        # the phone's Shortcut keeps no query string on an ordinary page, so the saved copy may be the bare address
        bare = link.split("?", 1)[0]
        out += [bare, bare[:-1] if bare.endswith("/") else bare + "/"]
    elif "?" not in link:
        out.append(link[:-1] if link.endswith("/") else link + "/")
    return list(dict.fromkeys(out))


def seen(store, urls: list) -> dict:
    """{asked address: {saved, id, count, last}} for each address asked (at most MAX_URLS). Trash does not count as saved."""
    out = {}
    for asked in [u for u in urls if isinstance(u, str)][:MAX_URLS]:
        found = None
        for candidate in _variants(asked):
            row = store.item_by_url(candidate)
            if row and row.get("shelf") != "trash":
                found = row
                break
        out[asked] = ({"saved": True, "id": found["id"], "count": found["saved_count"], "last": found["last_shared_at"]}
                      if found else {"saved": False})
    return out


def _author(url: str) -> str:
    """Who wrote a post, where the address says: a Threads or X handle, a subreddit. Empty when it doesn't."""
    try:
        link = clean(url)
    except UnsupportedLink:
        return ""
    parts = [p for p in urlsplit(link.url).path.split("/") if p]
    if link.source in ("threads", "x") and parts:
        return f"{link.source}:{parts[0].lower()}"
    if link.source == "reddit" and len(parts) >= 2 and parts[0] == "r":
        return f"reddit:r/{parts[1].lower()}"
    return ""


def _active_boards(store) -> dict:
    """{id: name} of the boards the phone's picker would list today, as the extension's board list does."""
    out = {}
    for line in boards.phone_list(store).split("\n"):
        parts = line.split("\t")
        if len(parts) == 3:
            out[parts[2]] = parts[1]
    return out


def _my_adds(store, board_id: str) -> list[tuple[float, str]]:
    """(when, address) of every post this Mac put on the board, published or still waiting to go out."""
    try:
        me = identity.public_key()
    except Exception:  # no identity yet: nothing of mine is published
        me = ""
    adds = [(float(ev["at"]), str(ev["body"].get("url", ""))) for ev in store.board_events(board_id)
            if ev["type"] == "add" and ev["member"] == me]
    for row in store.board_pending():
        if row["board_id"] == board_id:
            try:
                adds.append((datetime.fromisoformat(row["created_at"]).timestamp(), row["canonical_url"]))
            except ValueError:
                pass
    return adds


def suggest(store, url: str, now: float | None = None) -> dict | None:
    """The board that likeliest fits this link, with the reason in a line, or None. Two signals only, both from what this
    Mac already knows: the same author is already on a board (strongest), or you saved to a board in the last 45 minutes.
    A link nobody has read yet has no content to compare, so there is no topic matching here."""
    active = _active_boards(store)
    if not active:
        return None
    now = datetime.fromisoformat(store.now()).timestamp() if now is None else now   # the store's clock: the real one, except in tests
    who = _author(url)
    best_author: tuple[int, str] = (0, "")
    best_recent: tuple[float, str] = (0.0, "")
    for board_id in active:
        adds = _my_adds(store, board_id)
        if who:
            same = sum(1 for _, u in adds if _author(u) == who)
            if same > best_author[0]:
                best_author = (same, board_id)
        latest = max((t for t, _ in adds), default=0.0)
        if latest > best_recent[0] and -60 <= now - latest <= RECENT_SECONDS:   # a minute of clock skew is fine, the future is not
            best_recent = (latest, board_id)
    if best_author[1]:
        name = who.split(":", 1)[1]
        return {"id": best_author[1], "name": active[best_author[1]],
                "reason": f"{name if name.startswith(('@', 'r/')) else '@' + name} is already on it"}
    if best_recent[1]:
        minutes = max(1, round((now - best_recent[0]) / 60))
        return {"id": best_recent[1], "name": active[best_recent[1]],
                "reason": "You saved to it just now" if minutes <= 1 else f"You saved to it {minutes} minutes ago"}
    return None
