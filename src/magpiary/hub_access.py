"""Settings for phone access to the library (docs/specs.md, "Phone access to the library on the local network"), mixed into Hub:
the switch, the pairing QR and its guided steps, the paired phones with Revoke, and the access log. Mac only: a paired phone
can never reach these (phone_gate.py)."""

import time
from urllib.parse import quote

from magpiary import access, ui
from magpiary.hub_settings import _fold, _group, _menu, _row, _stat
from magpiary.web import Response, alone_page, e, phone_page

RISK = ("Anyone on this network who gets past the next two checks could open your library: they would need a phone you paired "
        "here, and your PIN if the hub lock is on. Everything travels encrypted, but a paired phone that is lost can open the "
        "library until you revoke it here. Turn this on only on a network you trust.")
REMOVE_CERT = ("To remove the certificate from the phone too: Settings → General → VPN & Device Management → "
               "Magpiary local network CA → Remove Profile.")
BACK = "/settings/phones#phoneaccess"


class AccessPages:
    """Needs Hub's store, csrf, devices, _form and _switch (hub_settings)."""

    _pairing: tuple[str, float] | None = None  # the pairing code on show (memory only) and when it was made

    # ---- the Settings block ----

    def access_group(self, q: dict) -> str:
        on = access.enabled(self.store)
        port = access.https_port(getattr(self, "port", 0) or 0)
        status = (_stat("On", "ok") if on else _stat("Off", "off"))
        error = self.store.get_setting(access.SETTING + "_error")
        rows = [_row("Open the library on a phone", "Off unless you turn it on. Each phone is paired once and can be removed any time.",
                     status + self._switch("/hub/access/toggle", on, {"enabled": "0"}, {"enabled": "1"},
                                           "Open the library on paired phones", confirm=RISK, ok="I understand, turn it on"),
                     lead=ui.icon("phone"), sid="phoneaccess")]
        if error:
            rows.append(f'<p class="gnote">{e(error)}</p>')
        if on:
            rows.append(_row("Address", f"<code>https://{access.NAME}:{port}/</code>. Phones must be on the same network as this Mac.",
                             self._form("/hub/access/pair", {}, "Pair a phone", "btn sm dark"), lead=ui.icon("wifi")))
            rows.append(self._pair_panel())
            rows.append(self._devices())
            rows.append(self._log())
            rows.append(_fold("Reset the certificate", "only if a phone was lost and you want a fresh start",
                              '<div class="padvbody"><p class="hint">Makes a new certificate authority and removes every paired phone. '
                              'Each phone must pair again and install the new certificate.</p>'
                              + self._form("/hub/access/reset", {}, "Reset and remove all phones", "btn sm bad",
                                           confirm="Remove every paired phone and make a new certificate?") + "</div>"))
        return _group("Phone access", "".join(rows), gid="phoneaccessgroup", cls="hero lilac",
                      desc="Open your library on your iPhone over your home network, encrypted, with a key for each phone.",
                      status="" if on else "")

    def _pair_panel(self) -> str:
        if not self._pairing or not self.devices.pair_token_valid(self._pairing[0]):
            return ""
        import segno

        token = self._pairing[0]
        url = f"http://{access.NAME}:{self.port}/phone-access/{token}"
        qr = segno.make(url, error="m").svg_inline(border=2, omitsize=True, dark="#000", light="#fff")
        left = max(0, int(access.PAIR_FOR - (time.monotonic() - self._pairing[1])))
        steps = ("Scan this code with the iPhone camera and tap the banner.",
                 "Tap <b>Download certificate</b>, then <b>Allow</b>. In Settings tap <b>Profile Downloaded</b> and <b>Install</b>.",
                 "Settings → General → About → <b>Certificate Trust Settings</b>: switch on <b>Magpiary local network CA</b>.",
                 "Open the certificate on the phone (Settings → Profile Downloaded → More Details) and check its SHA-256 fingerprint matches the one below, then tap <b>Continue</b> on the phone.")
        lis = "".join(f"<li>{s}</li>" for s in steps)
        return (f'<div class="srow"><div class="srl"><b>Pair a phone</b><p>This code works once, for about {left // 60 + 1} minutes.</p>'
                f'<div class="acode" style="width:200px;background:#fff;padding:6px;border-radius:12px;margin:10px 0">{qr}</div><ol class="hint">{lis}</ol>'
                f'<p class="hint">Fingerprint (SHA-256) to compare:<br><code style="word-break:break-all">{e(access.ca_fingerprint())}</code></p>'
                f'<p class="hint">If the address does not open, use <code>{e(self.mac_name())}</code> instead of {access.NAME}.</p></div></div>')

    def _devices(self) -> str:
        rows = []
        for d in self.devices.active():
            seen = ui.day(d["last_seen"]) if d["last_seen"] else "not yet"
            menu = _menu(f"More for {d['name']}",
                         self._form("/hub/access/revoke", {"id": str(d["id"])}, "Revoke this phone", "bad",
                                    confirm=f"Revoke {d['name']}? It can no longer open the library. {REMOVE_CERT}"))
            rows.append(_row(e(d["name"]), f"Paired {e(ui.day(d['paired_at']))}. Last seen {e(seen)}.", menu, lead=ui.icon("phone")))
        return "".join(rows) or _row("No phone paired yet", "Choose Pair a phone.", cls="emptyrow")

    def _log(self) -> str:
        entries = self.devices.recent(12)
        lines = "".join(
            f'<li><b>{e(r["kind"])}</b> {e(r["device"] or "")} {e(r["detail"])} <small>{e(ui.day(r["at"]))}'
            f'{" · " + e(r["address"]) if r["address"] else ""}</small></li>' for r in entries) or "<li>Nothing yet.</li>"
        refused = sum(1 for r in entries if r["kind"] == "refused")
        return _fold("Access log", f"{refused} refused in the last entries" if refused else "who connected and what was refused",
                     f'<div class="padvbody"><ul class="hint">{lines}</ul></div>')

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

    # ---- posts from the Mac ----

    def access_post(self, path: str, form: dict) -> Response | None:
        if not path.startswith("/hub/access/"):
            return None
        if path == "/hub/access/toggle":
            on = form.get("enabled") == "1"
            self.store.set_setting(access.SETTING, "1" if on else "")
            self._pairing = None if not on else self._pairing
            self.devices.log("enabled" if on else "disabled")
        elif path == "/hub/access/pair" and access.enabled(self.store):
            access.ca_certificate()  # made on first use
            self._pairing = (self.devices.new_pair_token(), time.monotonic())
        elif path == "/hub/access/revoke" and form.get("id", "").isdigit():
            self.devices.revoke(int(form["id"]))
        elif path == "/hub/access/reset":
            self.devices.revoke_all()
            access.forget_authority()
            self._pairing = None
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
        if rest[1:] == ["ca.crt"]:
            return Response(200, access.ca_pem(), "application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="magpiary-local-network-ca.crt"',
                                     "Cache-Control": "no-store"})
        port = access.https_port(self.port)
        body = ('<main class="alone"><h1>Set up this phone</h1>'
                f'<p><a class="btn" href="/phone-access/{quote(token)}/ca.crt">Download certificate</a></p>'
                "<ol><li>Tap <b>Allow</b>, then open <b>Settings</b> and tap <b>Profile Downloaded</b>, then <b>Install</b>.</li>"
                "<li>Settings → General → About → <b>Certificate Trust Settings</b>: switch on <b>Magpiary local network CA</b>.</li>"
                "<li>Before you trust it, open the certificate's <b>More Details</b> on the phone and check that its <b>SHA-256</b> "
                "fingerprint is the one shown on your Mac. This page cannot show it to you: anything on this network could change it.</li></ol>"
                f'<p><a class="btn" href="https://{access.NAME}:{port}/phone/pair/{quote(token)}">Continue</a></p>'
                "<p>If the Continue button says it cannot connect securely, step 2 is not done yet.</p></main>")
        return phone_page("Set up this phone", body)
