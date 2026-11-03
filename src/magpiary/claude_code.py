"""Claude Code on the owner's Claude plan, as a Magpiary helper: how it is used (the digest story today), how it
stands, and how to switch it off. Checks never spend the plan; only the test button does, a few tokens, when pressed."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from magpiary.config import data_dir

USE = "claude_use"
WAIT = "claude_wait_hours"
TEST = "claude_test"
DEFAULT_WAIT = 24
CHOICES = {
    "first": ("Claude Code first, then my key", "Claude Code writes it. If that hasn't worked in the time below, your AI key does."),
    "only": ("Claude Code only", "Only Claude Code writes it. If it can't, the digest waits."),
    "key": ("My key only", "Your AI key writes it straight away. Claude Code isn't used."),
}
WAIT_CHOICES = {6: "6 hours", 12: "12 hours", 24: "1 day", 48: "2 days", 72: "3 days"}


def mode(store) -> str:
    v = store.get_setting(USE, "first")
    return v if v in CHOICES else "first"


def wait_hours(store) -> int:
    try:
        v = int(store.get_setting(WAIT, str(DEFAULT_WAIT)))
    except ValueError:
        return DEFAULT_WAIT
    return v if v in WAIT_CHOICES else DEFAULT_WAIT


def command() -> str:
    """Where the service finds Claude Code: its PATH, then the usual install folder."""
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def folder() -> Path:
    return data_dir() / "claude"


def check(run=subprocess.run) -> dict:
    """Installed, which version, signed in. Free: it never sends a prompt."""
    out = {"installed": False, "version": "", "signed_in": None, "plan": "", "why": ""}
    cmd = command()
    try:
        v = run([cmd, "--version"], capture_output=True, text=True, timeout=20)
        out["installed"] = v.returncode == 0
        out["version"] = (v.stdout or "").split(" ")[0].strip()
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        out["why"] = "Claude Code isn't installed on this Mac."
        return out
    if not out["installed"]:
        out["why"] = "Claude Code isn't installed on this Mac."
        return out
    try:
        a = run([cmd, "auth", "status"], capture_output=True, text=True, timeout=20)
        info = json.loads(a.stdout or "{}")
        out["signed_in"] = bool(info.get("loggedIn"))
        out["plan"] = str(info.get("subscriptionType") or "")
        if not out["signed_in"]:
            out["why"] = "Claude Code isn't signed in. Run claude in Terminal and sign in."
    except (ValueError, OSError, subprocess.SubprocessError):
        out["why"] = "Couldn't read whether Claude Code is signed in."
    return out


def tiny_test(store, run=subprocess.run, now: datetime | None = None) -> dict:
    """One short prompt through the same headless path the digest uses; spends a few tokens. Remembered."""
    folder().mkdir(parents=True, exist_ok=True)
    ok, text = False, ""
    try:
        done = run([command(), "-p", "--model", "sonnet", "--system-prompt", "Reply with the single word ok.", "--tools", "",
                    "--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence"],
                   input="ok?", capture_output=True, text=True, timeout=120, cwd=folder())
        ok = done.returncode == 0 and bool((done.stdout or "").strip())
        text = "Answered." if ok else "Claude Code gave no answer. Check that it is signed in."
    except FileNotFoundError:
        text = "Claude Code isn't installed."
    except (OSError, subprocess.SubprocessError) as err:
        text = f"It did not finish: {type(err).__name__}"
    result = {"at": (now or datetime.now()).isoformat(timespec="seconds"), "ok": ok, "text": text}
    store.set_setting(TEST, json.dumps(result))
    return result


def last_test(store) -> dict | None:
    try:
        return json.loads(store.get_setting(TEST, "") or "null")
    except ValueError:
        return None


def last_run(store) -> dict:
    """The newest digest story Claude Code wrote, and the newest failure after it: {"ok": iso|None, "err": (iso, why)|None}."""
    ok = None
    err = None
    for row in store.digests(10):
        data = store.digest(row["id"])["data"]
        if data.get("story_by") == "Claude Code" and data.get("story_at") and (ok is None or data["story_at"] > ok):
            ok = data["story_at"]
        for t in data.get("story_tries", []):
            if t.get("by") == "Claude Code" and (err is None or t["at"] > err[0]):
                err = (t["at"], t.get("why", ""))
    if err and ok and err[0] <= ok:
        err = None
    return {"ok": ok, "err": err}


def clear_folder() -> bool:
    """Delete Magpiary's own working folder for Claude Code. Claude Code itself stays installed."""
    f = folder()
    if f.exists():
        shutil.rmtree(f, ignore_errors=True)
        return True
    return False
