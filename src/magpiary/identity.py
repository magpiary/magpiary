"""Who this Magpiary is on shared boards (M9): a key pair and a profile.

The key pair is made on this Mac the first time it is needed and is the account: board events are signed with it, so
nobody can act as someone else and no server is needed. It is a secp256k1 key with Schnorr signatures, as Nostr
requires, so the same key works on Nostr relays and in a board's own bucket. The secret lives in
~/.config/magpiary/identity.key (mode 0600) and is never shown, logged or sent; only the public key travels.

The profile is a name, a photo (shrunk to 256 px on this Mac) and a colour. Friends see it next to the cards you add.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from coincurve import PrivateKey, PublicKey, PublicKeyXOnly

from magpiary.config import config_dir, data_dir

NAME = "profile_name"
COLOUR = "profile_colour"
ABOUT = "profile_about"
LINKS = "profile_links"
TOPICS_HIDDEN = "profile_topics_hidden"  # pile names the owner took off their profile
TOPICS_ADDED = "profile_topics_added"  # topics the owner typed
NAME_MAX = 40
ABOUT_MAX = 160
TOPICS_MAX = 8
TOPIC_LEN = 32
LINK_SLOTS = ("website", "instagram", "x", "github")  # fixed slots (owner, 27 Oct 2026)
HANDLE = {"instagram": re.compile(r"^[A-Za-z0-9._]{1,30}$"), "x": re.compile(r"^[A-Za-z0-9_]{1,15}$"),
          "github": re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")}
LINK_HOST = {"instagram": "https://www.instagram.com/", "x": "https://x.com/", "github": "https://github.com/"}
PHOTO_SIZE = 256
PHOTO_MAX = 400_000  # bytes of the picture the page sends, before it is shrunk again here
COLOURS = {"#ff2e93": "Pink", "#2f6bff": "Blue", "#8a3ffc": "Purple", "#00a37a": "Green",
           "#f5a300": "Amber", "#e04b00": "Orange", "#0091b3": "Teal", "#ff4f2b": "Red",
           # eight more (owner, 27 Oct 2026): twice the choice for a board's folder and a person's colour
           "#8ab32d": "Lime", "#c026d3": "Magenta", "#4f46e5": "Indigo", "#64748b": "Slate",
           "#22a14b": "Forest", "#e11d48": "Berry", "#0284c7": "Ocean", "#c8a26b": "Sand"}


def _key_path() -> Path:
    return config_dir() / "identity.key"


def _secret() -> bytes:
    """This Mac's secret key, made on first use."""
    path = _key_path()
    try:
        secret = bytes.fromhex(path.read_text().strip())
        if len(secret) == 32:
            return secret
    except (OSError, ValueError):
        pass
    if path.exists():  # unreadable or damaged: never replace an identity silently
        raise RuntimeError(f"{path} is damaged; move it away to make a new identity")
    secret = PrivateKey().secret
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secret.hex())
    return secret


def exists() -> bool:
    return _key_path().exists()


def public_key() -> str:
    """The public key as 64 hex characters (a Nostr public key)."""
    return PublicKeyXOnly.from_secret(_secret()).format().hex()


def short_id(public: str | None = None) -> str:
    """A short, readable form of a public key, for telling two people with the same name apart."""
    public = public or public_key()
    return "-".join(public[i:i + 4] for i in (0, 4, 8)).upper()


def sign(message: bytes) -> str:
    """A Schnorr signature (hex) over the message's SHA-256."""
    return PrivateKey(_secret()).sign_schnorr(hashlib.sha256(message).digest()).hex()


def verify(public: str, message: bytes, signature: str) -> bool:
    return verify_digest(public, hashlib.sha256(message).digest(), signature)


def sign_digest(digest: bytes) -> str:
    """A Schnorr signature over a 32-byte digest as it is (a Nostr event id)."""
    return PrivateKey(_secret()).sign_schnorr(digest).hex()


def verify_digest(public: str, digest: bytes, signature: str) -> bool:
    try:
        return PublicKeyXOnly(bytes.fromhex(public)).verify(bytes.fromhex(signature), digest)
    except (ValueError, TypeError):
        return False


def shared_key(public: str) -> bytes:
    """A 32-byte secret only this Mac and the owner of `public` can work out (ECDH on the x coordinate, so the
    sign of the other point does not matter): used to hand a new board key to each remaining member."""
    point = PublicKey(b"\x02" + bytes.fromhex(public)).multiply(_secret())
    return hashlib.sha256(b"magpiary-shared:" + point.format()[1:]).digest()


# ---- the profile ---------------------------------------------------------------------------------

def photo_path() -> Path:
    return data_dir() / "profile" / "photo.jpg"


def profile(store) -> dict:
    colour = store.get_setting(COLOUR, "")
    return {"name": store.get_setting(NAME, ""), "colour": colour if colour in COLOURS else next(iter(COLOURS)),
            "photo": photo_path().exists(), "about": store.get_setting(ABOUT, ""), "links": _json(store, LINKS, {}),
            "topics": topics(store)}


def set_name(store, name: str) -> None:
    store.set_setting(NAME, " ".join(name.split())[:NAME_MAX])


def set_colour(store, colour: str) -> None:
    if colour in COLOURS:
        store.set_setting(COLOUR, colour)


# ---- about, links and topics (everything shown to the members of boards you join) -----------------

def _json(store, key: str, default):
    try:
        value = json.loads(store.get_setting(key, "") or "null")
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _text(value: object, limit: int) -> str:
    """Plain one-line text: no control characters, spaces tidied, cut to `limit`."""
    cleaned = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in str(value or ""))
    return " ".join(cleaned.split())[:limit]


def clean_link(slot: str, value: object) -> str:
    """One link slot as stored: a website address, or a bare handle for Instagram, X and GitHub. "" if it is not valid."""
    text = _text(value, 200).strip()
    if slot == "website":
        text = text if "://" in text else "https://" + text if text else ""
        parts = urlsplit(text)
        host = parts.hostname or ""
        return text if parts.scheme in ("http", "https") and "." in host and not parts.username and len(text) <= 200 else ""
    if slot in HANDLE:
        if "/" in text:  # a pasted profile address: keep the name at its end
            text = urlsplit(text if "://" in text else "https://" + text).path.strip("/").split("/")[0]
        text = text.lstrip("@")
        return text if HANDLE[slot].match(text) else ""
    return ""


def clean_links(links: object) -> dict:
    links = links if isinstance(links, dict) else {}
    out = {slot: clean_link(slot, links.get(slot, "")) for slot in LINK_SLOTS}
    return {slot: v for slot, v in out.items() if v}


def link_url(slot: str, value: str) -> str:
    """The address to open for a stored link."""
    return value if slot == "website" else LINK_HOST[slot] + value


def clean_topics(topics: object) -> list[str]:
    out: list[str] = []
    for t in topics if isinstance(topics, list) else []:
        t = _text(t, TOPIC_LEN)
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:TOPICS_MAX]


def clean_extras(body: dict) -> dict:
    """What a friend's profile message may add to a member: only these three, each checked again here."""
    return {"about": _text(body.get("about"), ABOUT_MAX), "links": clean_links(body.get("links")),
            "topics": clean_topics(body.get("topics"))}


def auto_topics(store, count: int = 6) -> list[str]:
    """The biggest piles' names, so the profile follows what this library is about now."""
    piles = [p for p in store.piles() if p.get("members")]
    piles.sort(key=lambda p: (-len(p["members"]), p["id"]))
    return clean_topics([p["name"] for p in piles[:count]])


def topic_rows(store) -> list[tuple[str, bool]]:
    """(topic, from your piles) in the order a friend sees them: piles you have not taken off, then ones you typed."""
    hidden = {t.lower() for t in _json(store, TOPICS_HIDDEN, [])}
    rows = [(t, True) for t in auto_topics(store) if t.lower() not in hidden]
    rows += [(t, False) for t in clean_topics(_json(store, TOPICS_ADDED, [])) if t.lower() not in {r[0].lower() for r in rows}]
    return rows[:TOPICS_MAX]


def topics(store) -> list[str]:
    return [t for t, _ in topic_rows(store)]


def set_about(store, text: str) -> None:
    store.set_setting(ABOUT, _text(text, ABOUT_MAX))


def set_links(store, links: dict) -> None:
    store.set_setting(LINKS, json.dumps(clean_links(links)))


def hide_topic(store, topic: str) -> None:
    """Take a topic off: a pile's name is remembered as hidden, a typed one is deleted."""
    added = [t for t in clean_topics(_json(store, TOPICS_ADDED, [])) if t.lower() != topic.lower()]
    store.set_setting(TOPICS_ADDED, json.dumps(added))
    if topic.lower() in {t.lower() for t in auto_topics(store, 12)}:
        hidden = clean_topics(_json(store, TOPICS_HIDDEN, []) + [topic])
        store.set_setting(TOPICS_HIDDEN, json.dumps(hidden))


def add_topic(store, topic: str) -> None:
    topic = _text(topic, TOPIC_LEN)
    if not topic:
        return
    hidden = [t for t in _json(store, TOPICS_HIDDEN, []) if t.lower() != topic.lower()]  # typing a pile's name puts it back
    store.set_setting(TOPICS_HIDDEN, json.dumps(hidden))
    store.set_setting(TOPICS_ADDED, json.dumps(clean_topics(_json(store, TOPICS_ADDED, []) + [topic])))


def set_photo(data_url: str, shrink=None) -> str | None:
    """Save a photo the page sent as a data URL (already shrunk in the browser). It is shrunk and re-encoded again
    here, which also drops anything stored inside the file, such as where it was taken. Returns an error, or None."""
    head, _, body = data_url.partition(",")
    if head not in ("data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"):
        return "Pick a photo (JPEG, PNG or WebP)."
    try:
        raw = base64.b64decode(body, validate=True)
    except ValueError:
        return "That photo could not be read."
    if not raw or len(raw) > PHOTO_MAX:
        return "That photo is too large."
    out = photo_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in", Path(tmp) / "out.jpg"
        src.write_bytes(raw)
        if not (shrink or _shrink)(src, dst) or not dst.exists() or dst.read_bytes()[:2] != b"\xff\xd8":
            return "That photo could not be read."
        os.replace(dst, out)
    return None


def _shrink(src: Path, dst: Path) -> bool:
    """ffmpeg (Magpiary's own copy): a centred square of at most 256 px, a fresh JPEG with no metadata."""
    from magpiary.tools import find

    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return False
    side = "min(iw\\,ih)"
    done = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-frames:v", "1", "-map_metadata", "-1",
                           "-vf", f"crop={side}:{side},scale='min({PHOTO_SIZE}\\,iw)':-2", "-q:v", "4", str(dst)],
                          capture_output=True, timeout=30)
    return done.returncode == 0


def remove_photo() -> None:
    photo_path().unlink(missing_ok=True)


def initials(name: str) -> str:
    words = name.split()
    return "".join(w[0] for w in words[:2]).upper() or "?"
