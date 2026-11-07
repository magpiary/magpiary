"""Phone access to the library over the home network (docs/specs.md, "Phone access to the library on the local network").

Three things live here and nothing else:
- Our own certificate authority, name-constrained to `.local`, and the short-lived server certificate it signs.
  The CA key never leaves this Mac (mode 0600, created private from the first byte). The server certificate lasts
  under 398 days (iOS refuses longer) and is remade when it is close to ending or the names change.
- The paired phones: one random key per phone, kept only as a SHA-256 hash, shown to the phone once as a cookie.
- The access log: pairs, visits, refusals, with the reason. Never the key.

The on/off switch is the setting `phone_access` (off unless it is "1").
"""

import hashlib
import hmac
import ipaddress
import os
import secrets
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from magpiary.config import config_dir

SETTING = "phone_access"
NAME = "magpiary.local"
HTTPS_PORT_OFFSET = 100  # the phone door sits 100 above the hub's own port (8765 -> 8865), one per Mac account
CA_YEARS = 10
LEAF_DAYS = 397  # under 398: iOS refuses a longer certificate
RENEW_BEFORE_DAYS = 30
COOKIE = "mp_phone"
PAIR_FOR = 600  # seconds a pairing QR works
APP_FOR = 24 * 3600  # seconds the Home Screen hand-over link works (until its first launch)
LOG_KEEP = 500
SEEN_EVERY = 60  # seconds between "last seen" writes for one phone


def enabled(store) -> bool:
    return store.get_setting(SETTING, "") == "1"


def https_port(hub_port: int) -> int:
    return hub_port + HTTPS_PORT_OFFSET


def access_dir() -> Path:
    return config_dir() / "access"


def _write_private(path: Path, data: bytes) -> None:
    """Private from the first byte, replaced atomically (never a moment at a wider mode)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _now() -> datetime:
    return datetime.now(UTC)


def _make_ca(folder: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Magpiary local network CA"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Magpiary")])
    now = _now()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(days=365 * CA_YEARS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            # only names ending in .local can ever be vouched for by this authority, whatever happens to its key
            .add_extension(x509.NameConstraints(permitted_subtrees=[x509.DNSName(".local")], excluded_subtrees=None),
                           critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(folder / "ca.key", _key_pem(key))
    _write_private(folder / "ca.pem", cert.public_bytes(serialization.Encoding.PEM))


def ca_certificate(folder: Path | None = None) -> x509.Certificate:
    """The authority's certificate, made on first use."""
    folder = folder or access_dir()
    if not (folder / "ca.key").exists() or not (folder / "ca.pem").exists():
        _make_ca(folder)
    return x509.load_pem_x509_certificate((folder / "ca.pem").read_bytes())


def ca_pem(folder: Path | None = None) -> bytes:
    """The public certificate a phone installs (never the key)."""
    return ca_certificate(folder).public_bytes(serialization.Encoding.PEM)


def ca_der(folder: Path | None = None) -> bytes:
    return ca_certificate(folder).public_bytes(serialization.Encoding.DER)


def fingerprint(cert: x509.Certificate) -> str:
    """SHA-256 of the certificate as iOS shows it in the certificate's details: pairs of hex, spaced."""
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return " ".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def ca_fingerprint(folder: Path | None = None) -> str:
    return fingerprint(ca_certificate(folder))


def _leaf_ok(cert: x509.Certificate, names: list[str], ca: x509.Certificate) -> bool:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        return False
    if set(san) != set(names) or cert.issuer != ca.subject:
        return False
    return cert.not_valid_after_utc - _now() > timedelta(days=RENEW_BEFORE_DAYS)


def server_files(names: list[str], folder: Path | None = None) -> tuple[Path, Path]:
    """(certificate chain, key) for the HTTPS door. Made, or remade when it is near its end or the names changed."""
    folder = folder or access_dir()
    ca = ca_certificate(folder)
    names = sorted({n.lower() for n in names if n.lower().endswith(".local")} | {NAME})
    cert_path, key_path = folder / "server.pem", folder / "server.key"
    if cert_path.exists() and key_path.exists():
        try:
            if _leaf_ok(x509.load_pem_x509_certificate(cert_path.read_bytes()), names, ca):
                return cert_path, key_path
        except ValueError:
            pass
    ca_key = serialization.load_pem_private_key((folder / "ca.key").read_bytes(), None)
    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(days=LEAF_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    # the key first, then the chain: a reader never pairs a new chain with an old key for longer than one swap
    _write_private(key_path, _key_pem(key))
    _write_private(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def forget_authority(folder: Path | None = None) -> None:
    """Delete the authority and the server certificate (phones must install the new one). Paired keys stay valid."""
    folder = folder or access_dir()
    for n in ("ca.key", "ca.pem", "server.key", "server.pem"):
        (folder / n).unlink(missing_ok=True)


# ---- paired phones and the access log ------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS paired_devices (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
    paired_at TEXT NOT NULL, last_seen TEXT, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, device_id INTEGER, kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS app_tokens (token_hash TEXT PRIMARY KEY, device_id INTEGER NOT NULL, expires REAL NOT NULL);
"""


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Devices:
    """Paired phones and the log, on the hub's own database connection and lock."""

    def __init__(self, store, now=None) -> None:
        self.store = store
        self._now = now or (lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
        self._pairs: dict[str, float] = {}  # one-time pairing tokens -> expiry (monotonic seconds)
        self._lock = threading.Lock()
        self._seen: dict[int, float] = {}
        with store._lock:
            store._db.executescript(SCHEMA)

    # ---- pairing tokens (one use, ten minutes, memory only) ----

    def new_pair_token(self, clock: float | None = None) -> str:
        import time

        token = secrets.token_urlsafe(18)
        with self._lock:
            now = clock if clock is not None else time.monotonic()
            self._pairs = {t: exp for t, exp in self._pairs.items() if exp > now}
            self._pairs[token] = now + PAIR_FOR
        return token

    def pair_token_valid(self, token: str, clock: float | None = None) -> bool:
        import time

        with self._lock:
            now = clock if clock is not None else time.monotonic()
            return any(hmac.compare_digest(token.encode(), t.encode()) and exp > now for t, exp in self._pairs.items())

    def spend_pair_token(self, token: str, clock: float | None = None) -> bool:
        import time

        with self._lock:
            now = clock if clock is not None else time.monotonic()
            for t in list(self._pairs):
                if hmac.compare_digest(token.encode(), t.encode()):
                    exp = self._pairs.pop(t)
                    return exp > now
            return False

    # ---- the Home Screen app: iOS keeps its cookies apart from Safari's, so it claims its own key once ----

    def new_app_token(self, device_id: int, wall: float | None = None) -> str:
        import time

        token = secrets.token_urlsafe(24)
        now = wall if wall is not None else time.time()
        with self.store._lock, self.store._db:
            self.store._db.execute("DELETE FROM app_tokens WHERE expires < ?", (now,))
            self.store._db.execute("INSERT INTO app_tokens VALUES (?,?,?)", (_hash(token), device_id, now + APP_FOR))
        return token

    def app_token_device(self, token: str, wall: float | None = None) -> dict | None:
        """The paired phone a hand-over link was made for (not spent), if the link is live and the phone not revoked."""
        import time

        now = wall if wall is not None else time.time()
        with self.store._lock:
            row = self.store._db.execute(
                "SELECT d.id, d.name FROM app_tokens t JOIN paired_devices d ON d.id = t.device_id "
                "WHERE t.token_hash=? AND t.expires>? AND d.revoked_at IS NULL", (_hash(token), now)).fetchone()
        return dict(row) if row else None

    def claim_app_token(self, token: str, agent: str = "", wall: float | None = None) -> tuple[int, str] | None:
        """Spend a hand-over link: the Home Screen app gets its own key (listed as "<phone> app"). Once only."""
        device = self.app_token_device(token, wall)
        if device is None:
            return None
        with self.store._lock, self.store._db:
            gone = self.store._db.execute("DELETE FROM app_tokens WHERE token_hash=?", (_hash(token),)).rowcount
        if not gone:
            return None
        name = device["name"] if device["name"].endswith(" app") else device["name"] + " app"
        return self.add(name, agent)

    # ---- phones ----

    def add(self, name: str, agent: str = "") -> tuple[int, str]:
        """Pair a phone. Returns (id, key); the key is not kept anywhere else."""
        key = secrets.token_urlsafe(32)
        name = " ".join(name.split())[:40] or "iPhone"
        with self.store._lock, self.store._db:
            cur = self.store._db.execute(
                "INSERT INTO paired_devices (name, key_hash, agent, paired_at) VALUES (?,?,?,?)",
                (name, _hash(key), agent[:200], self._now()))
        self.log("paired", cur.lastrowid, name)
        return cur.lastrowid, key

    def check(self, key: str) -> dict | None:
        """The active phone this key belongs to, or None (unknown or revoked)."""
        if not key:
            return None
        with self.store._lock:
            row = self.store._db.execute(
                "SELECT id, name, paired_at, last_seen FROM paired_devices WHERE key_hash=? AND revoked_at IS NULL",
                (_hash(key),)).fetchone()
        return dict(row) if row else None

    def touch(self, device_id: int, address: str = "", clock: float | None = None) -> bool:
        """Note a visit. True the first time this phone shows up since the service started (a new connection)."""
        import time

        now = clock if clock is not None else time.monotonic()
        first = device_id not in self._seen
        if first or now - self._seen[device_id] >= SEEN_EVERY:
            self._seen[device_id] = now
            with self.store._lock, self.store._db:
                self.store._db.execute("UPDATE paired_devices SET last_seen=? WHERE id=?", (self._now(), device_id))
            if first:
                self.log("connected", device_id, address=address)
        return first

    def revoke(self, device_id: int) -> bool:
        with self.store._lock, self.store._db:
            cur = self.store._db.execute(
                "UPDATE paired_devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (self._now(), device_id))
        self._seen.pop(device_id, None)
        if cur.rowcount:
            self.log("revoked", device_id)
        return bool(cur.rowcount)

    def revoke_all(self) -> int:
        n = 0
        for d in self.active():
            n += self.revoke(d["id"])
        return n

    def active(self) -> list[dict]:
        with self.store._lock:
            rows = self.store._db.execute(
                "SELECT id, name, paired_at, last_seen FROM paired_devices WHERE revoked_at IS NULL ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---- the log ----

    def log(self, kind: str, device_id: int | None = None, detail: str = "", address: str = "") -> None:
        """kind: paired, connected, revoked, refused. `detail` is a reason, never a key or a cookie."""
        with self.store._lock, self.store._db:
            self.store._db.execute("INSERT INTO access_log (at, device_id, kind, detail, address) VALUES (?,?,?,?,?)",
                                   (self._now(), device_id, kind, detail[:200], address[:64]))
            self.store._db.execute(
                "DELETE FROM access_log WHERE id <= (SELECT MAX(id) FROM access_log) - ?", (LOG_KEEP,))

    def recent(self, limit: int = 50) -> list[dict]:
        with self.store._lock:
            rows = self.store._db.execute(
                "SELECT l.at, l.kind, l.detail, l.address, d.name AS device FROM access_log l "
                "LEFT JOIN paired_devices d ON d.id = l.device_id ORDER BY l.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def refused_count(self, since: str = "") -> int:
        with self.store._lock:
            return self.store._db.execute("SELECT COUNT(*) FROM access_log WHERE kind='refused' AND at>=?",
                                          (since,)).fetchone()[0]


def is_private_address(address: str) -> bool:
    """A phone on the home network: private, link-local or loopback. Anything else (a public address) is refused
    even with a paired key, so a forwarded port on the router does not expose the library."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local
