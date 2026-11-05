"""Strings the phone and the Mac must agree on. The Shortcut is generated from these."""

ACK = "magpiary-ok"  # the Shortcut clears its outbox only when the reply carries this
ITEMS_PATH = "/v1/items"
PING_PATH = "/v1/ping"
BOARDS_PATH = "/v1/boards"  # the phone asks for the latest board list before "Which board?"
PORT_BASE, PORT_SPAN = 8765, 20  # one port per Mac account, so two accounts never share a hub (or a library)


def default_port() -> int:
    """This account's port: 8765 for the first account (user id 501), the next one up for the next account, and so on.
    MAGPIARY_PORT overrides it (tests and screenshots)."""
    import os

    try:
        return int(os.environ["MAGPIARY_PORT"])
    except (KeyError, ValueError):
        return PORT_BASE + (os.getuid() - 501) % PORT_SPAN


DEFAULT_PORT = default_port()


def ping_is_mine(port: int, timeout: float = 3) -> bool:
    """True only when a Magpiary hub answers on this port AND it belongs to this Mac account. A hub that is another
    account's (or an older one that does not say whose it is) is not ours: its library must never be shown to this user."""
    import json
    import os
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{PING_PATH}", timeout=timeout) as response:
            body = json.loads(response.read() or b"{}")
            return response.status == 200 and body.get("uid") == os.getuid()
    except (OSError, ValueError):
        return False

DEFAULT_RETRY_WAIT = 15  # minutes a phone waits before trying a Wi-Fi again after a try the Mac never answered (owner: 15)

# Signed sends (0.1.5): the Shortcut never sends its key. It holds S = sha256(key) (what the Mac keeps as key_hash), names
# itself by a tag made from S, and signs each request with S, the request line, its own clock and the body's hash. Shortcuts
# has Generate Hash (SHA256) but no HMAC, so the signature is a hash of a fixed-shape text whose last part is a fixed-length
# hash; nothing can be appended to it unnoticed.
SIGN_DEVICE, SIGN_TIME, SIGN_SIG = "X-Magpiary-Device", "X-Magpiary-Time", "X-Magpiary-Signature"
SIGN_WINDOW = 600  # seconds either side of the Mac's clock


def _sha(text: str | bytes) -> str:
    import hashlib

    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def device_tag(secret: str) -> str:
    """Which phone is sending; not secret, and different for every key."""
    return _sha("magpiary-device|" + secret)[:24]


def sign_text(secret: str, request: str, stamp: str, body_hash: str | None = None) -> str:
    """The text the phone hashes into the signature: "S|POST /v1/items|time|sha256(body)" (a GET has no body part)."""
    return "|".join([secret, request, stamp] + ([body_hash] if body_hash is not None else []))


def signature(secret: str, request: str, stamp: str, body: bytes | None = None) -> str:
    return _sha(sign_text(secret, request, stamp, None if body is None else _sha(body)))
