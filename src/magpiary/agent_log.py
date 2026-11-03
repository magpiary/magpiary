"""What AI agents did, kept in a private file next to the keys (not in the database, so reading stays read-only).
Written by the commands and the MCP server; shown in Settings → AI agents."""

import json
import os
from datetime import datetime

from magpiary.config import config_dir

FILE = "agent-activity.jsonl"
KEEP = 500


def _path():
    return config_dir() / FILE


def record(tool: str, detail: str = "", ok: bool = True, why: str = "") -> None:
    """One line per action. Never raises: a full disk must not stop an agent's answer."""
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if tool == "add":
            from magpiary.cleaner import UnsupportedLink, clean

            try:
                detail = clean(detail).url
            except UnsupportedLink:
                detail = "(unsupported link)"
        line = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "tool": tool, "detail": detail[:120],
                "ok": ok, "why": why[:200]}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
        if path.stat().st_size > 256_000:
            lines = path.read_text().splitlines()[-KEEP:]
            path.write_text("\n".join(lines) + "\n")
    except (OSError, ValueError):
        pass


def recent(n: int = 10) -> list[dict]:
    try:
        lines = _path().read_text().splitlines()[-n:]
    except (OSError, ValueError):
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def clear() -> None:
    try:
        _path().unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
