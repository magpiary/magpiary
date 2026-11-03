"""The hub lock's pages and routes, mixed into Hub: the lock card, the JSON the open tabs poll, the PIN and Touch ID
posts, and the Settings controls. The rules live in lock.py."""

import json
import re
from urllib.parse import quote, urlencode

from magpiary import lock as lk
from magpiary import ui
from magpiary.protocol import DEFAULT_PORT
from magpiary.web import Response, e

OPEN_WHILE_LOCKED = ("/lock", "/lock.json", "/panel.json")  # /panel.json says only "locked" while locked
POSTS_WHILE_LOCKED = ("/hub/lock/pin", "/hub/lock/challenge", "/hub/lock/verify")
FRAGMENTS = re.compile(r"^/(media/|profile/photo|board/[0-9a-f]{16}/pick|item/\d+/related|search\.json|boards\.json|activity\.json"
                       r"|welcome\.json|pair\.json)")


def _json(data: dict, status: int = 200) -> Response:
    return Response(status, json.dumps(data).encode(), "application/json", headers={"Cache-Control": "no-store"})


class LockPages:
    """Needs Hub's store, csrf, shell, _form and `self.lock` (a lock.Lock)."""

    # ---- the gate ------------------------------------------------------------------------

    def locked_get(self, path: str, query: dict) -> Response | None:
        """None when the request may go on; otherwise what to answer instead (also notes that someone is using the hub)."""
        if path.startswith("/static/") or path in OPEN_WHILE_LOCKED:
            return None
        self.lock.tick(touched=not path.endswith(".json") or path == "/search.json")
        if not self.lock.is_locked():
            return None
        if FRAGMENTS.match(path) or query.get("frag") == ["1"]:
            return Response(423, b"locked", "text/plain", headers={"Cache-Control": "no-store"})
        target = path + ("?" + urlencode({k: v[0] for k, v in query.items()}) if query else "")
        return Response(303, b"", headers={"Location": "/lock?next=" + quote(target, safe="")})

    def locked_post(self, path: str) -> Response | None:
        if path in POSTS_WHILE_LOCKED:
            return None
        self.lock.tick(touched=True)
        if self.lock.is_locked():
            return Response(423, b"locked", "text/plain", headers={"Cache-Control": "no-store"})
        return None

    # ---- pages ---------------------------------------------------------------------------

    def lock_get(self, path: str, q: dict) -> Response:
        if path == "/lock.json":
            self.lock.tick(touched=q.get("a") == "1")
            locked = self.lock.is_locked()
            return _json({"on": self.lock.enabled, "locked": locked, "wait": self.lock.wait_left(),
                          "ids": [c["id"] for c in self.lock.credentials()] if self.lock.enabled else [],
                          "proven": self.lock.proven()})
        card = self._lock_card(q.get("next", "/"))
        if q.get("frag") == "1":
            return Response(200, card.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})
        if self.lock.enabled and not self.lock.is_locked():
            return Response(303, b"", headers={"Location": _safe(q.get("next", "/"))})
        body = f'<div class="lockveil standalone" id="lockveil">{card}</div>'
        return self.shell("Locked", body, "lock", bare=True)

    def _lock_card(self, target: str) -> str:
        wait = self.lock.wait_left()
        return (
            f'<form class="lockcard" id="lockcard" method="post" action="/hub/lock/pin" data-lockform data-next="{e(_safe(target))}" '
            f'data-wait="{wait}" role="dialog" aria-modal="true" aria-labelledby="lk-h" aria-describedby="lk-p">'
            f'{ui.hidden(self.csrf, next=_safe(target))}'
            f'<span class="lkmark" aria-hidden="true">{ui.logo_mark()}</span>'
            f'<h2 id="lk-h">Magpiary is locked</h2>'
            f'<p id="lk-p" class="lkp">Enter your 6-digit PIN.</p>'
            f'<input class="lkpin" id="lkpin" name="pin" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="{lk.PIN_LEN}" '
            f'autocomplete="off" aria-label="PIN" placeholder="••••••"{" disabled" if wait else ""}>'
            f'<p class="lkerr" id="lkerr" role="alert">{self._wait_text(wait)}</p>'
            f'<button class="btn dark lkgo" type="submit"{" disabled" if wait else ""}>Unlock</button>'
            f'<button class="btn lktouch" type="button" data-touch disabled>{ui.icon("fingerprint")}Use Touch ID</button>'
            f'<p class="lkhint" data-touch-hint></p>'
            f'</form>')

    @staticmethod
    def _wait_text(wait: int) -> str:
        return f"Too many tries. Try again in {wait} seconds." if wait else ""

    # ---- posts ---------------------------------------------------------------------------

    def lock_post(self, path: str, form: dict, host: str) -> Response | None:
        origin = f"http://{host}"
        if path == "/hub/lock/pin":
            result = self.lock.unlock_with_pin(form.get("pin", ""))
            wait = self.lock.wait_left()
            if form.get("json") == "1":
                return _json({"ok": result == "ok", "wait": wait, "error": self._pin_error(result, wait)},
                             200 if result == "ok" else 403)
            if result == "ok":
                return Response(303, b"", headers={"Location": _safe(form.get("next", "/"))})
            return Response(303, b"", headers={"Location": "/lock?next=" + quote(_safe(form.get("next", "/")), safe="")})
        if path == "/hub/lock/now":
            self.lock.lock_now()
            return Response(303, b"", headers={"Location": "/lock"})
        if path == "/hub/lock/challenge":
            purpose = {"unlock": "unlock", "confirm": "confirm", "register": "register"}.get(form.get("purpose", ""), "")
            if not purpose or (purpose == "register" and not self.lock.proven()):
                return _json({"error": "Confirm it's you first."}, 403)
            if purpose == "unlock" and not self.lock.credentials():
                return _json({"error": "No Touch ID is set up yet."}, 404)
            return _json({"challenge": self.lock.challenge(purpose), "rp": lk.RP_ID, "ids": [c["id"] for c in self.lock.credentials()],
                          "user": lk.b64e(b"magpiary")})
        if path == "/hub/lock/register":
            problem = self.lock.register(origin, form.get("id", ""), form.get("key", ""), form.get("client", ""),
                                         form.get("label", ""))
            return _json({"ok": not problem, "error": problem}, 200 if not problem else 400)
        if path == "/hub/lock/verify":
            args = (origin, form.get("id", ""), form.get("auth", ""), form.get("client", ""), form.get("sig", ""))
            ok = self.lock.prove_with_key(*args) if form.get("purpose") == "confirm" else self.lock.unlock_with_key(*args)
            return _json({"ok": ok, "error": "" if ok else "That didn't work. Try again or use your PIN."}, 200 if ok else 403)
        return self.lock_settings_post(path, form)

    @staticmethod
    def _pin_error(result: str, wait: int) -> str:
        if result == "ok":
            return ""
        return "Too many tries. Try again in %d seconds." % wait if result == "wait" or wait else "That PIN is not right."

    def lock_settings_post(self, path: str, form: dict) -> Response | None:
        """The Settings → Privacy forms. Each ends at the Privacy page with a note or a problem."""
        problem, note, was_on = "", "", self.lock.enabled
        if path == "/hub/lock/on":
            problem = self.lock.turn_on(form.get("pin", ""), form.get("again", ""))
            note = "The lock is on. It starts locked after a restart, and asks again after sleep or idle time." \
                if not was_on else "Your PIN was changed."
        elif path == "/hub/lock/off":
            problem = self.lock.turn_off()
            note = "The lock is off. Your PIN and Touch ID were forgotten."
        elif path == "/hub/lock/idle":
            problem = self.lock.set_idle(form.get("idle", ""))
            note = "Saved."
        elif path == "/hub/lock/prove":
            result = self.lock.prove_with_pin(form.get("pin", ""))
            problem = self._pin_error(result, self.lock.wait_left())
            note = "Confirmed. These controls stay open for two minutes."
        elif path == "/hub/lock/forget":
            problem = self.lock.forget_credential(form.get("id", ""))
            note = "That Touch ID was removed."
        else:
            return None
        if form.get("json") == "1":
            return _json({"ok": not problem, "error": problem, "next": "/settings/privacy?" + urlencode({"note": note, **({"offer": "touch"} if not was_on else {})}) + "#lock"},
                         200 if not problem else 403)
        query = urlencode({"error": problem} if problem else {"note": note})
        return Response(303, b"", headers={"Location": f"/settings/privacy?{query}#lock"})

    # ---- Settings → Privacy → Hub lock ---------------------------------------------------

    def lock_group(self) -> str:
        from magpiary.hub_settings import _group, _row

        lock, csrf = self.lock, self.csrf
        proven = lock.proven()

        def pin_fields(first: str = "PIN") -> str:
            box = ('<label class="lkl"><span>{}</span><input class="lkpin" name="{}" type="password" inputmode="numeric" '
                   'pattern="[0-9]*" maxlength="6" autocomplete="off" placeholder="\u2022\u2022\u2022\u2022\u2022\u2022" required></label>')
            return box.format(first, "pin") + box.format("Same PIN again", "again")

        def dialog(name: str, title: str, icon: str, intro: str, main: str, confirm: bool = True) -> str:
            guard = ""
            if confirm:
                guard = (f'<div class="lkstep" data-step="confirm"><p class="lkintro">Enter your PIN, or use Touch ID, to go on.</p>'
                         f'<form class="lkform" data-lk-confirm><label class="lkl"><span>Your PIN</span><input class="lkpin" name="pin" '
                         f'type="password" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="off" '
                         f'placeholder="\u2022\u2022\u2022\u2022\u2022\u2022" required></label><p class="lkerr" role="alert"></p>'
                         f'<div class="lkacts"><button class="btn dark" type="submit">Confirm</button>'
                         f'<button class="btn" type="button" data-touch-confirm disabled>{ui.icon("fingerprint")}Use Touch ID</button></div>'
                         f'<p class="lkhint" data-touch-hint></p></form></div>')
            return (f'<dialog class="lkd" id="lkd-{name}" aria-labelledby="lkd-{name}-h" data-confirm-first="{1 if confirm else 0}">'
                    f'<header class="lkdh"><span class="lkic">{ui.icon(icon)}</span><h3 id="lkd-{name}-h">{e(title)}</h3>'
                    f'<button class="lkx" type="button" data-lk-close aria-label="Close">\u00d7</button></header>{guard}'
                    f'<div class="lkstep" data-step="main"><p class="lkintro">{intro}</p>{main}</div></dialog>')

        def opener(name: str, label: str, cls: str = "btn sm dark") -> str:
            return f'<button class="{cls}" type="button" data-lk-open="{name}">{label}</button>'

        touch_body = (f'<p class="lkerr" role="alert" data-touch-error></p><div class="lkacts"><button class="btn dark" type="button" data-touch-add>'
                      f'{ui.icon("fingerprint")}Set up now</button><button class="btn" type="button" data-lk-close>Not now</button></div>')
        touch_intro = ("Your browser asks for your fingerprint once. From then on this browser skips the PIN. "
                       "Other browsers set up on their own.")
        pin_form = (lambda title: f'<form class="lkform" method="post" action="/hub/lock/on" data-lk-pin>{ui.hidden(csrf)}'
                    f'{pin_fields("New PIN" if lock.enabled else "Choose a PIN")}<p class="lkerr" role="alert"></p>'
                    f'<div class="lkacts"><button class="btn dark" type="submit">{title}</button>'
                    f'<button class="btn" type="button" data-lk-close>Cancel</button></div></form>')
        if not lock.enabled:
            dlg = dialog("pin", "Choose a PIN", "lock", "Six digits. Magpiary asks for it when the hub is locked. You can add Touch ID next.",
                         pin_form("Turn the lock on"), confirm=False)
            dlg = dlg.replace("</dialog>", f'<div class="lkstep" data-step="touch" hidden><p class="lkintro">{touch_intro}</p>{touch_body}</div></dialog>')
            rows = _row("Lock the hub with a PIN", "Magpiary asks for it after your Mac sleeps or locks, after the idle time you choose, "
                        "and each time the service starts.", opener("pin", "Set a PIN"), lead=ui.icon("lock"), cls="lkrow")
            return _group("Hub lock", rows + dlg, gid="lock", desc="A casual lock for anyone at your unlocked Mac. It is not disk "
                          "encryption: your library folder stays readable by your Mac account.").replace(
                'id="lock"', 'id="lock" data-proven="1"', 1)
        idle_now = str(lock.idle_minutes())
        idle = "".join(f'<label class="lkseg"><input type="radio" name="idle" value="{k}"{" checked" if idle_now == k else ""}>'
                       f"<span>{e(v.replace(' minutes', ' min'))}</span></label>" for k, v in lk.IDLE_CHOICES.items())
        creds = lock.credentials()
        keys = "".join(
            f'<li><span>{ui.icon("fingerprint")}{e(c["label"])}</span><form method="post" action="/hub/lock/forget" data-lk-guard>'
            f'{ui.hidden(csrf, id=c["id"])}<button class="btn sm" type="submit">Remove</button></form></li>' for c in creds)
        idle_text = ("Never by itself: only sleep, a locked screen, a restart or the Lock button lock it." if idle_now == "0"
                     else f"Locks after {lk.IDLE_CHOICES[idle_now]} without using the hub, and on sleep, a locked screen or a restart.")
        status = _row("The lock is on", idle_text,
                      self._form("/hub/lock/now", {}, "Lock now", "btn sm") + opener("off", "Turn off", "btn sm danger"),
                      lead=ui.icon("lock"), cls="lkrow lkstatus")
        pin_row = _row("PIN", "Six digits, kept only as a salted hash.", opener("change", "Change PIN", "btn sm"),
                       lead=ui.icon("lock"), cls="lkrow")
        idle_row = _row("Lock after being idle", "Sleep and a locked screen always lock, whatever you pick here.",
                        f'<form class="lkidle" method="post" action="/hub/lock/idle" data-lk-guard data-autosubmit>{ui.hidden(csrf)}'
                        f'<div class="lkseggroup" role="radiogroup" aria-label="Idle time">{idle}</div></form>',
                        lead=ui.icon("clock"), cls="lkrow")
        touch_row = _row("Touch ID", f"Skip the PIN in this browser. Each browser is set up on its own, at localhost:{DEFAULT_PORT}; the PIN "
                         "always works." + (f'<ul class="lkcreds">{keys}</ul>' if keys else ""),
                         '<span class="lkhint" data-touch-note></span>' + opener("touch", "Set up Touch ID", "btn sm dark"),
                         lead=ui.icon("fingerprint"), cls="lkrow")
        dialogs = (dialog("change", "Change your PIN", "lock", "Six digits. The old PIN stops working at once.", pin_form("Save new PIN"))
                   + dialog("touch", "Set up Touch ID", "fingerprint",
                            touch_intro, touch_body)
                   + dialog("off", "Turn the lock off?", "lock", "Your PIN and every Touch ID are forgotten. Anyone at this Mac can open the hub.",
                            f'<form class="lkform" method="post" action="/hub/lock/off">{ui.hidden(csrf)}<div class="lkacts">'
                            f'<button class="btn danger" type="submit">Turn the lock off</button><button class="btn" type="button" data-lk-close>Keep it on</button></div></form>')
                   + dialog("guard", "Confirm it's you", "lock", "This change needs your PIN or Touch ID.", "", confirm=True))
        more = (f'<details class="advmini lkmore"><summary><span class="amt"><b>More options</b><small>change PIN, lock after being idle</small></span>'
                f'<span class="advc">{ui.icon("chev")}</span></summary>{pin_row}{idle_row}</details>')
        return _group("Hub lock", status + touch_row + more + dialogs, gid="lock", tag="On",
                      desc="Everything here changes only after you confirm with your PIN or Touch ID.").replace(
            'id="lock"', f'id="lock" data-proven="{1 if proven else 0}"', 1)

    def lock_button(self) -> str:
        """The header's Lock button, only while the lock is on."""
        if not self.lock.enabled:
            return ""
        return (f'<form class="lockform" method="post" action="/hub/lock/now">{ui.hidden(self.csrf)}'
                f'<button class="ubtn lockbtn" type="submit" title="Lock Magpiary now" aria-label="Lock Magpiary now">'
                f'{ui.icon("lock")}<span class="lbl">Lock</span></button></form>')

    def lock_nav_status(self) -> str:
        if not self.lock.enabled:
            return ""
        return f"Lock on · {lk.IDLE_CHOICES.get(str(self.lock.idle_minutes()), '15 minutes').lower()}" \
            if self.lock.idle_minutes() else "Lock on · no idle timer"


def _safe(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"
