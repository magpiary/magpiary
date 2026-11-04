"""The Mac receiver: a small HTTP server on the standard library.

    GET  /v1/ping     no key; reveals nothing stored
    POST /v1/items    Authorization: Bearer <phone key>; {"items": [{id, url, shared_at, note, ...}]}

The reply to a batch is sent only after every item is committed to the queue. The
fixed `ack` string is what the Shortcut looks for before it clears its outbox.
"""

import hmac
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from magpiary.activity import Activity
from magpiary.config import data_dir
from magpiary.expand import Fetch, http_fetch
from magpiary.hub import Hub, backfill_details
from magpiary.power import KeepAwake
from magpiary import agent_policy
from magpiary.protocol import ACK, BOARDS_PATH, DEFAULT_PORT
from magpiary.digest import story_due, weekly_due as digest_due
from magpiary.embed import Warm
from magpiary.setup import Setup
from magpiary.shortcut import sign
from magpiary.system import current_wifi_name, local_name
from magpiary.web import Response, local_only
from magpiary.store import TRASH_DAYS, ItemResult, Store
from magpiary import update
from magpiary.tools import update_ytdlp
from magpiary.worker import brain_due, deep_due, fetch_due, jitter_pause, links_due, process_due, related_due, screen_due, icons_due

MAX_BODY = 1_000_000  # bytes
VOICE_FORM = 700_000  # a spoken question for Ask Magpiary (at most a minute of speech, as base64)
PHOTO_FORM = 600_000  # a profile photo, already shrunk by the page, as a data URL
MAX_ITEMS = 1000
RETRY_CHECK_SECONDS = 60


HUB_PAGES = ("/", "/ask", "/lock", "/lock.json", "/pair.json", "/add", "/help", "/profile/photo.jpg", "/boards.json", "/digest", "/settings", "/nest", "/activity.json", "/queue", "/doctor", "/doctor.json",
             "/welcome", "/welcome.json", "/map", "/graph.json", "/search.json", "/checklist/panel", "/panel.json")
HUB_PREFIXES = ("/stats/", "/board/", "/join/", "/item/", "/media/", "/pile/", "/static/", "/settings/", "/welcome/", "/digest/", "/ask/", "/icon/")


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def message_for(result: ItemResult) -> str:
    """Words the phone shows. Written here so they can change without reinstalling the Shortcut."""
    if result.status == "empty":
        return "Nothing new to save."
    if result.status == "rejected":
        return "Magpiary can't save this kind of link yet."
    if result.status in ("again", "replay") and result.saved_count > 1:
        return f"Already in Magpiary. Noted that you saved it again ({result.saved_count}×)."
    if result.status == "replay":
        return "Already in Magpiary."
    return "Saved to Magpiary ✅"


def build_reply(results: list[ItemResult]) -> dict:
    stored = [r for r in results if r.status in ("new", "again", "replay")]
    if len(stored) == 1:
        message = message_for(stored[0])
    elif stored:
        message = f"Saved {len(stored)} items to Magpiary ✅"
    else:
        message = message_for(results[0]) if results else "Nothing new to save."
    return {
        "ack": ACK,
        # all-empty = a run with nothing shared (the automation): stay silent
        "notify": "yes" if any(r.status != "empty" for r in results) else "no",
        "accepted": [r.id for r in results if r.status != "rejected"],
        "rejected": [{"id": r.id, "reason": r.reason} for r in results if r.status == "rejected"],
        "results": [{"id": r.id, "status": r.status, "saved_count": r.saved_count,
                     "message": message_for(r)} for r in results],
        "message": message,
    }


class Server(ThreadingHTTPServer):
    """Carries the store. A phone dropping a connection mid-request is normal: one calm line."""

    daemon_threads = True
    # a library page asks for dozens of thumbnails at once; the default queue of 5 refused some (broken tiles)
    request_queue_size = 128
    max_connections = 64
    request_timeout = 15  # idle seconds: incomplete headers/bodies must release a worker

    def __init__(self, address, store: Store, setup: Setup | None = None):
        super().__init__(address, Handler)
        self._slots = threading.BoundedSemaphore(self.max_connections)
        self.store = store
        self.setup = setup
        if setup is not None:
            setup.port = self.server_port
            setup.wake = self.wake
        self.work_wanted = threading.Event()  # fetch lane: new items arrived
        self.process_wanted = threading.Event()  # process lane: new items archived
        self.stats_wanted = threading.Event()  # stats lane: posts were queued for a refresh
        self.boards_wanted = threading.Event()  # board lane: Sync now, or a board changed here
        self.activity = Activity(store)
        self.library: Path | None = None  # set by serve(); tests leave fetching off
        self.hub = Hub(store, wake=self.wake, activity=self.activity)
        self.hub.setup = setup
        self.hub.sync_boards = self.boards_wanted.set
        self.hub.stats_wanted = self.stats_wanted
        self.fail_next_posts = 0  # test hook: answer this many authorized POSTs with 503

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.request_timeout)
        return request, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def wake(self) -> None:
        self.work_wanted.set()
        self.process_wanted.set()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)):
            log(f"  {client_address[0]} dropped the connection mid-request (ignored)")
        else:
            super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "Magpiary"

    def log_message(self, *args) -> None:  # we log ourselves, and never the Authorization header
        pass

    def send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_page(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        length = response.stream[2] if response.stream else len(response.body)
        self.send_header("Content-Length", str(length))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if response.stream is None:
            self.wfile.write(response.body)
            return
        path, start, remaining = response.stream
        with open(path, "rb") as f:  # chunks, so a long video never sits in memory
            f.seek(start)
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        setup = self.server.setup
        if parts.path == "/v1/ping":
            self.send_json(200, {"ok": True, "service": "magpiary", "v": 1, "uid": os.getuid()})
        elif parts.path == BOARDS_PATH:  # the phone, with its own key: the board list, nothing else
            from magpiary import boards

            phone = self.server.store.phone_for_key(self._bearer())
            if phone is None:
                self.send_json(401, {"error": "unauthorized"})
                return
            if self.server.store.phone_kind(phone.id) == "agent":
                self.send_json(403, {"error": "agent keys cannot use phone routes"})
                return
            self.send_json(200, {"ack": ACK, "boards": boards.phone_list(self.server.store),
                                 "wifi": self.server.store.wifi_mode_of(phone.id)})
        elif parts.path in HUB_PAGES or parts.path.startswith(HUB_PREFIXES):
            self.send_page(self.server.hub.get(parts.path, parse_qs(parts.query), self.client_address[0],
                                               self.headers.get("Host", ""), self.headers.get("Range", "")))
        elif setup and (parts.path == "/install" or parts.path.startswith(("/install/", "/s/"))):
            self.send_page(setup.get(parts.path, parse_qs(parts.query), self.client_address[0],
                                     self.headers.get("Host", "")))
        elif "text/html" in self.headers.get("Accept", "") and not local_only(self.client_address[0], self.headers.get("Host", "")):
            self.send_page(self.server.hub.not_found_page())
        else:
            self.send_json(404, {"error": "not found"})

    def _ask_about_links(self, path: str) -> None:
        """The extension asks whether a link is saved (/v1/seen) or which board fits it (/v1/suggest). A paired key only."""
        from magpiary import seen

        phone = self.server.store.phone_for_key(self._bearer())
        if phone is None:
            self.send_json(401, {"error": "unauthorized"})
            return
        if self.server.store.phone_kind(phone.id) == "agent":
            self.send_json(403, {"error": "agent keys cannot use browser routes"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 10_000:
                raise ValueError("size")
            body = json.loads(self.rfile.read(length))
            if path == "/v1/seen":
                urls = body["urls"]
                if not isinstance(urls, list):
                    raise ValueError("urls")
            else:
                url = body["url"]
                if not isinstance(url, str):
                    raise ValueError("url")
        except Exception:
            self.send_json(400, {"error": "bad request"})
            return
        if path == "/v1/seen":
            self.send_json(200, {"results": seen.seen(self.server.store, urls)})
        else:
            self.send_json(200, {"suggestion": seen.suggest(self.server.store, url)})

    def _pair_browser(self) -> None:
        """The Chrome extension trades its one-time pairing code for its key. Only from this Mac, never with a key in the request."""
        setup = self.server.setup
        if setup is None or self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1000:
                raise ValueError("size")
            code = json.loads(self.rfile.read(length))["code"]
        except Exception:
            self.send_json(400, {"error": "bad request"})
            return
        key = setup.redeem(code)
        if key is None:
            log("POST /v1/pair -> 403 (wrong, used or expired code)")
            self.send_json(403, {"error": "code not accepted"})
            return
        log("POST /v1/pair -> 200 (browser paired)")
        self.send_json(200, {"key": key})

    def _extension_hello(self) -> None:
        """The Chrome extension says it is installed, and whether it is pinned. From this Mac only; no key (it has none before pairing)."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 500:
                raise ValueError("size")
            body = json.loads(self.rfile.read(length))
            version, pinned = body["v"], body.get("pinned")
            if not isinstance(version, str) or pinned not in (None, True, False):
                raise ValueError("fields")
        except Exception:
            self.send_json(400, {"error": "bad request"})
            return
        self.server.store.extension_hello(version, pinned)
        self.send_json(200, {"ok": True})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/hub/"):
            form = self._read_form(PHOTO_FORM if path == "/hub/profile/photo" else VOICE_FORM if path == "/hub/ask/voice" else 20_000)
            if form is None:
                self.send_json(413, {"error": "request too large"})
                return
            self.send_page(self.server.hub.post(path, form, self.client_address[0],
                                                self.headers.get("Host", ""), self.headers.get("Origin")))
            return
        if path == "/v1/pair":
            self._pair_browser()
            return
        if path == "/v1/hello":
            self._extension_hello()
            return
        if path in ("/v1/seen", "/v1/suggest"):
            self._ask_about_links(path)
            return
        if path == "/v1/agent/note":
            self._agent_note()
            return
        if path != "/v1/items":
            self.send_json(404, {"error": "not found"})
            return
        phone = self.server.store.phone_for_key(self._bearer())
        if phone is None:
            log(f"POST /v1/items from {self.client_address[0]} -> 401 (bad, missing or revoked key)")
            self.send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length > MAX_BODY:
            log(f"POST /v1/items from {phone.name} -> 413 (too large)")
            self.send_json(413, {"error": "request too large"})
            return
        try:
            if length <= 0:
                raise ValueError("empty")
            items = json.loads(self.rfile.read(length))["items"]
            if not isinstance(items, list):
                raise ValueError("items")
        except Exception:
            log(f"POST /v1/items from {phone.name} -> 400 (bad body)")
            self.send_json(400, {"error": "bad request"})
            return
        if len(items) > MAX_ITEMS:
            log(f"POST /v1/items from {phone.name} -> 413 ({len(items)} items)")
            self.send_json(413, {"error": "too many items"})
            return
        # Serialize policy checks, writes and usage accounting across HTTP worker threads.
        with self.server.store._lock:
            is_agent = self.server.store.phone_kind(phone.id) == "agent"
            if is_agent:
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    self.send_json(403, {"error": "AI agents are local to this Mac"})
                    return
                why = agent_policy.refusal(self.server.store, "add")
                if why is None:
                    why = agent_policy.over_limit(self.server.store, "add", len(items))
                if why:
                    log(f"POST /v1/items from {phone.name} -> 403 (agent switch, permission or daily limit)")
                    self.send_json(403, {"error": why})
                    return
                if not all(isinstance(i, dict) and set(i) <= {"id", "url"} for i in items):
                    log(f"POST /v1/items from {phone.name} -> 403 (an agent key may only save links)")
                    self.send_json(403, {"error": "an agent key can only save links"})
                    return
            if self.server.fail_next_posts > 0:
                self.server.fail_next_posts -= 1
                self.send_json(503, {"error": "simulated failure"})
                return

            results = self.server.store.receive(phone, items)  # committed before we reply
            if is_agent and any(r.status == "new" for r in results):
                self.server.store.agent_use("add", sum(r.status == "new" for r in results))
        if any(r.status == "new" for r in results):
            self.server.work_wanted.set()
        to_boards = [i.get("board") for i in items if isinstance(i, dict) and i.get("board") and i.get("url")]
        if to_boards:
            self.server.boards_wanted.set()  # anything already read goes on its board now
        tally: dict[str, int] = {}
        for r in results:
            tally[r.status] = tally.get(r.status, 0) + 1
        log(f"POST /v1/items from {phone.name} at {self.client_address[0]}, {len(items)} item(s) -> 200 {tally}")  # the address shows which network
        reply = build_reply(results)
        if is_agent:
            # The agent API needs acknowledgements, never board names, Wi-Fi or owner save counts.
            reply["message"] = "Saved to Magpiary."
            for result in reply["results"]:
                result.pop("saved_count", None)
                result["message"] = "Saved to Magpiary."
            self.send_json(200, reply)
            return
        from magpiary import boards

        reply["boards"] = boards.phone_list(self.server.store)  # the phone's copy, for the "Which board?" question
        reply["wifi"] = self.server.store.wifi_mode_of(phone.id)  # "home" or "any": where the phone may send
        stored = [r for r in results if r.status in ("new", "again", "replay")]
        board = self.server.store.board(to_boards[-1]) if to_boards and len(stored) == 1 else None
        if board:
            reply["message"] = f"Saved, and on its way to {board['name']} ✅"
        self.send_json(200, reply)

    def _read_form(self, limit: int = 20_000) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= limit:
            return None
        return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace")).items()}

    def _agent_note(self) -> None:
        """An AI agent's note on a save (`magpiary note`). Only a key made for agents may write it; it never touches the
        owner's own note, and every change keeps the version it replaced."""
        store = self.server.store
        phone = store.phone_for_key(self._bearer())
        if phone is None:
            self.send_json(401, {"error": "unauthorized"})
            return
        if store.phone_kind(phone.id) != "agent":
            self.send_json(403, {"error": "this key is not an agent key"})
            return
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_json(403, {"error": "AI agents are local to this Mac"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 20_000:
                raise ValueError("size")
            body = json.loads(self.rfile.read(length))
            item_id, mode = body["id"], body.get("mode", "set")
            text, by = body.get("text", ""), body.get("by", "")
            if not (isinstance(item_id, int) and not isinstance(item_id, bool) and isinstance(mode, str)
                    and isinstance(text, str) and isinstance(by, str)):
                raise ValueError("types")
        except Exception:
            self.send_json(400, {"error": "bad request"})
            return
        with store._lock:
            why = agent_policy.refusal(store, "note")
            if why:
                self.send_json(403, {"error": why})
                return
            if mode != "undo":
                why = agent_policy.over_limit(store, "note")
                if why:
                    self.send_json(429, {"error": why})
                    return
            target = store.item_by_id(item_id)
            if target and target["canonical_url"] in agent_policy.hidden_urls(store):
                self.send_json(404, {"error": "no such save"})  # a hidden save does not exist, as far as an agent can tell
                return
            try:
                note = store.set_agent_note(item_id, mode, text, by.strip() or phone.name)
            except ValueError as err:
                self.send_json(409 if str(err) == "nothing to undo" else 400, {"error": str(err)})
                return
            if note is None:
                self.send_json(404, {"error": "no such save"})
                return
            if mode != "undo":
                store.agent_use("note")
        log(f"POST /v1/agent/note from {phone.name} -> 200 ({mode})")
        self.send_json(200, {"ok": True, "agent_note": note})

    def _bearer(self) -> str:
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        return token.strip() if hmac.compare_digest(scheme.lower().encode(), b"bearer") else ""


def make_server(store: Store, host: str = "0.0.0.0", port: int = DEFAULT_PORT, setup: Setup | None = None) -> Server:
    return Server((host, port), store, setup)


def expansion_loop(server: Server, fetch: Fetch = http_fetch, pause=jitter_pause) -> None:
    """Lane 1, forever: expand short links, then fetch and archive posts one at a time.
    Runs when new items arrive, and on a slow timer for retries."""
    while True:
        server.work_wanted.wait(RETRY_CHECK_SECONDS)
        server.work_wanted.clear()
        try:
            expanded = process_due(server.store, fetch, pause)
            if expanded:
                log(f"expanded {expanded} short link(s)")
        except Exception as err:  # never let the worker die; log the type only
            log(f"expansion pass failed: {type(err).__name__}")
        if server.library is None:
            continue
        try:
            update_ytdlp(server.store)  # at most once a day
            update.check_daily(server.store)  # is a newer Magpiary out? (once a day)
            archived = fetch_due(server.store, server.library, activity=server.activity,
                                 on_archived=server.process_wanted.set)
            if archived:
                log(f"archived {archived} item(s)")
            purged = server.hub.purge_old_trash()
            if purged:
                log(f"deleted {purged} item(s) left in the Trash for {TRASH_DAYS} days")
        except Exception as err:
            log(f"fetch pass failed: {type(err).__name__}")


def process_loop(server: Server) -> None:
    """Lane 2, forever: transcribe, pick frames and summarise archived items one at a time."""
    while True:
        server.process_wanted.wait(RETRY_CHECK_SECONDS)
        server.process_wanted.clear()
        try:
            summarised = brain_due(server.store, data_dir() / "notes", log=log, activity=server.activity)
            if summarised:
                log(f"summarised {summarised} item(s)")
                server.boards_wanted.set()  # a post waiting for its board may be ready now
            dived = deep_due(server.store, data_dir() / "notes", activity=server.activity, log=log)
            if dived:
                log(f"made {dived} deeper dive(s)")
            linked = links_due(server.store, activity=server.activity, log=log)
            if linked:
                log(f"found links for {linked} item(s)")
            icons_due(server.store, log=log)
            read = screen_due(server.store, activity=server.activity, log=log)
            if read:
                log(f"read the on-screen text of {read} item(s)")
                server.process_wanted.set()  # more may be waiting (the older posts catch up a few at a time)
            if related_due(server.store, log=log):
                log("updated related items and piles")
            if digest_due(server.store) is not None:
                log("made a digest")
            story_due(server.store, log=log)
        except Exception as err:
            log(f"summary pass failed: {type(err).__name__}")


STATS_CHECK_SECONDS = 30


def stats_loop(server: Server) -> None:
    """Lane 4, forever: refresh likes, comments and views one post at a time, very slowly (see stats.py). Seeds the
    table from what each post already saved, and queues the newest month once a week."""
    from magpiary import stats

    try:
        server.store.stats_backfill()
    except Exception as err:
        log(f"stats seed failed: {type(err).__name__}")
    while True:
        server.stats_wanted.wait(STATS_CHECK_SECONDS)
        server.stats_wanted.clear()
        try:
            queued = stats.weekly_queue(server.store)
            if queued:
                log(f"queued {queued} post(s) for the weekly stats refresh")
            outcome = stats.step(server.store)
            if outcome.startswith("stopped"):
                _, site, why = (outcome.split(":") + ["", ""])[:3]
                log(f"{site or 'a site'} showed a warning sign ({why or 'unknown'}): its stats refresh waits a day")
        except Exception as err:
            log(f"stats pass failed: {type(err).__name__}")


def board_loop(server: Server) -> None:
    """Lane 3, forever: sync shared boards every 15 minutes while the Mac is awake, and soon after Sync now or a
    change made here. Network waits stay out of the other lanes."""
    from magpiary import boards

    while True:
        server.boards_wanted.wait(boards.SYNC_EVERY)
        server.boards_wanted.clear()
        try:
            boards.sync_all(server.store, log=log)
        except Exception as err:
            log(f"board sync pass failed: {type(err).__name__}")


def serve(store: Store, host: str, port: int) -> None:
    setup = Setup(store, host_name=local_name(), signer=sign, keep_awake=KeepAwake(),
                  wifi_suggestion=current_wifi_name)
    server = make_server(store, host, port, setup)
    server.library = server.hub.library = data_dir() / "library"
    server.hub.keep_awake = setup.keep_awake
    server.hub.lock.watch()  # sleep and the screen lock lock the hub even when no tab is open
    server.hub.meaning = Warm()  # search by meaning; loaded on the first search, let go when idle
    backfill_details(store)
    setup.apply_saved_settings()
    server.wake()  # catch up on anything left waiting before this start
    threading.Thread(target=expansion_loop, args=(server,), daemon=True).start()
    threading.Thread(target=process_loop, args=(server,), daemon=True).start()
    server.boards_wanted.set()  # a first sync right after starting
    threading.Thread(target=board_loop, args=(server,), daemon=True).start()
    threading.Thread(target=stats_loop, args=(server,), daemon=True).start()
    log(f"Magpiary receiver listening on {host}:{port}")
    log(f"Set up a phone: http://localhost:{server.server_port}/settings/phones")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("stopped")
    finally:
        server.server_close()
