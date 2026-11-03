"""Pairing a phone: the install codes behind the QR code in Settings → Phones, and the phone's two pages.

Routes (the phone's two are behind a short-lived token; pairing itself happens in the hub, for this Mac only):
    GET  /install?t=TOKEN          the phone. Download page
    GET  /install/fonts/NAME.woff2 the phone. The hub's two fonts (Open Font License), so the page looks like the hub
    GET  /s/TOKEN/Magpiary.shortcut  the phone. The personalised, signed Shortcut

A key is never shown on a page: the QR code leads to a token, the token to the Shortcut.
"""

import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import segno

from magpiary.power import KeepAwake
from magpiary.shortcut import share_shortcut, sign
from magpiary.store import Store
from magpiary import ui
from magpiary.protocol import DEFAULT_RETRY_WAIT
from magpiary.web import Response, alone_page, e, icon, phone_page

TOKEN_TTL_SECONDS = 15 * 60
BROWSER_CODE_TRIES = 10  # wrong codes allowed in one window, then the Mac refuses all until the window ends
BROWSER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
TOKEN_DOWNLOADS = 3  # a retry in Safari may fetch the file more than once
SHORTCUT_FILENAME = "Magpiary.shortcut"
FONTS = Path(__file__).with_name("static") / "fonts"
FONT_FILES = ("bricolage-grotesque.woff2", "dm-sans.woff2")

@dataclass
class _Token:
    phone: str
    key: str
    home_wifi: str
    retry_wait: int
    expires: float
    downloads_left: int = TOKEN_DOWNLOADS
    issued_at: str = ""  # the store's clock, to tell this install's first share from older ones
    opened: bool = False  # the phone opened the install page
    downloaded: bool = False  # the phone got the Shortcut


class Setup:
    def __init__(self, store: Store, *, host_name: str, signer: Callable[[dict], bytes] = sign,
                 keep_awake: KeepAwake | None = None, wifi_suggestion: Callable[[], str] = lambda: "",
                 now: Callable[[], float] = time.time):
        self.store = store
        self.host_name = host_name
        self.port = 0  # set once the server knows its port
        self.signer = signer
        self.keep_awake = keep_awake or KeepAwake()
        self.wifi_suggestion = wifi_suggestion
        self.now = now
        self.wake: Callable[[], None] = lambda: None  # the receiver sets this to wake its worker
        self._tokens: dict[str, _Token] = {}
        self._codes: dict[str, tuple[str, float]] = {}  # browser pairing code -> (device name, expires)
        self._code_misses: list[float] = []
        self._signing: tuple[str, float] = ("", 0.0)  # (state, when): "ok", "icloud" or "error"; "" until the first check ends
        self._signing_busy = False

    # ---- can this Mac sign the Shortcut? ------------------------------------------------------

    def check_signing(self, wait: bool = False) -> None:
        """Try signing an empty Shortcut in the background, so the Welcome page can say before the phone does if Apple will
        not sign here (a Mac that is not signed in to iCloud, or offline). The answer is kept for two minutes."""
        if self._signing_busy or (self._signing[0] and self.now() - self._signing[1] < 120):
            return
        self._signing_busy = True

        def run() -> None:
            try:
                self.signer({"WFWorkflowActions": [], "WFWorkflowClientVersion": "900", "WFWorkflowTypes": []})
                state = "ok"
            except Exception as err:
                state = "icloud" if "icloud" in str(err).lower() else "error"
                print(f"{time.strftime('%H:%M:%S')} shortcut signing check failed ({state}): {str(err)[:300]}", flush=True)
            self._signing = (state, self.now())
            self._signing_busy = False

        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def signing_state(self) -> str:
        return self._signing[0]

    # ---- settings -----------------------------------------------------------------------

    def apply_saved_settings(self) -> None:
        """At startup: honour the owner's earlier choice. Never turns anything on by itself."""
        if self.store.get_setting("stay_awake") == "1":
            self.keep_awake.start()

    # ---- routing ------------------------------------------------------------------------

    def get(self, path: str, query: dict[str, list[str]], client_ip: str, host: str) -> Response:
        if path == "/install":
            return self._install_page((query.get("t") or [""])[0])
        if path == "/install/state":  # the install page asks whether its Shortcut went out yet
            record = self._tokens.get((query.get("t") or [""])[0])
            if record is None:
                return Response(404, b"{}", "application/json", {"Cache-Control": "no-store"})
            return Response(200, json.dumps({"ready": record.downloaded}).encode(), "application/json",
                            {"Cache-Control": "no-store"})
        if path.startswith("/install/fonts/") and path.rsplit("/", 1)[1] in FONT_FILES:
            return Response(200, (FONTS / path.rsplit("/", 1)[1]).read_bytes(), "font/woff2",
                            {"Cache-Control": "max-age=86400"})
        if path.startswith("/s/"):
            parts = path.split("/")  # ["", "s", token, "Magpiary.shortcut"]
            if len(parts) == 4 and parts[3] == SHORTCUT_FILENAME:
                return self._shortcut(parts[2])
        return alone_page("Not found", "var(--indigo)", "lost", "Nothing here",
                          "This address isn't part of Magpiary. Scan the QR code on your Mac again.", status=404)

    # ---- actions ------------------------------------------------------------------------

    def _issue(self, phone: str, key: str, home_wifi: str, retry_wait: int = DEFAULT_RETRY_WAIT) -> str:
        now = self.now()
        self._tokens = {t: v for t, v in self._tokens.items() if v.expires > now - 3600}  # an hour on, for status()
        token = secrets.token_urlsafe(16)
        self._tokens[token] = _Token(phone, key, home_wifi, retry_wait, now + TOKEN_TTL_SECONDS, issued_at=self.store.now())
        return token

    def _valid(self, token: str) -> _Token | None:
        record = self._tokens.get(token)
        if record is None or record.expires <= self.now() or record.downloads_left <= 0:
            return None
        return record

    def _shortcut(self, token: str) -> Response:
        record = self._valid(token)
        if record is None:
            return self._expired(404)
        config = {"v": 1, "host": self.host_name, "port": self.port, "key": record.key}
        if record.home_wifi:
            config["home_wifi"] = record.home_wifi
        if record.retry_wait != DEFAULT_RETRY_WAIT:
            config["retry_wait"] = record.retry_wait
        try:
            data = self.signer(share_shortcut(config))
        except Exception as err:  # signing needs Apple's server; say so plainly, never leak details to the phone
            print(f"{time.strftime('%H:%M:%S')} shortcut signing failed: {str(err)[:300]}", flush=True)  # the reason, for the log only
            icloud = "icloud" in str(err).lower()
            return alone_page("Try again", "var(--blue)", "retry", "iCloud isn't ready on this Mac" if icloud else "Apple didn't answer",
                              "Apple signs the Shortcut through iCloud. On the Mac, open System Settings, click your name, choose iCloud, "
                              "turn on iCloud Drive and open the Shortcuts app once, then press Try again here." if icloud else
                              "Every Shortcut is signed by Apple's server, and it didn't reply just now. Check that this Mac is online "
                              "and signed in to iCloud (System Settings, your name at the top), wait a moment and try again.", f'<a class="get calm" href="/install?t={quote(token)}">Try again</a>', 503)
        record.downloads_left -= 1
        record.downloaded = True
        return Response(200, data, "application/vnd.apple.shortcut", {
            "Content-Disposition": f'attachment; filename="{SHORTCUT_FILENAME}"', "Cache-Control": "no-store"})

    # ---- for the hub's Settings and first-run pages ----------------------------------------

    def pair(self, name: str, home_wifi: str, retry_wait: int = DEFAULT_RETRY_WAIT) -> tuple[str, str]:
        """Add a phone; returns (its name, the install link for the QR code). Raises ValueError with a plain reason."""
        phone, key = self.store.add_phone(name.strip(), home_wifi.strip(), retry_wait)
        saved = self.store.get_phone(phone.name)
        return phone.name, self.install_url(self._issue(phone.name, key, home_wifi.strip(), saved["retry_wait"]))

    def pair_browser(self, name: str = "Chrome") -> tuple[str, str]:
        """A one-time code (15 minutes) to paste into the Chrome extension; returns (the device's name, the code). Nothing is
        paired until redeem(): an unused or expired code leaves no trace. A key is never shown; redeem() hands it over."""
        now = self.now()
        self._codes = {c: v for c, v in self._codes.items() if v[1] > now}
        raw = "".join(secrets.choice(BROWSER_CODE_ALPHABET) for _ in range(12))
        self._codes[raw] = (name.strip() or "Chrome", now + TOKEN_TTL_SECONDS)
        return self._codes[raw][0], "-".join(raw[i:i + 4] for i in range(0, 12, 4))

    def redeem(self, code: str) -> str | None:
        """Exchange a browser pairing code for a key, once. One Chrome only: pairing again replaces the key of the one already
        paired. None for a wrong, used or expired code, or after too many misses."""
        now = self.now()
        self._code_misses = [t for t in self._code_misses if t > now - TOKEN_TTL_SECONDS]
        if len(self._code_misses) >= BROWSER_CODE_TRIES:
            return None
        raw = "".join(ch for ch in str(code).upper() if ch.isalnum())
        entry = self._codes.pop(raw, None)
        if entry is None or entry[1] <= now:
            self._code_misses.append(now)
            return None
        existing = next((p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") == "browser"), None)
        if existing:
            renewed = self.store.new_key(existing["name"])
            if renewed:
                return renewed[1]
        return self.store.add_phone(entry[0], kind="browser")[1]

    def renew(self, name: str) -> str | None:
        """A fresh install code for a paired phone (its old key stops working); None if it is not paired."""
        phone = self.store.get_phone(name)
        renewed = self.store.new_key(name) if phone else None
        if renewed is None:
            return None
        return self.install_url(self._issue(name, renewed[1], phone["home_wifi"], phone["retry_wait"]))

    def install_url(self, token: str) -> str:
        return f"http://{self.host_name}:{self.port}/install?t={quote(token)}"

    def status(self, install_url: str) -> dict | None:
        """How far a phone got with an install code, for the QR window's ticks: None for a code this Mac didn't make."""
        token = (parse_qs(urlsplit(install_url).query).get("t") or [""])[0]
        record = self._tokens.get(token)
        if record is None:
            return None
        return {"phone": record.phone, "left": max(0, round(record.expires - self.now())), "opened": record.opened,
                "downloaded": record.downloaded, "shared": self.store.phone_shared_since(record.phone, record.issued_at)}

    @staticmethod
    def qr_svg(url: str) -> str:
        return segno.make(url, error="m").svg_inline(border=2, omitsize=True, dark="#000", light="#fff")  # viewBox only, so it fills its frame

    def set_awake(self, enabled: bool) -> bool:
        """The stay-awake switch; False if macOS's tool would not start."""
        if enabled and not self.keep_awake.start():
            return False
        if not enabled:
            self.keep_awake.stop()
        self.store.set_setting("stay_awake", "1" if enabled else "0")
        return True

    # ---- pages --------------------------------------------------------------------------

    def _expired(self, status: int) -> Response:
        return alone_page("Expired", "var(--purple)", "clock", "This link has run out",
                          f"Install links work for {TOKEN_TTL_SECONDS // 60} minutes. On your Mac, open "
                          "<b>Settings → Phones</b> and make a new code for this phone.", status=status)

    def _install_page(self, token: str) -> Response:
        record = self._valid(token)
        if record is None:
            return self._expired(403)
        record.opened = True
        link = f"/s/{quote(token)}/{SHORTCUT_FILENAME}"
        minutes = max(1, round((record.expires - self.now()) / 60))
        steps = (("c1", "tap", "Tap the button above", "Tap <b>Get the Shortcut</b>."),
                 ("c2", "down", "Download it", "Safari asks to download. Tap <b>Download</b>."),
                 ("c3", "open", "Open the download", "Tap the <b>arrow</b> in Safari's address bar, then tap "
                                                     "<b>Magpiary.shortcut</b>."),
                 ("c4", "add", "Add Shortcut", "Shortcuts opens. Tap <b>Add Shortcut</b>."))
        cards = "".join(f'<li class="in" style="--i:{n + 5}" data-step="{n}"><div class="ic {c}">{icon(i)}</div><div><h3>{h}'
                        f'</h3><p>{t}</p></div><span class="num">{n}/4</span></li>' for n, (c, i, h, t) in enumerate(steps, 1))
        check = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" ' \
                'stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
        return phone_page("Install", f"""<div class="brand in">{ui.logo_mark()}magpiary</div>
<h1 class="in" style="--i:1">Save posts to <em>your Mac.</em></h1>
<p class="sub in" style="--i:2">Add the Magpiary Shortcut to this iPhone. It's already set up for <b>{e(record.phone)}</b> and your Mac.</p>
<a class="get in" style="--i:3" id="get" href="{link}"><span class="spin"></span>{icon("down")}<span id="getl">Get the Shortcut</span></a>
<div class="timer in" style="--i:4" id="timer"><i></i>This link works for {minutes} more minute{"s" if minutes != 1 else ""}</div>
<div class="sect in" style="--i:5">Then, in 4 taps</div>
<ol class="cards">{cards}</ol>
<div class="note in" style="--i:10"><h3>One last thing</h3>Open the <b>Shortcuts</b> app, tap the Magpiary tile once and tap
<b>Allow</b> on every question. Never dismiss one: a dismissed question blocks Magpiary until it's fixed in Shortcuts' settings.</div>
<p class="foot">This page comes from your Mac over your home Wi-Fi. Nothing goes through a server.
Local HTTP is unencrypted: pair and send only on trusted Wi-Fi.</p>
<template id="tick">{check}</template>
<script>
(() => {{
  // Get the Shortcut: Apple signs it first, which takes a few seconds, so the button spins until the Mac says it went out
  const get = document.getElementById("get"), label = document.getElementById("getl"), token = {json.dumps(token)};
  let timer = 0, waited = 0;
  const step = (n, cls) => document.querySelector(`[data-step="${{n}}"]`)?.classList.add(cls);
  const ready = () => {{
    clearInterval(timer); get.classList.remove("busy"); get.classList.add("ready");
    get.querySelector("svg").outerHTML = document.getElementById("tick").innerHTML;
    label.textContent = "Ready: tap Download";
    step(1, "done"); step(2, "next");
    setTimeout(() => {{ document.querySelector('[data-step="2"]')?.classList.replace("next", "done"); step(3, "next");
      label.textContent = "Shortcut ready"; }}, 5000);
  }};
  get.addEventListener("click", () => {{
    if (get.classList.contains("ready")) return;
    get.classList.add("busy"); label.textContent = "Getting it ready…"; waited = 0;
    clearInterval(timer);
    timer = setInterval(async () => {{
      waited += 700;
      try {{
        const r = await fetch("/install/state?t=" + encodeURIComponent(token), {{ cache: "no-store" }});
        if (r.ok && (await r.json()).ready) return ready();
      }} catch (_) {{ /* asked again next round */ }}
      if (waited > 30000) {{ clearInterval(timer); get.classList.remove("busy"); label.textContent = "Try again"; }}
    }}, 700);
  }});
}})();
</script>""")
