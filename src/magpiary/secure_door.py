"""The phone door: the hub over HTTPS for paired phones (docs/specs.md, "Phone access to the library on the local network").

A second listener on its own port (hub port + 100), alive only while the Settings switch is on. It serves the hub's own
pages and nothing of the phone-send API (/v1/...). Every request needs the paired phone's key, kept in a Secure cookie,
and comes from a private address with a Host name we vouch for. The Mac's plain-HTTP hub stays exactly as it is.
"""

import http.cookies
import ipaddress
import socket
import ssl
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit

from magpiary import access
from magpiary.receiver import HUB_PAGES, HUB_PREFIXES, Handler, Server, log
from magpiary.web import Response, alone_page, e, phone_page

HSTS = "max-age=31536000"
COOKIE_AGE = 60 * 60 * 24 * 400
PAIR_PATH = "/phone/pair/"
APP_PATH = "/phone/app"
PUBLIC_FILES = ("/static/apple-touch-icon.png",)  # only the logo: iOS fetches the Home Screen icon without our cookie


class SecureHandler(Handler):
    server: "SecureServer"

    def handle_one_request(self) -> None:  # a failed TLS handshake (phone without our certificate) is one calm line
        try:
            super().handle_one_request()
        except ssl.SSLError as err:
            self.close_connection = True
            self.server.devices.log("refused", None, f"TLS: {err.reason or 'handshake failed'}", self.client_address[0])

    def send_page(self, response: Response) -> None:
        response.headers = {**response.headers, "Strict-Transport-Security": HSTS}
        super().send_page(response)

    # ---- the checks every request passes ----

    def _refuse(self, why: str, message: str, status: int = 403, device_id: int | None = None) -> None:
        self.server.devices.log("refused", device_id, why, self.client_address[0])
        self.send_page(alone_page("Not allowed", "var(--indigo)", "mac", "Can't open this", e(message), status=status))

    def _key(self) -> str:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return ""
        return jar[access.COOKIE].value if access.COOKIE in jar else ""

    def _gate(self) -> tuple[bool, dict | None]:
        """(may go on, the paired phone or None on a pairing page)."""
        ip = self.client_address[0]
        if not access.enabled(self.server.store):
            self._refuse("access is off", "Phone access is switched off on the Mac.")
            return False, None
        if not access.is_private_address(ip):
            self._refuse("not a home-network address", "Only phones on the same network as the Mac can open this.")
            return False, None
        host = self.headers.get("Host", "")
        name = (host if host.endswith("]") else host.rsplit(":", 1)[0]).lower()
        if name not in self.server.names:
            self._refuse(f"wrong host name {name[:40]}", "Open this at magpiary.local.", 421)
            return False, None
        path = urlsplit(self.path).path
        if path.startswith(PAIR_PATH) or path in PUBLIC_FILES or path.startswith(APP_PATH + "/"):
            return True, self.server.devices.check(self._key())  # these decide for themselves; a key is optional
        device = self.server.devices.check(self._key())
        if device is None:
            self._refuse("no valid key (not paired, or revoked)",
                         "This phone isn't paired with this Mac, or it was removed. Pair it again from Settings on the Mac. "
                         "If this is a Home Screen icon, delete it, open the address in Safari and add it again from the page that follows pairing.", 401)
            return False, None
        if self.server.devices.touch(device["id"], ip):
            self.server.announce(device["name"])
        return True, device

    # ---- pairing over HTTPS (reaching this page proves the phone trusts our certificate) ----

    def _pair(self, method: str) -> None:
        token = urlsplit(self.path).path.removeprefix(PAIR_PATH).strip("/")
        devices = self.server.devices
        if not devices.pair_token_valid(token):
            self._refuse("pairing code expired or already used", "This pairing code has expired. Make a new one on your Mac.", 410)
            return
        if method == "GET":
            body = ('<main class="alone"><h1>Pair this phone</h1><p>Name it, so you can tell it apart on your Mac.</p>'
                    f'<form method="post" action="{e(PAIR_PATH + token)}"><input name="name" value="iPhone" maxlength="40" '
                    'style="font-size:16px;padding:10px;width:100%;box-sizing:border-box" autocomplete="off">'
                    '<p><button class="btn" type="submit">Pair this phone</button></p></form></main>')
            self.send_page(phone_page("Pair this phone", body))
            return
        form = self._read_form(2000) or {}
        if not devices.spend_pair_token(token):
            self._refuse("pairing code expired or already used", "This pairing code has expired. Make a new one on your Mac.", 410)
            return
        _, key = devices.add(form.get("name", "iPhone"), self.headers.get("User-Agent", ""))
        cookie = f"{access.COOKIE}={key}; Max-Age={COOKIE_AGE}; Path=/; Secure; HttpOnly; SameSite=Strict"
        self.send_page(Response(303, b"", headers={"Location": APP_PATH, "Set-Cookie": cookie}))

    # ---- the Home Screen app (iOS gives it its own cookies, so it claims its own key once) ----

    def _app_landing(self, device: dict | None) -> None:
        """Safari, paired: the steps to add the library to the Home Screen. The address is swapped for a one-time link so the
        icon opens already paired."""
        if device is None:
            self._refuse("no valid key (not paired, or revoked)", "Pair this phone first.", 401)
            return
        token = self.server.devices.new_app_token(device["id"])
        link = f"{APP_PATH}/{token}"
        body = ('<main class="alone"><h1>Add to your Home Screen</h1>'
                '<p>Tap <b>Share</b> (the square with the arrow) in Safari, then <b>Add to Home Screen</b>, then <b>Add</b>.</p>'
                '<p>The icon opens the library on its own, without Safari bars.</p>'
                '<p><a class="btn" href="/">Open the library</a></p></main>'
                f'<script>history.replaceState(null,"",{link!r});</script>')
        self.send_page(phone_page("Add to Home Screen", body))

    def _app(self, method: str, device: dict | None) -> None:
        token = urlsplit(self.path).path.removeprefix(APP_PATH + "/").strip("/")
        devices = self.server.devices
        if device is not None:  # already holds a key (Safari, or the icon after its first launch): just go in
            self.send_page(Response(303, b"", headers={"Location": "/"}))
            return
        if devices.app_token_device(token) is None:
            self._refuse("home screen link expired or already used", "This icon needs pairing again. Open magpiary.local in Safari, "
                         "pair, and add it to the Home Screen from the page that follows.", 410)
            return
        if method == "GET":
            body = ('<main class="alone"><h1>Opening Magpiary…</h1><p id="m">Open this from the Magpiary icon on your Home Screen.</p>'
                    f'<form id="f" method="post" action="{e(APP_PATH + "/" + token)}"></form></main>'
                    '<script>if(navigator.standalone){document.getElementById("m").textContent="One moment…";'
                    'document.getElementById("f").submit()}</script>')
            self.send_page(phone_page("Opening Magpiary", body))
            return
        claimed = devices.claim_app_token(token, self.headers.get("User-Agent", ""))
        if claimed is None:
            self._refuse("home screen link already used", "This link was already used. Pair again.", 410)
            return
        cookie = f"{access.COOKIE}={claimed[1]}; Max-Age={COOKIE_AGE}; Path=/; Secure; HttpOnly; SameSite=Strict"
        self.send_page(Response(303, b"", headers={"Location": "/", "Set-Cookie": cookie}))

    # ---- the hub, for a paired phone ----

    def do_GET(self) -> None:
        ok, device = self._gate()
        if not ok:
            return
        parts = urlsplit(self.path)
        if parts.path.startswith(APP_PATH + "/"):
            self._app("GET", device)
            return
        if parts.path == APP_PATH:
            self._app_landing(device)
            return
        if parts.path.startswith(PAIR_PATH):
            self._pair("GET")
            return
        if parts.path in PUBLIC_FILES:
            from magpiary import ui

            self.send_page(ui.static(parts.path))
            return
        if not (parts.path in HUB_PAGES or parts.path.startswith(HUB_PREFIXES)):
            self.send_json(404, {"error": "not found"})
            return
        self.send_page(self.server.hub.get(parts.path, parse_qs(parts.query), self.client_address[0],
                                           self.headers.get("Host", ""), self.headers.get("Range", ""),
                                           self.headers.get("User-Agent", ""), device=device))

    def do_POST(self) -> None:
        ok, device = self._gate()
        if not ok:
            return
        path = urlsplit(self.path).path
        if path.startswith(APP_PATH + "/"):
            self._app("POST", device)
            return
        if path.startswith(PAIR_PATH):
            self._pair("POST")
            return
        if not path.startswith("/hub/"):
            self.send_json(404, {"error": "not found"})
            return
        form = self._read_form(20_000)
        if form is None:
            self.send_json(413, {"error": "request too large"})
            return
        self.send_page(self.server.hub.post(path, form, self.client_address[0], self.headers.get("Host", ""),
                                            self.headers.get("Origin"), device=device))


class SecureServer(Server):
    """Shares the primary server's hub, store and lanes; only the door differs."""

    def __init__(self, address, primary: Server, names: list[str], cert: str, key: str, announce=lambda name: None):
        super().__init__(address, primary.store, None)
        self.RequestHandlerClass = SecureHandler
        self.hub, self.activity, self.primary = primary.hub, primary.activity, primary
        self.devices = primary.hub.devices
        self.names = {n.lower() for n in names}
        self.announce = announce
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self._ctx.load_cert_chain(cert, key)

    def get_request(self):
        sock, address = super().get_request()
        # the handshake happens in the worker thread on first read, so a slow phone never stalls the listener
        return self._ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), address

    def handle_error(self, request, client_address):
        log(f"  phone door: {client_address[0]} connection ended")


def lan_ip() -> str:
    """The address other devices on this network reach the Mac at (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


class Bonjour:
    """Announces magpiary.local with macOS's own dns-sd tool (no new dependency). If it cannot run, the Mac's own
    .local name still works, because macOS announces that itself."""

    def __init__(self, port: int, run=subprocess.Popen):
        self.port, self._run, self.proc, self.ip = port, run, None, ""

    def sync(self, ip: str) -> None:
        if self.proc and self.proc.poll() is None and ip == self.ip:
            return
        self.stop()
        if not ip:
            return
        try:
            ipaddress.ip_address(ip)
            self.proc = self._run(["dns-sd", "-P", "Magpiary", "_https._tcp", "local", str(self.port), access.NAME, ip],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            self.ip = ip
        except (OSError, ValueError):
            self.proc = None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc, self.ip = None, ""


class Door:
    """Opens and closes the phone door to follow the Settings switch. `poll()` is cheap; the service calls it every few
    seconds, so a switch flipped in Settings takes effect within moments, and a restart keeps the switch as it was."""

    def __init__(self, primary: Server, mac_name, announce=lambda name: None, bonjour=None, port: int | None = None):
        self.primary, self.mac_name, self.announce = primary, mac_name, announce
        self.port = port if port is not None else access.https_port(primary.server_port)
        self.bonjour = bonjour or Bonjour(self.port)
        self.menubar = None  # the menu bar icon's process while the door is open
        self.start_menubar = self._start_menubar
        self.server: SecureServer | None = None
        self.thread: threading.Thread | None = None

    def poll(self) -> None:
        on = access.enabled(self.primary.store)
        if on and self.server is None:
            self._open()
        elif not on and self.server is not None:
            self._close()
        if self.server is not None:
            self.bonjour.sync(lan_ip())

    def _open(self) -> None:
        names = [access.NAME, self.mac_name()]
        cert, key = access.server_files(names)
        try:
            self.server = SecureServer(("0.0.0.0", self.port), self.primary, names, str(cert), str(key), self.announce)
        except OSError as err:
            log(f"phone door could not open port {self.port}: {err}")
            self.primary.store.set_setting(access.SETTING + "_error", f"Port {self.port} is busy.")
            return
        self.primary.store.set_setting(access.SETTING + "_error", "")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="phone-door")
        self.thread.start()
        log(f"phone door open on https port {self.port}")
        self.start_menubar()

    def _start_menubar(self) -> None:
        import sys

        from magpiary.config import db_path

        try:
            self.menubar = subprocess.Popen(
                [sys.executable, "-m", "magpiary.menubar", str(db_path()),
                 f"http://localhost:{self.primary.server_port}/settings/phones#phoneaccess"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.menubar = None

    def _close(self) -> None:
        server, self.server = self.server, None
        self.bonjour.stop()
        if self.menubar and self.menubar.poll() is None:
            self.menubar.terminate()
        self.menubar = None
        if server:
            server.shutdown()
            server.server_close()
            log("phone door closed")
