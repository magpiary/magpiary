"""An optional proxy for popularity refreshes (owner's request, 1 Nov 2026).

Bring your own: the owner pastes the address a VPN or proxy service gave them. It is used only by the stats refresh for
the sites read through yt-dlp (Instagram, YouTube), never for downloads, logins, the phone link or AI calls. The address
may hold a user name and password, so it lives in the config folder with the keys (mode 0600), is never shown back in
full and never logged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

from magpiary import keys

SCHEMES = {"http", "https", "socks5", "socks5h"}
TEST_URL = "https://api.ipify.org"


def _file() -> Path:
    return keys._path().parent / "stats-proxy"


def check(address: str) -> tuple[str, str]:
    """Tidy a pasted address. Returns (address, "") or ("", what is wrong, in plain words). A user name or password with
    odd characters (@ : / # ?) is percent-encoded, so the address can be typed the way the provider shows it."""
    text = address.strip()
    scheme, sep, rest = text.partition("://")
    scheme = scheme.lower()
    if not sep or scheme not in SCHEMES:
        return "", "It must start with socks5:// (or socks5h://, http://, https://). Do not leave out the two slashes."
    if any(c.isspace() for c in rest):
        return "", "There is a space in it. Paste the address with no spaces."
    userinfo, at, hostport = rest.rpartition("@")  # the last @, so a password may hold an @
    host, colon, port = hostport.rpartition(":")
    if not colon or not host or not port.isdigit() or not 0 < int(port) < 65536 or any(c in host for c in "/?#@") or (":" in host and not host.startswith("[")):
        return "", ("After the login (if any) it needs host and port, like 192.168.1.20:1080. The port is a number. "
                    "With a login, write username:password@host:port; there must be an @ before the host.")
    if at:
        user, _, password = userinfo.partition(":")
        quoted = lambda t: t if "%" in t else quote(t, safe="")  # already encoded? leave it
        userinfo = quoted(user) + (":" + quoted(password) if _ else "")
        hostport = f"{userinfo}@{hostport}"
    return f"{scheme}://{hostport}", ""


def valid(address: str) -> bool:
    return not check(address)[1]


def get() -> str:
    try:
        saved = _file().read_text().strip()
    except OSError:
        return ""
    return saved if valid(saved) else ""  # a damaged or hand-edited file is ignored, never trusted


def save(address: str) -> str:
    """Save a proxy address ('' removes it). Returns "" when saved, or what is wrong with the address."""
    address = address.strip()
    path = _file()
    if not address:
        path.unlink(missing_ok=True)
        return ""
    address, wrong = check(address)
    if wrong:
        return wrong
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(address)
    return ""


def mask(address: str) -> str:
    """Enough to recognise it, nothing secret: scheme://host:port, no user name or password."""
    try:
        parts = urlsplit(address)
        return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "") if parts.hostname else ""
    except ValueError:
        return ""


def test(address: str, run=subprocess.run) -> tuple[bool, str]:
    """Fetch the public address of this Mac directly and through the proxy; True when they differ."""
    def ask(*extra: str) -> str:
        done = run(["curl", "-s", "--max-time", "20", *extra, TEST_URL], capture_output=True, text=True, timeout=30)
        return done.stdout.strip() if done.returncode == 0 else ""
    direct = ask()
    through = ask("--proxy", address)
    if not through:
        return False, "The proxy did not answer. Check the address, user name and password."
    if through == direct:
        return False, "It answered, but the outside address is the same as without it, so it is not hiding anything."
    return True, f"Works. Requests now appear to come from {through} instead of your own address."
