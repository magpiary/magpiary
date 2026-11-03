"""Ask Magpiary on Codex (the owner's ChatGPT plan): the same open question-and-answer as Claude Code, run headless with
`codex exec --json`. It can search the web and look through the owner's saves (the read-only library tools, on this Mac).

Codex always has a shell, so the shell is confined by the operating system, not by a request: a permissions profile gives it read access
to the minimum the system needs and to its empty working folder, and nothing else (no home folder, no keys, no library, no Codex login).
The library tools run as a separate read-only server outside the shell. Before every first run, `confined()` proves the profile really
blocks a canary file, and Ask refuses to start Codex if it does not (a future Codex version could change the rules).

Answers arrive a message at a time (no word-by-word), so the page shows the steps live and the answer when it is written."""

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from magpiary import ask_open, askconfig
from magpiary.brain import BrainFailed

APPROVE = 'mcp_servers.magpiary.default_tools_approval_mode="approve"'
PROFILE = "magpiary_ask"


def profile_config(folder: Path | str) -> list[str]:
    """Shell commands may read system files and the empty working folder only; the home folder, keys and library stay closed."""
    return ["-c", f'default_permissions="{PROFILE}"', "-c", f'permissions.{PROFILE}.filesystem={{":minimal"="read","{folder}"="read"}}']


_confined: bool | None = None


def binary() -> str:
    """The codex program, or "" when this Mac has none."""
    found = shutil.which("codex")
    if found:
        return found
    for guess in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        if Path(guess).exists():
            return guess
    return ""


def signed_in() -> bool:
    return (Path.home() / ".codex" / "auth.json").exists()


def confined(run=subprocess.run) -> bool:
    """True only if a shell under our profile cannot read a secret file in the home folder. Checked once per run of the hub; free (no model call)."""
    global _confined
    if _confined is not None:
        return _confined
    codex = binary()
    if not codex:
        return False
    import secrets
    import tempfile

    with tempfile.TemporaryDirectory(prefix=".magpiary-canary-", dir=Path.home()) as home_dir, \
            tempfile.TemporaryDirectory(prefix=".magpiary-work-", dir=Path.home()) as work:
        canary = Path(home_dir) / "secret.txt"
        token = secrets.token_hex(8)
        canary.write_text(token)
        (Path(work) / "ok.txt").write_text("ok")
        try:
            blocked = run([codex, "sandbox", *profile_config(work), "-P", PROFILE, "-C", work, "--", "cat", str(canary)],
                          capture_output=True, text=True, timeout=30)
            allowed = run([codex, "sandbox", *profile_config(work), "-P", PROFILE, "-C", work, "--", "cat", "ok.txt"],
                          capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False  # not cached: try again next time
    _confined = token not in (blocked.stdout or "") and blocked.returncode != 0 and "ok" in (allowed.stdout or "")
    return _confined


def available() -> bool:
    return bool(binary()) and signed_in()


def command(codex: str, model: str, effort: str, web: bool, python: str | None = None, folder: Path | str = "") -> list[str]:
    """Headless, read-only, nothing saved, no approvals. The library tools are the same read-only server Claude Code uses."""
    import sys

    return [codex, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", *profile_config(folder),
            "-c", 'shell_environment_policy.inherit="core"', "-m", model,
            "-c", f"model_reasoning_effort={effort}", "-c", f'web_search="{"live" if web else "disabled"}"',
            "-c", f'mcp_servers.magpiary.command="{python or sys.executable}"', "-c", 'mcp_servers.magpiary.args=["-m","magpiary.mcp_library"]',
            "-c", APPROVE, "-"]


def step_for(item: dict) -> dict | None:
    """The thinking-tree step for something Codex started, or None."""
    kind = item.get("type")
    if kind == "web_search":
        query = str(item.get("query") or (item.get("action") or {}).get("query") or "")[:90]
        return {"step": f"Searching the web: {query}", "kind": "search", "arg": query}
    if kind == "mcp_tool_call":
        return ask_open.step_for(str(item.get("tool", "")), item.get("arguments") or {})
    if kind == "command_execution":
        return {"step": "Looking around on this Mac", "kind": "work", "arg": ""}
    return None


def handle(line: str, on_event: Callable[[dict], None], state: dict) -> str | None:
    """One line of Codex's stream. Steps and text go to on_event; the usage arrives at the end. Returns "done" once the turn is
    complete. `state` remembers what was already shown."""
    try:
        data = json.loads(line)
    except ValueError:
        return None
    kind, item = data.get("type"), data.get("item") or {}
    seen = state.setdefault("seen", set())
    if kind in ("item.started", "item.completed") and item.get("type") != "agent_message":
        # a web search names its query when it finishes; the other tools when they start
        right_moment = kind == ("item.completed" if item.get("type") == "web_search" else "item.started")
        step = step_for(item)
        if right_moment and step and item.get("id") not in seen:
            seen.add(item.get("id"))
            on_event(step)
    elif kind == "item.completed" and item.get("text"):
        on_event({"text": ("\n\n" if state.get("wrote") else "") + item["text"]})
        state["wrote"] = True
    elif kind == "turn.completed":
        u = data.get("usage") or {}
        on_event({"usage": {"in": int(u.get("input_tokens", 0)) - int(u.get("cached_input_tokens", 0)), "cached": int(u.get("cached_input_tokens", 0)), "out": int(u.get("output_tokens", 0)) + int(u.get("reasoning_output_tokens", 0)),
                            "cost": 0.0}})
        return "done"
    elif kind in ("error", "turn.failed"):
        raise BrainFailed("unknown", "Codex stopped without a usable answer")
    return None


def run(question: str, items: list[dict], history: list[tuple[str, str]], scope: str, on_event: Callable[[dict], None],
        cancelled: Callable[[], bool] = lambda: False, popen=subprocess.Popen, timeout: int = 300,
        model: str = "gpt-6-luna", effort: str = "medium", web: bool = True, context: str = "", depth: str = "short", goals: str = "") -> str:
    """Ask Codex. Streams steps; returns the answer text. Raises BrainFailed with a plain reason."""
    from magpiary.config import data_dir

    codex = binary()
    if not codex:
        raise BrainFailed("unknown", "Codex is not installed")
    if not confined():
        raise BrainFailed("unknown", "Codex is not started: this Mac's Codex does not enforce the file restrictions Magpiary needs")
    folder = data_dir() / "codex"  # an empty folder: nothing here to read
    folder.mkdir(parents=True, exist_ok=True)
    posts = ask_open.posts_for(items, question)
    prompt = (ask_open.system(depth) + "\nDo not run shell commands and do not read files on this computer: use only web search (when you have "
              "it) and the search_saves and read_save tools.\n\n" + ask_open.build_prompt(question, posts, history, scope, context, goals))
    try:
        proc = popen(command(codex, model, effort, web, folder=folder), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=folder)
    except OSError as err:
        raise BrainFailed("unknown", f"Codex did not start: {type(err).__name__}") from err
    timer = threading.Timer(max(timeout, askconfig.DEPTH_SECONDS.get(depth, timeout)), proc.kill)
    timer.start()
    parts: list[str] = []
    finished = False
    state: dict = {}

    def forward(ev: dict) -> None:
        if "text" in ev:
            parts.append(ev["text"])
        on_event(ev)
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            if cancelled():
                proc.kill()
                break
            if handle(line, forward, state) == "done":
                finished = True
        proc.wait()
    finally:
        timer.cancel()
    text = "".join(parts).strip()
    if not finished or not text:
        raise BrainFailed("unknown", "Codex gave no answer (is it signed in?)")
    return text
