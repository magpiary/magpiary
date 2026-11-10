"""What a paired phone may ask the hub for. The server enforces this; hiding a button is never the limit.

It is an allow-list: a path that is not named here is refused for a phone. The owner's decisions (6 Nov 2026): a phone
can do everything except Settings, AI keys and the lock settings; Ask Magpiary is off; the other AI actions
(re-run a summary, Deeper dive, Digest, link search again) work only after a confirm tap.
"""

# pages and data a phone may read
GET_PAGES = {"/", "/add", "/help", "/profile/photo.jpg", "/boards.json", "/digest", "/nest", "/activity.json", "/queue",
             "/map", "/graph.json", "/search.json", "/checklist/panel", "/panel.json", "/lock", "/lock.json",
             "/settings", "/doctor"}  # Settings pages open (owner's list, 7 Nov); what they may change is POST_PATHS below
GET_PREFIXES = ("/stats/", "/board/", "/join/", "/item/", "/media/", "/pile/", "/static/", "/digest/", "/icon/", "/settings/")

# actions a phone may post
POST_PATHS = {
    "/hub/add", "/hub/bulk", "/hub/tags", "/hub/tag/add", "/hub/tag/remove", "/hub/facet/add", "/hub/facet/remove",
    "/hub/accept-tags", "/hub/not-related", "/hub/note", "/hub/shelf", "/hub/retry", "/hub/empty-trash", "/hub/pdf",
    "/hub/panel/save", "/hub/checklist", "/hub/activity", "/hub/control", "/hub/refresh-stats", "/hub/keep-link",
    "/hub/archive-link", "/hub/links/add", "/hub/links/remove", "/hub/view/save", "/hub/view/delete",
    "/hub/pile/rename", "/hub/pile/merge", "/hub/pile/split", "/hub/pile/delete", "/hub/pile/remove",
    "/hub/pile/note-delete", "/hub/piles/regroup", "/hub/whatsnew/seen",
    "/hub/boards/new", "/hub/boards/rename", "/hub/boards/delete", "/hub/boards/share", "/hub/boards/unshare",
    "/hub/boards/invite", "/hub/boards/invite-friend", "/hub/boards/join", "/hub/boards/leave", "/hub/boards/new-code",
    "/hub/boards/remove-card", "/hub/boards/remove-member", "/hub/boards/dismiss", "/hub/boards/restore",
    "/hub/boards/offer", "/hub/boards/to-library", "/hub/boards/vote", "/hub/boards/sync",
    # settings the phone may change (the owner's list, 7 Nov): profile, Wi-Fi mode per phone, Smart/Private, digest, Deeper dive,
    # Ask and agent switches, key permission switches, appearance, keep-awake. Never: keys, the lock, pairing, files, relays.
    "/hub/profile", "/hub/profile/about", "/hub/profile/links", "/hub/profile/photo", "/hub/profile/photo/remove",
    "/hub/profile/topic", "/hub/phones/wifi", "/hub/settings/mode", "/hub/settings/long-video", "/hub/digest/on",
    "/hub/digest/when", "/hub/digest/engine", "/hub/digest/goals", "/hub/digest/pick", "/hub/deep/on", "/hub/deep/engine",
    "/hub/askset", "/hub/engine/allow", "/hub/agents/on", "/hub/agents/perm", "/hub/ui", "/hub/awake",
    # the lock: enter the PIN, lock this phone; nothing that changes the lock
    "/hub/lock/pin", "/hub/lock/now",
}
# AI actions: they spend the owner's AI allowance, so they need the phone's confirm tap (field `phone_confirm=1`)
AI_PATHS = {"/hub/again", "/hub/deep", "/hub/digest/make", "/hub/screen-again", "/hub/links/again"}
CONFIRM = "phone_confirm"

_AI_BULK = ("again",)


def is_ai_action(path: str, form: dict) -> bool:
    return path in AI_PATHS or (path == "/hub/bulk" and form.get("action") in _AI_BULK)


def get_allowed(path: str, query: dict | None = None) -> bool:
    if path == "/doctor.json":  # the health check's result may be read; starting a live check is for the Mac
        return not any(k in (query or {}) for k in ("start", "live"))
    return path in GET_PAGES or path.startswith(GET_PREFIXES)


def post_decision(path: str, form: dict) -> str:
    """'ok', 'confirm' (an AI action without its confirm tap) or 'refuse'."""
    if path == "/hub/control":  # the Nest's pause/resume buttons only: never the proxy; resuming starts AI or network work
        if form.get("part") not in ("transcribe", "summary", "links", "stats", "statsauto") or form.get("action") not in ("pause", "resume"):
            return "refuse"
        if form.get("action") == "resume":
            return "ok" if form.get(CONFIRM) == "1" else "confirm"
    if path == "/hub/askset" and any(k in form for k in ("setup", "remove")):
        return "refuse"  # installing or removing a tool on the Mac stays on the Mac
    if (path == "/hub/engine/allow" and form.get("enabled") == "1") or (path == "/hub/settings/mode" and form.get("mode") == "smart") \
            or (path == "/hub/digest/on" and form.get("enabled") == "1") or (path == "/hub/deep/on" and form.get("enabled") == "1"):
        return "ok" if form.get(CONFIRM) == "1" else "confirm"  # these start AI work (a test prompt, waiting summaries, a digest, queued Deeper dives)
    if is_ai_action(path, form):
        return "ok" if form.get(CONFIRM) == "1" else "confirm"
    return "ok" if path in POST_PATHS else "refuse"


def why_refused(path: str) -> str:
    if path.startswith(("/ask", "/hub/ask")):
        return "Ask Magpiary is not available on the phone yet."
    if path.startswith(("/settings", "/hub/settings", "/hub/keys", "/hub/askset", "/hub/lock/", "/hub/phones", "/hub/access",
                        "/hub/boards", "/hub/backup", "/hub/restore", "/hub/login", "/hub/browsers", "/hub/agents")):
        return "AI keys, the lock, pairing, backups and similar settings can only be changed on your Mac."
    return "This isn't available from a phone."

