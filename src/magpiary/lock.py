"""The hub lock: a casual lock for someone sitting at your unlocked Mac (docs/specs.md, "Hub lock").

Not disk encryption: anyone with your Mac account can still read ~/Magpiary. The lock keeps the hub's pages, pictures
and files behind a 6-digit PIN or Touch ID. Touch ID is the browser's own passkey prompt (WebAuthn at localhost), so
no native code ships; the PIN always works.

Settings live in the database (so `magpiary lock reset` works while the service runs); whether the hub is locked right
now lives in memory, and a fresh start is always locked.
"""

import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key

ON, PIN, IDLE, CREDS = "lock_on", "lock_pin", "lock_idle", "lock_creds"
FAILS, STRIKES, WAIT_UNTIL = "lock_fails", "lock_strikes", "lock_wait_until"
IDLE_CHOICES = {"5": "5 minutes", "15": "15 minutes", "60": "1 hour", "0": "Never"}
DEFAULT_IDLE = "0"
PIN_LEN = 6
TRIES = 5  # wrong PINs before the wait
WAIT = 60  # seconds; doubles each time the wait is earned again
PROOF_FOR = 120  # seconds the Settings controls stay open after the PIN or Touch ID was shown again
CHALLENGE_FOR = 120
RP_ID = "localhost"
SLEEP_GAP = 20  # seconds the wall clock may run ahead of the monotonic clock before we call it a sleep
CREDS_MAX = 6


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return f"{salt.hex()}${hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"


def check_hash(pin: str, stored: str) -> bool:
    try:
        salt, want = stored.split("$")
        got = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    except ValueError:
        return False
    return hmac.compare_digest(got, want)


def screen_locked(run=subprocess.run) -> bool:
    """Whether the Mac's screen lock (or login window) is up: macOS keeps that on its registry root."""
    try:
        out = run(["ioreg", "-n", "Root", "-d1"], capture_output=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return b'"IOConsoleLocked" = Yes' in out


class Lock:
    """Needs the Store. One instance per hub; `tick()` is cheap and called on every request and by the watcher."""

    def __init__(self, store, now=time.time, mono=time.monotonic, screen=screen_locked):
        self.store, self._now, self._mono, self._screen = store, now, mono, screen
        self._mu = threading.Lock()
        self.locked = True  # a start (reboot, update, restart) always begins locked once the lock is on
        self.active = now()  # the last time someone used the hub
        self._wall, self._tick = now(), mono()
        self.proof = 0.0
        self._challenges: dict[str, tuple[str, float, str]] = {}  # challenge -> (purpose, expires, cred_id)
        self._watcher = False

    # ---- settings -----------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.store.get_setting(ON) == "1" and bool(self.store.get_setting(PIN))

    def idle_minutes(self) -> int:
        value = self.store.get_setting(IDLE, DEFAULT_IDLE)
        return int(value) if value in IDLE_CHOICES else int(DEFAULT_IDLE)

    def credentials(self) -> list[dict]:
        try:
            data = json.loads(self.store.get_setting(CREDS, "[]"))
        except ValueError:
            return []
        return [c for c in data if isinstance(c, dict) and c.get("id") and c.get("key")]

    def _save_credentials(self, creds: list[dict]) -> None:
        self.store.set_setting(CREDS, json.dumps(creds))

    # ---- state --------------------------------------------------------------------------

    def tick(self, touched: bool = False) -> None:
        """Look at the clock: a gap between wall and monotonic time means the Mac slept; idle time locks too.
        `touched`: the request came from someone using the hub (not a background poll)."""
        with self._mu:
            now, mono = self._now(), self._mono()
            slept = (now - self._wall) - (mono - self._tick) > SLEEP_GAP
            self._wall, self._tick = now, mono
            if not self.enabled:
                self.locked = False
                return
            if slept:
                self.locked = True
            idle = self.idle_minutes()
            if not self.locked and idle and now - self.active > idle * 60:
                self.locked = True
            if touched and not self.locked:
                self.active = now

    def is_locked(self) -> bool:
        self.tick()
        return self.enabled and self.locked

    def lock_now(self) -> None:
        with self._mu:
            self.locked, self.proof = True, 0.0

    def _open(self) -> None:
        with self._mu:
            self.locked, self.active, self._wall, self._tick = False, self._now(), self._now(), self._mono()

    def proven(self) -> bool:
        """Settings controls that change the lock are open for a couple of minutes after a fresh PIN or Touch ID."""
        return self._now() < self.proof

    def _prove(self) -> None:
        self.proof = self._now() + PROOF_FOR

    def watch(self) -> None:
        """Start the background watcher: catches sleep and the screen lock even when no page is open."""
        if self._watcher:
            return
        self._watcher = True

        def loop() -> None:
            while True:
                time.sleep(10)
                try:
                    self.tick()
                    if self.enabled and not self.locked and self._screen():
                        self.lock_now()
                except Exception:  # noqa: BLE001  the watcher must never die
                    pass

        threading.Thread(target=loop, daemon=True, name="lock-watch").start()

    # ---- the PIN ------------------------------------------------------------------------

    def wait_left(self) -> int:
        return max(0, int(float(self.store.get_setting(WAIT_UNTIL, "0") or 0) - self._now()))

    def check_pin(self, pin: str) -> str:
        """'ok', 'wrong' or 'wait'. Five wrong tries earn a wait that doubles each time it is earned again."""
        with self._mu:
            return self._check_pin(pin)

    def _check_pin(self, pin: str) -> str:
        """The cooldown check, hash and failure counters form one serialized attempt."""
        if self.wait_left():
            return "wait"
        stored = self.store.get_setting(PIN)
        if stored and len(pin) == PIN_LEN and pin.isdigit() and check_hash(pin, stored):
            self.store.set_setting(FAILS, "0")
            return "ok"
        fails = int(self.store.get_setting(FAILS, "0") or 0) + 1
        if fails >= TRIES:
            strikes = int(self.store.get_setting(STRIKES, "0") or 0)
            self.store.set_setting(WAIT_UNTIL, str(self._now() + WAIT * 2 ** min(strikes, 6)))
            self.store.set_setting(STRIKES, str(strikes + 1))
            fails = 0
        self.store.set_setting(FAILS, str(fails))
        return "wrong"

    def unlock_with_pin(self, pin: str) -> str:
        result = self.check_pin(pin)
        if result == "ok":
            self.store.set_setting(STRIKES, "0")
            self._open()
            self._prove()
        return result

    def prove_with_pin(self, pin: str) -> str:
        result = self.check_pin(pin)
        if result == "ok":
            self._prove()
        return result

    def turn_on(self, pin: str, again: str) -> str:
        """'' when it worked, otherwise a plain sentence saying what to fix."""
        if self.enabled and not self.proven():
            return "Confirm it's you first."
        if not (pin.isdigit() and len(pin) == PIN_LEN):
            return f"The PIN is {PIN_LEN} digits."
        if pin != again:
            return "The two PINs are different."
        self.store.set_setting(PIN, hash_pin(pin))
        self.store.set_setting(ON, "1")
        self.store.set_setting(FAILS, "0")
        self.store.set_setting(STRIKES, "0")
        self.store.set_setting(WAIT_UNTIL, "0")
        self._open()
        self._prove()
        return ""

    def turn_off(self) -> str:
        if self.enabled and not self.proven():
            return "Confirm it's you first."
        self.reset()
        return ""

    def reset(self) -> None:
        """Lock off, PIN and every Touch ID forgotten (also what `magpiary lock reset` does)."""
        for key in (ON, PIN, CREDS, FAILS, STRIKES, WAIT_UNTIL):
            self.store.set_setting(key, "")
        self.locked, self.proof = False, 0.0

    def set_idle(self, minutes: str) -> str:
        if self.enabled and not self.proven():
            return "Confirm it's you first."
        if minutes in IDLE_CHOICES:
            self.store.set_setting(IDLE, minutes)
        return ""

    # ---- Touch ID (WebAuthn, platform authenticator, localhost) ---------------------------

    def challenge(self, purpose: str, cred_id: str = "") -> str:
        now = self._now()
        self._challenges = {c: v for c, v in self._challenges.items() if v[1] > now}
        token = b64e(secrets.token_bytes(32))
        self._challenges[token] = (purpose, now + CHALLENGE_FOR, cred_id)
        return token

    def _client(self, client_json: str, kind: str, origin: str) -> str:
        """The challenge's purpose when the browser's client data is genuine for this hub; '' otherwise."""
        try:
            data = json.loads(b64d(client_json))
        except (ValueError, TypeError):
            return ""
        if data.get("type") != kind or data.get("origin") != origin:
            return ""
        entry = self._challenges.pop(data.get("challenge", ""), None)
        return entry[0] if entry and entry[1] > self._now() else ""

    def register(self, origin: str, cred_id: str, public_key: str, client_json: str, label: str) -> str:
        """Save a passkey made in this browser. Needs a fresh proof (the PIN or Touch ID, just now). '' on success."""
        if not self.enabled:
            return "Turn the lock on first."
        if not self.proven():
            return "Confirm it's you first."
        if self._client(client_json, "webauthn.create", origin) != "register":
            return "That took too long. Try again."
        try:
            key = load_der_public_key(b64d(public_key))
        except ValueError:
            return "This browser did not give a usable key."
        if not isinstance(key, ec.EllipticCurvePublicKey):
            return "This browser did not give a usable key."
        creds = [c for c in self.credentials() if c["id"] != cred_id][-(CREDS_MAX - 1):]
        creds.append({"id": cred_id, "key": public_key, "label": " ".join(label.split())[:40] or "This browser",
                      "added": int(self._now())})
        self._save_credentials(creds)
        return ""

    def verify(self, origin: str, cred_id: str, auth_data: str, client_json: str, signature: str) -> str:
        """The purpose ('unlock' or 'confirm') when the signed answer is good; '' otherwise."""
        cred = next((c for c in self.credentials() if c["id"] == cred_id), None)
        purpose = self._client(client_json, "webauthn.get", origin)
        if not cred or purpose not in ("unlock", "confirm"):
            return ""
        try:
            data = b64d(auth_data)
            key = load_der_public_key(b64d(cred["key"]))
            if len(data) < 37 or data[:32] != hashlib.sha256(RP_ID.encode()).digest() or data[32] & 0x05 != 0x05:
                return ""  # wrong site, or no touch / no Touch ID check
            key.verify(b64d(signature), data + hashlib.sha256(b64d(client_json)).digest(), ec.ECDSA(hashes.SHA256()))
        except (ValueError, InvalidSignature, TypeError, AttributeError):
            return ""
        return purpose

    def unlock_with_key(self, *args) -> bool:
        if self.verify(*args) != "unlock":
            return False
        self._open()
        self._prove()
        return True

    def prove_with_key(self, *args) -> bool:
        if self.verify(*args) != "confirm":
            return False
        self._prove()
        return True

    def forget_credential(self, cred_id: str) -> str:
        if not self.proven():
            return "Confirm it's you first."
        self._save_credentials([c for c in self.credentials() if c["id"] != cred_id])
        return ""
