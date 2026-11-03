# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography", "coincurve", "websockets"]
# ///
"""S9a spike: board events on public Nostr relays.

Throwaway. Makes a test identity (secp256k1, as Nostr requires) and a test board
key, seals small board events plus larger ones (a card with a thumbnail inside)
with the board key, publishes them to three relays and reads them back by the
board's tag. Nothing from the library is sent: the cards are made up.

    uv run spikes/S9a/nostr.py            # publish and read back now
    uv run spikes/S9a/nostr.py --check    # later: what each relay still has

State (test keys, event ids) goes to spikes/S9a/state.json, which git ignores.
"""

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from coincurve import PrivateKey, PublicKeyXOnly
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from websockets.sync.client import connect

RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]
KIND = 4917  # a regular (stored) kind with no public meaning, so no app shows these
STATE = Path(__file__).with_name("state.json")
SIZES = {"event": 0, "card 16 KB": 16_000, "card 40 KB (thumbnail)": 40_000, "card 100 KB": 100_000}


def sign(secret, created, tags, content):
    pub = PublicKeyXOnly.from_secret(secret).format().hex()
    raw = json.dumps([0, pub, created, KIND, tags, content], separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(raw.encode()).hexdigest()
    sig = PrivateKey(secret).sign_schnorr(bytes.fromhex(eid)).hex()
    return {"id": eid, "pubkey": pub, "created_at": created, "kind": KIND, "tags": tags, "content": content, "sig": sig}


def seal(board_key, plain):
    nonce = os.urandom(12)
    return base64.b64encode(nonce + ChaCha20Poly1305(board_key).encrypt(nonce, plain, None)).decode()


def unseal(board_key, text):
    raw = base64.b64decode(text)
    return ChaCha20Poly1305(board_key).decrypt(raw[:12], raw[12:], None)


def publish(relay, event):
    start = time.monotonic()
    try:
        with connect(relay, open_timeout=10, close_timeout=2, max_size=2**22) as ws:
            ws.send(json.dumps(["EVENT", event]))
            while True:
                msg = json.loads(ws.recv(timeout=15))
                if msg[0] == "OK" and msg[1] == event["id"]:
                    return msg[2], msg[3], time.monotonic() - start
    except Exception as err:
        return False, f"{type(err).__name__}: {err}"[:120], time.monotonic() - start


def fetch(relay, tag):
    found = {}
    try:
        with connect(relay, open_timeout=10, close_timeout=2, max_size=2**22) as ws:
            ws.send(json.dumps(["REQ", "s", {"kinds": [KIND], "#b": [tag], "limit": 100}]))
            while True:
                msg = json.loads(ws.recv(timeout=15))
                if msg[0] == "EVENT":
                    found[msg[2]["id"]] = msg[2]
                elif msg[0] in ("EOSE", "CLOSED"):
                    return found, (msg[2] if msg[0] == "CLOSED" else "")
    except Exception as err:
        return found, f"{type(err).__name__}: {err}"[:120]


def run():
    secret, board_key = os.urandom(32), ChaCha20Poly1305.generate_key()
    tag = hashlib.sha256(b"magpiary-board:" + board_key).hexdigest()[:32]  # board id relays can index, not the key
    sent = {}
    for relay in RELAYS:
        print(relay)
        for n, (label, size) in enumerate(SIZES.items()):
            card = {"seq": n + 1, "type": "add", "url": f"https://www.instagram.com/reel/TEST{n}/", "title": "Spike card",
                    "thumb": base64.b64encode(os.urandom(size)).decode() if size else ""}
            event = sign(secret, int(time.time()), [["b", tag]], seal(board_key, json.dumps(card).encode()))
            ok, note, secs = publish(relay, event)
            print(f"  {label:24} {len(json.dumps(event)) // 1000:>4} KB  {'accepted' if ok else 'REFUSED'} {secs:.1f}s {note}")
            if ok:
                sent.setdefault(relay, []).append({"id": event["id"], "label": label})
    STATE.write_text(json.dumps({"secret": secret.hex(), "board_key": board_key.hex(), "tag": tag,
                                 "published": int(time.time()), "sent": sent}, indent=1))
    time.sleep(3)
    check()


def check():
    state = json.loads(STATE.read_text())
    board_key, age = bytes.fromhex(state["board_key"]), (time.time() - state["published"]) / 86400
    print(f"\nRead back, {age:.1f} days after publishing:")
    for relay in RELAYS:
        found, note = fetch(relay, state["tag"])
        wanted = state["sent"].get(relay, [])
        kept = [s["label"] for s in wanted if s["id"] in found]
        opened = sum(1 for e in found.values() if json.loads(unseal(board_key, e["content"]))["title"] == "Spike card")
        print(f"  {relay:24} kept {len(kept)}/{len(wanted)} accepted, all opened with the board key: {opened == len(found)} {note}")
        missing = [s["label"] for s in wanted if s["id"] not in found]
        if missing:
            print("    missing:", ", ".join(missing))


if __name__ == "__main__":
    check() if "--check" in sys.argv else run()
