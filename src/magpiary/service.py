"""Run the receiver as a background service (a launchd agent) so it starts at login and restarts if it stops.

launchd starts the hub through a small launcher inside a bundle named Magpiary (helper/hub.c), so macOS permission
prompts say "Magpiary" with its icon rather than "Python 3.12": Magpiary.app (the DMG) carries one, and other installs
build one once in the config folder. Without Apple's command line tools the hub runs directly, as before.

Every outside action goes through the injected `run`, so tests never touch the real launchd.
"""

import hashlib
import os
import plistlib
import shutil
import subprocess
import tempfile
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


HELPER_EXE = "magpiary-hub"


def helper_app() -> Path:
    from magpiary.config import config_dir

    return config_dir() / "Magpiary.app"


def bundled_helper(program: Path) -> Path | None:
    """Magpiary.app (the DMG) has the launcher beside its own program: prompts then name the app itself."""
    for parent in program.parents:
        if parent.suffix == ".app":
            exe = parent / "Contents" / "MacOS" / HELPER_EXE
            return exe if exe.is_file() else None
    return None


def build_helper(run: Run = default_run) -> Path | None:
    """The launcher bundle for installs without Magpiary.app. Built only when missing or its source changed, because
    macOS ties what the owner allowed to this exact build. None when it can't be built (no command line tools: never
    start Apple's installer pop-up for this)."""
    from importlib import resources

    from magpiary import __version__

    folder = resources.files("magpiary") / "helper"
    source = (folder / "hub.c").read_bytes()
    icon = (folder / "icon.png").read_bytes()
    digest = hashlib.sha256(source + icon).hexdigest()
    app = helper_app()
    exe = app / "Contents" / "MacOS" / HELPER_EXE
    stamp = app / "Contents" / "Resources" / "source.sha256"
    if exe.is_file() and stamp.is_file() and stamp.read_text().strip() == digest:
        return exe
    try:
        if run(["xcode-select", "-p"]).returncode != 0:
            return None
        work = Path(tempfile.mkdtemp(prefix="magpiary-helper-"))
        try:
            bundle = work / "Magpiary.app"
            (bundle / "Contents" / "MacOS").mkdir(parents=True)
            (bundle / "Contents" / "Resources").mkdir()
            (work / "hub.c").write_bytes(source)
            built = bundle / "Contents" / "MacOS" / HELPER_EXE
            if run(["xcrun", "clang", "-O2", "-o", str(built), str(work / "hub.c")]).returncode != 0 or not built.is_file():
                return None
            (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleName": "Magpiary", "CFBundleDisplayName": "Magpiary", "CFBundleIdentifier": "org.magpiary.hub",
                "CFBundleExecutable": HELPER_EXE, "CFBundlePackageType": "APPL", "CFBundleIconFile": "Magpiary",
                "CFBundleShortVersionString": __version__, "LSUIElement": True, "LSBackgroundOnly": True}))
            iconset = work / "Magpiary.iconset"
            iconset.mkdir()
            (work / "icon.png").write_bytes(icon)
            for size in (16, 32, 128, 256):
                for scale, name in ((1, f"icon_{size}x{size}.png"), (2, f"icon_{size}x{size}@2x.png")):
                    run(["sips", "-z", str(size * scale), str(size * scale), str(work / "icon.png"), "--out", str(iconset / name)])
            run(["iconutil", "-c", "icns", str(iconset), "-o", str(bundle / "Contents" / "Resources" / "Magpiary.icns")])
            (bundle / "Contents" / "Resources" / "source.sha256").write_text(digest)
            if run(["codesign", "--force", "--sign", "-", str(bundle)]).returncode != 0:
                return None
            app.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(app, ignore_errors=True)
            shutil.move(str(bundle), str(app))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if exe.is_file() else None


def build_plist(program: Path, port: int, env: dict[str, str], helper: Path | None = None) -> bytes:
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"}
    for name in ("MAGPIARY_HOME", "MAGPIARY_CONFIG"):
        if env.get(name):
            environment[name] = env[name]
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ([str(helper)] if helper else []) + [str(program), "serve", "--port", str(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "EnvironmentVariables": environment,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    })


def install(program: Path, port: int, run: Run = default_run, env: dict[str, str] | None = None,
            wait: Callable[[float], None] = time.sleep, helper: Path | None = None) -> str:
    program = stable_path(program.resolve() if program.exists() else program)
    check_program(program)
    if helper is None and run is default_run:  # a real install: prompts should name Magpiary (tests pass their own)
        helper = bundled_helper(program) or build_helper()
    plist_path().parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    plist_path().write_bytes(build_plist(program, port, env if env is not None else dict(os.environ), helper))
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
    named = "Magpiary" if helper else "Python (Apple's command line tools are missing, so macOS prompts name Python)"
    return f"Service installed. The receiver now starts at login and macOS prompts name it {named}. Log: {log_path()}"


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
