"""A fake iPhone: runs the Shortcut's steps in Python against the real receiver over HTTP.

It copies what Shortcuts really does (see spikes/S2/fake_phone.py and docs/findings): only
"could not connect" stops a run; an error reply (401, 503) does NOT stop it, so the Shortcut
clears its outbox only when the reply carries the ack string. It does not test iOS itself
(prompts, file-to-text conversion, share sheet, the Wi-Fi automation).
"""

import json
import random
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from magpiary.receiver import make_server
from magpiary.store import Store


class CouldNotConnect(Exception):
    """What Shortcuts reports as "Could not connect to the server": the run stops here."""


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 23, 12, 0, 0).astimezone()

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class Mac:
    """A receiver on a free local port that can be stopped and restarted on the same port."""

    def __init__(self, db_path, clock: Clock, setup_factory=None):
        self.db_path = db_path
        self.clock = clock
        self.setup_factory = setup_factory
        self.store = Store(db_path, now=clock.now)
        self.server = None
        self.port = 0
        self.setup = setup_factory(self.store) if setup_factory else None
        self.start()

    def start(self) -> None:
        self.server = make_server(self.store, "127.0.0.1", self.port, self.setup)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def raw_post(self, key: str | None, body: bytes | str, path: str = "/v1/items") -> tuple[int, dict]:
        """One HTTP POST exactly as given; returns (status, parsed JSON body)."""
        data = body if isinstance(body, bytes) else body.encode()
        headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
        req = urllib.request.Request(self.url + path, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except ValueError:
                return e.code, {}

    def counts(self) -> dict[str, int]:
        return {i["canonical_url"]: i["saved_count"] for i in self.store.items()}


class Phone:
    def __init__(self, mac: Mac, key: str = "", secret: str = ""):
        """key: the phone's key (the Mac's test side has it); secret: what a real Shortcut holds, sha256(key)."""
        import hashlib

        self.mac, self.key = mac, key
        self.secret = secret or hashlib.sha256(key.encode()).hexdigest()
        self.outbox = ""
        self.boards_file = ""  # magpiary-boards.txt: the Mac's last list of active boards
        self.reachable = True  # False: the Mac is somewhere else; a request never gets an answer
        self.try_file = ""  # magpiary-try.txt
        self.no_home = False  # paired without a home Wi-Fi name: any Wi-Fi unless the Mac says "home"
        self.wifi_file = ""  # magpiary-wifi.txt: "home" or "any", where the Mac lets this phone send (learned from replies)
        self.asked: list[list[str]] = []  # the "Add it to a board too?" choices shown
        self.sent_bodies: list[str] = []

    # --- the Shortcut's steps
    @staticmethod
    def clean(shared: str) -> str:
        m = re.match(r"(?s)^.*?(https?://[^\s]+).*$", shared)
        found = m.group(1) if m else shared  # Replace Text leaves non-matching text alone
        once = re.sub(r"(?<!youtube\.com/watch)[?#].*$", "", found)
        return re.sub(r"(watch\?v=[^&#]+).*$", r"\1", once)

    def board_line(self, item_line: str, pick: str) -> str:
        """After the post is queued: the board question, and the choice as one more line (none for the library)."""
        item = json.loads(item_line)
        board = self.board_for(item["url"], pick)
        return json.dumps({"id": item["id"] + "-b", "url": item["url"], "board": board, "attach": 1, "v": 1},
                          separators=(",", ":")) if board else ""

    def board_for(self, url: str, pick: str) -> str:
        """The board question, as the Shortcut asks it: only with a link and an active board today."""
        if "http" not in url:
            return ""
        today = self.mac.clock.now().strftime("%Y%m%d")
        active = re.sub(f"(?m)^(?!.*{today}).*(\n|$)", "", self.boards_file)
        lines = re.sub(r"(?m)^[0-9 ]+\t", "", active)
        if "\t" not in lines:
            return ""
        menu = ("Just my library\n" + re.sub(r"\t[0-9a-f]{16}", "", lines)).splitlines()
        self.asked.append(menu)
        chosen = pick or menu[0]
        found = re.sub(r"(?s)^(?:.*\n)?" + chosen + r"\t([0-9a-f]{16}).*$", r"\1", lines)
        return re.sub(r"(?s)^(?![0-9a-f]{16}$).*$", "", found)

    def signed(self, request: str, body: bytes | None = None) -> dict:
        """The headers the Shortcut sends (0.1.5): who, when and the signature, never the key."""
        from magpiary.protocol import SIGN_DEVICE, SIGN_SIG, SIGN_TIME, device_tag, signature

        secret = self.secret
        stamp = self.mac.clock.now().isoformat(timespec="seconds")
        return {SIGN_DEVICE: device_tag(secret), SIGN_TIME: stamp, SIGN_SIG: signature(secret, request, stamp, body)}

    def item_line(self, shared: str, pick: str = "") -> str:
        now = self.mac.clock.now()
        item_id = f"{now:%Y%m%d%H%M%S}-{random.randint(100000, 999999)}"
        url = self.clean(shared)
        return json.dumps({"id": item_id, "url": url, "shared_at": now.isoformat(timespec="seconds"), "note": "",
                           "v": 1}, separators=(",", ":"))

    def post(self, body: str) -> dict:
        self.sent_bodies.append(body)
        req = urllib.request.Request(self.mac.url + "/v1/items", data=body.encode(), method="POST",
                                     headers=self.signed("POST /v1/items", body.encode()))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:  # reached the server: Shortcuts carries on with the body
            try:
                return json.loads(e.read())
            except ValueError:
                return {}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise CouldNotConnect(str(e)) from e

    def check_reachable(self) -> None:
        if not self.reachable:
            raise CouldNotConnect("the request timed out")

    def sends_now(self, shared: str, at_home: bool, network: str) -> bool:
        """The Shortcut's send decision (shortcut.send_gate, proved on its own regex in test_shortcut.py): on the home
        Wi-Fi; or the Mac said "any" and the phone is on some Wi-Fi; or run by hand with nothing shared."""
        network = network or ("home" if at_home else "mobile")
        any_wifi = self.wifi_file.strip() == "any" or (self.no_home and self.wifi_file.strip() != "home")
        return network == "home" or (network == "other" and any_wifi) or not self.clean(shared)

    def run(self, shared: str = "", at_home: bool = True, pick: str = "", network: str = "") -> str:
        """One run of the Shortcut. Returns the ONE notification it shows ("" = stays quiet). `pick` answers the
        board question when it is asked (empty: the first choice, Just my library). `network` is "home", "other"
        (some other Wi-Fi) or "mobile" (no Wi-Fi); empty follows `at_home`."""
        network = network or ("home" if at_home else "mobile")
        name = {"home": "Example Net", "other": "Cafe", "mobile": ""}[network]
        # the same try note the Shortcut keeps: this network in this 5-minute slot, left behind by a try nobody answered
        minute = self.mac.clock.now().strftime("%Y%m%d%H%M")
        cur = f"{name}\u00a6{minute[:-2]}{'abcd'[int(minute[-2:]) // 15]}"   # 15-minute slots (the default)
        manual = not self.clean(shared)
        decided = self.sends_now(shared, at_home, network)
        blocked = decided and not manual and self.try_file == cur
        go = decided and not blocked
        at_home = go
        item = self.item_line(shared)
        lines = [ln for ln in self.outbox.splitlines() if ln.strip()] + [item]
        self.outbox = "\n".join(lines)                                   # save first
        if "http" in self.clean(shared):                                 # then ask about boards
            if at_home:  # the latest list first; a Mac that can't be reached stops the run, the post is queued
                self.try_file = cur                                      # note the try before the first request
                self.check_reachable()
                req = urllib.request.Request(self.mac.url + "/v1/boards", headers=self.signed("GET /v1/boards"))
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        fresh = json.loads(r.read())
                except urllib.error.HTTPError:
                    fresh = {}
                except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                    raise CouldNotConnect(str(e)) from e
                self.try_file = " "                                      # the Mac answered
                if fresh.get("ack") == "magpiary-ok":
                    self.boards_file = fresh.get("boards", "") + "\n"
                    self.wifi_file = fresh.get("wifi", "")
            extra = self.board_line(item, pick)
            if extra:
                lines.append(extra)
                self.outbox = "\n".join(lines)
        if not at_home:
            return ("Saved. Your Mac wasn't reachable on this Wi-Fi a moment ago. It will send when it is, or run Magpiary "
                    "from Shortcuts to try now.") if blocked else "Saved. It will send when you're home."
        self.try_file = cur
        self.check_reachable()
        reply = self.post('{"items":[' + ",".join(lines) + "]}")        # may raise CouldNotConnect
        self.try_file = " "                                              # any answer clears the note
        if reply.get("ack") != "magpiary-ok":
            return "Saved on your phone. The Mac didn't accept it yet."
        self.boards_file = reply.get("boards", "") + "\n"               # the list for the next share
        self.wifi_file = reply.get("wifi", "")                           # where the Mac lets this phone send
        self.outbox = ""                                                 # blank it
        return reply.get("message", "") if reply.get("notify") == "yes" else ""

    def waiting(self) -> int:
        """Items in the outbox, not counting runs with nothing shared."""
        return len([ln for ln in self.outbox.splitlines() if ln.strip() and '"url":""' not in ln])
