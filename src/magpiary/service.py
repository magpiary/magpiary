"""Run the receiver as a background service (a launchd agent) so it starts at login and restarts if it stops.

Every outside action goes through the injected `run`, so tests never touch the real launchd.
"""

import os
import plistlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

LABEL = "org.magpiary.receiver"
PROTECTED_FOLDERS = ("Documents", "Desktop", "Downloads")

Run = Callable[[list[str]], subprocess.CompletedProcess]


class ServiceError(Exception):
    """Something the owner can fix; the message says what."""


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "Magpiary" / "receiver.log"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def default_run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def check_program(program: Path) -> None:
    """macOS refuses to let background services read files in Documents, Desktop or Downloads."""
    if not program.is_file():
        raise ServiceError(f"The magpiary program was not found at {program}.")
    home = Path.home()
    for folder in PROTECTED_FOLDERS:
        if program.is_relative_to(home / folder):
            raise ServiceError(
                f"The program is inside ~/{folder}, which macOS does not let background services read.\n"
                "Install a copy outside it, then run this again from that copy:\n"
                "  uv tool install --reinstall .")


def stable_path(program: Path) -> Path:
    """Homebrew keeps each version in its own Cellar folder, removed on upgrade; its `opt` link always points at the
    current one, so the service uses that."""
    parts = program.parts
    if "Cellar" in parts:
        i = parts.index("Cellar")
        return Path(*parts[:i], "opt", parts[i + 1], *parts[i + 3:])
    return program


def build_plist(program: Path, port: int, env: dict[str, str]) -> bytes:
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"}
    for name in ("MAGPIARY_HOME", "MAGPIARY_CONFIG"):
        if env.get(name):
            environment[name] = env[name]
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(program), "serve", "--port", str(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "EnvironmentVariables": environment,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    })


def install(program: Path, port: int, run: Run = default_run, env: dict[str, str] | None = None,
            wait: Callable[[float], None] = time.sleep) -> str:
    program = stable_path(program.resolve() if program.exists() else program)
    check_program(program)
    plist_path().parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    plist_path().write_bytes(build_plist(program, port, env if env is not None else dict(os.environ)))
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])  # fine if it was not loaded
    for _ in range(20):  # the old copy takes a moment to stop; starting too early fails with error 5
        if run(["launchctl", "print", f"{_domain()}/{LABEL}"]).returncode != 0:
            break
        wait(0.5)
    for attempt in range(3):
        result = run(["launchctl", "bootstrap", _domain(), str(plist_path())])
        if result.returncode == 0:
            break
        wait(1.0)
    if result.returncode != 0:
        raise ServiceError(f"launchd refused the service: {result.stderr.strip() or result.stdout.strip()}")
    run(["launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}"])
    return f"Service installed. The receiver now starts at login. Log: {log_path()}"


def uninstall(run: Run = default_run) -> str:
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    existed = plist_path().exists()
    plist_path().unlink(missing_ok=True)
    return "Service removed." if existed else "The service was not installed."


def status(port: int, run: Run = default_run, ping: Callable[[int], bool] | None = None) -> str:
    if not plist_path().exists():
        return "Not installed."
    result = run(["launchctl", "print", f"{_domain()}/{LABEL}"])
    if result.returncode != 0:
        return "Installed, but not loaded. Run: magpiary service install"
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep:
            fields.setdefault(key, value)
    state, pid = fields.get("state", "unknown"), fields.get("pid")
    answering = (ping or _ping)(port)
    lines = [f"Installed. launchd state: {state}" + (f", process {pid}" if pid else ""),
             f"Receiver answering on port {port}: {'yes' if answering else 'no'}",
             f"Log: {log_path()}"]
    return "\n".join(lines)


def _ping(port: int) -> bool:
    from magpiary.protocol import ping_is_mine

    return ping_is_mine(port)
