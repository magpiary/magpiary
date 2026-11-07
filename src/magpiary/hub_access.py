"""Settings for phone access to the library (docs/specs.md, "Phone access to the library on the local network"), mixed into Hub:
the switch, the pairing card with live progress, the paired phones with Revoke, and the access log. Mac only: a paired phone
can never reach these (phone_gate.py).

Layout, top to bottom: the header (what it is, on or off, the switch); then, when it is on, "Your phones" (the list and the one
main button), the pairing card while a code is live, and two quiet folds (activity, and the rarely needed options)."""

import json
import time

from magpiary import access, ui
from magpiary.web import Response, alone_page, e

RISK = ("Anyone on this network who gets past the next two checks could open your library: they would need a phone you paired "
        "here, and your PIN if the hub lock is on. Everything travels encrypted, but a paired phone that is lost can open the "
        "library until you revoke it here. Turn this on only on a network you trust.")
REMOVE_CERT = ("To remove the certificate from the phone too: Settings → General → VPN & Device Management → "
               "Magpiary local network CA → Remove Profile.")
BACK = "/settings/phones#phoneaccess"
STEPS = (  # (stage the phone must reach, title, what to do)
    ("opened", "Scan the code", "Point the iPhone camera at the code and tap the banner that appears."),
    ("downloaded", "Install the certificate", "On the phone: <b>Download certificate</b> → <b>Allow</b> → Settings → "
                                                "<b>Profile Downloaded</b> → <b>Install</b>."),
    ("trusted", "Trust it", "Settings → General → About → <b>Certificate Trust Settings</b> → switch on "
                            "<b>Magpiary local network CA</b>."),
    ("paired", "Name the phone", "Back in Safari tap <b>Continue</b>, give the phone a name and tap <b>Pair this phone</b>."),
)
FACTS = (("lock", "Encrypted", "Your phone and Mac talk over HTTPS, with a certificate only this Mac can make."),
         ("phone", "One key per phone", "Each phone is paired once and can be revoked any time."),
         ("check", "Off until you turn it on", "A phone can never change AI keys, the lock or pairing, and Ask Magpiary stays off on it."))


def _fingerprint_html(text: str) -> str:
    """The fingerprint in rows of eight pairs, so it can be read out loud against the phone."""
    pairs = text.split(" ")
    rows = [" ".join(pairs[i:i + 8]) for i in range(0, len(pairs), 8)]
    return "<br>".join(e(r) for r in rows)


class AccessPages:
    """Needs Hub's store, csrf, devices, _form and _switch (hub_settings)."""

    _pairing: tuple[str, float] | None = None  # the pairing code on show (memory only) and when it was made

    # ---- the Settings block ----

    def access_group(self, q: dict) -> str:
        if getattr(self._ctx, "device", None) is not None:
            return ""  # pairing and revoking phones is done on the Mac
        on = access.enabled(self.store)
        port = access.https_port(getattr(self, "port", 0) or 0)
        state = f'<span class="pa-state {"on" if on else "off"}"><i></i>{"On" if on else "Off"}</span>'
        switch = self._switch("/hub/access/toggle", on, {"enabled": "0"}, {"enabled": "1"}, "Open the library on paired phones",
                              confirm=RISK, ok="I understand, turn it on")
        head = (f'<header class="pa-head"><span class="pa-ic">{ui.icon("phone")}</span><div class="pa-t"><h3>Phone access</h3>'
                '<p>Open your library on your iPhone, over your home Wi-Fi.</p></div>'
                f'<div class="pa-ctl">{state}{switch}</div></header>')
        error = self.store.get_setting(access.SETTING + "_error")
        body = f'<p class="pa-err">{e(error)}</p>' if error else ""
        body += self._on_body(port) if on else self._off_body()
        return f'<section class="sgroup pa" id="phoneaccess">{head}{body}</section>'

    def _off_body(self) -> str:
        facts = "".join(f'<li><span>{ui.icon(i)}</span><div><b>{t}</b><p>{d}</p></div></li>' for i, t, d in FACTS)
        return f'<ul class="pa-facts">{facts}</ul>'

    def _on_body(self, port: int) -> str:
        phones = self.devices.active()
        live = self._live_pairing()
        pair = self._form("/hub/access/pair", {}, "Pair a phone", "btn dark")
        title = f'<div class="pa-sec"><h4>Your phones<span>{len(phones)}</span></h4>{pair if (phones and not live) else ""}</div>'
        rows = "".join(self._phone_row(d) for d in phones)
        if not phones and not live:
            rows = f'<div class="pa-empty"><b>No phone paired yet</b><p>Pair your iPhone to open your library on it.</p>{pair}</div>'
        address = (f'<p class="pa-addr">{ui.icon("wifi")}<span>Address <code>https://{access.NAME}:{port}</code> · the phone must be '
                   'on the same network as this Mac.</span></p>')
        return title + self._pair_card() + f'<div class="pa-list">{rows}</div>' + address + self._log() + self._more()

    def _live_pairing(self) -> bool:
        return bool(self._pairing and self.devices.pair_token_valid(self._pairing[0]))

    def _phone_row(self, d: dict) -> str:
        seen = ui.day(d["last_seen"]) if d["last_seen"] else "not opened yet"
        revoke = self._form("/hub/access/revoke", {"id": str(d["id"])}, "Revoke", "btn sm",
                            confirm=f"Revoke {d['name']}? It can no longer open the library. {REMOVE_CERT}")
        return (f'<div class="pa-phone"><span class="pa-pi">{ui.icon("phone")}</span><div><b>{e(d["name"])}</b>'
                f'<p>Paired {e(ui.day(d["paired_at"]))} · last seen {e(seen)}</p></div>{revoke}</div>')

    def _pair_card(self) -> str:
        if not self._live_pairing():
            return ""
        import segno

        token = self._pairing[0]
        from magpiary.secure_door import lan_ip

        # the Mac's network address, not magpiary.local: a phone that once got an HSTS rule for that name from an older version
        # would turn this plain-HTTP link into HTTPS and fail; an address has no such rule
        url = f"http://{lan_ip() or access.NAME}:{self.port}/phone-access/{token}"
        qr = segno.make(url, error="m").svg_inline(border=2, omitsize=True, dark="#000", light="#fff")
        left = self.devices.progress(token)["left"]
        steps = "".join(f'<li data-stage="{st}"><span class="pa-mk"></span><div><b>{t}</b><p>{d}</p></div></li>'
                        for st, t, d in STEPS)
        return (f'<div class="pa-card" data-access data-left="{left}">'
                f'<div class="pa-steps"><h4>Pair a new phone</h4><p class="pa-live" data-live>Waiting for the phone to scan the code…</p>'
                f'<ol>{steps}</ol>'
                f'<details class="pa-check"><summary>Check the certificate fingerprint (recommended)</summary>'
                f'<p>Before you trust the certificate, open it on the phone (Profile Downloaded → More Details) and make sure its '
                f'<b>SHA-256</b> fingerprint is exactly this one. A page on a network cannot be trusted to show it.</p>'
                f'<code class="pa-fp">{_fingerprint_html(access.ca_fingerprint())}</code></details></div>'
                f'<div class="pa-qr"><div class="pa-code" role="img" aria-label="Pairing code">{qr}</div>'
                f'<p class="pa-time">Works once · <b data-timer>{left // 60}:{left % 60:02d}</b> left</p>'
                f'<div class="pa-qa">{self._form("/hub/access/pair", {}, "New code", "btn sm")}'
                f'{self._form("/hub/access/cancel", {}, "Cancel", "btn sm")}</div>'
                f'<p class="pa-alt">Address not opening? Use <code>{e(self.mac_name())}</code> in place of {access.NAME}.</p></div></div>')

    def _log(self) -> str:
        entries = self.devices.recent(12)
        lines = "".join(
            f'<li><b>{e(r["kind"])}</b> {e(r["device"] or "")} {e(r["detail"])} <small>{e(ui.day(r["at"]))}'
            f'{" · " + e(r["address"]) if r["address"] else ""}</small></li>' for r in entries) or "<li>Nothing yet.</li>"
        refused = sum(1 for r in entries if r["kind"] == "refused")
        pill = f'<span class="pa-pill bad">{refused} refused</span>' if refused else ""
        return (f'<details class="pa-fold"><summary><span>Activity</span>{pill}<small>who connected and what was refused</small>'
                f'{ui.icon("chev")}</summary><ul class="pa-log">{lines}</ul></details>')

    def _more(self) -> str:
        reset = self._form("/hub/access/reset", {}, "Reset and remove all phones", "btn sm bad",
                           confirm="Remove every paired phone and make a new certificate?")
        return ('<details class="pa-fold"><summary><span>More</span><small>removing the certificate, starting over</small>'
                f'{ui.icon("chev")}</summary><div class="pa-more"><p><b>Remove the certificate from a phone.</b> {REMOVE_CERT} Revoke '
                'the phone here first.</p>'
                '<p><b>Start over.</b> Makes a new certificate authority and removes every paired phone. Each phone must pair again '
                f'and install the new certificate.</p>{reset}</div></details>')

    def access_button(self) -> str:
        """Top bar, Mac only: a quiet phone icon with a green glowing dot while phone access is on."""
        if getattr(self._ctx, "device", None) is not None or not access.enabled(self.store):
            return ""
        n = len(self.devices.active())
        tip = f"Phone access is on ({n} phone{'' if n == 1 else 's'} paired)"
        return (f'<a class="ubtn phacc" href="/settings/phones#phoneaccess" id="t-phacc" aria-label="{e(tip)}" title="{e(tip)}">'
                f'{ui.icon("phone")}<i class="phdot" aria-hidden="true"></i></a>')

    def mac_name(self) -> str:
        from magpiary.system import local_name

        return local_name()

    def access_json(self) -> Response:
        """How far the phone has got with the code on screen, for the pairing card."""
        token = self._pairing[0] if self._pairing else ""
        data = {"on": access.enabled(self.store), "phones": len(self.devices.active()), "left": 0, "stages": []}
        if token:
            data.update(self.devices.progress(token))
        return Response(200, json.dumps(data).encode(), "application/json", headers={"Cache-Control": "no-store"})

    # ---- posts from the Mac ----

    def _drop_pairing(self) -> None:
        if self._pairing:
            self.devices.cancel_pair_token(self._pairing[0])
        self._pairing = None

    def access_post(self, path: str, form: dict) -> Response | None:
        if not path.startswith("/hub/access/"):
            return None
        if path == "/hub/access/toggle":
            on = form.get("enabled") == "1"
            self.store.set_setting(access.SETTING, "1" if on else "")
            if not on:
                self._drop_pairing()
            self.devices.log("enabled" if on else "disabled")
        elif path == "/hub/access/pair" and access.enabled(self.store):
            access.ca_certificate()  # made on first use
            self._drop_pairing()  # a new code replaces the old one, which stops working
            self._pairing = (self.devices.new_pair_token(), time.monotonic())
        elif path == "/hub/access/cancel":
            self._drop_pairing()
        elif path == "/hub/access/revoke" and form.get("id", "").isdigit():
            self.devices.revoke(int(form["id"]))
        elif path == "/hub/access/reset":
            self.devices.revoke_all()
            access.forget_authority()
            self._drop_pairing()
        return Response(303, b"", headers={"Location": BACK})

    # ---- the guide a phone opens from the QR (plain HTTP: it carries only the public certificate) ----

    def access_guide(self, path: str, client_ip: str) -> Response:
        """/phone-access/<code> (the steps) and /phone-access/<code>/ca.crt (the public certificate). Nothing else is
        served over plain HTTP, and nothing secret is on these pages."""
        rest = path.removeprefix("/phone-access/").strip("/").split("/")
        token = rest[0]
        if not access.enabled(self.store) or not access.is_private_address(client_ip) or not self.devices.pair_token_valid(token):
            self.devices.log("refused", None, "pairing page: access off, wrong network or expired code", client_ip)
            return alone_page("Expired", "var(--indigo)", "lost", "This code has expired",
                              "Make a new pairing code on your Mac (Settings → Phones → Phone access).", status=410)
        self.devices.mark(token, "opened")
        if rest[1:] == ["ca.crt"]:
            self.devices.mark(token, "downloaded")
            return Response(200, access.ca_pem(), "application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="magpiary-local-network-ca.crt"',
                                     "Cache-Control": "no-store"})
        from magpiary import phone_guide

        return phone_guide.certificate_guide(token, access.https_port(self.port))
