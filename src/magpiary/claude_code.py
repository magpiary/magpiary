"""Claude Code on the owner's Claude plan: where it is installed and how it stands. The check never spends the plan.
Whether it may be used at all is engines.py's rule (allowed in AI keys, after a test run)."""

import json
import shutil
import subprocess
from pathlib import Path


def command() -> str:
    """Where the service finds Claude Code: its PATH, then the usual install folder."""
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


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
