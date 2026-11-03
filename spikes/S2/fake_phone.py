"""A fake iPhone for the S2 spike. Throwaway.

Runs the outbox Shortcut's steps in Python against the real receiver.py (on port 8791, with a throwaway
database and key, so your real data is never touched), and breaks things on purpose.

    python3 spikes/S2/fake_phone.py

It copies what Shortcuts really does, including that "Get Contents of URL" only stops the Shortcut when it
cannot connect. A reply with an error status (401, 503, ...) does NOT stop it; the next step just sees an
error body. It does not test iOS itself (prompts, file-to-text conversion, share sheet, automation).
"""

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


class CouldNotConnect(Exception):
    """What Shortcuts reports as "Could not connect to the server": the Shortcut stops here."""


class Phone:
    def __init__(self, key: str, outbox: Path, guard: bool):
        self.key, self.outbox, self.guard = key, outbox, guard
        self.outbox.write_text(" ")

    # --- the Shortcut's steps
    @staticmethod
    def clean(shared: str) -> str:
        m = re.match(r"(?s)^.*?(https?://[^\s]+).*$", shared)
        found = m.group(1) if m else shared  # Replace Text leaves non-matching text alone
        once = re.sub(r"(?<!youtube\.com/watch)[?#].*$", "", found)
        return re.sub(r"(watch\?v=[^&#]+).*$", r"\1", once)

    def item_line(self, shared: str) -> str:
        now = datetime.now().astimezone()
        iid = f"{now:%Y%m%d%H%M%S}-{random.randint(100000, 999999)}"
        return json.dumps({"id": iid, "url": self.clean(shared), "shared_at": now.isoformat(timespec="seconds"),
                           "source": "", "note": "", "v": 1}, separators=(",", ":"))

    def post(self, body: str) -> dict:
        req = urllib.request.Request(f"{BASE}/v1/items", data=body.encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:      # reached the server: Shortcuts carries on with the error body
            try:
                return json.loads(e.read())
            except Exception:
                return {}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise CouldNotConnect(str(e)) from e

    def run(self, shared: str = "", at_home: bool = True) -> str:
        """One run of the Shortcut. Returns the ONE notification text it shows ("" = stays quiet)."""
        raw = self.outbox.read_text() + "\n" + self.item_line(shared)
        trim = raw.strip()
        self.outbox.write_text(trim)                                     # save first
        if not at_home:                                                  # Get Network Details says not home
            return "Saved. It will send when you're home."
        body = '{"items":[' + re.sub(r"\s*\n\s*", ",", trim) + "]}"
        reply = self.post(body)                                          # may raise CouldNotConnect
        if self.guard and reply.get("ack") != "magpiary-ok":
            return "Saved on your phone. The Mac didn't accept it yet."
        self.outbox.write_text(" ")                                      # blank it
        if self.guard and reply.get("notify") != "yes":
            return ""
        return reply.get("message", "")

    def waiting(self) -> int:
        t = self.outbox.read_text().strip()
        return len([ln for ln in t.splitlines() if ln.strip() and '"url":""' not in ln])


class Mac:
    def __init__(self, tmp: Path):
        self.env = {**os.environ, "MAGPIARY_SPIKE_DB": str(tmp / "t.db"), "MAGPIARY_SPIKE_KEY": str(tmp / "k")}
        self.db, self.proc = tmp / "t.db", None

    def start(self, *args: str) -> None:
        self.stop()
        self.proc = subprocess.Popen(["uv", "run", str(HERE / "receiver.py"), "--port", str(PORT), *args],
                                     env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/v1/ping", timeout=1).read()
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("receiver did not start")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait()
            self.proc = None

    def key(self) -> str:
        return Path(self.env["MAGPIARY_SPIKE_KEY"]).read_text().strip()

    def rows(self) -> dict[str, int]:
        out = subprocess.run(["sqlite3", str(self.db), "select canonical_url, saved_count from items"],
                             capture_output=True, text=True).stdout
        return {ln.split("|")[0]: int(ln.split("|")[1]) for ln in out.splitlines() if ln}


results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))


def scenarios(guard: bool) -> None:
    print(f"\n=== phone {'WITH' if guard else 'WITHOUT'} the ack guard ===")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mac = Mac(tmp)
        try:
            mac.start()
            phone = Phone(mac.key(), tmp / "outbox.txt", guard)
            A = "https://www.instagram.com/reel/AAAA111/"
            B, C = "https://www.instagram.com/reel/BBBB222/", "https://www.threads.com/@examplecreator/post/CCCC333/"
            F = "https://www.instagram.com/reel/FFFF666/"

            msg = phone.run(A + "?igsh=abc&utm_source=ig_web_copy_link")
            check("share with tracking tail -> stored clean", mac.rows() == {A: 1}, msg)
            check("outbox blank after a confirmed send", phone.waiting() == 0)

            msg = phone.run("Look at this " + A + "?igsh=zzz\nthanks")
            check("same reel again -> saved_count 2, friendly message", mac.rows()[A] == 2 and "Already in Magpiary" in msg, msg)

            Y1, Y2, Y3 = ("https://www.youtube.com/watch?v=Example0005", "https://youtu.be/Example0006", "https://youtube.com/shorts/Example0007")
            phone.run(Y1 + "&si=track&t=42s")
            phone.run(Y2 + "?si=track")
            phone.run(Y3 + "?feature=share")
            yt = sorted(u for u in mac.rows() if "you" in u)
            check("YouTube: watch keeps only v=ID; youtu.be and shorts lose the tail (no ? or &)",
                  "https://www.youtube.com/watch?v=Example0005" in yt and not any(("?" in u and "v=" not in u) or "&" in u for u in yt),
                  str(yt))

            msg = phone.run("")
            check("run with nothing shared (the automation) stays quiet", msg == "" or not guard, repr(msg))

            msg = phone.run(B + "?igsh=away", at_home=False)
            check("away from home: saved, nothing sent, one calm message",
                  phone.waiting() == 1 and B not in mac.rows() and "send when you're home" in msg, msg)
            msg = phone.run("", at_home=True)
            check("back home: the waiting reel is sent and the outbox blanks",
                  mac.rows().get(B) == 1 and phone.waiting() == 0, msg)

            mac.stop()
            for link in (F, C):
                try:
                    phone.run(link + "?utm_source=x")
                    check(f"offline share raises Could not connect ({link[-8:]})", False)
                except CouldNotConnect:
                    pass
            check("two offline shares both wait in the outbox", phone.waiting() == 2, f"{phone.waiting()} waiting")

            mac.start()
            msg = phone.run("")
            check("flush sends both, outbox blank", mac.rows().get(F) == 1 and mac.rows().get(C) == 1 and phone.waiting() == 0, msg)

            msg = phone.run("https://example.com/not-supported?x=1")
            check("unsupported link: Mac rejects, outbox retired not stuck", phone.waiting() == 0, msg)

            # a reply with an error status must not wipe the outbox
            mac.stop(); mac.start("--fail", "1")
            try:
                msg = phone.run("https://www.instagram.com/reel/DDDD444/?igsh=q")
            except CouldNotConnect:
                msg = "(stopped)"
            check("Mac answers 503: the reel is NOT lost", phone.waiting() == 1, f"{phone.waiting()} waiting; {msg}")
            msg = phone.run("")
            check("retry after the 503 stores it exactly once", mac.rows().get("https://www.instagram.com/reel/DDDD444/") == 1, msg)

            # wrong key -> 401
            bad = Phone("wrong-key", tmp / "outbox2.txt", guard)
            bad.run("https://www.instagram.com/reel/EEEE555/")
            check("wrong key (401): the reel is NOT lost", bad.waiting() == 1, f"{bad.waiting()} waiting")
        finally:
            mac.stop()


if __name__ == "__main__":
    scenarios(guard=False)
    scenarios(guard=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)
