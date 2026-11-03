# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography"]
# ///
"""S9b spike: a board bucket on Backblaze B2, reached over the S3 protocol.

Throwaway. With the owner's main key (read from ~/.config/magpiary/b2.env, never
printed) it makes a private test bucket and a key limited to that bucket, as an
invite would. With the limited key only, it uploads sealed event files and a
thumbnail over S3, lists them, downloads and opens them. Then it checks the
limited key cannot reach anything else, deletes the key (removing a member) and
checks it stops working, and finally removes every file, the key and the bucket.

    uv run spikes/S9b/b2.py

S3 requests are signed with SigV4 written here on the standard library, to see
whether the connector needs any S3 client library at all.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

ENV = Path.home() / ".config" / "magpiary" / "b2.env"
AUTH = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"


def read_env():
    pairs = dict(line.split("=", 1) for line in ENV.read_text().split() if "=" in line)
    return pairs["B2_KEY_ID"], pairs["B2_APP_KEY"]


def call(url, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def authorize(key_id, key):
    token = base64.b64encode(f"{key_id}:{key}".encode()).decode()
    status, body = call(AUTH, headers={"Authorization": f"Basic {token}"})
    if status != 200:
        raise SystemExit(f"authorize failed: {status}")
    return json.loads(body)


class Native:
    """B2's own API, used only with the main key: buckets and keys."""

    def __init__(self, auth):
        self.account = auth["accountId"]
        self.api = auth["apiInfo"]["storageApi"]["apiUrl"] + "/b2api/v3/"
        self.token = auth["authorizationToken"]

    def __call__(self, name, **body):
        status, raw = call(self.api + name, body, {"Authorization": self.token, "Content-Type": "application/json"})
        if status != 200:
            raise SystemExit(f"{name} failed: {status} {raw[:200]!r}")
        return json.loads(raw)


class S3:
    """Path-style S3 requests signed with SigV4 (standard library only)."""

    def __init__(self, endpoint, key_id, key):
        self.endpoint, self.key_id, self.key = endpoint.rstrip("/"), key_id, key
        self.host = urllib.parse.urlparse(self.endpoint).netloc
        self.region = self.host.split(".")[1]  # s3.<region>.backblazeb2.com

    def request(self, method, path, query="", body=b""):
        now = datetime.datetime.now(datetime.UTC)
        stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        payload = hashlib.sha256(body).hexdigest()
        path = urllib.parse.quote(path)
        canon_query = "&".join(sorted(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
                                      for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)))
        headers = {"host": self.host, "x-amz-content-sha256": payload, "x-amz-date": stamp}
        signed = ";".join(sorted(headers))
        canonical = "\n".join([method, path, canon_query, *(f"{k}:{headers[k]}" for k in sorted(headers)), "", signed, payload])
        scope = f"{day}/{self.region}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = ("AWS4" + self.key).encode()
        for part in (day, self.region, "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
        url = self.endpoint + path + (f"?{canon_query}" if canon_query else "")
        return call(url, body if method == "PUT" else None, headers, method)


def seal(board_key, plain):
    nonce = os.urandom(12)
    return nonce + ChaCha20Poly1305(board_key).encrypt(nonce, plain, None)


def unseal(board_key, sealed):
    return ChaCha20Poly1305(board_key).decrypt(sealed[:12], sealed[12:], None)


def timed(label, fn):
    start = time.monotonic()
    out = fn()
    print(f"  {label}: {out[0] if isinstance(out, tuple) else 'ok'} in {time.monotonic() - start:.2f}s")
    return out


def main():
    main_auth = authorize(*read_env())
    print("Main key: accepted;", "can make keys" if "writeKeys" in main_auth["apiInfo"]["storageApi"]["capabilities"] else "CANNOT make keys")
    b2 = Native(main_auth)
    endpoint = main_auth["apiInfo"]["storageApi"]["s3ApiUrl"]
    print("S3 endpoint region:", urllib.parse.urlparse(endpoint).netloc.split(".")[1])

    name = "magpiary-spike-" + secrets.token_hex(6)
    bucket = b2("b2_create_bucket", accountId=b2.account, bucketName=name, bucketType="allPrivate")
    print("Test bucket made (private)")
    member = None
    try:
        member = b2("b2_create_key", accountId=b2.account, keyName="spike-member", bucketId=bucket["bucketId"],
                    namePrefix="boards/", capabilities=["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"])
        print("Member key made, limited to this bucket and boards/")
        s3 = S3(endpoint, member["applicationKeyId"], member["applicationKey"])
        board_key = ChaCha20Poly1305.generate_key()

        print("With the member key over S3:")
        events = [json.dumps({"seq": n, "type": "add", "url": f"https://www.instagram.com/reel/TEST{n}/",
                              "title": "Spike card", "at": time.time()}).encode() for n in range(1, 4)]
        for n, event in enumerate(events, 1):
            timed(f"upload event {n} ({len(event)} B sealed {len(seal(board_key, event))} B)",
                  lambda e=event, n=n: s3.request("PUT", f"/{name}/boards/b1/members/m1/{n}.bin", body=seal(board_key, e)))
        thumb = os.urandom(40_000)  # about a 400 px JPEG
        timed("upload thumbnail (40 KB)", lambda: s3.request("PUT", f"/{name}/boards/b1/thumbs/abc.bin", body=seal(board_key, thumb)))
        status, listing = timed("list member's events", lambda: s3.request("GET", f"/{name}", "list-type=2&prefix=boards/b1/members/"))
        print("  listed files:", listing.count(b"<Key>"))
        status, sealed = timed("download event 2", lambda: s3.request("GET", f"/{name}/boards/b1/members/m1/2.bin"))
        print("  opened with board key:", json.loads(unseal(board_key, sealed))["seq"] == 2)
        status, sealed = s3.request("GET", f"/{name}/boards/b1/thumbs/abc.bin")
        print("  thumbnail round trip intact:", unseal(board_key, sealed) == thumb)
        try:
            unseal(ChaCha20Poly1305.generate_key(), sealed)
            print("  wrong key opened it: YES (bad)")
        except Exception:
            print("  a wrong board key cannot open it: yes")

        print("Limits of the member key:")
        print("  write outside boards/:", s3.request("PUT", f"/{name}/other.bin", body=b"x")[0], "(want 403)")
        print("  make a bucket:", s3.request("PUT", f"/{name}-x")[0], "(want 403)")

        print("Removing the member (deleting their key):")
        b2("b2_delete_key", applicationKeyId=member["applicationKeyId"])
        member = None
        for wait in (0, 5, 30):
            time.sleep(wait)
            code = s3.request("GET", f"/{name}", "list-type=2&prefix=boards/")[0]
            print(f"  after {wait}s more, member key gets: {code}")
            if code in (401, 403):
                break
    finally:
        if member:
            b2("b2_delete_key", applicationKeyId=member["applicationKeyId"])
        versions = b2("b2_list_file_versions", bucketId=bucket["bucketId"], maxFileCount=1000)["files"]
        for f in versions:
            b2("b2_delete_file_version", fileName=f["fileName"], fileId=f["fileId"])
        b2("b2_delete_bucket", accountId=b2.account, bucketId=bucket["bucketId"])
        left = [b["bucketName"] for b in b2("b2_list_buckets", accountId=b2.account)["buckets"] if b["bucketName"].startswith("magpiary-spike-")]
        print(f"Cleaned up: {len(versions)} files, key and bucket deleted; spike buckets left: {len(left)}")


if __name__ == "__main__":
    main()
