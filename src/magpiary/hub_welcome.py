"""The first run (M7a, C1+, reworked for 0.1.4), mixed into Hub: a full-screen guide from a fresh install to the first save,
every screen skippable:

0. Hello.
1. How posts are read: Smart (your AI key) or Private (no AI).
2. Save from this Mac: the Chrome extension, from the Chrome Web Store (adding it by hand stays as a fold).
3. Add your iPhone (optional): one card, QR code, Shortcut, "allow everything once"; says plainly when iCloud is off.
4. First save: from Chrome, the phone or a pasted link, checked live.

Steps tick themselves where Magpiary can see them (the open page polls /welcome.json and reloads when a step ticks).
"Send when I get home" and "Keep this Mac awake" live in Settings. The guide can be opened again from Settings.
"""

import json

from magpiary import keys as keyring
from magpiary import modes, ui
from magpiary.web import Response, e

DONE_SETTING = "setup_done"
STEPS = (("reading", "Reading"), ("browser", "Browser"), ("phone", "iPhone"), ("share", "First save"))


CHROME_STORE = "https://chromewebstore.google.com/detail/magpiary/elfmjdafgmbmfkpanlbfdpcoihmikgah"  # live 4 Nov 2026

class WelcomePages:
    """Needs Hub's store, csrf, shell, _form and setup; `keep_awake` is set by the service when it has one."""

    def needs_welcome(self) -> bool:
        return (self.store.get_setting(DONE_SETTING) != "1" and not self._phones()
                and not self.store.extension_status()["paired"])

    def _phones(self) -> list[dict]:
        return [p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]

    def _welcome_state(self) -> dict:
        mode = self.store.get_setting(modes.SETTING, "")
        has_key = any(keyring.PROVIDERS[k.provider]["kind"] == "ai" for k in keyring.load())
        phones = self._phones()
        kinds = self.store.delivered_kinds()
        ext = self.store.extension_status()
        ext["pinned"] = ext["pinned"] or self.store.get_setting("ext_pinned_manual") == "1"
        return {"phones": phones, "delivered": bool(self.store.last_delivery()), "ext": ext,
                "fetched": bool(self.store.get_setting("shortcut_fetched_at")),
                "contact": any(p.get("first_seen_at") for p in phones), "phone_saved": "phone" in kinds,
                "chrome_saved": "browser" in kinds,
                "chosen": mode == "private" or (mode in ("smart", "") and has_key), "mode": modes.current(self.store),
                "has_key": has_key}

    @staticmethod
    def _sig(s: dict) -> str:
        """Changes whenever a step ticks, so the open page can reload itself (see hub.js, data-wsig)."""
        e_ = s["ext"]
        return "".join("1" if x else "0" for x in (s["chosen"], e_["added"], e_["pinned"], e_["paired"], s["chrome_saved"],
                                                   bool(s["phones"]), s["fetched"], s["contact"], s["phone_saved"], s["delivered"]))

    def welcome_json(self) -> Response:
        s = self._welcome_state()
        data = {"phones": len(s["phones"]), "delivered": s["delivered"], "sig": self._sig(s)}
        return Response(200, json.dumps(data).encode(), "application/json", {"Cache-Control": "no-store"})

    def _wtop(self, cur: str, s: dict) -> str:
        done = {"reading": s["chosen"], "browser": s["ext"]["paired"], "phone": s["phone_saved"] or s["contact"],
                "share": s["delivered"]}
        prog = "".join(f'<a href="/welcome/{k}" class="{"on" if k == cur else "done" if done[k] else ""}"'
                       f'{" aria-current=step" if k == cur else ""}><i>{"✓" if done[k] and k != cur else n}</i><b>{e(label)}</b></a>'
                       for n, (k, label) in enumerate(STEPS, 1))
        skip = self._form("/hub/welcome/done", {"next": "/"}, "Go to my library →", "w-skip")
        return f'<div class="w-top"><a class="logo" href="/welcome">{ui.logo_mark()}magpiary</a><nav class="w-prog" aria-label="Setup steps">{prog}</nav>{skip}</div>'

    def welcome_page(self, step: str, q: dict) -> Response:
        s = self._welcome_state()
        pages = {"": self._hello, "reading": self._w_reading, "browser": self._w_browser, "phone": self._w_phone,
                 "share": self._w_share}
        if step not in pages:
            step = ""
        error = q.get("error", "")[:200]
        flash = f'<div class="flash err">{e(error)}</div>' if error else ""
        inner = pages[step](s, q, flash)
        top = (self._wtop(step, s) if step else
               '<div class="w-top"><span class="logo">' + ui.logo_mark() + 'magpiary</span></div>')
        return self.shell("Welcome", f'<div class="wel" data-wsig="{self._sig(s)}">{top}{inner}</div>', "welcome", bare=True)

    def _ws(self, n, state: str, title: str, body: str, badge: str = "", ident: str = "") -> str:
        mark = "✓" if state == "ok" else n
        tid = f' id="{ident}"' if ident else ""
        return (f'<div class="ws {state}"{tid}><span class="n">{mark}</span><div><b class="t">{title}</b>{body}</div>'
                + (f'<span class="st">{badge}</span>' if badge else "<span></span>") + "</div>")

    def _hello(self, s: dict, q: dict, flash: str) -> str:
        return ('<div class="w-body"><div><div class="w-kick">Welcome</div>'
                '<h1 class="w-h">Everything you save, <em>finally useful.</em></h1>'
                '<p class="w-p">Save from your Mac\'s browser or your iPhone. Your Mac downloads it, listens to it, and files it '
                'where you can search it by what was said, shown or written.</p><div class="priv">'
                '<div><span style="background:color-mix(in srgb,var(--t-howto) 15%,transparent)">🖥</span><div><b>Runs on this '
                'Mac</b><small>No Magpiary account, no Magpiary server. Your library is one folder you own.</small></div></div>'
                '<div><span style="background:color-mix(in srgb,var(--t-design) 15%,transparent)">➜</span><div><b>Saves only travel '
                'to this Mac</b><small>From Chrome or your iPhone, straight to your own Mac.</small>'
                '</div></div><div><span style="background:color-mix(in srgb,var(--t-explainer) 15%,transparent)">🔑</span><div>'
                '<b>Videos never leave</b><small>Only the caption, transcript and a few frames go to your own AI key, or '
                'nothing at all in Private.</small></div></div></div>'
                '<div class="w-cta"><a class="btn next" href="/welcome/reading">Get started → <span>(About 2 minutes)</span></a>'
                + self._form("/hub/welcome/done", {"next": "/"}, "Skip, go to my library", "w-link") + '</div></div>'
                + self._sample() + "</div>")

    def _wtile(self, it: dict | None, line: str) -> str:
        """A post as a simple card: its picture, then its title and one line (the approved Welcome preview, 3 Nov 2026)."""
        thumb = self.thumb_url(it) if it else ""
        title = ui.title_of(it) if it else "Ten things to do before 1,000 users"
        return (f'<div class="wtile"><div class="sq" style="background:{ui.gradient(it) if it else "linear-gradient(160deg,#ff2e93,#2f6bff)"}">'
                + (f'<img src="{e(thumb)}" alt="">' if thumb else "")
                + f'</div><div class="lb"><b>{e(title[:90])}</b><small>{e(line)}</small></div></div>')

    def _sample(self) -> str:
        """Hello's right column: your newest finished save as a card, or a sample one on a fresh install."""
        items = self.store.hub_items("inbox", limit=30)
        pick = next((i for i in items if self.thumb_url(i) and i.get("ai_status") == "done" and i.get("summary")), None)
        line = (pick or {}).get("summary") or "Summaries, key moments and the links a post mentions, ready when you are."
        return f'<div class="art">{self._wtile(pick, line[:160])}</div>'

    def _w_reading(self, s: dict, q: dict, flash: str) -> str:
        mode = s["mode"] if s["chosen"] or self.store.get_setting(modes.SETTING, "") else ""
        leaves = {"smart": ["Sent to your AI: caption, transcript, a few frames", "The video stays on your Mac"],
                  "private": ["Sent to any AI: nothing", "No summaries"]}
        presets = "".join(
            f'<form method="post" action="/hub/settings/mode">{ui.hidden(self.csrf, mode=m, next="/welcome/reading")}'
            f'<button type="submit" class="wp{" on" if m == mode else ""}{" hero" if m == "smart" else ""}" aria-pressed="{str(m == mode).lower()}">'
            f'<span class="rd"></span><span><b>{e(name)}{"<em>Recommended</em>" if m == "smart" else ""}</b><p>{e(text)}</p>'
            f'<span class="leaves">{"".join(f"<span>{e(x)}</span>" for x in leaves[m])}</span></span></button></form>'
            for m, (name, text) in modes.MODES.items())
        if mode == "private":
            side = ('<div class="keybox"><h3>No key needed</h3><p class="small" style="margin:0;color:var(--fg-2)">Saves are '
                    'downloaded, transcribed on this Mac, grouped into piles and searchable by caption and by what was said. '
                    'Switch to Smart any time in Settings to have summaries written.</p></div>')
        elif mode == "smart":
            ai = {p: v for p, v in keyring.PROVIDERS.items() if v["kind"] == "ai"}
            keys = [k for k in keyring.load() if keyring.PROVIDERS[k.provider]["kind"] == "ai"]
            have = "".join(f'<div class="key" style="background:var(--bg)"><span class="ord">✓</span><div><b>{e(k.name)}</b>'
                           f'<small>{e(keyring.PROVIDERS[k.provider]["name"].split(" (")[0])}</small></div></div>' for k in keys)
            first = next(iter(ai))
            options = "".join(f'<li role="option" id="opt-{p}" data-v="{p}" aria-selected="{str(p == first).lower()}"><span>'
                              f'<b>{e(v["name"].split(" (")[0])}</b><small>{e(self.GUIDE_CHIP.get(p, ""))}</small></span>'
                              f'<i aria-hidden="true">✓</i></li>' for p, v in ai.items())
            picker = (f'<div class="dd" id="prov"><input type="hidden" name="provider" value="{first}">'
                      f'<button type="button" class="dd-btn" id="provbtn" role="combobox" aria-haspopup="listbox" aria-expanded="false" '
                      f'aria-controls="provlist" aria-label="Provider"><span>{e(ai[first]["name"])}</span>{ui.icon("chev")}</button>'
                      f'<ul class="dd-list" id="provlist" role="listbox" aria-label="Provider" tabindex="-1" hidden>{options}</ul></div>')
            guides = self._key_guides(ai)
            side = (f'<div class="keybox"><h3>{"Your AI keys" if keys else "Paste your AI key"}</h3>{have}'
                    f'<form method="post" action="/hub/keys/add" autocomplete="off">{ui.hidden(self.csrf, next="/welcome/reading", tier="free")}'
                    f'<div class="field"><label>Provider</label>{picker}</div>'
                    f'<div class="field"><label for="wkey">Key</label><input id="wkey" type="password" name="key" '
                    f'placeholder="{"Add another key" if keys else "Paste the key"}" required></div>'
                    f'<button class="btn dark sm" type="submit">Check and save</button>'
                    f'<button class="helpbtn" type="button" aria-expanded="false" aria-controls="guidewrap" data-helpbtn>Need help getting a key? {ui.icon("chev")}</button>'
                    f'<div id="guidewrap" hidden>{guides}</div></form>'
                    f'<p class="note2">Stored only on this Mac (~/.config/magpiary, owner-only) and never shown again. With a free '
                    f'Gemini key, Google may use what is sent to improve its products.</p></div>')
        else:
            side = ('<div class="keybox"><h3>Choose one to continue</h3><p class="small" style="margin:0;color:var(--fg-2)">Smart writes '
                    'summaries with an AI key you provide. Private uses no AI at all. You can change this any time in Settings.</p></div>')
        ready = s["chosen"]
        decide = self._form("/hub/welcome/no-ai", {"next": "/welcome/browser"}, "Decide later", "w-link")
        return (f'<div class="w-body"><div><div class="w-kick">Step 1 of 3</div><h1 class="w-h">How should posts be <em>read?</em></h1>'
                f'<p class="w-p">Smart sends the caption, the transcript and a few frames to the AI you choose. The video file stays on your Mac. Private sends nothing to any AI.</p>{flash}'
                f'<div class="wpre">{presets}</div><div class="w-cta"><a class="btn next" href="/welcome/browser"'
                f'{"" if ready else " aria-disabled=true"}>Continue →</a>{"" if ready else decide}'
                f'<small>{"" if ready else "Deciding later chooses Private for now."}</small></div></div>'
                f'<div>{side}</div></div>')

    def _w_browser(self, s: dict, q: dict, flash: str) -> str:
        x = s["ext"]
        code = q.get("chromecode", "")
        code = code if len(code) == 14 and all(ch.isalnum() or ch == "-" for ch in code) else ""
        back = {"next": "/welcome/browser"}
        hand = (f'<small>Free from the Chrome Web Store. Press <b>Add to Chrome</b> there, then come back here.</small>'
                f'<div style="margin-top:8px"><a class="btn sm dark" href="{CHROME_STORE}" target="_blank" rel="noopener">'
                f'{ui.icon("ext")}Get it from the Chrome Web Store</a></div>'
                '<details class="handadd"><summary>Or add it by hand</summary>'
                '<ol class="mini"><li><span>a</span><div>Open Chrome\'s extensions page. Copy the address, paste it into Chrome\'s '
                'address bar and press Enter.<div class="inl"><code>chrome://extensions</code><button type="button" class="btn sm" '
                'data-copycode="chrome://extensions" data-copywhat="Address">Copy</button></div></div></li>'
                '<li><span>b</span><div>Turn on <b>Developer mode</b>, the switch at the top right of that page.</div></li>'
                '<li><span>c</span><div>Click <b>Load unpacked</b>, then choose the <b>chrome-extension</b> folder inside Magpiary.'
                f'<div class="inl">{self._form("/hub/extension/get", back, "Show the folder", "btn sm")}</div></div></li></ol></details>')
        pin_btn = ("" if x["pinned"] or not x["added"] else
                   f'<div style="margin-top:8px">{self._form("/hub/welcome/pinned", back, "I\'ve pinned it", "btn sm")}</div>')
        if x["paired"]:
            connect_body, connect_badge = "<small>The extension and this Mac are talking.</small>", "✓ Chrome connected"
        elif code:
            connect_body = ('<small>Open the extension and paste this code. It works once and runs out in 15 minutes.</small>'
                            f'<span class="code"><b>{e(code)}</b><button type="button" class="btn sm" data-copycode="{e(code)}" '
                            f'data-copywhat="Code">Copy</button></span>')
            connect_badge = "Waiting…"
        else:
            connect_body = ('<small>Click the Magpiary button in Chrome\'s toolbar. It asks for a one-time code.</small>'
                            f'<div style="margin-top:8px">{self._form("/hub/browsers/add", back, "Show my code", "btn sm")}</div>')
            connect_badge = "Next" if x["added"] else ""
        rows = (self._ws(1, "ok" if x["added"] else "wait", "Add the extension to Chrome", hand, "✓ Added" if x["added"] else "Next")
                + self._ws(2, "ok" if x["pinned"] else "wait" if x["added"] else "", "Pin it",
                           "<small>Click the puzzle-piece icon in Chrome's toolbar, then the pin beside Magpiary, so the button stays "
                           "in sight.</small>" + pin_btn, "✓ Pinned" if x["pinned"] else "Next" if x["added"] else "")
                + self._ws(3, "ok" if x["paired"] else "wait" if x["added"] else "", "Connect it", connect_body, connect_badge)
                + self._ws(4, "ok" if s["chrome_saved"] else "wait" if x["paired"] else "", "Try it",
                           "<small>Open any page and click the Magpiary button. This screen tells you when the save arrives.</small>",
                           "✓ Saved" if s["chrome_saved"] else "Waiting…" if x["paired"] else ""))
        art = ('<div class="art"><div class="chrome"><div class="bar"><span class="dots"><i></i><i></i><i></i></span>'
               '<span class="url">example.com/article</span><span class="tbtn">⋯</span><span class="tbtn me">' + ui.logo_mark() +
               '</span></div><div class="pg"><i style="width:70%"></i><i></i><i style="width:90%"></i><i style="width:55%"></i></div>'
               '<div class="pop"><b>Save to Magpiary</b>' + ('<span class="ok">✓ Saved to your Mac</span>' if s["chrome_saved"] else
               'Page: example.com/article<br><span style="color:#888">Board: none · Note: none</span>') + '</div></div></div>')
        return (f'<div class="w-body"><div><div class="w-kick">Step 2 of 3</div><h1 class="w-h">Save from your <em>Mac.</em></h1>'
                f'<p class="w-p">Add the Magpiary extension to Chrome. One click saves the page you are on, or pick a single post from a feed. It talks only to this Mac.</p>{flash}'
                f'<div class="wsteps">{rows}</div><div class="w-cta"><a class="btn next" href="/welcome/phone">Continue →</a>'
                f'<a class="w-link" href="/welcome/phone">Not using Chrome? Skip</a></div></div>{art}</div>')

    def _w_phone(self, s: dict, q: dict, flash: str) -> str:
        phones = s["phones"]
        state = ""
        if self.setup:
            self.setup.check_signing()  # in the background: ready by the time a name is typed
            state = self.setup.signing_state()
        name = phones[0]["name"] if phones else ""
        if state in ("icloud", "error") and not phones:
            card = ('<div class="card"><h3>Your iPhone</h3><div class="note"><b>' + (
                "Phone setup needs iCloud on this Mac." if state == "icloud" else "Apple's Shortcut signing isn't answering.") + '</b><p>' + (
                "Apple signs the Shortcut through iCloud, and iCloud Drive is off here. Turn it on in System Settings, click your name, "
                "choose iCloud, then turn on iCloud Drive and open the Shortcuts app once. Or skip the phone and use the Chrome extension. "
                "You can add the phone any time in Settings." if state == "icloud" else
                "Check this Mac is online (and not on a VPN) and signed in to iCloud in System Settings. Or skip the phone and use the "
                "Chrome extension. You can add the phone any time in Settings.") + '</p><div class="w-cta" style="margin:0">'
                '<a class="btn dark sm" href="/welcome/share">Skip, I\'ll use Chrome</a>'
                '<a class="btn sm" href="/welcome/phone">I turned it on, check again</a></div></div></div>')
        elif not phones:
            card = ('<div class="card"><h3>Your iPhone</h3>'
                    '<p class="small" style="color:var(--fg-2);margin:0">First, on the iPhone open <b>Settings → Safari → Downloads</b> '
                    'and choose <b>On My iPhone</b> (a full iCloud Drive stops the Shortcut installing), and join your home Wi-Fi.</p>'
                    + (f'<form method="post" action="/hub/phones/add">{ui.hidden(self.csrf, next="/welcome/phone")}'
                       '<div class="field"><label for="nm">Name for this phone</label><input id="nm" type="text" name="name" required '
                       'maxlength="60" placeholder="Like “My iPhone”"><small style="color:var(--fg-2)">The phone sends on any Wi-Fi your Mac is on.</small></div>'
                       f'{self.phone_advanced()}<button class="btn dark sm" type="submit" style="margin-top:12px">Show the QR code</button></form>'
                       if self.setup else '<p class="small">Pairing runs with the background service. Start it with <code>magpiary service install</code>.</p>')
                    + self._ws(2, "fold", "Scan the code and add the Shortcut", "") + self._ws(3, "fold", "Allow everything once", "") + '</div>')
        else:
            qr = ""
            token_url = q.get("qr", "")
            if self.setup and token_url.startswith(f"http://{self.setup.host_name}:") and not s["fetched"]:
                qr = (f'<div class="qr">{self.setup.qr_svg(token_url)}</div><small style="color:var(--fg-3)">Can\'t scan? Send this link to '
                      f'the iPhone and open it there: <code>{e(token_url)}</code></small>'
                      + self._form("/hub/phones/new-code", {"name": name, "next": "/welcome/phone"}, "The code ran out? Make a new one", "btn sm"))
            elif not s["fetched"] and not s["contact"]:
                qr = self._form("/hub/phones/new-code", {"name": name, "next": "/welcome/phone"}, "Show the QR code again", "btn sm")
            got = s["fetched"] or s["contact"]
            add = self._ws(2, "ok" if got else "wait", "Scan the code and add the Shortcut",
                           "<small>On the iPhone, open Camera and point it at the code, tap the banner, then <b>Get “Magpiary”</b> then "
                           "<b>Download</b>. Open the download from Safari's address bar and tap <b>Add Shortcut</b>.</small>",
                           "✓ Shortcut downloaded" if got else "Waiting…")
            allow = self._ws(3, "ok" if s["contact"] or s["phone_saved"] else "wait" if got else "fold", "Allow everything once",
                             "<small>Open the <b>Shortcuts</b> app and tap the Magpiary tile once. Tap <b>Allow</b> or <b>Always Allow</b> on "
                             "every question. Never dismiss one. The first share from each app (Instagram, YouTube and others) asks a few "
                             "more: tap <b>Always Allow</b> each time. After that it stays quiet.</small>" if got else "",
                             "✓ Done" if s["contact"] or s["phone_saved"] else "Next" if got else "")
            head = self._ws(1, "ok", f"Paired: {e(name)}", "", "✓ Done") if got else ""
            card = f'<div class="card"><h3>Your iPhone</h3>{head}{add if not got else head and add}{qr if not got else ""}{allow}</div>'
        done = s["contact"] or s["phone_saved"]
        art = ('<div class="art"><div class="wphone"><div class="wscr"><div class="wshr"><span><i></i>Messages</span><span><i></i>Notes</span>'
               '<span class="mg"><i></i>Magpiary</span><span><i></i>Mail</span></div></div></div></div>')
        return (f'<div class="w-body"><div><div class="w-kick">Step 3 of 3 · Optional</div><h1 class="w-h">Add your <em>iPhone.</em></h1>'
                f'<p class="w-p">Share from any app on your iPhone and it arrives here. A few taps on the phone, once. Skip it now and add it later in Settings.</p>{flash}{card}'
                f'<div class="w-cta"><a class="btn next" href="/welcome/share">{"Continue" if done else "Continue without a phone"} →</a>'
                f'<a class="w-link" href="/welcome/share">Skip for now</a></div></div>{art}</div>')

    def _w_share(self, s: dict, q: dict, flash: str) -> str:
        newest = self.store.hub_items("inbox", limit=1)
        saved = bool(s["delivered"] or newest)  # a share from the phone, a pasted link or the browser extension all count
        ready = saved and s["chosen"]
        done = self._form("/hub/welcome/done", {"next": "/"}, "Open my library →" if ready else "Skip for now",
                          "btn next" if ready else "w-link")
        hint = ("" if s["chosen"] else '<small>Choose Smart or Private any time in Settings.</small>') if saved else (
            '<small>No save yet? You can skip and save later.</small>')
        listen = ('<div class="listen ok" id="listen"><i></i>Saved. Your Mac is reading it now.</div>' if saved
                  else '<div class="listen" id="listen"><i></i>Listening for your first save…</div>')
        arrived = '<div class="art"><div class="chips"><span>Your first save appears here</span></div></div>'
        if newest:
            from magpiary.hub_settings import ago

            it = newest[0]
            when = ago(it.get("first_shared_at") or "")
            arrived = self._wtile(it, f'{ui.source_name(it["source"])} · saved {when}')
        return (f'<div class="w-body"><div><div class="w-kick">Last step</div><h1 class="w-h">Now save <em>something.</em></h1>'
                f'<p class="w-p">Use whichever is closest. Any one of these finishes setup.</p>{flash}'
                f'<div class="ways"><div class="way"><span class="ic">1</span><div><b>From Chrome</b><small>Open a page and click the Magpiary button.</small></div></div>'
                f'<div class="way"><span class="ic">2</span><div><b>From your iPhone</b><small>Share a reel or post, then tap Magpiary.</small></div></div></div>'
                f'{listen}<p class="small muted" style="margin:0 0 8px">Or paste a link here:</p>'
                f'<form method="post" action="/hub/add" class="orpaste">{ui.hidden(self.csrf, next="/welcome/share")}'
                f'<input type="url" name="url" placeholder="https://example.com/a-page" required aria-label="Link to a page">'
                f'<button class="btn dark sm" type="submit">Add</button></form><div class="w-cta">{done}{hint}</div>'
                f'<p class="small muted" style="margin:18px 0 0">Optional, any time in Settings: <a class="link" href="/settings/privacy#lock">lock your library '
                f'with a PIN or Touch ID</a>.</p></div><div>{arrived}</div></div>')

    def welcome_post(self, path: str, form: dict) -> bool:
        if path == "/hub/welcome/done":
            self.store.set_setting(DONE_SETTING, "1")  # the guide is never a trap: every step can be skipped
        elif path == "/hub/welcome/no-ai":
            self.store.set_setting(modes.SETTING, "private")
        elif path == "/hub/welcome/pinned":  # an extension too old to report it: the owner says so
            self.store.set_setting("ext_pinned_manual", "1")
        else:
            return False
        return True
