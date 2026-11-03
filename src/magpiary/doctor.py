"""`magpiary doctor`: is everything Magpiary needs in place, and do the sites still answer?

Offline checks look at the tools, models, folders, database, keys, phones and service. Live checks (only when
the owner runs the doctor, never on a schedule) make one test request per site, using the newest saved post
from that site and fetching its details only (no download), and check each AI key by listing its models,
which uses none of the key's quota. Nothing secret is ever shown.
"""

import hashlib
import shutil
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from magpiary.config import config_dir, data_dir, db_path
from magpiary.protocol import DEFAULT_PORT
from magpiary.tools import YtDlp, find, in_mac_app

OK, WARN, FAIL = "ok", "warning", "problem"
_CHECKED_FILES: set = set()
SOURCES = ("instagram", "youtube", "threads", "reddit", "x", "linkedin")


@dataclass
class Check:
    area: str
    name: str
    state: str
    detail: str
    fix: str = ""
    link: str = ""        # a page in the hub that helps, shown as a button beside the problem
    link_label: str = ""


# where each check's problem is fixed, by check name (or area for the live site and key rows)
LINKS = {
    "Library folder": ("/settings/storage", "Open Library settings"),
    "Free disk space": ("/settings/storage", "Open Library settings"),
    "Saves needing attention": ("/?attention=1", "Show them"),
    "Paused work": ("/nest", "Open the Nest"),
    "AI keys": ("/settings/ai", "Open AI settings"),
    "Paired phones": ("/settings/phones#phones", "Add a phone"),
    "Last delivery": ("/settings/phones#phones", "Open phone settings"),
    "Copy of your login": ("/settings/phones#instagram", "Open login settings"),
    "Digest writer": ("/settings/ai#digest", "Open Digest settings"),
}
AREA_LINKS = {"Keys": ("/settings/ai", "Open AI settings")}


def linked(checks: list["Check"]) -> list["Check"]:
    """Give each check that is not fine its fix button."""
    for c in checks:
        if c.state != OK and not c.link:
            c.link, c.link_label = LINKS.get(c.name) or AREA_LINKS.get(c.area) or ("", "")
    return checks


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def offline(store, port: int = DEFAULT_PORT, ping: Callable[[int], bool] | None = None) -> list[Check]:
    from magpiary import keys as keyring
    from magpiary import login
    from magpiary.embed import FILES, model_dir
    from magpiary.service import _ping

    out: list[Check] = []
    add = lambda *a: out.append(Check(*a))  # noqa: E731

    running = (ping or _ping)(port)
    add("Mac", "Background service", OK if running else FAIL,
        f"Answering on port {port}." if running else "Not answering.",
        "" if running else "Run: magpiary service install")

    ytdlp = YtDlp()
    version = ytdlp.version()
    updated = store.get_setting("ytdlp_updated_on", "")
    add("Tools", "yt-dlp (downloads)", OK if version else FAIL,
        f"Version {version}" + (f", last update check {updated}." if updated else ".") if version else "Not found.",
        "" if version else "Reinstall Magpiary." if in_mac_app() else "Run: uv tool install yt-dlp")
    for name, why, fix in (("ffmpeg", "frames from videos", "brew install ffmpeg"),
                           ("ffprobe", "video lengths", "brew install ffmpeg"),
                           ("uv", "keeps yt-dlp up to date", "see https://docs.astral.sh/uv/"),
                           ("node", "YouTube needs a JavaScript runtime", "brew install node")):
        if name == "uv" and in_mac_app():  # the app updates yt-dlp without it
            continue
        found = find(name) or (name == "node" and find("deno"))
        add("Tools", f"{name} ({why})", OK if found else (WARN if name in ("uv", "node") else FAIL),
            "Found." if found else "Not found.", "" if found else f"Install it: {fix}")

    try:
        import pywhispercpp.constants as wc
        whisper = Path(wc.MODELS_DIR) / "ggml-small.bin"
        add("Models", "Whisper small (transcripts)", OK if whisper.exists() else WARN,
            f"{whisper.stat().st_size / 1e6:.0f} MB on disk." if whisper.exists() else "Not downloaded yet.",
            "" if whisper.exists() else "It downloads by itself (about 470 MB) with the first video.")
    except ImportError:
        add("Models", "Whisper small (transcripts)", FAIL, "pywhispercpp is missing.", "Reinstall Magpiary.")

    folder = model_dir()
    bad = []
    for name, (_, sha) in FILES.items():
        path = folder / name
        if not path.exists():
            bad.append(name)
            continue
        stamp = (name, path.stat().st_size, path.stat().st_mtime_ns)  # reading 135 MB each time made the page wait; a file that has not changed has not changed
        if stamp not in _CHECKED_FILES:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                bad.append(name)
                continue
            _CHECKED_FILES.add(stamp)
    add("Models", "Meaning model (Related and Piles)", OK if not bad else WARN,
        "Present and checked." if not bad else "Missing or changed: " + ", ".join(bad) + ".",
        "" if not bad else "It downloads again by itself (about 135 MB).")

    home = data_dir()
    free = shutil.disk_usage(home if home.exists() else Path.home()).free / 1e9
    add("Library", "Library folder", OK if home.exists() else FAIL, f"{home}", "" if home.exists() else "Start the service once.")
    add("Library", "Free disk space", OK if free >= 5 else (WARN if free >= 1 else FAIL), f"{free:.0f} GB free.",
        "" if free >= 5 else "Videos need room; free some space.")
    integrity = store.integrity()
    add("Library", "Database", OK if integrity == "ok" else FAIL,
        f"{db_path().name}: {integrity}." if integrity != "ok" else f"{store.count_items()} saves, no damage found.",
        "" if integrity == "ok" else "Copy ~/Magpiary somewhere safe and ask for help.")
    attention = store.hub_counts()["attention"]
    add("Library", "Saves needing attention", OK if not attention else WARN,
        f"{attention} save(s)." if attention else "None.", "Open the Library's “Needs attention” filter." if attention else "")
    paused = [p for p in ("transcribe", "summary", "links") if store.paused(p)]
    add("Library", "Paused work", OK if not paused else WARN, ("Paused: " + ", ".join(paused) + ".") if paused else "Nothing paused.",
        "Resume it on the Activity page." if paused else "")

    cfg = config_dir()
    keyfile = cfg / "keys.json"
    if keyfile.exists():
        private = _mode(keyfile) == 0o600
        add("Keys", "Key file is private", OK if private else FAIL, f"Mode {_mode(keyfile):o}.",
            "" if private else f"Run: chmod 600 {keyfile}")
    from magpiary import modes

    mode = modes.current(store)
    add("Keys", "Mode", OK, f"{modes.MODES[mode][0]}: {modes.MODES[mode][1]}")
    ai = [k for k in keyring.load() if keyring.PROVIDERS.get(k.provider, {}).get("kind") == "ai"]
    usable = keyring.usable()
    add("Keys", "AI keys", OK if usable or mode == "private" else WARN,
        f"{len(ai)} saved, {len(usable)} usable now." if ai else "None saved: summaries wait.",
        "" if usable else "Add a key in Settings, or wait for a key's daily limit to reset.")

    phones = [p for p in store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]
    last = store.last_delivery()
    add("Phone", "Paired phones", OK if phones else WARN, f"{len(phones)} paired" + (f"; last delivery {last[:16]}." if last else "."),
        "" if phones else "Pair one on the Phones page.")
    if phones and last:
        try:
            quiet = (date.today() - date.fromisoformat(last[:10])).days
        except ValueError:
            quiet = 0
        add("Phone", "Last delivery", OK if quiet < 14 else WARN,
            "Something arrived in the last two weeks." if quiet < 14 else f"Nothing has arrived for {quiet} days.",
            "" if quiet < 14 else "Check the Shortcut and the home Wi-Fi automation on the phone, or that this Mac was awake.")

    day = login.connected(store)
    if day:
        old = (date.today() - date.fromisoformat(day)).days
        path = login.login_path()
        add("Instagram login", "Copy of your login", OK if old < 60 and _mode(path) == 0o600 else WARN,
            f"Copied {old} day(s) ago, private: {'yes' if _mode(path) == 0o600 else 'no'}.",
            "Copy it again in Settings if blocked posts still fail." if old >= 60 else "")
    else:
        add("Instagram login", "Copy of your login", OK, "Not connected (optional).")
    return linked(out)


def live(store, describe=None, call=None, pause: Callable[[float], None] = time.sleep,
         emit: Callable[[Check], None] | None = None) -> list[Check]:
    from magpiary import keys as keyring
    from magpiary.brain import API, http_call
    from magpiary.queuepage import REASONS, SOURCE_NAMES
    from magpiary.sources import FetchFailed
    from magpiary.sources import describe as real_describe

    describe, call = describe or real_describe, call or http_call
    out: list[Check] = []

    def add(check: Check) -> None:
        linked([check])
        out.append(check)
        if emit:
            emit(check)
    newest = store.newest_by_source()
    for n, source in enumerate(SOURCES):
        url, name = newest.get(source), SOURCE_NAMES.get(source, source)
        if not url:
            add(Check("Sites", name, OK, "No saved post from here to test with yet."))
            continue
        if n:
            pause(2)  # one request at a time, gently
        started = time.monotonic()
        try:
            describe(source, url)
            add(Check("Sites", name, OK, f"Answered logged out in {time.monotonic() - started:.1f} s."))
        except FetchFailed as err:
            add(Check("Sites", name, FAIL, f"{REASONS.get(err.reason, err.reason)}: {err.detail[:120]}",
                             "yt-dlp updates itself daily; if this lasts, the site may have changed."))
        except Exception as err:  # a check must never crash the doctor
            add(Check("Sites", name, FAIL, f"Unexpected error: {type(err).__name__}"))
    for key in keyring.load():
        kind = keyring.PROVIDERS.get(key.provider, {}).get("kind")
        if kind == "search":
            add(Check("Keys", key.name, OK, "Saved. Not tested, to keep your monthly searches."))
            continue
        if key.provider != "gemini":
            continue
        try:
            status, _ = call("GET", f"{API}/models?pageSize=1", key.secret, None, 20)
        except OSError as err:
            add(Check("Keys", key.name, FAIL, f"Could not reach Google: {type(err).__name__}"))
            continue
        state = OK if status == 200 else FAIL
        detail = {200: "Google accepts it", 400: "Google refused it", 403: "Google refused it"}.get(status, f"HTTP {status}")
        limit = " (at its daily limit today)" if key.limit_day == date.today().isoformat() else ""
        add(Check("Keys", key.name, state, f"{detail}{limit}. Model: {key.model}.",
                         "" if state == OK else "Replace the key in Settings."))
    return out


def report(checks: list[Check]) -> str:
    """Plain text for Terminal."""
    marks = {OK: "✓", WARN: "!", FAIL: "✗"}
    lines, area = [], None
    for c in checks:
        if c.area != area:
            area = c.area
            lines.append(f"\n{area}")
        lines.append(f"  {marks[c.state]} {c.name}: {c.detail}" + (f"\n      → {c.fix}" if c.fix else ""))
    problems = sum(c.state == FAIL for c in checks)
    warnings = sum(c.state == WARN for c in checks)
    lines.append(f"\n{problems} problem(s), {warnings} warning(s).")
    return "\n".join(lines).lstrip("\n")
