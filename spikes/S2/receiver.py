# /// script
# requires-python = ">=3.12"
# dependencies = ["segno"]
# ///
"""S2/S3/S6 spike: minimal Magpiary receiver. Throwaway; the real one is M1.

    uv run spikes/S2/receiver.py                 # listen on 0.0.0.0:8765
    uv run spikes/S2/receiver.py --fail 2        # answer the first 2 valid POSTs with 503
    uv run spikes/S2/receiver.py --show-key      # also print the pairing key

Endpoints
    GET  /v1/ping    no auth. {"ok": true, ...}
    POST /v1/items   Authorization: Bearer <key>. {"items": [{id, url, shared_at, source, note, v}]}
                     -> {"accepted": [ids], "rejected": [{id, reason}]}
    GET  /setup      loopback only. Shows the pairing config, a shortcuts:// link and a QR code.

Items are written to received.db before the response, so an ack means stored.
The same id twice is a no-op; a different id with the same canonical URL bumps saved_count.
The URL is re-cleaned here, and a query string or fragment in what the phone sent is
logged as UNCLEAN so S2 can check the phone's cleaning.
"""

import argparse
import hmac
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

import segno

import make_shortcuts

HERE = Path(__file__).parent
TOKEN_TTL = 15 * 60  # seconds an install link stays valid
tokens: dict[str, float] = {}
# env overrides let tests (fake_phone.py) run against a throwaway key and database
KEY_FILE = Path(os.environ.get("MAGPIARY_SPIKE_KEY", HERE / ".pairing_key"))
DB_FILE = Path(os.environ.get("MAGPIARY_SPIKE_DB", HERE / "received.db"))
MAX_BODY = 1_000_000
MAX_ITEMS = 100

# host -> (source, identity query params kept)
HOSTS = {
    "instagram.com": ("instagram", ()),
    "threads.net": ("threads", ()),
    "threads.com": ("threads", ()),
    "x.com": ("x", ()),
    "twitter.com": ("x", ()),
    "reddit.com": ("reddit", ()),
    "youtube.com": ("youtube", ("v",)),
    "youtu.be": ("youtube", ()),
}

db_lock = threading.Lock()

# name -> function(config) -> signed .shortcut bytes, with the pairing config baked in
PERSONAL = {
    "Magpiary": lambda config: make_shortcuts.sign(make_shortcuts.share_shortcut(config)),
}


def new_token() -> str:
    t = secrets.token_urlsafe(16)
    cutoff = time.time()
    for old in [k for k, exp in tokens.items() if exp < cutoff]:
        del tokens[old]
    tokens[t] = cutoff + TOKEN_TTL
    return t


def valid_token(t: str | None) -> bool:
    return bool(t) and tokens.get(t, 0) > time.time()


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def local_name() -> str:
    try:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip() + ".local"
    except Exception:
        pass
    return socket.gethostname()


def lan_ip() -> str:
    try:
        out = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "127.0.0.1"


def load_key() -> str:
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    key = secrets.token_urlsafe(24)
    KEY_FILE.write_text(key + "\n")
    KEY_FILE.chmod(0o600)
    return key


def canonicalize(url: str) -> tuple[str, str, bool] | None:
    """Returns (canonical_url, source, had_query_or_fragment), or None if unsupported."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if parts.scheme not in ("http", "https") or host not in HOSTS:
        return None
    source, keep = HOSTS[host]
    query = ""
    if keep:
        params = parse_qs(parts.query)
        pairs = [f"{k}={params[k][0]}" for k in keep if k in params]
        query = "?" + "&".join(pairs) if pairs else ""
    path = parts.path or "/"
    if host in ("instagram.com", "threads.net", "threads.com") and not path.endswith("/"):
        path += "/"
    netloc = "www." + ("threads.com" if host.startswith("threads.") else host)
    canonical = f"https://{netloc}{path}{query}"
    # "dirty" means the phone sent more than the identity parameters.
    sent_query = parts.query != "" and parts.query.split("&") != query.removeprefix("?").split("&")
    return canonical, source, sent_query or bool(parts.fragment)


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                canonical_url TEXT PRIMARY KEY, source TEXT, first_id TEXT, shared_at TEXT,
                note TEXT, first_seen TEXT, last_seen TEXT, saved_count INTEGER);
            CREATE TABLE IF NOT EXISTS seen_ids (id TEXT PRIMARY KEY, seen_at TEXT);
            """
        )


def saved_count_for(url: object) -> int:
    clean = canonicalize(url) if isinstance(url, str) else None
    if clean is None:
        return 0
    with db_lock, sqlite3.connect(DB_FILE) as db:
        row = db.execute("SELECT saved_count FROM items WHERE canonical_url=?", (clean[0],)).fetchone()
    return row[0] if row else 0


def message_for(status: str, count: int) -> str:
    """Words the phone shows. Written here so they can change without reinstalling the Shortcut."""
    if status == "empty":
        return "Nothing new to save."
    if status == "new":
        return "Saved to Magpiary \u2705"
    if status in ("again", "replay") and count > 1:
        return f"Already in Magpiary. Noted that you saved it again ({count}\u00d7)."
    if status == "replay":
        return "Already in Magpiary."
    if status.startswith("rejected:"):
        return "Magpiary can't save this kind of link yet."
    return "Saved to Magpiary \u2705"


def store(item: dict) -> tuple[str, bool]:
    """Returns (status, unclean). status is one of: new, again, replay, rejected:<reason>."""
    item_id, url = item.get("id"), item.get("url")
    if not isinstance(item_id, str) or not item_id or len(item_id) > 64:
        return "rejected:bad_id", False
    if not isinstance(url, str):
        return "rejected:bad_url", False
    if not url.strip():  # a run with nothing shared (e.g. the Wi-Fi automation): acknowledge, store nothing
        return "empty", False
    clean = canonicalize(url)
    if clean is None:
        return "rejected:unsupported_link", False
    canonical, source, unclean = clean
    with db_lock, sqlite3.connect(DB_FILE) as db:
        if db.execute("SELECT 1 FROM seen_ids WHERE id=?", (item_id,)).fetchone():
            return "replay", unclean
        db.execute("INSERT INTO seen_ids VALUES (?,?)", (item_id, now()))
        row = db.execute("SELECT saved_count FROM items WHERE canonical_url=?", (canonical,)).fetchone()
        if row:
            db.execute(
                "UPDATE items SET saved_count=saved_count+1, last_seen=? WHERE canonical_url=?",
                (now(), canonical),
            )
            return "again", unclean
        db.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,1)",
            (canonical, source, item_id, str(item.get("shared_at", ""))[:40], str(item.get("note", ""))[:2000], now(), now()),
        )
        return "new", unclean


class QuietServer(ThreadingHTTPServer):
    """A phone that drops a connection mid-request (network switch, a prompt) is normal: one calm line."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            log(f"  {client_address[0]} dropped the connection mid-request (ignored)")
        else:
            super().handle_error(request, client_address)


def make_handler(key: str, host: str, port: int, fail_budget: list[int], home_wifi: str = ""):
    config = {"v": 1, "host": host, "port": port, "key": key}
    if home_wifi:
        config["home_wifi"] = home_wifi

    class Handler(BaseHTTPRequestHandler):
        server_version = "MagpiarySpike/0.1"

        def log_message(self, *args) -> None:  # we log ourselves
            pass

        def send(self, code: int, body, ctype: str = "application/json", filename: str | None = None) -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if filename:  # so the imported Shortcut gets its proper name
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def query_token(self) -> str | None:
            return parse_qs(urlsplit(self.path).query).get("t", [None])[0]

        def authorized(self) -> bool:
            sent = self.headers.get("Authorization", "").encode()
            return hmac.compare_digest(sent, f"Bearer {key}".encode())

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/v1/ping":
                log(f"GET  /v1/ping from {self.client_address[0]}")
                self.send(200, {"ok": True, "service": "magpiary-spike", "v": 1, "name": host})
            elif path.startswith("/shortcuts/"):
                name = unquote(path.removeprefix("/shortcuts/")).removesuffix(".shortcut")
                if not valid_token(self.query_token()) or name not in PERSONAL:
                    self.send(404, {"error": "not found"})
                    return
                try:
                    data = PERSONAL[name](config)
                except Exception as e:
                    log(f"  could not build/sign shortcut {name!r}: {e}")
                    self.send(500, {"error": "could not build shortcut"})
                    return
                log(f"GET  {path} from {self.client_address[0]} (personalised shortcut, {len(data)} bytes)")
                self.send(200, data, "application/vnd.apple.shortcut", filename=name + ".shortcut")
            elif path.startswith("/s/"):
                parts = path.split("/")  # ["", "s", token, "Magpiary-Pair.shortcut"]
                name = parts[3].removesuffix(".shortcut").replace("-", " ") if len(parts) == 4 else ""
                if not valid_token(parts[2] if len(parts) > 2 else None) or name not in PERSONAL:
                    self.send(404, {"error": "not found"})
                    return
                try:
                    data = PERSONAL[name](config)
                except Exception as e:
                    log(f"  could not build/sign shortcut {name!r}: {e}")
                    self.send(500, {"error": "could not build shortcut"})
                    return
                log(f"GET  /s/<token>/{parts[3]} from {self.client_address[0]} (personalised shortcut, {len(data)} bytes)")
                self.send(200, data, "application/vnd.apple.shortcut", filename=name + ".shortcut")
            elif path == "/try":
                token = self.query_token()
                if not valid_token(token):
                    self.send(403, "<p>Expired. Reload the setup page on your Mac.</p>".encode(), "text/html; charset=utf-8")
                    return
                self.send(200, self.try_page(token).encode(), "text/html; charset=utf-8")
            elif path == "/install":
                token = self.query_token()
                if not valid_token(token):
                    self.send(403, "<p>This link has expired. Reload the setup page on your Mac for a new code.</p>".encode(), "text/html; charset=utf-8")
                    return
                log(f"GET  /install from {self.client_address[0]}")
                self.send(200, self.install_page(token).encode(), "text/html; charset=utf-8")
            elif path == "/setup":
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    self.send(403, {"error": "setup is only available on this Mac"})
                    return
                self.send(200, self.setup_page().encode(), "text/html; charset=utf-8")
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/v1/items":
                self.send(404, {"error": "not found"})
                return
            if not self.authorized():
                log(f"POST /v1/items from {self.client_address[0]} -> 401 (bad or missing key)")
                self.send(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("size")
                payload = json.loads(self.rfile.read(length))
                items = payload["items"]
                if not isinstance(items, list) or len(items) > MAX_ITEMS:
                    raise ValueError("items")
            except Exception:
                log(f"POST /v1/items from {self.client_address[0]} -> 400 (bad body)")
                self.send(400, {"error": "bad request"})
                return
            if fail_budget[0] > 0:
                fail_budget[0] -= 1
                log(f"POST /v1/items with {len(items)} item(s) -> 503 (--fail, {fail_budget[0]} left)")
                self.send(503, {"error": "simulated failure"})
                return
            accepted, rejected, results, tally = [], [], [], {}
            for item in items if all(isinstance(i, dict) for i in items) else []:
                status, unclean = store(item)
                tally[status] = tally.get(status, 0) + 1
                if status.startswith("rejected:"):
                    rejected.append({"id": str(item.get("id", ""))[:64], "reason": status.split(":", 1)[1]})
                    u = urlsplit(str(item.get("url", "")))
                    log(
                        f"  rejected ({status.split(':', 1)[1]}): keys={sorted(item)} id={str(item.get('id'))[:40]!r} "
                        f"url_len={len(str(item.get('url', '')))} scheme={u.scheme!r} host={u.netloc[:40]!r} "
                        f"path_len={len(u.path)} shared_at={str(item.get('shared_at'))[:32]!r}"
                    )
                else:
                    accepted.append(item["id"])
                n = saved_count_for(item.get("url"))
                results.append({"id": str(item.get("id", ""))[:64], "status": status.split(":", 1)[0],
                                "saved_count": n, "message": message_for(status, n)})
                if unclean:
                    shown = urlsplit(str(item.get("url", "")))
                    log(f"  UNCLEAN URL from phone (query/fragment present): {shown.netloc}{shown.path}")
            log(f"POST /v1/items with {len(items)} item(s) -> 200 {tally}")
            real = [x for x in results if x["status"] in ("new", "again", "replay")]
            if len(real) == 1:
                message = real[0]["message"]
            elif real:
                message = f"Saved {len(real)} items to Magpiary \u2705"
            else:
                message = results[0]["message"] if results else "Nothing new to save."
            notify = "yes" if any(x["status"] != "empty" for x in results) else "no"  # all-empty = a no-input run
            self.send(200, {"ack": "magpiary-ok", "notify": notify, "accepted": accepted, "rejected": rejected,
                            "results": results, "message": message})

        def install_page(self, token: str) -> str:
            """Phone-facing download page. Reached only with a valid, short-lived token."""
            style = (
                "display:block;margin:12px 0;padding:16px;background:#0E6B66;color:#fff;"
                "border-radius:12px;text-align:center;text-decoration:none;font-weight:600"
            )
            buttons = "".join(
                f'<a href="/s/{token}/{quote(n.replace(" ", "-"))}.shortcut" style="{style}">Get “{n}”</a>'
                for n in PERSONAL
            )
            return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Install Magpiary</title>
<body style="font:17px system-ui;max-width:32rem;margin:0 auto;padding:24px 16px">
<h1 style="font-size:1.5rem">Install Magpiary</h1>
<ol style="padding-left:1.2rem;line-height:1.6">
<li>Tap the green button below.</li>
<li>Safari asks <b>“Do you want to download…?”</b> Tap <b>Download</b>.</li>
<li>Tap the <b>download arrow</b> in Safari’s address bar, then tap the file.</li>
<li>Shortcuts opens. Tap <b>Add Shortcut</b>.</li>
</ol>
{buttons}
<p style="color:#555;font-size:.9rem">It is already set up for your Mac. This link stops working after {TOKEN_TTL // 60} minutes.</p></body>"""

        def setup_page(self) -> str:
            token = new_token()
            install_url = f"http://{host}:{port}/install?t={token}"
            qr_install = segno.make(install_url, error="m").svg_inline(scale=6, dark="#000", light="#fff")
            return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Magpiary spike setup</title>
<body style="font:16px system-ui;max-width:42rem;margin:2rem auto;padding:0 1rem">
<h1>Set up your iPhone (spike)</h1>
<p>This page is only served to this Mac. Scan with the iPhone Camera, on the same Wi-Fi. The code installs a Shortcut already paired to this Mac. It expires after {TOKEN_TTL // 60} minutes; reload this page for a fresh code.</p>
<div style="background:#fff;padding:12px;display:inline-block">{qr_install}</div>
<p>Or open this on the iPhone: <a href="{install_url}"><code style="word-break:break-all">{install_url}</code></a></p>
</body>"""

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fail", type=int, default=0, help="answer the first N authorized POSTs with 503")
    ap.add_argument("--show-key", action="store_true", help="print the pairing key")
    ap.add_argument("--home-wifi", default=os.environ.get("MAGPIARY_HOME_WIFI", ""),
                    help="home Wi-Fi name; the shortcut then only sends when joined to it")
    args = ap.parse_args()

    init_db()
    key, host = load_key(), local_name()
    server = QuietServer(("0.0.0.0", args.port), make_handler(key, host, args.port, [args.fail], args.home_wifi))
    print(f"Magpiary spike receiver on http://{host}:{args.port}")
    print(f"  pairing key file: {KEY_FILE}" + (f"\n  key: {key}" if args.show_key else "  (use --show-key to print it)"))
    print(f"  setup page with the QR code (this Mac only): http://localhost:{args.port}/setup")
    print(f"  database: {DB_FILE}")
    if args.fail:
        print(f"  --fail: the first {args.fail} authorized POST(s) will get 503")
    print("Ctrl-C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
