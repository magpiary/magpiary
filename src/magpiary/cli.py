"""The `magpiary` command. Subcommands are added as each stage is built."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from magpiary import __version__
from magpiary.config import db_path


def build_parser() -> argparse.ArgumentParser:
    from magpiary.protocol import DEFAULT_PORT

    parser = argparse.ArgumentParser(
        prog="magpiary",
        description="Turn shared posts into a searchable library on your Mac.",
    )
    parser.add_argument("--version", action="version", version=f"magpiary {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the receiver that your iPhone sends shared links to")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default: the local network)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)

    phone = sub.add_parser("phone", help="manage paired phones")
    phone_sub = phone.add_subparsers(dest="phone_command", required=True)
    add = phone_sub.add_parser("add", help="pair a phone; its key is shown once")
    add.add_argument("name")
    phone_sub.add_parser("list", help="show paired phones")
    revoke = phone_sub.add_parser("revoke", help="cut off a phone; its key stops working")
    revoke.add_argument("name")

    ext = sub.add_parser("extension", help="set up the Chrome extension that saves pages and posts to Magpiary")
    ext.add_argument("--no-open", action="store_true", help="only print the steps; open nothing")

    login = sub.add_parser("login", help="borrow your login to a site from Chrome, for blocked posts you choose")
    login_sub = login.add_subparsers(dest="login_command", required=True)
    for name, text in (("connect", "copy just your login to one site from Chrome into a private file"),
                       ("disconnect", "delete Magpiary's copy of your login to a site"),
                       ("status", "show whether a login copy is saved")):
        one = login_sub.add_parser(name, help=text)
        one.add_argument("site", nargs="?", default="instagram.com", help="like behance.net (default: instagram.com)")

    lock = sub.add_parser("lock", help="the hub lock (PIN and Touch ID)")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    lock_sub.add_parser("status", help="show whether the hub lock is on")
    lock_sub.add_parser("reset", help="turn the lock off and forget the PIN and every Touch ID (for a forgotten PIN)")

    tools = sub.add_parser("tools", help="ffmpeg, ffprobe and a JavaScript runtime, without Homebrew")
    tools.add_argument("tools_command", choices=["install"], help="download what is missing (checked copies)")
    downloads = sub.add_parser("downloads", help="list what Magpiary downloads, from where, how big, and why")
    downloads.add_argument("action", nargs="?", choices=["list", "install"], default="list",
                           help="list (default) shows them; install downloads what is missing, resuming where it stopped")
    downloads.add_argument("--json", action="store_true", help="machine-readable output (one JSON event per line when installing; used by the installer)")
    models = sub.add_parser("models", help="the transcript and meaning models")
    models.add_argument("models_command", choices=["install"], help="download them now (about 600 MB)")

    for name, text in (("search", "find saves by words and meaning (read-only)"), ("show", "read one save in full (read-only)"),
                       ("list", "browse saves, newest first (read-only)"), ("status", "library counts and what is still processing (read-only)")):
        one = sub.add_parser(name, help=text)
        one.add_argument("--json", action="store_true", help="machine-readable answer for AI agents and scripts")
        if name == "search":
            one.add_argument("query", help="words to look for")
            one.add_argument("--words-only", action="store_true", help="skip the meaning search")
        if name == "show":
            one.add_argument("id", type=int, help="the save's number, from search or list")
        if name in ("search", "list"):
            one.add_argument("--limit", type=int, default=10 if name == "search" else 20)
            one.add_argument("--source", default="", help="only one site, such as youtube")
            one.add_argument("--tag", default="")
        if name == "list":
            one.add_argument("--shelf", choices=["inbox", "archive", "kept"], default="inbox")
    adder = sub.add_parser("add", help="save a link (needs the hub running; for AI agents and scripts)")
    adder.add_argument("url")
    noter = sub.add_parser("note", help="write, add to, undo or clear an AI agent's note on a save (needs the hub running)")
    noter.add_argument("id", type=int, help="the save's number, from search or list")
    noter.add_argument("text", nargs="?", default="", help="the note")
    noter.add_argument("--append", action="store_true", help="add a line to the agent note instead of replacing it")
    noter.add_argument("--undo", action="store_true", help="bring back the version before the last change")
    noter.add_argument("--clear", action="store_true", help="empty the agent note (it can still be undone)")
    noter.add_argument("--by", default="", help="who is writing, such as Claude Code")
    for one in (adder, noter):
        one.add_argument("--json", action="store_true", help="machine-readable answer")
        one.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    mcp = sub.add_parser("mcp", help="run the Magpiary MCP server for AI tools (Claude Code, Codex...) over stdio")
    mcp.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    skill = sub.add_parser("skill", help="the skill file that teaches Claude to use Magpiary (prints it, or --install)")
    skill.add_argument("--install", action="store_true", help="save it where Claude Code finds skills")
    skill.add_argument("--dir", default="", help="the skills folder to save into (default: Claude's, ~/.claude/skills)")
    helper = sub.add_parser("help", help="guides; try: magpiary help agents")
    helper.add_argument("topic", nargs="?", choices=["agents"], default="agents")

    sub.add_parser("update", help="install the newest Magpiary (and yt-dlp) and restart the service")
    remove = sub.add_parser("uninstall", help="remove Magpiary's service and commands; your library stays")
    remove.add_argument("--delete-library", action="store_true", help="also delete ~/Magpiary and your settings")
    remove.add_argument("--yes", action="store_true", help="do not ask first")

    doctor = sub.add_parser("doctor", help="check that everything Magpiary needs works, including each site")
    doctor.add_argument("--offline", action="store_true", help="skip the test requests to sites and AI keys")
    doctor.add_argument("--port", type=int, default=DEFAULT_PORT)

    service = sub.add_parser("service", help="run the receiver in the background, starting at login")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    for name, text in (("install", "start the receiver at login and keep it running"),
                       ("uninstall", "stop and remove the background service"),
                       ("status", "show whether the service is running")):
        one = service_sub.add_parser(name, help=text)
        if name != "uninstall":
            one.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "service":
        return _service(args)
    if args.command == "uninstall":
        return _uninstall(args)
    if args.command == "tools":
        from magpiary.tools import install_tools, missing_tools

        missing = missing_tools()
        if not missing:
            print("ffmpeg, ffprobe and a JavaScript runtime are already here.")
            return 0
        problems = install_tools(missing, report=lambda m: print(m, flush=True))
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    if args.command == "downloads":
        return _downloads(args)
    if args.command == "models":
        return _models()
    if args.command == "extension":
        return _extension(args)
    if args.command == "help":
        from magpiary.library import AGENT_GUIDE

        print(AGENT_GUIDE)
        return 0
    if args.command in ("search", "show", "list", "status"):
        return _library(args)
    if args.command in ("add", "note"):
        return _agent(args, parser)
    if args.command == "mcp":
        from magpiary import mcp_agent

        mcp_agent.main(args.port)
        return 0
    if args.command == "skill":
        from magpiary.skilltext import SKILL

        if not args.install:
            print(SKILL, end="")
            return 0
        folder = Path(args.dir) if args.dir else Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
        target = folder / "magpiary" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(SKILL)
        print(f"Saved the Magpiary skill to {target}. Claude Code picks it up in its next session.")
        return 0

    from magpiary.store import Store  # imported here so --version stays instant

    store = Store(db_path())
    if args.command == "update":
        from magpiary import update

        found = update.latest() if not os.environ.get("MAGPIARY_SOURCE") else "local"
        if not found:
            print(f"Magpiary {__version__}: could not find a newer release (none published, or offline).")
            return 0
        if found != "local" and not update.newer(found):
            print(f"Magpiary {__version__} is the newest.")
            return 0
        print(f"Installing Magpiary {found}…", flush=True)
        problem = update.install(found)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        from magpiary import service

        if service.plist_path().exists():
            subprocess.run([str(Path.home() / ".local" / "bin" / "magpiary"), "service", "install"], check=False)
        print("Updated.")
        return 0

    if args.command == "login":
        from magpiary import login

        site = args.site.strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
        if args.login_command == "connect":
            print(f"Copying your {site} login from Chrome. macOS may ask twice: to let Terminal use data from "
                  "other apps, and to use “Chrome Safe Storage”. Choose Allow both times.", flush=True)
            problem = login.connect(store, domain=site)
            if problem:
                print(problem, file=sys.stderr)
                return 1
            print("Connected. Open a blocked post in the hub and press “Retry with my login”.")
        elif args.login_command == "disconnect":
            try:
                login.disconnect(store, site)
            except ValueError as err:
                print(err, file=sys.stderr)
                return 1
            print(f"Deleted Magpiary's copy of your {site} login.")
        else:
            day = login.connected(store, site)
            print(f"Connected to {site} (copied {day})." if day else f"Not connected to {site}.")
        return 0

    if args.command == "lock":
        from magpiary.lock import Lock

        lock = Lock(store)
        if args.lock_command == "reset":
            lock.reset()
            print("The hub lock is off. Your PIN and Touch ID were forgotten; your library and boards are untouched. "
                  "Turn it on again in Settings → Privacy.")
        else:
            print("The hub lock is on." if lock.enabled else "The hub lock is off.")
        return 0

    if args.command == "doctor":
        from magpiary import doctor

        print("Checking… (each site gets one test request)" if not args.offline else "Checking (offline)…", flush=True)
        checks = doctor.offline(store, args.port) + ([] if args.offline else doctor.live(store))
        print(doctor.report(checks))
        return 1 if any(c.state == doctor.FAIL for c in checks) else 0

    if args.command == "serve":
        from magpiary.receiver import serve

        print(f"Database: {db_path()}")
        serve(store, args.host, args.port)
        return 0

    if args.phone_command == "add":
        try:
            phone, key = store.add_phone(args.name)
        except ValueError as err:
            print(f"Could not add the phone: {err}", file=sys.stderr)
            return 1
        print(f"Paired {phone.name!r}. Its key (shown once, keep it private):\n{key}")
    elif args.phone_command == "list":
        for p in store.list_phones():
            print(f"{p['name']}  paired {p['created_at']}" + (f"  REVOKED {p['revoked_at']}" if p["revoked_at"] else ""))
    elif args.phone_command == "revoke":
        if not store.revoke_phone(args.name):
            print(f"No active phone called {args.name!r}.", file=sys.stderr)
            return 1
        print(f"Revoked {args.name!r}.")
    return 0


def _agent(args, parser) -> int:
    """`add` and `note`: the only commands for AI agents that change anything. They go through the running hub."""
    from magpiary import agent

    try:
        if args.command == "add":
            data = agent.add(args.url, args.port)
            line = (("Already in Magpiary" + (f" as #{data['id']}." if data["id"] else ".")) if data["status"] == "again"
                    else f"Saved as #{data['id']}. It downloads and is read in the background; `magpiary status` shows progress.")
        else:
            modes = [m for m, on in (("undo", args.undo), ("clear", args.clear)) if on]
            if len(modes) + bool(args.text) != 1:
                parser.error("give the note text, or exactly one of --undo or --clear")
            mode = modes[0] if modes else ("append" if args.append else "set")
            data = agent.note(args.id, mode, args.text, args.by, args.port)
            current = data["agent_note"]
            line = (f"Agent note on #{args.id} ({current['by']}): {current['text']}" if current["text"]
                    else f"The agent note on #{args.id} is empty.")
    except agent.AgentError as err:
        from magpiary import agent_log

        agent_log.record(args.command, args.url if args.command == "add" else f"#{args.id}", ok=False, why=str(err))
        print(str(err), file=sys.stderr)
        return 1
    from magpiary import agent_log, library

    agent_log.record(args.command, data["url"] if args.command == "add" else f"#{args.id} {mode}")

    print(library.as_json(data) if args.json else line)
    return 0


def _library(args) -> int:
    """The read-only commands for AI agents and people. They open the database read-only, so they work while the hub
    runs or is stopped, and they can never change the library."""
    import sqlite3

    from magpiary import library
    from magpiary.store import Store

    try:
        store = Store(db_path(), read_only=True)
    except sqlite3.OperationalError:
        print("No Magpiary library found yet. Save something from your phone first, or run `magpiary doctor`.", file=sys.stderr)
        return 1
    from magpiary import agent_log, agent_policy

    why = agent_policy.refusal(store, "read")
    if why:
        store.close()
        agent_log.record(args.command, getattr(args, "query", "") or str(getattr(args, "id", "")), ok=False, why=why)
        print(why, file=sys.stderr)
        return 1
    meaning = None
    try:
        if args.command == "search":
            if not args.words_only:
                from magpiary.embed import Warm

                meaning = Warm(idle=1)
            data = library.search(store, args.query, args.limit, args.words_only, args.source, args.tag, meaning)
        elif args.command == "show":
            data = library.show(store, args.id)
            if data is None:
                agent_log.record("show", f"#{args.id}", ok=False, why="no such save")
                print(f"There is no saved post with number {args.id}.", file=sys.stderr)
                return 1
        elif args.command == "list":
            data = library.listing(store, args.shelf, args.source, args.tag, args.limit)
        else:
            data = library.status(store)
        agent_log.record(args.command, getattr(args, "query", "") or (f"#{args.id}" if args.command == "show" else
                         getattr(args, "shelf", "") or ""))
        print(library.as_json(data) if args.json else library.as_text(args.command, data))
        return 0
    finally:
        if meaning is not None:
            meaning.stop()
        store.close()


def _extension(args) -> int:
    """Copy the extension to a stable folder (Chrome remembers where it was loaded from) and say how to load it."""
    import subprocess

    from magpiary import chrome_ext

    target = chrome_ext.prepare()
    print(f"The Magpiary extension is ready in:\n  {target}\n")
    print("To add it to Chrome (one time):\n"
          "  1. Open chrome://extensions and turn on Developer mode (top right).\n"
          "  2. Press Load unpacked and choose the folder above.\n"
          "  3. Pin Magpiary from the puzzle-piece menu.\n"
          "  4. In Magpiary, open Settings → Phones → Add Chrome, copy the code, and paste it into the extension.\n"
          "After updating Magpiary, run this command again and press Reload on the extension.")
    if not args.no_open and sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
        subprocess.run(["open", "-a", "Google Chrome", "chrome://extensions"], check=False, stderr=subprocess.DEVNULL)
    return 0


def _downloads(args) -> int:
    from magpiary import downloads

    if args.action == "install":
        return _downloads_install(args)

    entries = downloads.catalog()
    if args.json:
        print(json.dumps({"downloads": [e.as_dict() for e in entries], "total_bytes": downloads.total_bytes(entries),
                          "missing_bytes": downloads.total_bytes(entries, only_missing=True)}))
        return 0
    for e in entries:
        print(f"{'✓' if e.installed else '·'} {e.name} ({downloads.human_size(e.bytes)}) from {e.source}\n    {e.why}")
    print(f"\nTotal {downloads.human_size(downloads.total_bytes(entries))}; "
          f"still to download {downloads.human_size(downloads.total_bytes(entries, only_missing=True))}.")
    return 0


def _downloads_install(args) -> int:
    from magpiary import downloads, installer

    def emit(event: dict) -> None:
        if args.json:
            print(json.dumps(event), flush=True)
            return
        kind = event["event"]
        if kind == "step_start":
            print(f"{event['name']}…", flush=True)
        elif kind == "retry":
            print(f"  trying again in {event['wait']:.0f}s ({event['reason']})", flush=True)
        elif kind == "precheck":
            for problem in event["problems"]:
                print(problem["message"], file=sys.stderr)
        elif kind == "step_error":
            print(event["message"], file=sys.stderr)
        elif kind == "plan":
            print(f"To download: {downloads.human_size(event['total_bytes'])}", flush=True)
        elif kind == "finished":
            print("All set." if event["ok"] else "Not finished.", flush=True)

    return 0 if installer.install(emit) else 1


def _models() -> int:
    from magpiary.embed import EmbedFailed, ensure_model

    try:
        from pywhispercpp.utils import download_model

        from magpiary.transcribe import MODEL
        print(f"Transcript model (Whisper {MODEL}, about 470 MB)…", flush=True)
        download_model(MODEL)
        print("Meaning model (about 135 MB)…", flush=True)
        ensure_model()
    except (EmbedFailed, OSError) as err:
        print(f"Could not download a model: {err}", file=sys.stderr)
        return 1
    print("Models ready.")
    return 0


def _uninstall(args) -> int:
    from magpiary import update

    if args.delete_library:
        if not args.yes and input("This deletes your whole library, notes and settings for good. "
                                  "Type “delete my library” to go ahead: ").strip() != "delete my library":
            print("Nothing was removed.")
            return 1
    elif not args.yes and input("Remove Magpiary's service and commands? Your library stays. [y/N] ").strip().lower() != "y":
        print("Nothing was removed.")
        return 1
    print("\n".join(update.remove(args.delete_library)))
    return 0


def _service(args) -> int:
    from magpiary import service

    try:
        if args.service_command == "install":
            print(service.install(Path(os.environ.get("MAGPIARY_PROGRAM") or sys.argv[0]).absolute(), args.port))  # the app's launcher sets MAGPIARY_PROGRAM
        elif args.service_command == "uninstall":
            print(service.uninstall())
        else:
            print(service.status(args.port))
    except service.ServiceError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
