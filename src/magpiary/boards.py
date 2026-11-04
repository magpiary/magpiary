"""Shared boards (M9): creating them, the events members write, checking events from other Macs, and replaying
every member's log into what the board shows.

A board is a set of per-member logs. This Mac writes only its own log: each event is numbered (1, 2, 3…), signed
with this Mac's identity key, sealed with the board key and published by the sync loop (boardsync). Events from
other members are opened, checked (the right board, the sender is who the transport says, the number matches, the
signature is good) and kept. The board is never stored as a whole: it is the replay of everyone's events, so two
Macs never conflict. Cards are identified by canonical URL, so the same post from two people is one card.

Event types: create (the creator, first), add (a card), remove (one's own card), vote (+1, -1 or 0, latest wins),
profile (name, colour, small photo), and from the creator only: rename, remove_member.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from magpiary import boardsync, identity, stickers
from magpiary.config import config_dir

NAME_MAX = 60
VIA = ("nostr", "bucket")
KINDS = ("create", "join", "add", "remove", "vote", "profile", "rename", "remove_member", "rekey", "close", "reopen", "leave")
INVITE_DAYS = 7
INVITE_PREFIX = "magpiary-board:"
THUMB_MAX = 20_000  # bytes of a card's thumbnail; keeps an event under every relay's limit
PHOTO_MAX = 12_000
LIMITS = {"title": 200, "summary": 1500, "author": 120, "source": 40, "kind": 40, "note": 500, "name": 60, "sticker": 16}


# ---- the board keys (secret) ---------------------------------------------------------------------------

def _keys_path() -> Path:
    return config_dir() / "boards.json"


def _keys() -> dict:
    try:
        return json.loads(_keys_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_keys(keys: dict) -> None:
    """Written whole to a private temporary file, then swapped in: a crash never leaves half a file of keys."""
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".boards-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(keys, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_KEYS_LOCK = threading.RLock()  # every read-change-write of boards.json holds it: two boards made at once keep both keys


def board_key(board_id: str) -> bytes:
    """The board's current key: what this Mac seals new events with."""
    return bytes.fromhex(_keys()[board_id]["key"])


def board_keys(board_id: str) -> list[bytes]:
    """Every key the board has had that this Mac knows, newest first: older events stay readable."""
    entry = _keys().get(board_id, {})
    return [bytes.fromhex(k) for k in [entry.get("key"), *entry.get("old", [])] if k]


def remember_key(board_id: str, key: bytes, bucket: dict | None = None, older: list[bytes] = ()) -> None:
    """Make `key` the board's current key; earlier ones (and any `older` an invite brought) stay to read old events."""
    with _KEYS_LOCK:
        keys = _keys()
        entry = keys.get(board_id, {})
        old = list(dict.fromkeys(k for k in [entry.get("key"), *entry.get("old", []), *(o.hex() for o in older)]
                                 if k and k != key.hex()))
        keys[board_id] = {"key": key.hex(), "old": old, **({"bucket": bucket} if bucket else
                                                           {"bucket": entry["bucket"]} if entry.get("bucket") else {})}
        _save_keys(keys)


def forget_key(board_id: str) -> None:
    with _KEYS_LOCK:
        keys = _keys()
        if keys.pop(board_id, None) is not None:
            _save_keys(keys)


def keys_path_for(backup: Path) -> Path:
    """Where a database backup's board keys sit: beside it, same name (owner, 4 Nov 2026)."""
    return backup.with_suffix(".boards.json")


def back_up_keys(backup: Path) -> bool:
    """Copy the board keys beside a database backup, owner-only, so a restore on a new Mac can still open its boards.
    False when there are none to copy."""
    with _KEYS_LOCK:
        keys = _keys()
        if not keys:
            return False
        path = keys_path_for(backup)
        path.unlink(missing_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            json.dump(keys, f)
    return True


def restore_keys(backup: Path) -> int:
    """Add the board keys kept beside a backup to this Mac's. Nothing is lost: a board this Mac already knows keeps
    its current key and gains the backup's keys as older ones. Returns how many boards gained keys."""
    try:
        saved = json.loads(keys_path_for(backup).read_text())
    except (OSError, ValueError):
        return 0
    added = 0
    with _KEYS_LOCK:
        keys = _keys()
        for board_id, entry in (saved.items() if isinstance(saved, dict) else ()):
            if not isinstance(entry, dict) or not entry.get("key"):
                continue
            if board_id not in keys:
                keys[board_id] = {k: v for k, v in entry.items() if k in ("key", "old", "bucket")}
                added += 1
                continue
            mine = keys[board_id]
            known = {mine["key"], *mine.get("old", [])}
            extra = [k for k in [entry["key"], *entry.get("old", [])] if k not in known]
            if extra:
                mine["old"] = [*mine.get("old", []), *dict.fromkeys(extra)]
                added += 1
        if added:
            _save_keys(keys)
    return added


# ---- writing this Mac's events ---------------------------------------------------------------------------

def _envelope(event: dict) -> str:
    text = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return json.dumps({"e": text, "s": identity.sign(text.encode())}, separators=(",", ":"))


def write(store, board_id: str, etype: str, sealed_with: bytes | None = None, **body) -> int:
    """Add one event to this Mac's log of a board; the sync loop publishes it, sealed with the board's current key
    (or `sealed_with`: a new key is announced under the old one). Returns its number."""
    reserved = {"v", "board", "member", "seq", "at", "type", "k"} & set(body)
    if reserved:
        raise ValueError(f"These names belong to the event itself: {', '.join(sorted(reserved))}")
    me = identity.public_key()
    at = int(time.time())
    key_tag = boardsync.board_tag(sealed_with or board_key(board_id))

    def sign(seq):
        return _envelope({"v": 1, "board": board_id, "member": me, "seq": seq, "at": at, "type": etype, "k": key_tag, **body})

    return store.append_board_event(board_id, me, at, etype, body, sign)


def create(store, name: str, via: str = "nostr") -> str:
    """A new board starts solo: its events stay on this Mac until the owner shares it (owner, 26 Oct 2026)."""
    name = " ".join(name.split())[:NAME_MAX]
    if not name:
        raise ValueError("Give the board a name.")
    if via not in VIA:
        raise ValueError("Pick where the board syncs.")
    board_id = secrets.token_hex(8)
    remember_key(board_id, boardsync.new_board_key())
    store.save_board(board_id, name, identity.public_key(), via, shared=False)
    write(store, board_id, "create", name=name)
    write(store, board_id, "profile", **profile_body(store))
    return board_id


def profile_body(store) -> dict:
    me = identity.profile(store)
    photo = _small_jpeg(identity.photo_path(), 96, PHOTO_MAX) if me["photo"] else b""
    body = {"name": me["name"] or "Someone", "colour": me["colour"],
            "photo": base64.b64encode(photo).decode() if photo else ""}
    extras = identity.clean_extras(me)
    return {**body, **{k: v for k, v in extras.items() if v}}  # empty fields are left out of the message


TOPICS_EVERY = 3600  # piles shift as the library grows: new topics go out at most once an hour


def republish_profile(store) -> int:
    """Send this Mac's profile to each live board whose copy of it is out of date (the last profile message this Mac wrote
    there differs). Name, photo, about and links go at once; topics that only follow the piles wait up to an hour.
    Returns how many boards got a new message."""
    body = profile_body(store)
    me, n = identity.public_key(), 0
    for board in store.boards():
        if board["archived_at"] or board["ended"]:
            continue
        mine = [ev for ev in store.board_events(board["id"]) if ev["member"] == me and ev["type"] == "profile"]
        last = max(mine, key=lambda ev: ev["seq"], default=None)
        if last is not None:
            if last["body"] == body:
                continue
            same_but_topics = {k: v for k, v in last["body"].items() if k != "topics"} == {k: v for k, v in body.items() if k != "topics"}
            if same_but_topics and time.time() - last["at"] < TOPICS_EVERY:
                continue
        write(store, board["id"], "profile", **body)
        n += 1
    return n


def _open(store, board_id: str) -> None:
    """Cards, votes and renames only on a board that is still alive: not deleted, not ended by its creator."""
    board = store.board(board_id)
    if board and (board["archived_at"] or board["ended"]):
        raise PermissionError("This board was deleted, so it can't be changed.")


def add_card(store, board_id: str, item: dict, library: Path | None = None, note: str = "") -> int:
    """A post from this library as a finished card: never the video, only what describes it and a small picture."""
    _open(store, board_id)
    url = item["canonical_url"]
    links = [{"name": link["name"], "url": link["url"]} for link in store.links_for(url)
             if link.get("role", "main") == "main" and link.get("central", 1)][:8]
    thumb = b""
    if item.get("thumb") and item.get("archive_dir"):
        folder = Path(item["archive_dir"])
        if library is None or folder.resolve().is_relative_to(Path(library).resolve()):
            thumb = _small_jpeg(folder / item["thumb"], 320, THUMB_MAX)
    return write(store, board_id, "add", url=url, title=item.get("ai_title") or item.get("title") or "",
                 summary=item.get("summary") or "", kind=item.get("ai_type") or "", source=item.get("source") or "",
                 author=item.get("author") or "", tags=list(item.get("tags") or [])[:12], links=links,
                 note=note.strip()[:LIMITS["note"]], thumb=base64.b64encode(thumb).decode() if thumb else "")


def remove_card(store, board_id: str, url: str) -> int:
    _open(store, board_id)
    return write(store, board_id, "remove", url=url)


def vote(store, board_id: str, url: str, value: int) -> int:
    _open(store, board_id)
    return write(store, board_id, "vote", url=url, value=max(-1, min(1, int(value))))


def rename(store, board_id: str, name: str, sticker: str = "", colour: str = "") -> int:
    """The creator renames the board, or picks its sticker or its colour; all travel in one rename event."""
    board = store.board(board_id)
    if not board or board["creator"] != identity.public_key():
        raise PermissionError("Only the board's creator can rename it.")
    _open(store, board_id)
    name = " ".join(name.split())[:NAME_MAX]
    v = view(store, board_id)
    sticker = sticker if stickers.valid(sticker) and sticker != v["sticker"] else ""
    colour = colour if colour in identity.COLOURS and colour != v["colour"] else ""
    if not name or (name == v["name"] and not sticker and not colour):
        return 0
    store.update_board(board_id, name=name)
    return write(store, board_id, "rename", name=name, **({"sticker": sticker} if sticker else {}),
                 **({"colour": colour} if colour else {}))


# ---- solo or shared, delete and leave (owner, 26 Oct 2026) ---------------------------------------------

def _mine(store, board_id: str) -> dict:
    board = store.board(board_id)
    if not board or board["creator"] != identity.public_key():
        raise PermissionError("Only the board's creator can do this.")
    return board


def people(v: dict) -> list[dict]:
    """Who is on a board now: everyone who has not left."""
    return [m for m in v["members"].values() if not m.get("left")]


def share(store, board_id: str, via: str = "nostr") -> None:
    """Turn sync on: from now this board is published (sealed with its key) and can be invited to. Events already
    written on this Mac go out with the first sync."""
    _mine(store, board_id)
    if via not in VIA or (via == "bucket" and not boardsync.load_bucket()):
        raise ValueError("Connect a bucket in Settings first." if via == "bucket" else "Pick where the board syncs.")
    store.update_board(board_id, shared=1, via=via)


def unshare(store, board_id: str) -> None:
    """Back to solo, only while no one else is on the board (they would lose it)."""
    _mine(store, board_id)
    if len(people(view(store, board_id))) > 1:
        raise ValueError("Other people are on this board. Remove them first, or delete the board.")
    retire_code(store, board_id)
    store.update_board(board_id, shared=0, sync_error="")


def end_board(store, board_id: str) -> None:
    """The creator deletes the board: archived and hidden for 30 days, restorable. A shared board with other people on
    it also ends for them: a notice goes out with the next sync."""
    board = _mine(store, board_id)
    if board["archived_at"]:
        return
    if board["shared"] and len(people(view(store, board_id))) > 1:
        write(store, board_id, "close")
    store.update_board(board_id, archived_at=store.now())


def restore_board(store, board_id: str) -> None:
    board = _mine(store, board_id)
    if not board["archived_at"]:
        return
    if any(ev["member"] == board["creator"] and ev["type"] in ("close", "reopen") for ev in store.board_events(board_id)):
        write(store, board_id, "reopen")
    store.update_board(board_id, archived_at="")


def leave_board(store, board_id: str, relay_connect=None, call=None) -> None:
    """A member (not the creator) leaves: the others are told, the board and its key leave this Mac, and the cards
    this member added stay on the board."""
    board = store.board(board_id)
    if not board:
        return
    if board["creator"] == identity.public_key():
        raise PermissionError("The creator can't leave their own board. Delete it instead.")
    write(store, board_id, "leave")
    connector = connector_for(board, relay_connect, call)
    result = sync(store, board_id, connector, call, relay_connect) if connector else {"ok": False}
    if not result["ok"]:
        raise ValueError("Couldn't tell the others you're leaving. Check your connection and try again.")
    store.delete_board(board_id)
    forget_key(board_id)


def dismiss_board(store, board_id: str) -> None:
    """A board its creator ended: remove this Mac's read-only copy."""
    board = store.board(board_id)
    if board and board["ended"]:
        store.delete_board(board_id)
        forget_key(board_id)


def sort_sharing(store) -> int:
    """Once, for boards from before solo boards: one person on it means solo (sync off, nothing deleted from the
    relays); two or more stay shared. Returns how many became solo."""
    if store.get_setting("boards_sharing_sorted"):
        return 0
    n = 0
    for b in store.boards() + store.boards(archived=True):
        v = view(store, b["id"])
        if b["shared"] and v and len(people(v)) <= 1:
            store.update_board(b["id"], shared=0)
            n += 1
    store.set_setting("boards_sharing_sorted", "1")
    return n


def removed_members(store, board_id: str) -> set[str]:
    board = store.board(board_id)
    if not board:
        return set()
    return {ev["body"].get("who", "") for ev in store.board_events(board_id)
            if ev["member"] == board["creator"] and ev["type"] == "remove_member"} - {board["creator"]}


def remove_member(store, board_id: str, member: str, call=None) -> None:
    """The creator removes a member: everyone's board drops them, their bucket key is deleted, and the board gets a
    new key, handed to each remaining member sealed for them alone, so the removed member can't read what comes next."""
    board = store.board(board_id)
    me = identity.public_key()
    if not board or board["creator"] != me:
        raise PermissionError("Only the board's creator can remove a member.")
    if member == me:
        raise ValueError("The creator can't remove themselves.")
    write(store, board_id, "remove_member", who=member)
    for invite in store.invites(board_id):
        # their own key, and the current code's key (they may hold it): those who still use it get their own
        if (invite["used_by"] == member or invite["state"] == "shared") and invite["bucket_key_id"]:
            _delete_bucket_key(invite["bucket_key_id"], call)
            store.update_invite(invite["id"], state="removed")
    retire_code(store, board_id)
    rekey(store, board_id)


def rekey(store, board_id: str) -> bytes:
    """A new board key for every member still on the board, announced under the old key."""
    me, old, new = identity.public_key(), board_key(board_id), boardsync.new_board_key()
    remaining = [m for m, info in view(store, board_id)["members"].items() if m != me and not info.get("left")]
    sealed = {m: base64.b64encode(boardsync.seal(identity.shared_key(m), new)).decode() for m in remaining}
    write(store, board_id, "rekey", sealed_with=old, keys=sealed)
    remember_key(board_id, new)
    return new


def take_new_key(store, board_id: str) -> bool:
    """Pick up a new board key the creator announced for this Mac. True if one was added."""
    board, me = store.board(board_id), identity.public_key()
    known, added = {k.hex() for k in board_keys(board_id)}, False
    for ev in store.board_events(board_id):
        if ev["type"] != "rekey" or ev["member"] != board["creator"] or ev["member"] == me:
            continue
        sealed = ev["body"].get("keys", {}).get(me)
        if not sealed:
            continue
        try:
            key = boardsync.unseal(identity.shared_key(board["creator"]), base64.b64decode(sealed))
        except ValueError:
            continue
        if len(key) == 32 and key.hex() not in known:
            remember_key(board_id, key)
            known.add(key.hex())
            added = True
    return added


# ---- invites -------------------------------------------------------------------------------------------

CODE_LETTERS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # no I, L, O or U: nothing to mix up when typed or read out


def new_code() -> str:
    """A short invite code, MAG-XXXX-XXXX-XXXX: 12 letters, 60 bits of chance."""
    letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(12))
    return f"MAG-{letters[:4]}-{letters[4:8]}-{letters[8:]}"


def normal_code(code: str) -> str:
    """A code as typed or pasted (any case, spaces, dashes, O for 0, I or L for 1, with or without MAG) to its
    12 letters, or "" if it can't be one."""
    text = "".join(ch for ch in code.upper() if ch.isalnum()).replace("O", "0").replace("I", "1").replace("L", "1")
    if len(text) == 15 and text.startswith("MAG"):
        text = text[3:]
    return text if len(text) == 12 and all(ch in CODE_LETTERS for ch in text) else ""


def _code_keys(code: str) -> tuple[bytes, str]:
    """From a code: the key that seals the parked invite, and the tag relays find it by. Slow on purpose
    (scrypt), so someone holding the sealed note can't try every code."""
    derived = hashlib.scrypt(normal_code(code).encode(), salt=b"magpiary-invite-v1", n=2 ** 14, r=8, p=1, dklen=64)
    return derived[:32], hashlib.sha256(derived[32:]).hexdigest()[:32]


_CODE_LOCK = threading.Lock()  # two quick presses of Invite make one code, not two


def board_code(store, board_id: str, call=None, relay_connect=None, renew: bool = False) -> dict:
    with _CODE_LOCK:
        return _board_code(store, board_id, call, relay_connect, renew)


def _board_code(store, board_id: str, call=None, relay_connect=None, renew: bool = False) -> dict:
    """The board's invite code (owner, 25 Oct 2026): one per board, for anyone it is sent to, made the first time
    Invite is pressed and renewed after 7 days, by New code, or when the board gets a new key (removing someone).
    Everything a friend's Magpiary needs to join is sealed with a key made from the code and left on the relays; the
    code alone opens it. Returns {"code", "expires"}; the code is kept with the board keys (owner-only)."""
    board = store.board(board_id)
    if board and not board["shared"]:
        raise ValueError("Turn on sharing for this board before inviting anyone.")
    keys = _keys()
    entry = keys.get(board_id, {}).get("code")
    current = boardsync.board_tag(board_key(board_id))
    if entry and not renew and entry["expires"] > time.time() and entry["key_tag"] == current:
        return {"code": entry["code"], "expires": entry["expires"]}
    if entry:
        retire_code(store, board_id)
    data, key_id = _invite_data(store, board_id, call)
    code = new_code()
    seal_key, tag = _code_keys(code)
    try:
        note = boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {})).park(
            tag, boardsync.seal(seal_key, json.dumps(data, separators=(",", ":")).encode()))
    except boardsync.SyncError:
        if key_id:
            _delete_bucket_key(key_id, call)
        raise
    store.save_invite(data["i"], board_id, data["x"], key_id)
    store.update_invite(data["i"], state="shared")
    store.save_relay_note(note, "code")
    with _KEYS_LOCK:
        keys = _keys()
        keys.setdefault(board_id, {})["code"] = {"code": code, "expires": data["x"], "invite": data["i"], "key_tag": current,
                                                 "note": note, "tag": tag}
        _save_keys(keys)
    return {"code": code, "expires": data["x"]}


OLD_KEYS_MAX = 50  # earlier board keys an invite carries
NOTE_DAYS = 8  # an invite note runs out after 7 days; a day later it is deleted from the relays
KEY_NOTE_DAYS = 30  # a member's own bucket key waits longer, for a Mac that was away


def clean_relays(store, relay_connect=None, now=None) -> int:
    """Ask the relays to delete this Mac's invite notes that nobody needs any more: board codes that were replaced
    (or made twice), and notes older than their use. The current code of every board is kept. Returns how many."""
    now = now or time.time()
    keep = {e["code"].get("tag") or _code_keys(e["code"]["code"])[1]  # codes made before tags were kept
            for e in _keys().values() if e.get("code") and e["code"].get("expires", 0) > now}
    nostr = boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {}))
    old = []
    for event_id, tag in nostr.my_parked().items():
        if tag in keep:
            continue
        age, kind = store.relay_note_age(event_id, now), store.relay_note_kind(event_id)
        limit = KEY_NOTE_DAYS if kind == "key" else NOTE_DAYS
        if kind == "code" or age is None or age > limit * 86400:  # replaced codes, and anything past its use
            old.append(event_id)
    if old:
        nostr.delete(old)
        store.relay_notes_deleted(old)
    return len(old)


def retire_code(store, board_id: str) -> None:
    """The board's code stops being offered here; its sealed invite runs out on its own date. Its bucket key stays
    until a week after that, while the members who joined with it get keys of their own."""
    with _KEYS_LOCK:
        keys = _keys()
        if keys.get(board_id, {}).pop("code", None) is not None:
            _save_keys(keys)


def make_invite(store, board_id: str, call=None, relay_connect=None) -> str:
    """The board's current invite code (kept for callers of the first, per-person codes)."""
    return board_code(store, board_id, call, relay_connect)["code"]


def _invite_data(store, board_id: str, call=None) -> tuple[dict, str]:
    """What an invite carries, and the bucket key made for it (if any)."""
    board, me = store.board(board_id), identity.public_key()
    if not board:
        raise ValueError("No such board.")
    invite_id = secrets.token_hex(6)
    expires = int(time.time()) + INVITE_DAYS * 86400
    data = {"v": 1, "b": board_id, "n": board["name"], "c": board["creator"], "k": board_key(board_id).hex(),
            "via": board["via"], "i": invite_id, "x": expires}
    older = [k.hex() for k in board_keys(board_id)[1:OLD_KEYS_MAX + 1]]
    if older:  # the keys from before a removal, so a new member can read the whole board (owner, 4 Nov 2026)
        data["o"] = older
    key_id = ""
    if board["via"] == "bucket":
        own = _keys().get(board_id, {}).get("bucket")
        mine = boardsync.load_bucket()
        if own or not mine or board["creator"] != me:
            raise PermissionError("Only the board's creator can invite to a board in their bucket.")
        if mine["provider"] == "b2":
            b2 = boardsync.B2(mine["main_key_id"], mine["main_key"], **({"call": call} if call else {}))
            key = b2.limited_key(mine["bucket_id"], f"magpiary-invite-{invite_id}")
            key_id = key["applicationKeyId"]
            data["s"] = {"endpoint": mine["endpoint"], "bucket": mine["bucket"], "key_id": key_id,
                         "secret": key["applicationKey"]}
        else:  # R2 and others: no keys made here, so friends share this Mac's key (said in Help)
            data["s"] = {k: mine[k] for k in ("endpoint", "bucket", "key_id", "secret")}
    return data, key_id


def _checked(data) -> dict:
    try:
        assert data["v"] == 1 and len(bytes.fromhex(data["k"])) == 32 and len(bytes.fromhex(data["c"])) == 32
        assert data["via"] in VIA and isinstance(data["b"], str) and len(data["b"]) == 16 and data["n"]
        assert data["via"] == "nostr" or {"endpoint", "bucket", "key_id", "secret"} <= set(data["s"])
        assert len(data.get("o", [])) <= OLD_KEYS_MAX and all(len(bytes.fromhex(k)) == 32 for k in data.get("o", []))
    except Exception as err:
        raise ValueError("This invite is damaged. Ask for a new one.") from err
    if data["x"] < time.time():
        raise ValueError("This invite has expired. Ask for a new one.")
    return data


def read_invite(code: str, relay_connect=None) -> dict:
    """The invite behind a short code (fetched from the relays and opened), or behind an early long code; ValueError
    with a reason to show."""
    text = "".join(code.split())
    if text.startswith(INVITE_PREFIX):  # the long codes of 25 Oct, before short ones
        body = text[len(INVITE_PREFIX):]
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except Exception as err:
            raise ValueError("This invite is damaged. Ask for a new one.") from err
        return _checked(data)
    if not normal_code(code):
        raise ValueError("That doesn't look like an invite code. It looks like MAG-7K3P-QX9D-2HFW.")
    seal_key, tag = _code_keys(code)
    try:
        notes = boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {})).find_parked(tag)
    except boardsync.SyncError as err:
        raise ValueError("Couldn't reach the relays to look up the invite. Is this Mac online?") from err
    for sealed in notes:
        try:
            return _checked(json.loads(boardsync.unseal(seal_key, sealed)))
        except ValueError as err:
            if "expired" in str(err):
                raise
            continue
    raise ValueError("No invite was found for this code. Check it, or ask for a new one.")


def join(store, code: str, relay_connect=None) -> str:
    """Join a board from an invite code. Returns the board id; ValueError with a reason to show."""
    return _join(store, read_invite(code, relay_connect))


def _join(store, data: dict) -> str:
    if data["c"] == identity.public_key():
        raise ValueError("This invite is for a board you made.")
    if store.board(data["b"]):
        raise ValueError(f"You're already on “{data['n']}”.")
    bucket = None
    if data["via"] == "bucket":
        bucket = {"provider": "invite", **{k: str(data["s"][k]) for k in ("endpoint", "bucket", "key_id", "secret")}}
    remember_key(data["b"], bytes.fromhex(data["k"]), bucket, [bytes.fromhex(k) for k in data.get("o", [])])
    store.save_board(data["b"], " ".join(str(data["n"]).split())[:NAME_MAX], data["c"], data["via"])
    write(store, data["b"], "join", invite=data["i"])
    write(store, data["b"], "profile", **profile_body(store))
    return data["b"]


def inbox_tag(public: str) -> str:
    """Where invites sent straight to a member wait on the relays: says whose inbox, not who sent what."""
    return hashlib.sha256(b"magpiary-inbox:" + bytes.fromhex(public)).hexdigest()[:32]


def friends(store, board_id: str = "") -> list[dict]:
    """Everyone this Mac has shared a board with (their latest name, colour and photo), except those already on
    `board_id` and those its creator removed: who can be invited straight from the list."""
    me, people, here = identity.public_key(), {}, set()
    if board_id and store.board(board_id):
        here = set(view(store, board_id)["members"]) | removed_members(store, board_id)
    for b in store.boards():
        for key, m in view(store, b["id"])["members"].items():
            if key != me and key not in here and (key not in people or m["last"] > people[key]["last"]):
                people[key] = m
    return sorted(people.values(), key=lambda m: (m["name"] or "").lower())


def invite_friend(store, board_id: str, member: str, call=None, relay_connect=None) -> str:
    """Invite someone this Mac has shared a board with: the invite is sealed for them alone and left in their inbox
    on the relays; their Magpiary shows it after its next sync. Returns the invite id."""
    if not re.fullmatch(r"[0-9a-f]{64}", member or "") or member == identity.public_key():
        raise ValueError("Pick someone to invite.")
    data, key_id = _invite_data(store, board_id, call)
    try:
        note = boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {})).park(
            inbox_tag(member), boardsync.seal(identity.shared_key(member), json.dumps(data, separators=(",", ":")).encode()))
    except boardsync.SyncError:
        if key_id:
            _delete_bucket_key(key_id, call)
        raise
    store.save_relay_note(note, "inbox")
    store.save_invite(data["i"], board_id, data["x"], key_id)
    return data["i"]


def _inbox(relay_connect=None) -> list[tuple[str, dict]]:
    """Notes waiting for this Mac: (who sent it, what it says), opened; invites checked, broken ones left out."""
    me, out = identity.public_key(), []
    for sender, sealed in boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {})).find_parked_from(inbox_tag(me)):
        try:
            note = json.loads(boardsync.unseal(identity.shared_key(sender), sealed))
            if not (isinstance(note, dict) and note.get("t") == "bucket"):
                note = _checked(note)
        except ValueError:
            continue
        out.append((sender, note))
    return out


def check_inbox(store, relay_connect=None) -> int:
    """Invites friends sent straight to this Mac become offers on the hub, and a bucket key of one's own from a
    board's creator replaces the shared one. Returns how many offers are new."""
    new = 0
    for sender, note in _inbox(relay_connect):
        if note.get("t") == "bucket":
            board = store.board(str(note.get("b", "")))
            s = note.get("s") or {}
            if board and board["creator"] == sender and board["via"] == "bucket" and \
                    {"endpoint", "bucket", "key_id", "secret"} <= set(s):
                entry = _keys().get(board["id"], {})
                if entry.get("bucket", {}).get("key_id") != s["key_id"]:
                    remember_key(board["id"], board_key(board["id"]),
                                 {"provider": "member", **{k: str(s[k]) for k in ("endpoint", "bucket", "key_id", "secret")}})
            continue
        if not store.board(note["b"]) and store.save_offer(note["i"], note["b"], str(note["n"])[:NAME_MAX], sender):
            new += 1
    return new


def accept_offer(store, invite: str, relay_connect=None) -> str:
    """Join from an invite a friend sent straight here (fetched again: the board key is never kept before joining)."""
    offer = store.offer(invite)
    if not offer:
        raise ValueError("This invite is no longer here.")
    for _, data in _inbox(relay_connect):
        if data.get("i") == invite:
            board_id = _join(store, data)
            store.set_offer(invite, "joined")
            return board_id
    store.set_offer(invite, "gone")
    raise ValueError("This invite has expired or was withdrawn. Ask for a new one.")


def sender_name(store, sender: str) -> str:
    """A name for whoever sent an invite, from the boards shared with them."""
    for b in store.boards():
        m = view(store, b["id"])["members"].get(sender)
        if m and m["name"]:
            return m["name"]
    return f"Someone ({identity.short_id(sender)})"


GRACE = 7 * 86400  # a shared code's bucket key outlives the code by a week, while new members get their own


def settle_invites(store, board_id: str, call=None, relay_connect=None) -> None:
    """Keep this Mac's invites in order: an invite sent to one person is marked used when they join, and closed
    (its bucket key deleted) after 7 days if not; a board code's bucket key is deleted a week after the code runs
    out. On a board in this Mac's Backblaze bucket, everyone who joined gets a bucket key of their own, sealed for
    them in their relay inbox, so removing one person can cut off only them."""
    invites = store.invites(board_id)
    joins = {ev["body"].get("invite", ""): ev["member"] for ev in store.board_events(board_id) if ev["type"] == "join"}
    now = time.time()
    for invite in invites:
        if invite["state"] == "open" and invite["id"] in joins:
            store.update_invite(invite["id"], used_by=joins[invite["id"]], state="used")
        elif invite["state"] == "open" and invite["expires"] < now:
            if invite["bucket_key_id"]:
                _delete_bucket_key(invite["bucket_key_id"], call)
            store.update_invite(invite["id"], state="expired")
        elif invite["state"] == "shared" and invite["expires"] + GRACE < now:
            if invite["bucket_key_id"]:
                _delete_bucket_key(invite["bucket_key_id"], call)
            store.update_invite(invite["id"], state="expired")
    _personal_keys(store, board_id, call, relay_connect)


def _personal_keys(store, board_id: str, call=None, relay_connect=None) -> None:
    board, me, mine = store.board(board_id), identity.public_key(), boardsync.load_bucket()
    if not board or board["via"] != "bucket" or board["creator"] != me or not mine or mine.get("provider") != "b2":
        return
    have = {i["used_by"] for i in store.invites(board_id) if i["state"] in ("member", "used")}
    members = set(view(store, board_id)["members"]) - {me} - have - removed_members(store, board_id)
    for member in sorted(members):
        try:
            b2 = boardsync.B2(mine["main_key_id"], mine["main_key"], **({"call": call} if call else {}))
            key = b2.limited_key(mine["bucket_id"], f"magpiary-member-{member[:12]}")
            note = {"t": "bucket", "b": board_id, "s": {"endpoint": mine["endpoint"], "bucket": mine["bucket"],
                                                        "key_id": key["applicationKeyId"], "secret": key["applicationKey"]}}
            sent = boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {})).park(
                inbox_tag(member), boardsync.seal(identity.shared_key(member), json.dumps(note, separators=(",", ":")).encode()))
        except boardsync.SyncError:
            continue  # tried again at the next sync
        store.save_relay_note(sent, "key")
        record = f"m{secrets.token_hex(5)}"
        store.save_invite(record, board_id, 0, key["applicationKeyId"])
        store.update_invite(record, used_by=member, state="member")


def _delete_bucket_key(key_id: str, call=None) -> None:
    mine = boardsync.load_bucket()
    if not mine or mine.get("provider") != "b2":
        return
    try:
        boardsync.B2(mine["main_key_id"], mine["main_key"], **({"call": call} if call else {})).delete_key(key_id)
    except boardsync.SyncError:
        pass


def _small_jpeg(src: Path, side: int, limit: int) -> bytes:
    """A small JPEG of a picture, made with ffmpeg, lowering quality until it fits. Empty if it can't be made."""
    from magpiary.tools import find

    ffmpeg = find("ffmpeg")
    if not ffmpeg or not Path(src).is_file():
        return b""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "small.jpg"
        for size, quality in ((side, 5), (side, 9), (side * 3 // 4, 12), (side // 2, 16)):
            done = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-frames:v", "1", "-map_metadata", "-1",
                                   "-vf", f"scale='min({size}\\,iw)':-2", "-q:v", str(quality), str(out)],
                                  capture_output=True, timeout=30)
            if done.returncode == 0 and out.exists() and out.stat().st_size <= limit:
                return out.read_bytes()
    return b""


# ---- sealing for the sync loop, and checking what arrives ---------------------------------------------------

def outbox(store, board_id: str) -> list[tuple[int, bytes, bytes]]:
    """This Mac's events not published yet: (number, the key they go under, sealed bytes)."""
    keys = {boardsync.board_tag(k): k for k in board_keys(board_id)}
    out = []
    for row in store.unpublished_board_events(board_id, identity.public_key()):
        tag = json.loads(json.loads(row["signed"])["e"]).get("k", "")
        key = keys.get(tag, board_key(board_id))
        out.append((row["seq"], key, boardsync.seal(key, row["signed"].encode())))
    return out


def ingest(store, board_id: str, fetched: list, key: bytes | None = None) -> int:
    """Open, check and keep events fetched from a connector under one of the board's keys. Returns how many were
    new. Bad ones are skipped, and so is anything from a member the creator removed, whatever time it claims."""
    key, me, new = key or board_key(board_id), identity.public_key(), 0
    gone = removed_members(store, board_id)
    for f in fetched:
        if f.member == me or f.member in gone:
            continue  # our own events are already here
        event = open_event(key, board_id, f)
        if event and store.add_board_event(board_id, event["member"], event["seq"], event["at"], event["type"],
                                           _clean(event), "", ref=f.ref):
            new += 1
    if new:
        board = store.board(board_id)
        ended = False
        for ev in store.board_events(board_id):
            if board and ev["member"] == board["creator"] and ev["type"] in ("close", "reopen"):
                ended = ev["type"] == "close"
        if board and board["creator"] != me and bool(board["ended"]) != ended:
            store.update_board(board_id, ended=int(ended))
    return new


def open_event(key: bytes, board_id: str, f) -> dict | None:
    """The event inside fetched bytes, or None if it is not a good event of this board from that member."""
    try:
        envelope = json.loads(boardsync.unseal(key, f.sealed))
        text, sig = envelope["e"], envelope["s"]
        event = json.loads(text)
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(event, dict) or event.get("v") != 1 or event.get("board") != board_id \
            or event.get("member") != f.member or event.get("type") not in KINDS:
        return None
    if not isinstance(event.get("seq"), int) or event["seq"] < 1 or (f.seq and event["seq"] != f.seq):
        return None
    if not isinstance(event.get("at"), int) or not identity.verify(f.member, text.encode(), sig):
        return None
    return event


def _clean(event: dict) -> dict:
    """Only the fields a type uses, of the right kind and size: what friends send is data, never trusted."""
    body = {k: v for k, v in event.items() if k not in ("v", "board", "member", "seq", "at", "type", "k")}
    out = {}
    for k, v in body.items():
        if k in LIMITS and isinstance(v, str):
            out[k] = v[:LIMITS[k]]
        elif k in ("url", "who", "colour") and isinstance(v, str) and len(v) <= 500:
            out[k] = v
        elif k == "value" and v in (-1, 0, 1):
            out[k] = v
        elif k in ("thumb", "photo") and isinstance(v, str) and len(v) <= (THUMB_MAX if k == "thumb" else PHOTO_MAX) * 4 // 3 + 4:
            out[k] = v
        elif k == "tags" and isinstance(v, list):
            out[k] = [str(t)[:40] for t in v[:12]]
        elif k == "invite" and isinstance(v, str) and len(v) <= 40:
            out[k] = v
        elif k == "keys" and isinstance(v, dict):
            out[k] = {str(m)[:64]: str(s)[:200] for m, s in list(v.items())[:200]}
        elif k == "links" and isinstance(v, list):
            out[k] = [{"name": str(link.get("name", ""))[:80], "url": str(link.get("url", ""))[:500]}
                      for link in v[:8] if isinstance(link, dict) and str(link.get("url", "")).startswith(("https://", "http://"))]
    if out.get("colour") not in identity.COLOURS:
        out.pop("colour", None)
    if "url" in out and not out["url"].startswith(("https://", "http://")):
        out.pop("url")
    if event.get("type") == "profile":
        out.update(identity.clean_extras(body))
    return out


# ---- what the board shows --------------------------------------------------------------------------------

def view(store, board_id: str) -> dict | None:
    """Replay every member's events into the board: its name, members and cards.

    Members' clocks differ and events arrive in any order, so a card's state is settled per member by that member's
    own numbering: their latest add or remove of a URL wins, and so does their latest vote, whenever the card itself
    arrived."""
    board = store.board(board_id)
    if not board:
        return None
    creator, name, chosen, colour, ended = board["creator"], board["name"], "", "", False
    members: dict[str, dict] = {}
    removed: dict[str, int] = {}
    adds: dict[str, dict] = {}      # url → member → (seq, at, body) of their latest add
    takes: dict[str, dict] = {}     # url → member → seq of their latest remove
    votes: dict[str, dict] = {}     # url → member → (seq, value)
    events = store.board_events(board_id)
    for ev in events:  # the creator's removals first: they decide whose events count
        if ev["member"] == creator and ev["type"] == "remove_member" and ev["body"].get("who") not in (None, creator):
            removed[ev["body"]["who"]] = min(ev["at"], removed.get(ev["body"]["who"], ev["at"]))
    for ev in events:
        who, seq, at, kind, body = ev["member"], ev["seq"], ev["at"], ev["type"], ev["body"]
        if who in removed and at >= removed[who]:
            continue
        m = members.setdefault(who, {"key": who, "name": "", "colour": next(iter(identity.COLOURS)), "photo": "",
                                     "about": "", "links": {}, "topics": [], "joined": at, "last": at, "cards": 0, "creator": who == creator, "_seq": 0})
        m["last"], m["joined"] = max(m["last"], at), min(m["joined"], at)
        url = body.get("url", "")
        if kind == "profile" and seq > m["_seq"]:
            m.update({k: body[k] for k in ("name", "colour", "photo") if k in body}, _seq=seq)
            m.update(identity.clean_extras(body))  # a newer message replaces the extras too, so a cleared field clears
        elif kind in ("create", "rename") and who == creator and body.get("name"):
            name = body["name"]  # events come in time order: the latest name wins
            chosen = body["sticker"] if stickers.valid(body.get("sticker")) else chosen
            colour = body["colour"] if body.get("colour") in identity.COLOURS else colour
        elif kind == "leave" and who != creator:
            m["left"] = True
        elif kind in ("close", "reopen") and who == creator:
            ended = kind == "close"
        elif kind == "add" and url and seq > adds.setdefault(url, {}).get(who, (0,))[0]:
            adds[url][who] = (seq, at, body)
        elif kind == "remove" and url:
            takes.setdefault(url, {})[who] = max(seq, takes.get(url, {}).get(who, 0))
        elif kind == "vote" and url and seq > votes.setdefault(url, {}).get(who, (0,))[0]:
            votes[url][who] = (seq, body.get("value", 0))
    for who in removed:  # a removed member, their cards and their votes leave the board
        members.pop(who, None)
    shown = []
    for url, by in adds.items():
        adders = {who: (seq, at, body) for who, (seq, at, body) in by.items()
                  if who in members and seq > takes.get(url, {}).get(who, 0)}
        if not adders:
            continue
        first = min(adders, key=lambda w: (adders[w][1], w))
        card = {**adders[first][2], "url": url, "adders": {w: a[1] for w, a in adders.items()},
                "first": adders[first][1], "last": max(a[1] for a in adders.values())}
        if not card.get("thumb"):
            card["thumb"] = next((a[2]["thumb"] for a in adders.values() if a[2].get("thumb")), "")
        card["votes"] = {w: v for w, (_, v) in votes.get(url, {}).items() if w in members and v}
        card["score"] = sum(card["votes"].values())
        card["shared"] = len(adders) > 1
        for who in adders:
            members[who]["cards"] += 1
        shown.append(card)
    for m in members.values():
        m.pop("_seq", None)
    return {"id": board_id, "name": name, "creator": creator, "via": board["via"], "members": members,
            "sticker": chosen or stickers.pick(name),
            "colour": colour or list(identity.COLOURS)[int(board_id[:4], 16) % len(identity.COLOURS)],
            "cards": sorted(shown, key=lambda c: (-c["last"], c["url"])), "synced_at": board["synced_at"],
            "sync_error": board["sync_error"], "ended": ended, "shared": bool(board["shared"]),
            "archived": bool(board["archived_at"])}


def sort_cards(cards: list, by: str = "newest", member: str = "") -> list:
    """The board page's sort (newest, oldest, most votes, title) and member filter."""
    found = [c for c in cards if not member or member in c["adders"]]
    if by == "votes":
        return sorted(found, key=lambda c: (-c["score"], -c["last"]))
    if by == "oldest":
        return sorted(found, key=lambda c: (c["first"], c["url"]))
    if by == "title":
        return sorted(found, key=lambda c: ((c.get("title") or c["url"]).lower(), c["url"]))
    if by == "shared":
        return sorted([c for c in found if c["shared"]], key=lambda c: (-len(c["adders"]), -c["last"]))
    return found


# ---- one sync of one board ------------------------------------------------------------------------------

def connector_for(board: dict, relay_connect=None, call=None):
    """The board's connector: the relays, or the bucket its key file names (a member's) or this Mac's own."""
    if board["via"] == "bucket":
        data = _keys().get(board["id"], {}).get("bucket") or boardsync.load_bucket()
        return boardsync.bucket_connector(data, **({"call": call} if call else {}))
    return boardsync.Nostr(**({"connect": relay_connect} if relay_connect else {}))


def sync(store, board_id: str, connector, call=None, relay_connect=None) -> dict:
    """Publish this Mac's new events, then fetch and keep everyone else's under every key the board has had (a new
    key announced on the way is picked up in the same sync). Never raises: the result says."""
    with _SYNC_LOCK:
        return _sync(store, board_id, connector, call, relay_connect)


_SYNC_LOCK = threading.Lock()  # Sync now on a board and the board lane never sync at the same time


def _sync(store, board_id: str, connector, call=None, relay_connect=None) -> dict:
    board, me = store.board(board_id), identity.public_key()
    sent = got = 0
    started = int(time.time())
    try:
        for seq, key, sealed in outbox(store, board_id):
            connector.publish(key, seq, sealed)
            store.board_event_published(board_id, me, seq)
            sent += 1
        done: set[bytes] = set()
        while True:
            todo = [k for k in board_keys(board_id) if k not in done]
            if not todo:
                break
            for key in todo:
                done.add(key)
                got += ingest(store, board_id, connector.fetch(key, board["since"], store.board_refs(board_id)), key)
            take_new_key(store, board_id)
        settle_invites(store, board_id, call, relay_connect)
    except boardsync.SyncError as err:
        store.update_board(board_id, sync_error=str(err)[:300])
        return {"ok": False, "sent": sent, "got": got, "error": str(err)}
    store.update_board(board_id, since=started, synced_at=store.now(), sync_error="")
    return {"ok": True, "sent": sent, "got": got, "error": ""}


SYNC_EVERY = 15 * 60  # seconds between syncs while the Mac is awake; "Sync now" and board changes come sooner


def sync_all(store, relay_connect=None, call=None, log=None) -> dict:
    """Sync every board once. Returns totals; each board keeps its own time or error."""
    totals = {"boards": 0, "sent": 0, "got": 0, "failed": 0}
    if republish_profile(store) and log:
        log("sent your updated profile to your boards")
    if settle_pending(store) and log:
        log("added posts shared from the phone to their boards")
    try:
        if check_inbox(store, relay_connect) and log:
            log("a friend sent a board invite")
        if time.time() - float(store.get_setting("relays_cleaned", "0") or 0) > 86400:
            cleaned = clean_relays(store, relay_connect)
            store.set_setting("relays_cleaned", str(int(time.time())))
            if cleaned and log:
                log(f"asked the relays to delete {cleaned} old invite note(s)")
    except boardsync.SyncError:
        pass
    for board in store.boards_to_sync():
        if board["archived_at"] and not outbox(store, board["id"]):
            continue  # deleted: only until its last notice (the 'deleted' event) has gone out
        try:
            board_key(board["id"])
        except (KeyError, ValueError):
            store.update_board(board["id"], sync_error="This board's key is missing on this Mac.")
            totals["failed"] += 1
            continue
        connector = connector_for(board, relay_connect, call)
        if connector is None:
            store.update_board(board["id"], sync_error="No bucket is connected on this Mac.")
            totals["failed"] += 1
            continue
        result = sync(store, board["id"], connector, call, relay_connect)
        totals["boards"] += 1
        totals["sent"] += result["sent"]
        totals["got"] += result["got"]
        totals["failed"] += not result["ok"]
        if log and not result["ok"]:
            log(f"board sync failed: {board['name']}: {result['error']}")
    if log and (totals["sent"] or totals["got"]):
        log(f"synced {totals['boards']} board(s): sent {totals['sent']}, received {totals['got']}")
    return totals


# ---- posts shared to a board from the phone ------------------------------------------------------------

READY_AFTER = 3600  # seconds: a post still unsummarised an hour after it was archived goes on the board as it is


def settle_pending(store, library=None) -> int:
    """Posts the phone shared to a board become cards once this Mac has read them (fetched, and summarised when a
    summary is coming). Returns how many cards were added."""
    from datetime import datetime

    from magpiary import modes

    me, added = identity.public_key(), 0
    for row in store.board_pending():
        board = store.board(row["board_id"])
        item = store.item_by_url(row["canonical_url"])
        if not board or not item:
            store.board_pending_done(row["board_id"], row["canonical_url"])
            continue
        if item["status"] != "archived":
            continue
        waited = 0.0
        try:
            waited = (datetime.fromisoformat(store.now()) - datetime.fromisoformat(item.get("archived_at") or "")).total_seconds()
        except ValueError:
            pass
        ready = (item.get("ai_status") in ("done", "needs_attention") or modes.current(store) == "private"
                 or waited >= READY_AFTER)
        if not ready:
            continue
        mine = {c["url"] for c in view(store, board["id"])["cards"] if me in c["adders"]}
        if item["canonical_url"] not in mine:
            add_card(store, board["id"], item, library, note=row["note"])
            added += 1
        store.board_pending_done(row["board_id"], row["canonical_url"])
    return added


PICKER_UNSAFE = re.compile(r"[\\^$.|?*+()\[\]{}\t\n\r]")
NEW_DAYS, QUIET_DAYS = 7, 7  # a board is asked about while made or changed in the last 7 days (owner, 25 Oct)


def phone_list(store, today=None) -> str:
    """The boards the phone's Shortcut asks about, most recently active first. Only active boards: made in the last
    7 days, or changed by anyone in the last 7. Each line is "DAYS<TAB>Name<TAB>id", where DAYS are the dates
    (yyyyMMdd) the board stays active, so the phone keeps only today's boards even when it is away from home and
    can't ask the Mac. Names lose the characters the Shortcut's pattern would read as instructions."""
    from datetime import date, datetime, timedelta

    today = today or datetime.fromisoformat(store.now()).date()
    rows = []
    for b in store.boards():
        try:
            joined = datetime.fromisoformat(b["joined_at"]).date()
        except ValueError:
            joined = today
        last = max((ev["at"] for ev in store.board_events(b["id"])), default=0)
        until = max(joined + timedelta(days=NEW_DAYS - 1),
                    (date.fromtimestamp(last) + timedelta(days=QUIET_DAYS - 1)) if last else joined)
        if until >= today:
            rows.append((last, b, until))
    lines, seen = [], {}
    for last, b, until in sorted(rows, key=lambda r: (-r[0], r[1]["name"])):
        name = " ".join(PICKER_UNSAFE.sub(" ", b["name"]).split()) or "Board"
        seen[name] = seen.get(name, 0) + 1
        name = f"{name} {seen[name]}" if seen[name] > 1 else name
        days = " ".join((today + timedelta(days=n)).strftime("%Y%m%d") for n in range((until - today).days + 1))
        lines.append(f"{days}\t{name}\t{b['id']}")
    return "\n".join(lines)
