"""What `magpiary add` and `magpiary note` do. AI agents on this Mac save links and write notes through the running
hub, with their own key (a device of kind "agent", kept in ~/.config/magpiary/agent.key, mode 0600), so the hub's queue
stays in charge and the owner can cut an agent off by revoking that device."""

import json
import os
import urllib.error
import urllib.request
import uuid

from magpiary import agent_policy
from magpiary.cleaner import UnsupportedLink, clean
from magpiary.config import config_dir, db_path
from magpiary.library import NOTICE
from magpiary.protocol import DEFAULT_PORT
from magpiary.store import Store

KEY_FILE = "agent.key"
DEVICE_NAME = "AI agents (command line)"


class AgentError(Exception):
    pass


def key_path():
    return config_dir() / KEY_FILE


def ensure_key() -> str:
    """The agent key, made the first time. If the key file was lost, the old agent device is retired and a new one made."""
    path = key_path()
    if path.exists():
        return path.read_text().strip()
    store = Store(db_path())
    try:
        store.revoke_phone(DEVICE_NAME)
        _, key = store.add_phone(DEVICE_NAME, kind="agent")
    finally:
        store.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(key + "\n")
    return key


def _post(path: str, payload: dict, port: int) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", json.dumps(payload).encode(),
        {"Authorization": f"Bearer {ensure_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as err:
        try:
            message = json.loads(err.read()).get("error", "")
        except ValueError:
            message = ""
        if err.code == 401:
            raise AgentError(f"The hub did not accept the agent key. If it was revoked, delete {key_path()} and try again.") from None
        if err.code == 404 and path == "/v1/agent/note" and message == "not found":
            raise AgentError("The running hub is an older version without this command. Run `magpiary update`.") from None
        raise AgentError(message or f"The hub answered with an error ({err.code}).") from None
    except (urllib.error.URLError, OSError):
        raise AgentError(f"The Magpiary hub is not running on port {port}. Start it with `magpiary service install`, "
                         "then try again. (Searching and reading still work without it.)") from None


def add(url: str, port: int = DEFAULT_PORT) -> dict:
    try:
        link = clean(url)
    except UnsupportedLink:
        raise AgentError("Magpiary can't save that: it is not a link to a post or page it understands.") from None
    reply = _post("/v1/items", {"items": [{"id": uuid.uuid4().hex, "url": url}]}, port)
    result = (reply.get("results") or [{}])[0]
    rejected = reply.get("rejected") or []
    if rejected:
        raise AgentError(f"Magpiary can't save that link ({rejected[0].get('reason', 'rejected')}).")
    status = result.get("status", "new")
    try:
        store = Store(db_path(), read_only=True)
        try:
            item_id = store.id_for(link.url)
            if item_id is not None and link.url in agent_policy.hidden_urls(store):
                item_id, status = None, "again"  # a save the owner hid from agents: say only that it is already there
        finally:
            store.close()
    except Exception:
        item_id = None
    return {"notice": NOTICE, "status": "again" if status == "again" else "new", "id": item_id, "url": link.url}


def note(item_id: int, mode: str, text: str = "", by: str = "", port: int = DEFAULT_PORT) -> dict:
    reply = _post("/v1/agent/note", {"id": item_id, "mode": mode, "text": text, "by": by}, port)
    return {"notice": NOTICE, "id": item_id, "agent_note": reply["agent_note"]}
