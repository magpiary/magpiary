"""Setting up Claude Code or Codex from Settings → Ask Magpiary, with one tap: install it when this Mac doesn't have it, then
open its own sign-in page in the browser (the Mac asks for the usual permissions there). It runs in the background; the page
shows how far it got. Magpiary never sees the password or the sign-in: the tool's own login does that.

Each engine: (check installed, install command, sign-in command)."""

import shutil
import subprocess
import threading
import time
from pathlib import Path

from magpiary import ask_codex, claude_code

ENGINES = ("claude", "codex")
_jobs: dict[str, dict] = {}


def installed(engine: str) -> bool:
    if engine == "claude":
        return bool(shutil.which("claude")) or Path(claude_code.command()).exists()
    return bool(ask_codex.binary())


def commands(engine: str) -> tuple[list[str] | None, list[str]]:
    """(install, sign in). Install is None when the tool is already here."""
    if engine == "claude":
        have = installed("claude")
        return (None if have else ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"], [claude_code.command(), "auth", "login"])
    have = installed("codex")
    install = None if have else (["npm", "install", "-g", "@openai/codex"] if shutil.which("npm") else ["brew", "install", "codex"])
    return install, [ask_codex.binary() or "codex", "login"]


def status(engine: str) -> dict:
    """{"state": "idle" | "working" | "error", "text": plain words}."""
    return dict(_jobs.get(engine) or {"state": "idle", "text": ""})


def start(engine: str, run=subprocess.run) -> bool:
    """Begin (False when it is already running)."""
    if engine not in ENGINES or status(engine)["state"] == "working":
        return False
    _jobs[engine] = {"state": "working", "text": "Starting…", "at": time.monotonic()}

    def work() -> None:
        try:
            install, login = commands(engine)
            if install:
                _jobs[engine]["text"] = "Installing it on this Mac…"
                done = run(install, capture_output=True, text=True, timeout=900)
                if done.returncode != 0:
                    _jobs[engine] = {"state": "error", "text": "The install didn't finish. " + (done.stderr or "")[-160:].strip()}
                    return
                login = commands(engine)[1]
            _jobs[engine]["text"] = "Sign in on the page that opened in your browser…"
            run(login, capture_output=True, text=True, timeout=600)
            _jobs.pop(engine, None)
        except (OSError, subprocess.SubprocessError) as err:
            _jobs[engine] = {"state": "error", "text": f"Couldn't finish ({type(err).__name__}). Try again."}
    threading.Thread(target=work, name="ask-setup", daemon=True).start()
    return True
