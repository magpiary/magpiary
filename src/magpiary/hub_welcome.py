"""The first run (M7a, C1+), mixed into Hub: a full-screen guide from a fresh install to the first share arriving,
in four steps that keep everything learned on a real iPhone (docs/onboarding-notes.md):

1. Pair your iPhone: Safari downloads on the phone, the QR code and the Share shortcut, the "allow" prompts.
2. Make it automatic: the "join home Wi-Fi" automation and keeping this Mac ready.
3. Choose Smart (your AI key) or Private (no AI).
4. Share something: checked live; a pasted link works too.

The library sends the owner here until a phone is paired (or the guide is finished). Steps tick themselves where
Magpiary can see them. The guide can be opened again from Settings.
"""

import json

from magpiary import keys as keyring
from magpiary import modes, ui
from magpiary.web import Response, e

DONE_SETTING = "setup_done"
STEPS = (("phone", "Pair your iPhone"), ("automatic", "Make it automatic"), ("reading", "How posts are read"),
         ("share", "First share"))


class WelcomePages:
    """Needs Hub's store, csrf, shell, _form and setup; `keep_awake` is set by the service when it has one."""

    def needs_welcome(self) -> bool:
        return self.store.get_setting(DONE_SETTING) != "1" and not self._phones()

    def _phones(self) -> list[dict]:
        return [p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]

    def _welcome_state(self) -> dict:
        mode = self.store.get_setting(modes.SETTING, "")
        has_key = any(keyring.PROVIDERS[k.provider]["kind"] == "ai" for k in keyring.load())
        return {"phones": self._phones(), "delivered": bool(self.store.last_delivery()),
                "awake": getattr(getattr(self, "keep_awake", None), "running", False),
                "chosen": mode == "private" or (mode in ("smart", "") and has_key), "mode": modes.current(self.store),
                "has_key": has_key}

    def welcome_json(self) -> Response:
        s = self._welcome_state()
        data = {"phones": len(s["phones"]), "delivered": s["delivered"]}
        return Response(200, json.dumps(data).encode(), "application/json", {"Cache-Control": "no-store"})

    def _wtop(self, cur: str, s: dict) -> str:
        done = {"phone": bool(s["phones"]), "automatic": s["delivered"] or s["awake"], "reading": s["chosen"],
                "share": s["delivered"]}
        prog = "".join(f'<a href="/welcome/{k}" class="{"on" if k == cur else "done" if done[k] else ""}"'
                       f'{" aria-current=step" if k == cur else ""}><i>{"✓" if done[k] and k != cur else n}</i><b>{e(label)}</b></a>'
                       for n, (k, label) in enumerate(STEPS, 1))
        skip = '<a class="w-skip" href="/">Go to my library →</a>' if s["phones"] else '<span class="w-skip"></span>'
        return f'<div class="w-top"><a class="logo" href="/welcome">{ui.logo_mark()}magpiary</a><nav class="w-prog" aria-label="Setup steps">{prog}</nav>{skip}</div>'

    def welcome_page(self, step: str, q: dict) -> Response:
        s = self._welcome_state()
        pages = {"": self._hello, "phone": self._w_phone, "automatic": self._w_auto, "reading": self._w_reading,
                 "share": self._w_share}
        if step not in pages:
            step = ""
        error = q.get("error", "")[:200]
        flash = f'<div class="flash err">{e(error)}</div>' if error else ""
        inner = pages[step](s, q, flash)
        top = (self._wtop(step, s) if step else
               '<div class="w-top"><span class="logo">' + ui.logo_mark() + 'magpiary</span></div>')
        return self.shell("Welcome", f'<div class="wel">{top}{inner}</div>', "welcome", bare=True)

    def _ws(self, n, state: str, title: str, body: str, badge: str = "", ident: str = "") -> str:
        mark = "✓" if state == "ok" else n
        tid = f' id="{ident}"' if ident else ""
        return (f'<div class="ws {state}"{tid}><span class="n">{mark}</span><div><b>{title}</b>{body}</div>'
                + (f'<span class="st">{badge}</span>' if badge else "<span></span>") + "</div>")

    def _hello(self, s: dict, q: dict, flash: str) -> str:
        return ('<div class="w-body"><div><div class="w-kick">Welcome</div>'
                '<h1 class="w-h">Everything you save, <em>finally useful.</em></h1>'
                '<p class="w-p">Share a reel or post from your iPhone. Your Mac downloads it, listens to it, and files it '
                'where you can search it by what was said, shown or written.</p><div class="priv">'
                '<div><span style="background:color-mix(in srgb,var(--t-howto) 15%,transparent)">🖥</span><div><b>Runs on this '
                'Mac</b><small>No Magpiary account, no Magpiary server. Your library is one folder you own.</small></div></div>'
                '<div><span style="background:color-mix(in srgb,var(--t-design) 15%,transparent)">📶</span><div><b>Your phone '
                'only talks to this Mac</b><small>Shares wait on the phone and arrive when it\'s on Wi-Fi with this Mac.</small>'
                '</div></div><div><span style="background:color-mix(in srgb,var(--t-explainer) 15%,transparent)">🔑</span><div>'
                '<b>Videos never leave</b><small>Only the caption, transcript and a few frames go to your own AI key, or '
                'nothing at all in Private.</small></div></div></div>'
                '<div class="w-cta"><a class="btn dark" href="/welcome/phone">Set up · 4 steps, about 5 minutes</a></div></div>'
                + self._demo() + "</div>")

    def _demo(self) -> str:
        """Share → your Mac reads it → find it any time, looping; uses your newest save when there is one."""
        pick = next((i for i in self.store.hub_items("inbox", limit=30) if self.thumb_url(i) and i.get("ai_status") == "done"),
                    None) or next((i for i in self.store.hub_items("inbox", limit=30) if self.thumb_url(i)), None)
        bg = f"url({self.thumb_url(pick)})" if pick else "linear-gradient(160deg,#ff2e93,#2f6bff)"
        title = ui.title_of(pick) if pick else "Ten things to do before 1,000 users"
        summary = (pick or {}).get("summary") or "Summaries, key moments and the links a post mentions, ready when you are."
        kind = ui.type_name(pick.get("ai_type")) if pick and pick.get("ai_status") == "done" else "How-to"
        colour = ui.type_colour(pick.get("ai_type")) if pick and pick.get("ai_status") == "done" else "var(--t-howto)"
        apps = ('<div class="share"><div class="apps"><div class="ap"><i style="background:#25d366"></i>WhatsApp</div>'
                '<div class="ap mg"><i></i>Magpiary</div><div class="ap"><i style="background:#0a84ff"></i>Messages</div>'
                '<div class="ap"><i style="background:#ffcc00"></i>Notes</div></div></div>')
        return (f'<div><div class="demo" id="demo" data-f="0" style="--demo-bg:{e(bg)}">'
                f'<div class="fr0"><div class="iph"><div class="scr">{apps}</div></div></div>'
                f'<div class="fr1"><div class="mini-tile"><div class="sq"></div><div class="lbl">{e(title[:70])}</div>'
                f'<div class="stp"><div><i></i>Fetch</div><div><i></i>Listen</div><div><i></i>Look</div><div><i></i>Write</div></div></div></div>'
                f'<div class="fr2"><div class="res-card"><div class="v"></div><div class="in"><b class="ty" style="background:{colour}">'
                f'{e(kind)}</b><h4>{e(title[:70])}</h4><p>{e(summary[:180])}</p></div></div></div></div>'
                f'<div class="demo-cap" id="dcap"><span class="on">1 · Share</span><span>2 · Your Mac reads it</span>'
                f'<span>3 · Find it any time</span></div></div>')

    def _w_phone(self, s: dict, q: dict, flash: str) -> str:
        paired = ", ".join(p["name"] for p in s["phones"])
        steps = (self._ws(1, "", "Get your iPhone ready", "<small>On the iPhone open <b>Settings → Safari → Downloads</b> "
                          "and choose <b>On My iPhone</b> (a full iCloud Drive stops the Shortcut installing). Join your home "
                          "Wi-Fi.</small>")
                 + self._ws(2, "ok" if s["phones"] else "wait", "Scan the code and add the Shortcut",
                            "<small>Point the iPhone Camera at the code, tap the banner, then <b>Get “Magpiary”</b> → "
                            "<b>Download</b>. Open the download from Safari's address bar and tap <b>Add Shortcut</b>.</small>",
                            f"✓ Paired: {e(paired)}" if s["phones"] else "Waiting…")
                 + self._ws(3, "ok" if s["delivered"] else "", "Allow everything once",
                            "<small>Open the <b>Shortcuts</b> app and tap the Magpiary tile once. Tap <b>Allow</b> or <b>Always "
                            "Allow</b> on every question. Never dismiss one: a dismissed question blocks Magpiary until it is "
                            "fixed in Shortcuts' privacy settings. Expect a few more questions the first time you share from each app (Instagram, then "
                            "YouTube and others): tap <b>Always Allow</b> each time. After that it stays quiet.</small>", "✓ Done" if s["delivered"] else "Next"))
        qr, dialog = "", ""
        if self.setup:
            self.setup.check_signing()  # in the background: ready by the time a name is typed
            state = self.setup.signing_state()
            if state in ("icloud", "error"):
                flash += ('<div class="flash err"><b>iCloud isn\'t ready on this Mac.</b> Apple signs the Shortcut through iCloud. Open <b>System Settings</b>, '
                          'click your name, choose <b>iCloud</b>, turn on <b>iCloud Drive</b>, open the <b>Shortcuts</b> app once, then reload this page.</div>' if state == "icloud" else
                          '<div class="flash err"><b>Apple\'s Shortcut signing isn\'t answering.</b> Check this Mac is online (and not on a VPN) '
                          'and signed in to iCloud in System Settings, then reload this page.</div>')
        if q.get("qr") and self.setup:
            dialog = self._qr_block(q["qr"], q.get("phone", ""), "/welcome/phone")
        if self.setup:
            qr = (f'<div class="qrbox"><form method="post" action="/hub/phones/add">{ui.hidden(self.csrf, next="/welcome/phone")}'
                  f'<b>{"Pair another phone" if s["phones"] else "Your iPhone"}</b>'
                  f'<label>Name for this phone<input type="text" name="name" required maxlength="60" placeholder="Like “My iPhone”"></label>'
                  f'<small>The phone sends on any Wi-Fi your Mac is on.</small>'
                  f'{self.phone_advanced()}'
                  f'<button class="btn" type="submit">Show the QR code</button></form></div>')
        else:
            qr = '<div class="qrbox"><b>Pairing runs with the background service</b><small>Start it with <code>magpiary service install</code>.</small></div>'
        return (f'<div class="w-body"><div><div class="w-kick">Step 1 of 4</div><h1 class="w-h">Pair your <em>iPhone.</em></h1>'
                f'<p class="w-p">A few taps on the phone, once. These tick themselves off as Magpiary sees them happen.</p>{flash}'
                f'<div class="wsteps">{steps}</div><div class="why1"><b>Why “when I get home”?</b> Your phone never talks to the '
                f'internet for Magpiary. It keeps what you share while you\'re out and hands it to this Mac over Wi-Fi.</div>'
                f'<div class="w-cta"><a class="btn dark" href="/welcome/automatic"{"" if s["phones"] else " aria-disabled=true"}>Continue</a>'
                f'<a class="btn" style="background:none" href="/welcome/automatic">Skip for now</a></div></div><div>{qr}</div>{dialog}</div>')

    def _w_auto(self, s: dict, q: dict, flash: str) -> str:
        awake = s["awake"]
        toggle = ui.button_form(self.csrf, "/hub/awake", {"enabled": "0" if awake else "1", "next": "/welcome/automatic"},
                                f'<span class="tg{"" if awake else " off"}" style="margin:0"></span> Keep this Mac awake while '
                                f'plugged in: {"on" if awake else "off"}', "btn")
        steps = (self._ws(1, "ok" if s["delivered"] else "", "Send when I get home",
                          "<ol><li>In Shortcuts open <b>Automation</b> → <b>+</b> → <b>Wi-Fi</b>.</li><li>Choose your home "
                          "network and tick <b>Is Joined</b> only.</li><li>Pick <b>Run Immediately</b>.</li><li>Add the action "
                          "<b>Run Shortcut → Magpiary</b>.</li><li>Switch <b>Notify When Run</b> off.</li></ol><small>iPhones don't "
                          "let a program create this part, so it's done by hand once. Shares made away from home then arrive "
                          "by themselves when you get back.</small>")
                 + self._ws(2, "ok" if awake else "", "Keep this Mac ready",
                            f"<small>A sleeping Mac can't receive shares (nothing is lost; they wait on the phone). If the "
                            f"firewall asks whether Magpiary may accept incoming connections, choose <b>Allow</b>. Optional: "
                            f"System Settings → Battery → Options → <b>Wake for network access</b>.</small>"
                            f'<div style="margin-top:10px">{toggle}</div>'))
        return (f'<div class="w-body one"><div><div class="w-kick">Step 2 of 4</div><h1 class="w-h">Make it <em>automatic.</em></h1>'
                f'<p class="w-p">So you never have to think about it: shares go to this Mac whenever the phone gets home.</p>{flash}'
                f'<div class="wsteps">{steps}</div><div class="w-cta"><a class="btn dark" href="/welcome/reading">Continue</a>'
                f'<a class="btn" style="background:none" href="/welcome/phone">← Back</a></div></div></div>')

    def _w_reading(self, s: dict, q: dict, flash: str) -> str:
        mode = s["mode"] if s["chosen"] or self.store.get_setting(modes.SETTING, "") else ""
        leaves = {"smart": ["Sent to your AI: caption, transcript, a few frames", "The video file stays on your Mac", "~20 s a post"],
                  "private": ["Sent to any AI: nothing", "No summaries"]}
        presets = "".join(
            f'<form method="post" action="/hub/settings/mode">{ui.hidden(self.csrf, mode=m, next="/welcome/reading")}'
            f'<button type="submit" class="wp{" on" if m == mode else ""}" aria-pressed="{str(m == mode).lower()}">'
            f'<span class="rd"></span><span><b>{e(name)}{"<em>Recommended</em>" if m == "smart" else ""}</b><p>{e(text)}</p>'
            f'<span class="leaves">{"".join(f"<span>{e(x)}</span>" for x in leaves[m])}</span></span></button></form>'
            for m, (name, text) in modes.MODES.items())
        if mode == "private":
            side = ('<div class="keybox"><h3>No key needed</h3><p class="small" style="margin:0;color:var(--fg-2)">Saves are '
                    'downloaded, transcribed on this Mac, grouped into piles and searchable by caption and by what was said. '
                    'Switch to Smart any time in Settings to have summaries written.</p></div>')
        else:
            keys = [k for k in keyring.load() if keyring.PROVIDERS[k.provider]["kind"] == "ai"]
            have = "".join(f'<div class="key" style="background:var(--bg)"><span class="ord">✓</span><div><b>{e(k.name)}</b>'
                           f'<small>{e(keyring.PROVIDERS[k.provider]["name"].split(" (")[0])}</small></div></div>' for k in keys)
            options = "".join(f'<option value="{p}">{e(v["name"])}</option>' for p, v in keyring.PROVIDERS.items() if v["kind"] == "ai")
            guides = self._key_guides({p: v for p, v in keyring.PROVIDERS.items() if v["kind"] == "ai"})
            side = (f'<div class="keybox"><h3>{"Your AI keys" if keys else "Paste your AI key"}</h3>{have}'
                    f'<form method="post" action="/hub/keys/add" autocomplete="off">{ui.hidden(self.csrf, next="/welcome/reading", tier="free")}'
                    f'<div class="form" style="grid-template-columns:1fr"><select name="provider" id="provider" aria-label="Provider">{options}</select>'
                    f'<input type="password" name="key" placeholder="{"Add another key" if keys else "Paste the key"}" required aria-label="Key"></div>'
                    f'<div style="margin-top:10px">{guides}</div>'
                    f'<div class="row" style="margin-top:12px"><button class="btn dark" type="submit">Check and save</button></div></form>'
                    f'<p class="note2">Stored only on this Mac (~/.config/magpiary, owner-only) and never shown again. With a free '
                    f'Gemini key, Google may use what is sent to improve its products.</p></div>')
        ready = s["chosen"]
        return (f'<div class="w-body"><div><div class="w-kick">Step 3 of 4</div><h1 class="w-h">How should posts be <em>read?</em></h1>'
                f'<p class="w-p">Smart sends the caption, the transcript and a few frames to the AI you choose. The video file stays on your Mac. Private sends nothing to any AI. You can change this any time in Settings.</p>{flash}'
                f'<div class="wpre">{presets}</div><div class="w-cta"><a class="btn dark" href="/welcome/share"'
                f'{"" if ready else " aria-disabled=true"}>Continue</a>'
                f'<small>{"" if ready else "Choose Private, or add a key for Smart, to continue."}</small></div></div>'
                f'<div>{side}</div></div>')

    def _w_share(self, s: dict, q: dict, flash: str) -> str:
        finish = (self._form("/hub/welcome/done", {"next": "/"}, "Open my library", "btn dark") if s["phones"] and s["chosen"]
                  else '<small>Pair a phone and choose Smart or Private to finish. Your library opens after that.</small>')
        listen = ('<div class="listen ok" id="listen"><i></i>Arrived! Your phone and this Mac are talking.</div>' if s["delivered"]
                  else '<div class="listen" id="listen" data-listen><i></i>Listening for your iPhone on Wi-Fi…</div>')
        newest = self.store.hub_items("inbox", limit=1)
        arrived = ""
        if newest:
            it = newest[0]
            thumb = self.thumb_url(it)
            arrived = (f'<div class="big-tile"><div class="sq" style="background:{ui.gradient(it)}">'
                       + (f'<img src="{e(thumb)}" alt="">' if thumb else "") + f'</div><div class="label" style="background:'
                       f'{ui.type_colour(it.get("ai_type")) if it.get("ai_status") == "done" else ui.source_colour(it["source"])}">'
                       f'<div class="t">{e(ui.title_of(it))}</div><div class="m"><span>{e(ui.source_name(it["source"]))}</span></div></div></div>')
        return (f'<div class="w-body"><div><div class="w-kick">Step 4 of 4</div><h1 class="w-h">Now share <em>something.</em></h1>'
                f'<p class="w-p">On your iPhone, open any reel or post you like, tap <b>Share</b>, then <b>Magpiary</b>. Your '
                f'iPhone asks for permission separately for each kind of thing you share, so the first share from each app '
                f'(Instagram, then YouTube and others) can ask a few questions again: tap <b>Always Allow</b> every time, and '
                f'never dismiss one. After that it stays quiet. If the share sheet pauses for a few seconds, wait.</p>{flash}{listen}'
                f'<p class="small muted" style="margin:0 0 8px">No phone handy? Paste a link instead:</p>'
                f'<form method="post" action="/hub/add" class="orpaste">{ui.hidden(self.csrf, next="/welcome/share")}'
                f'<input type="url" name="url" placeholder="https://www.instagram.com/reel/…" required aria-label="Link to a post">'
                f'<button class="btn dark" type="submit">Add</button></form><div class="w-cta">{finish}</div>'
                f'<p class="small muted" style="margin:18px 0 0">Optional: <a class="link" href="/settings/privacy#lock">lock your library '
                f'with a PIN or Touch ID</a>. You can do this any time in Settings.</p></div>'
                f'<div>{arrived}</div></div>')

    def welcome_post(self, path: str, form: dict) -> bool:
        if path == "/hub/welcome/done":
            s = self._welcome_state()
            if s["phones"] and s["chosen"]:
                self.store.set_setting(DONE_SETTING, "1")
        elif path == "/hub/welcome/no-ai":
            self.store.set_setting(modes.SETTING, "private")
        else:
            return False
        return True
