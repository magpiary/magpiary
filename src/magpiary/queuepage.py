"""The delivery table used by the Nest's From your phones tab.

The hub owns routing and access checks. Phone and website values are escaped here;
original links open with rel=noopener noreferrer.
"""

from datetime import datetime

from magpiary.store import Store
from magpiary.web import e

MAX_ROWS = 500

SOURCE_NAMES = {"instagram": "Instagram", "threads": "Threads", "x": "X", "reddit": "Reddit",
                "youtube": "YouTube", "linkedin": "LinkedIn", "other": "Other"}

REASONS = {  # plain words for each needs-attention reason
    "short link not expanded": "The short link could not be opened",
    "rate_limited": "The site asked us to slow down",
    "login_wall": "The site wants a login (age-limited, followers only, or blocked)",
    "private": "The post is private",
    "deleted": "The post seems to be gone",
    "unsupported": "This kind of link cannot be fetched yet",
    "unknown": "Something went wrong",
}


def when(stamp: str | None) -> str:
    """An ISO time as the Mac's local 'Oct 23, 14:05'; anything unreadable is shown as it came."""
    if not stamp:
        return ""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%b %-d, %H:%M")
    except ValueError:
        return stamp


def status_cell(item: dict, csrf: str = "") -> str:
    status = item["status"]
    if status == "queued":
        return "Saved, waiting to be fetched"
    if status == "expanding":
        return "Looking up the full link…"
    if status == "archived":
        folder = (item.get("archive_dir") or "").rsplit("/", 1)[-1]
        return f'Archived<div class="small" title="library/{e(folder)}">{e(when(item.get("archived_at")))}</div>'
    retry = (f"Will try again about {e(when(item['next_retry_at']))}." if item["next_retry_at"]
             else "Not trying again by itself; the link is kept.")
    detail = f"({item['reason_detail']})" if item["reason_detail"] else ""
    reason = REASONS.get(item["reason"] or "unknown", item["reason"] or "unknown")
    button = (f'<form method="post" action="/hub/retry" class="inline"><input type="hidden" name="csrf" '
              f'value="{e(csrf)}"><input type="hidden" name="url" value="{e(item["canonical_url"])}">'
              f'<input type="hidden" name="next" value="/nest?tab=phones">'
              f'<button type="submit">Retry now</button></form>') if csrf else ""
    return (f'<span class="bad">Needs attention: {e(reason)}</span>'
            f'<div class="small">{e(detail)} {retry}</div>{button}')


def table(store: Store, csrf: str = "") -> tuple[str, str]:
    """(a one-line summary, the table) of everything that has arrived, newest first."""
    items = store.items()
    if not items:
        return "", ('<p class="empty">Nothing has arrived yet. Share a post from your iPhone with Share → Magpiary; '
                    "it shows up here once your phone is on a Wi-Fi with this Mac.</p>")
    attention = sum(1 for i in items if i["status"] == "needs_attention")
    archived = sum(1 for i in items if i["status"] == "archived")
    rows = "".join(
        f'<tr><td class="url"><a href="{e(i["canonical_url"])}" rel="noopener noreferrer" target="_blank">'
        f'{e(i["canonical_url"])}</a></td>'
        f"<td>{e(SOURCE_NAMES.get(i['source'], i['source']))}</td>"
        f"<td>{i['saved_count']}×</td>"
        f"<td>{e(when(i['last_shared_at']))}<div class=\"small\">{e(i['phone'] or '')}</div></td>"
        f"<td>{status_cell(i, csrf)}</td></tr>"
        for i in items[:MAX_ROWS])
    more = (f'<p class="small muted">Showing the newest {MAX_ROWS} of {len(items)}.</p>' if len(items) > MAX_ROWS else "")
    summary = f"{len(items)} item{'s' if len(items) != 1 else ''}, {archived} archived" + (
        f", {attention} need{'s' if attention == 1 else ''} attention" if attention else "")
    return summary, (f'<div class="tscroll"><table class="avg queue"><tr><th>Link</th><th>From</th><th>Shared</th>'
                     f'<th>Last shared</th><th>Status</th></tr>{rows}</table></div>{more}')

