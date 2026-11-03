"""Where shared boards sync (M9): two connectors behind one interface.

A board is a set of per-member logs. Each member's Mac publishes its own new events, sealed with the board key, and
fetches everyone else's. The connectors only carry sealed bytes; what is inside is checked when the board is replayed.

- **Nostr** (the default): sealed events go to a few public relays, signed with this Mac's identity key, tagged with a
  board tag (a hash of the board key, so relays can find a board's events without being able to open them). Nobody
  signs up for anything. Relays may drop old events or refuse large ones (spike S9a: one relay refused 71 KB), so an
  event stays under EVENT_MAX.
- **Own bucket** (for groups that want dependable sync): a storage bucket the board creator owns, over the S3
  protocol: Backblaze B2 first, Cloudflare R2 and other S3 services through the same code. Layout:
  `boards/<board>/members/<member>/<seq>.bin`.

Requests are made with the standard library (S3 is signed with SigV4 here) and the websockets library for relays.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from magpiary import identity
from magpiary.network import public_urlopen

KIND = 4917  # a regular (stored) Nostr kind with no public meaning, so no Nostr app shows board events
RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]  # all three passed spike S9a
EVENT_MAX = 48_000  # bytes of sealed content per event: under every default relay's limit
SLACK = 3600  # seconds fetched again before the last fetch, for relays that receive events late
TIMEOUT = 15


class SyncError(Exception):
    """A connector could not do what was asked; the message is safe to show (it never holds a key)."""


# ---- sealing ---------------------------------------------------------------------------------------

def new_board_key() -> bytes:
    return ChaCha20Poly1305.generate_key()


def board_tag(board_key: bytes) -> str:
    """What relays index a board's events by: says which board, not what is in it, and not the key."""
    return hashlib.sha256(b"magpiary-board:" + board_key).hexdigest()[:32]


def seal(board_key: bytes, plain: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + ChaCha20Poly1305(board_key).encrypt(nonce, plain, None)


def unseal(board_key: bytes, sealed: bytes) -> bytes:
    """Raises ValueError when the bytes were not sealed with this key or were changed."""
    try:
        return ChaCha20Poly1305(board_key).decrypt(sealed[:12], sealed[12:], None)
    except Exception as err:
        raise ValueError("not sealed with this board key") from err


# ---- what both connectors give back ----------------------------------------------------------------

@dataclass
class Fetched:
    member: str      # the member's public key (Nostr: the signer; bucket: the folder it was written to)
    seq: int
    sealed: bytes
    ref: str = ""    # Nostr event id or bucket file name, to skip what was already read


@dataclass
class Status:
    ok: bool
    detail: str
    parts: list = field(default_factory=list)  # (name, ok, detail) per relay or step


# ---- Nostr -----------------------------------------------------------------------------------------

def _connect(url: str):
    from websockets.sync.client import connect

    return connect(url, open_timeout=10, close_timeout=2, max_size=2 ** 22)


def make_event(created: int, tags: list, content: str, kind: int = KIND) -> dict:
    public = identity.public_key()
    raw = json.dumps([0, public, created, kind, tags, content], separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode()).digest()
    return {"id": digest.hex(), "pubkey": public, "created_at": created, "kind": kind, "tags": tags,
            "content": content, "sig": identity.sign_digest(digest)}


def event_valid(ev: dict) -> bool:
    """The id matches the content and the signature matches the id: relays are not trusted."""
    try:
        raw = json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
                         separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode()).digest()
        return digest.hex() == ev["id"] and identity.verify_digest(ev["pubkey"], digest, ev["sig"])
    except (KeyError, TypeError, ValueError):
        return False


class Nostr:
    name = "Nostr relays"

    def __init__(self, relays: list[str] | None = None, connect=None, clock=time.time):
        self.relays, self.connect, self.clock = list(relays or RELAYS), connect or _connect, clock

    def publish(self, board: bytes, seq: int, sealed: bytes) -> int:
        """Send one event to every relay. Returns how many took it; SyncError when none did."""
        if len(sealed) > EVENT_MAX:
            raise SyncError(f"Too large for the relays ({len(sealed) // 1000} KB); split it up.")
        event = make_event(int(self.clock()), [["b", board_tag(board)], ["seq", str(seq)]],
                           base64.b64encode(sealed).decode())
        took, why = 0, []
        for relay in self.relays:
            ok, note = self._send(relay, event)
            took += ok
            if not ok:
                why.append(f"{_host(relay)}: {note}")
        if not took:
            raise SyncError("No relay took it (" + "; ".join(why) + ").")
        return took

    def _send(self, relay: str, event: dict) -> tuple[bool, str]:
        try:
            with self.connect(relay) as ws:
                ws.send(json.dumps(["EVENT", event]))
                while True:
                    msg = json.loads(ws.recv(timeout=TIMEOUT))
                    if msg[0] == "OK" and msg[1] == event["id"]:
                        return bool(msg[2]), str(msg[3])[:120]
        except Exception as err:
            return False, _why(err)

    def fetch(self, board: bytes, since: int = 0, seen: set | None = None) -> list[Fetched]:
        """Every valid event of the board from all relays since a moment (less SLACK), each once."""
        seen = set(seen or ())
        tag, out, reached = board_tag(board), [], 0
        query = {"kinds": [KIND], "#b": [tag], "limit": 5000}
        if since:
            query["since"] = max(0, since - SLACK)
        for relay in self.relays:
            try:
                with self.connect(relay) as ws:
                    ws.send(json.dumps(["REQ", "m", query]))
                    while True:
                        msg = json.loads(ws.recv(timeout=TIMEOUT))
                        if msg[0] in ("EOSE", "CLOSED"):
                            break
                        if msg[0] != "EVENT":
                            continue
                        ev = msg[2]
                        if ev.get("id") in seen or not event_valid(ev) or ["b", tag] not in ev.get("tags", []):
                            continue
                        seq = next((int(t[1]) for t in ev["tags"] if t[:1] == ["seq"] and str(t[1]).isdigit()), 0)
                        try:
                            sealed = base64.b64decode(ev["content"], validate=True)
                        except ValueError:
                            continue
                        seen.add(ev["id"])
                        out.append(Fetched(ev["pubkey"], seq, sealed, ev["id"]))
                reached += 1
            except Exception:
                continue
        if not reached:
            raise SyncError("No relay could be reached. Is this Mac online?")
        return out

    def park(self, tag: str, sealed: bytes, created: int | None = None) -> str:
        """Leave one sealed note on the relays under a tag (an invite). Returns its event id, to delete it later."""
        event = make_event(int(created or self.clock()), [["i", tag]], base64.b64encode(sealed).decode())
        took = sum(self._send(relay, event)[0] for relay in self.relays)
        if not took:
            raise SyncError("No relay took the invite. Is this Mac online?")
        return event["id"]

    def my_parked(self) -> dict[str, str]:
        """This Mac's own notes still on the relays: event id → its tag."""
        me, found = identity.public_key(), {}
        for relay in self.relays:
            try:
                with self.connect(relay) as ws:
                    ws.send(json.dumps(["REQ", "o", {"kinds": [KIND], "authors": [me], "limit": 500}]))
                    while True:
                        msg = json.loads(ws.recv(timeout=TIMEOUT))
                        if msg[0] in ("EOSE", "CLOSED"):
                            break
                        ev = msg[2] if msg[0] == "EVENT" else {}
                        tag = next((x[1] for x in ev.get("tags", []) if x[:1] == ["i"] and len(x) > 1), "")
                        if tag and event_valid(ev) and ev["pubkey"] == me:
                            found[ev["id"]] = tag
            except Exception:
                continue
        return found

    def delete(self, event_ids: list[str]) -> int:
        """Ask the relays to delete some of this Mac's own notes (Nostr's deletion request, NIP-09). Returns how many
        relays took the request; a relay that ignores it keeps the sealed notes, which nobody can open anyway."""
        if not event_ids:
            return 0
        event = make_event(int(self.clock()), [["e", i] for i in event_ids] + [["k", str(KIND)]], "", kind=5)
        return sum(self._send(relay, event)[0] for relay in self.relays)

    def find_parked(self, tag: str) -> list[bytes]:
        """Every note parked under a tag, newest first (signatures checked)."""
        return [sealed for _, sealed in self.find_parked_from(tag)]

    def find_parked_from(self, tag: str) -> list[tuple[str, bytes]]:
        """Every note parked under a tag with who signed it, newest first (signatures checked)."""
        found, reached = {}, 0
        for relay in self.relays:
            try:
                with self.connect(relay) as ws:
                    ws.send(json.dumps(["REQ", "p", {"kinds": [KIND], "#i": [tag], "limit": 20}]))
                    while True:
                        msg = json.loads(ws.recv(timeout=TIMEOUT))
                        if msg[0] in ("EOSE", "CLOSED"):
                            break
                        if msg[0] == "EVENT" and event_valid(msg[2]) and ["i", tag] in msg[2].get("tags", []):
                            found[msg[2]["id"]] = msg[2]
                reached += 1
            except Exception:
                continue
        if not reached:
            raise SyncError("No relay could be reached. Is this Mac online?")
        out = []
        for ev in sorted(found.values(), key=lambda e: -e["created_at"]):
            try:
                out.append((ev["pubkey"], base64.b64decode(ev["content"], validate=True)))
            except ValueError:
                continue
        return out

    def check(self) -> Status:
        parts = []
        for relay in self.relays:
            start = time.monotonic()
            try:
                with self.connect(relay) as ws:
                    ws.send(json.dumps(["REQ", "c", {"kinds": [KIND], "limit": 1}]))
                    while json.loads(ws.recv(timeout=TIMEOUT))[0] not in ("EOSE", "CLOSED"):
                        pass
                parts.append((_host(relay), True, f"{time.monotonic() - start:.1f} s"))
            except Exception as err:
                parts.append((_host(relay), False, _why(err)))
        up = sum(ok for _, ok, _ in parts)
        return Status(up > 0, f"{up} of {len(parts)} relays answered", parts)


# ---- own bucket (S3) ---------------------------------------------------------------------------------

def http_call(method: str, url: str, body: bytes | None, headers: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with public_urlopen(req, timeout=30, redirects=False) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except (urllib.error.URLError, OSError) as err:
        raise SyncError(f"Could not reach the storage service ({_why(err)}).") from err


class Bucket:
    """One bucket over S3, path-style requests signed with SigV4."""

    name = "Own bucket"

    def __init__(self, endpoint: str, key_id: str, secret: str, bucket: str, region: str = "", call=http_call,
                 now=lambda: datetime.datetime.now(datetime.UTC)):
        self.endpoint, self.key_id, self.secret, self.bucket = endpoint.rstrip("/"), key_id, secret, bucket
        self.host = urllib.parse.urlparse(self.endpoint).netloc
        self.region = region or _region(self.host)
        self.call, self.now = call, now

    def _request(self, method: str, key: str = "", query: dict | None = None, body: bytes = b"") -> tuple[int, bytes]:
        stamp = self.now()
        amz, day = stamp.strftime("%Y%m%dT%H%M%SZ"), stamp.strftime("%Y%m%d")
        payload = hashlib.sha256(body).hexdigest()
        path = urllib.parse.quote(f"/{self.bucket}" + (f"/{key}" if key else ""))
        canon_query = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
                               for k, v in sorted((query or {}).items()))
        headers = {"host": self.host, "x-amz-content-sha256": payload, "x-amz-date": amz}
        signed = ";".join(sorted(headers))
        canonical = "\n".join([method, path, canon_query, *(f"{k}:{headers[k]}" for k in sorted(headers)), "",
                               signed, payload])
        scope = f"{day}/{self.region}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = ("AWS4" + self.secret).encode()
        for part in (day, self.region, "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={signed}, "
                                    f"Signature={signature}")
        del headers["host"]
        url = self.endpoint + path + (f"?{canon_query}" if canon_query else "")
        return self.call(method, url, body if method == "PUT" else None, headers)

    def publish(self, board: bytes, seq: int, sealed: bytes) -> int:
        key = f"boards/{board_tag(board)}/members/{identity.public_key()}/{seq}.bin"
        status, _ = self._request("PUT", key, body=sealed)
        if status != 200:
            raise SyncError(_refusal(status))
        return 1

    def _list(self, prefix: str) -> list[str]:
        names, token = [], ""
        while True:
            query = {"list-type": "2", "prefix": prefix, **({"continuation-token": token} if token else {})}
            status, body = self._request("GET", query=query)
            if status != 200:
                raise SyncError(_refusal(status))
            text = body.decode("utf-8", "replace")
            names += re.findall(r"<Key>([^<]+)</Key>", text)
            more = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
            if not more:
                return names
            token = more.group(1)

    def fetch(self, board: bytes, since: int = 0, seen: set | None = None) -> list[Fetched]:
        """Every member file of the board not read yet."""
        seen, out, me = set(seen or ()), [], identity.public_key()
        for name in self._list(f"boards/{board_tag(board)}/members/"):
            m = re.fullmatch(r"boards/[0-9a-f]+/members/([0-9a-f]{64})/(\d+)\.bin", name)
            if not m or name in seen or m.group(1) == me:  # this Mac's own files are already here
                continue
            status, body = self._request("GET", name)
            if status != 200:
                continue
            out.append(Fetched(m.group(1), int(m.group(2)), body, name))
        return out

    def check(self) -> Status:
        """Write, read back and remove one small file: proves the key, the bucket and the endpoint."""
        probe = f"boards/check/{os.urandom(6).hex()}.bin"
        steps = []
        for label, method, body in (("write", "PUT", b"magpiary"), ("read", "GET", b""), ("remove", "DELETE", b"")):
            try:
                status, got = self._request(method, probe, body=body)
            except SyncError as err:
                steps.append((label, False, str(err)))
                break
            good = status in (200, 204) and (method != "GET" or got == b"magpiary")
            steps.append((label, good, "ok" if good else _refusal(status)))
            if not good:
                break
        ok = len(steps) == 3 and all(s[1] for s in steps)
        return Status(ok, "Works: it can write, read and remove." if ok else
                      next(f"Could not {s[0]}: {s[2]}" for s in steps if not s[1]), steps)


def _region(host: str) -> str:
    """s3.<region>.backblazeb2.com → <region>; Cloudflare R2 signs with "auto"."""
    if host.endswith(".r2.cloudflarestorage.com"):
        return "auto"
    m = re.match(r"s3[.-]([a-z0-9-]+)\.", host)
    return m.group(1) if m else "us-east-1"


def _refusal(status: int) -> str:
    return {401: "the key was refused", 403: "the key was refused, or it may not use this bucket",
            404: "no such bucket"}.get(status, f"the service answered {status}")


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc or url


def _why(err: Exception) -> str:
    return type(err).__name__  # exception messages may contain credentials or private request context


# ---- the owner's bucket settings ---------------------------------------------------------------------
# ~/.config/magpiary/storage.json (mode 0600). For Backblaze it holds the main key (only to make keys limited to the
# boards bucket, one per invite) and this Mac's own limited key, since B2's main key cannot use S3. Never shown again.

B2_AUTH = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"
PROVIDERS = {"b2": "Backblaze B2", "r2": "Cloudflare R2", "s3": "Another S3 service"}


def _settings_path():
    from magpiary.config import config_dir

    return config_dir() / "storage.json"


def load_bucket() -> dict | None:
    try:
        data = json.loads(_settings_path().read_text())
        return data if data.get("bucket") else None
    except (OSError, ValueError, AttributeError):
        return None


def _save_bucket(data: dict | None) -> None:
    path = _settings_path()
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    path.chmod(0o600)


def bucket_connector(data: dict | None = None, call=http_call) -> Bucket | None:
    data = data or load_bucket()
    if not data:
        return None
    return Bucket(data["endpoint"], data["key_id"], data["secret"], data["bucket"], call=call)


class B2:
    """Backblaze's own API, used with the main key only: the boards bucket and keys limited to it."""

    def __init__(self, key_id: str, key: str, call=http_call):
        token = base64.b64encode(f"{key_id}:{key}".encode()).decode()
        status, body = call("GET", B2_AUTH, None, {"Authorization": f"Basic {token}"})
        if status != 200:
            raise SyncError("Backblaze refused this key. Check you copied both parts." if status in (401, 403)
                            else f"Backblaze answered {status}.")
        auth = json.loads(body)
        api = auth["apiInfo"]["storageApi"]
        if "writeKeys" not in api.get("capabilities", []):
            raise SyncError("This key can't make keys for friends. Use the main key (Generate New Master Application Key).")
        self.account, self.api, self.s3 = auth["accountId"], api["apiUrl"] + "/b2api/v3/", api["s3ApiUrl"]
        self.token, self.call = auth["authorizationToken"], call

    def __call__(self, name: str, **body) -> dict:
        status, raw = self.call("POST", self.api + name, json.dumps(body).encode(),
                                {"Authorization": self.token, "Content-Type": "application/json"})
        if status != 200:
            try:
                message = json.loads(raw).get("message", "")
            except ValueError:
                message = ""
            raise SyncError(f"Backblaze: {message or status}")
        return json.loads(raw)

    def boards_bucket(self, wanted: str = "") -> dict:
        """The boards bucket: the one named, else an existing magpiary-boards-… one, else a new private one."""
        found = self("b2_list_buckets", accountId=self.account)["buckets"]
        for b in found:
            if b["bucketName"] == wanted or (not wanted and b["bucketName"].startswith("magpiary-boards-")):
                return b
        return self("b2_create_bucket", accountId=self.account, bucketName="magpiary-boards-" + os.urandom(5).hex(),
                    bucketType="allPrivate")

    def limited_key(self, bucket_id: str, name: str) -> dict:
        return self("b2_create_key", accountId=self.account, keyName=name, bucketId=bucket_id, namePrefix="boards/",
                    capabilities=["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"])

    def delete_key(self, key_id: str) -> None:
        self("b2_delete_key", applicationKeyId=key_id)


def connect_b2(key_id: str, key: str, call=http_call) -> str | None:
    """Check the main key, find or make the boards bucket and this Mac's limited key, then save. An error, or None."""
    key_id, key = key_id.strip(), key.strip()
    if not key_id or not key or any(c.isspace() for c in key_id + key):
        return "Paste both the keyID and the applicationKey."
    try:
        b2 = B2(key_id, key, call)
        bucket = b2.boards_bucket()
        mine = b2.limited_key(bucket["bucketId"], "magpiary-this-mac")
        data = {"provider": "b2", "endpoint": b2.s3, "bucket": bucket["bucketName"], "bucket_id": bucket["bucketId"],
                "key_id": mine["applicationKeyId"], "secret": mine["applicationKey"],
                "main_key_id": key_id, "main_key": key, "added": datetime.date.today().isoformat()}
        status = bucket_connector(data, call).check()
        if not status.ok:
            b2.delete_key(mine["applicationKeyId"])
            return status.detail
        before = load_bucket()
        if before and before.get("provider") == "b2" and before.get("key_id") != data["key_id"]:
            try:  # connected again: the earlier key for this Mac is not needed any more
                b2.delete_key(before["key_id"])
            except SyncError:
                pass
    except SyncError as err:
        return str(err)
    _save_bucket(data)
    return None


def connect_s3(provider: str, endpoint: str, key_id: str, secret: str, bucket: str, call=http_call) -> str | None:
    """Cloudflare R2 or another S3 service: a key the owner made for one bucket. An error, or None."""
    endpoint, key_id, secret, bucket = endpoint.strip(), key_id.strip(), secret.strip(), bucket.strip()
    if provider not in ("r2", "s3"):
        return "Pick a storage service."
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?/?", endpoint):
        return "The address should look like https://<account>.r2.cloudflarestorage.com"
    if not key_id or not secret or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        return "Fill in the key, its secret and the bucket's name."
    data = {"provider": provider, "endpoint": endpoint.rstrip("/"), "bucket": bucket, "key_id": key_id,
            "secret": secret, "added": datetime.date.today().isoformat()}
    status = bucket_connector(data, call).check()
    if not status.ok:
        return status.detail
    _save_bucket(data)
    return None


def remove_bucket(call=http_call) -> None:
    """Forget the bucket here. For Backblaze, this Mac's limited key is deleted too; the bucket and its boards stay."""
    data = load_bucket()
    if data and data.get("provider") == "b2":
        try:
            B2(data["main_key_id"], data["main_key"], call).delete_key(data["key_id"])
        except (SyncError, KeyError, ValueError):
            pass
    _save_bucket(None)


def saved_b2_env() -> tuple[str, str] | None:
    """A Backblaze key saved by hand in ~/.config/magpiary/b2.env (the M9 spike), offered once in Settings."""
    from magpiary.config import config_dir

    try:
        pairs = dict(line.split("=", 1) for line in (config_dir() / "b2.env").read_text().split() if "=" in line)
        return (pairs["B2_KEY_ID"], pairs["B2_APP_KEY"]) if pairs.get("B2_KEY_ID") and pairs.get("B2_APP_KEY") else None
    except OSError:
        return None


def forget_b2_env() -> None:
    from magpiary.config import config_dir

    (config_dir() / "b2.env").unlink(missing_ok=True)
