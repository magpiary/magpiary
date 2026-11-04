"""First-run downloads: resumable, checksummed, quietly retried, with a stream of progress events for the installer window.

`plan()` lists what is still missing (the same things `downloads.catalog()` describes). `install()` fetches each one and emits
small dictionaries ("events") that the app shows as progress, or prints as JSON lines (`magpiary downloads install --json`).
A download that is stopped, cancelled or loses its connection keeps its `.part` file and carries on from there next time;
a file is only put in place after its SHA-256 matches. Nothing here needs the network until it is asked to download.
"""

import errno
import hashlib
import platform
import shutil
import socket
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from magpiary import downloads, embed, tools
from magpiary.config import data_dir

Emit = Callable[[dict], None]
CHUNK = 1 << 20
RETRY_DELAYS = (2, 5, 10, 20)  # seconds between the quiet retries; after the last one the error is shown
MIN_MACOS = (14, 0)  # the transcription libraries ship only for Apple Silicon on macOS 14+ (review 4 Nov 2026)
HEADROOM = 1_500_000_000  # kept free beyond the downloads: unpacking, the first library, the system
USER_AGENT = "Mozilla/5.0 (Macintosh) Magpiary"  # some download sites refuse Python's default (found in the M5 sandbox test)


class FetchError(Exception):
    """A download gave up. `kind`: offline, disk_full, server, checksum, permission, cancelled or tool."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


@dataclass
class Part:
    """One file to download. `unzip` names the file to take out of a zip."""
    url: str
    target: Path
    sha256: str
    bytes: int | None
    unzip: str = ""


@dataclass
class Step:
    id: str
    name: str
    parts: list[Part] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(p.bytes or 0 for p in self.parts)


# ---- reasons, in plain words ------------------------------------------------------------------

WORDS = {
    "offline": "Magpiary can't reach the internet right now. Check your connection; what's already downloaded is kept.",
    "disk_full": "This Mac is out of space. Free up some room and try again; what's already downloaded is kept.",
    "server": "The download site isn't answering properly. Try again in a little while.",
    "checksum": "A download didn't match its published checksum, so it wasn't used. Trying again usually fixes it.",
    "permission": "Magpiary couldn't write to its folder. Check that your user can write to it.",
    "tool": "A helper program needed for this step isn't available.",
    "cancelled": "Stopped. Open Magpiary again to carry on where it left off.",
}


def classify(err: BaseException) -> str:
    if isinstance(err, FetchError):
        return err.kind
    if isinstance(err, OSError) and err.errno == errno.ENOSPC:
        return "disk_full"
    if isinstance(err, PermissionError):
        return "permission"
    if isinstance(err, urllib.error.HTTPError):
        return "server"
    if isinstance(err, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError)):
        return "offline"
    return "server"


# ---- checks before anything is downloaded -----------------------------------------------------

def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def precheck(needed: int, home: Path | None = None, macos: str | None = None, machine: str | None = None) -> list[dict]:
    """Problems that stop an install before it starts, each {"kind", "message"}; empty when all is well."""
    problems = []
    version = macos if macos is not None else platform.mac_ver()[0]
    if version:
        try:
            have = tuple(int(x) for x in version.split(".")[:2])
        except ValueError:
            have = (99, 0)
        if have < MIN_MACOS:
            problems.append({"kind": "macos", "message": f"Magpiary needs macOS {MIN_MACOS[0]} or newer; this Mac has {version}."})
    chip = machine or platform.machine()
    if chip != "arm64":
        problems.append({"kind": "chip", "message": "Magpiary needs a Mac with Apple Silicon (M1 or newer)"
                         + (f"; this Mac has {chip}." if chip else ".")})
    need = needed + HEADROOM
    have_free = free_bytes(home or data_dir())
    if have_free < need:
        problems.append({"kind": "disk", "message": f"Magpiary needs about {downloads.human_size(need)} free to install; "
                                                     f"this Mac has {downloads.human_size(have_free)}. Free up some space and open it again."})
    return problems


# ---- the download itself ----------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(part: Part, report: Callable[[int, int], None] = lambda done, total: None, opener=urllib.request.urlopen,
          sleep: Callable[[float], None] = time.sleep, cancelled: Callable[[], bool] = lambda: False,
          on_retry: Callable[[int, float, str], None] = lambda attempt, wait, kind: None) -> Path:
    """Download one file to `<target>.part`, resuming where it stopped, retrying quietly, then verify it and move it into place.
    Raises FetchError. Returns the path of the verified download (the target, or the zip for `unzip` parts)."""
    target = part.target
    final = target if not part.unzip else target.with_name(target.name + ".zip")
    if final.exists() and not part.unzip:
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".part")
    fresh_tries = 0
    attempt = 0
    while True:
        try:
            have = partial.stat().st_size if partial.exists() else 0
            if part.bytes and have > part.bytes:
                partial.unlink()
                have = 0
            if part.bytes and free_bytes(final.parent) < part.bytes - have + 50_000_000:
                raise FetchError("disk_full", WORDS["disk_full"])
            if not (part.bytes and have == part.bytes):
                have = _download(part, partial, have, report, opener, cancelled)
            if _sha256(partial) != part.sha256:
                partial.unlink(missing_ok=True)
                fresh_tries += 1
                if fresh_tries > 1:
                    raise FetchError("checksum", WORDS["checksum"])
                continue  # one clean start from zero before giving up
            partial.rename(final)
            return final
        except FetchError as err:
            if err.kind in ("cancelled", "disk_full", "checksum", "permission"):
                raise
            kind = err.kind
        except BaseException as err:  # noqa: BLE001 - classified below; keyboard interrupts become "cancelled"
            if isinstance(err, KeyboardInterrupt):
                raise FetchError("cancelled", WORDS["cancelled"]) from err
            kind = classify(err)
            if kind in ("disk_full", "permission"):
                raise FetchError(kind, WORDS[kind]) from err
        if attempt >= len(RETRY_DELAYS):
            raise FetchError(kind, WORDS[kind])
        wait = RETRY_DELAYS[attempt]
        attempt += 1
        on_retry(attempt, wait, kind)
        sleep(wait)
        if cancelled():
            raise FetchError("cancelled", WORDS["cancelled"])


def _download(part: Part, partial: Path, have: int, report, opener, cancelled) -> int:
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(part.url, headers=headers)
    try:
        response = opener(request, timeout=30)
    except urllib.error.HTTPError as err:
        if err.code == 416 and have:  # asked for bytes past the end: the file is already whole
            return have
        raise
    with response:
        status = getattr(response, "status", 200)
        if have and status != 206:  # the server ignored the resume request: start again from zero
            have = 0
        length = int(response.headers.get("Content-Length") or 0)
        total = part.bytes or (have + length)
        with partial.open("ab" if have else "wb") as out:
            done = have
            report(done, total)
            while chunk := response.read(CHUNK):
                if cancelled():
                    raise FetchError("cancelled", WORDS["cancelled"])
                out.write(chunk)
                done += len(chunk)
                report(done, total)
    return done


def _unzip(archive: Path, part: Part) -> None:
    with zipfile.ZipFile(archive) as zf:
        inside = next((n for n in zf.namelist() if Path(n).name == part.unzip), None)
        if inside is None:
            archive.unlink(missing_ok=True)
            raise FetchError("checksum", f"The download did not contain {part.unzip}.")
        staging = part.target.with_suffix(".part")
        staging.write_bytes(zf.read(inside))
        staging.chmod(0o755)
        staging.rename(part.target)
    archive.unlink(missing_ok=True)


# ---- what to install --------------------------------------------------------------------------

def _whisper_target() -> Path:
    from pywhispercpp.constants import MODELS_DIR

    return Path(MODELS_DIR) / f"ggml-{downloads.WHISPER_MODEL}.bin"


def plan(only_missing: bool = True) -> list[Step]:
    """The downloads in the order they are fetched (small first). Already-installed ones are left out unless asked for."""
    arch = downloads._arch()
    catalog = {d.id: d for d in downloads.catalog()}
    steps = []
    for name in ("ffprobe", "ffmpeg", "deno"):
        url, sha = tools.STANDALONE[(name, arch)]
        steps.append(Step(name, catalog[name].name, [Part(url, tools.tools_dir() / name, sha, downloads._SIZES.get((name, arch)), unzip=name)]))
    steps.append(Step("meaning-model", catalog["meaning-model"].name, [
        Part(f"https://huggingface.co/{embed.REPO}/resolve/{embed.REVISION}/{remote}", embed.model_dir() / name, sha,
             {"model_quantized.onnx": 118_308_185, "tokenizer.json": 17_082_730}.get(name))
        for name, (remote, sha) in embed.FILES.items()]))
    steps.append(Step("whisper-model", catalog["whisper-model"].name,
                      [Part(downloads.WHISPER_URL, _whisper_target(), downloads.WHISPER_SHA256, downloads.WHISPER_BYTES)]))
    return [s for s in steps if not (only_missing and catalog[s.id].installed)]


def install(emit: Emit, steps: list[Step] | None = None, opener=urllib.request.urlopen, sleep=time.sleep,
            cancelled: Callable[[], bool] = lambda: False) -> bool:
    """Run every missing download. Emits events; returns True when everything is in place.

    Events: precheck (problems), plan (steps with sizes), step_start, progress (step and overall bytes), retry, step_done,
    step_error, finished (ok). A failed step stops the run, because the hub opens only when everything is here."""
    steps = plan() if steps is None else steps
    if not steps:  # everything is already here: nothing to check or fetch
        emit({"event": "plan", "steps": [], "total_bytes": 0})
        emit({"event": "finished", "ok": True})
        return True
    total = sum(s.bytes for s in steps)
    info = {d.id: d for d in downloads.catalog()}
    emit({"event": "plan", "total_bytes": total, "steps": [
        {"id": s.id, "name": s.name, "bytes": s.bytes or None, "source": info[s.id].source if s.id in info else "",
         "why": info[s.id].why if s.id in info else ""} for s in steps]})
    problems = precheck(total)
    if problems:
        emit({"event": "precheck", "problems": problems})
        emit({"event": "finished", "ok": False, "reason": problems[0]["kind"]})
        return False
    finished_bytes = 0
    for step in steps:
        emit({"event": "step_start", "id": step.id, "name": step.name, "bytes": step.bytes or None})
        try:
            for part in step.parts:
                base = finished_bytes

                def report(done: int, size: int, step=step, base=base) -> None:
                    emit({"event": "progress", "id": step.id, "done": done, "total": size, "overall_done": base + done, "overall_total": total})

                def retry(attempt: int, wait: float, kind: str, step=step) -> None:
                    emit({"event": "retry", "id": step.id, "attempt": attempt, "wait": wait, "reason": kind})

                path = fetch(part, report, opener, sleep, cancelled, retry)
                if part.unzip:
                    _unzip(path, part)
                finished_bytes += part.bytes or 0
        except FetchError as err:
            emit({"event": "step_error", "id": step.id, "kind": err.kind, "message": err.message})
            emit({"event": "finished", "ok": False, "reason": err.kind})
            return False
        emit({"event": "step_done", "id": step.id})
    emit({"event": "finished", "ok": True})
    return True
