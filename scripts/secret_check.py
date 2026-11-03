"""Refuse to commit anything that looks like a key, token or password, or a file named like Magpiary's secrets.

    python3 scripts/secret_check.py            # the staged changes (the commit check runs this)
    python3 scripts/secret_check.py --history --worktree  # refs/reflogs plus current files

Only the place and the kind of a finding are printed, never the value. Fake-marker comments do not bypass checks:
tests should construct synthetic key-shaped values at runtime rather than commit credential-shaped literals.
"""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "Google API key": r"AIza[0-9A-Za-z_\-]{35}",
    "OpenRouter key": r"sk-or-v1-[0-9a-f]{32,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "OpenAI key": r"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}",
    "Tavily key": r"tvly-[A-Za-z0-9_\-]{20,}",
    "Brave key": r"\bBSA[A-Za-z0-9_\-]{20,}",
    "Nostr private key": r"\bnsec1[023456789acdefghjklmnpqrstuvwxyz]{20,}",
    "Backblaze application key": r"\bK00[0-9A-Za-z+/]{28}\b",
    "AWS access key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "password or secret in quotes": r"(?i)\b(?:api_?key|secret|password|passwd|token|pairing_key|sessionid|csrftoken|b2_app_key|secret_?key|private_?key)\b[\"']?\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']",
}
FILES = re.compile(r"(?:^|/)(?:keys\.json|boards\.json|stats-proxy|agent-activity\.jsonl|identity\.key|b2\.env|instagram-login\.txt|[^/]*cookies[^/]*\.(?:txt|json)|\.pairing_key|\.env(?:\..+)?)$|\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$|\.(?:pem|key|p12|shortcut|mp4|mov|m4v|webm|mkv|mp3|m4a|wav)$")
EXAMPLES = {".env.example", ".env.sample"}
COMPILED = [(kind, re.compile(rx)) for kind, rx in PATTERNS.items()]


def scan(lines):
    """lines: (where, text) pairs. Yields (where, kind) for each finding."""
    for where, text in lines:
        for kind, rx in COMPILED:
            if rx.search(text):
                yield where, kind


def _git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace", check=True).stdout


def private_name(name: str) -> bool:
    return bool(FILES.search(name)) and Path(name).name not in EXAMPLES


def staged():
    names = [n for n in _git("diff", "--cached", "--name-only", "--diff-filter=AM").splitlines() if n]
    found = [(n, "a private file's name") for n in names if private_name(n)]
    lines, path, line_no = [], "", 0
    for raw in _git("diff", "--cached", "-U0", "--no-color", "--diff-filter=AM").splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+"):
            lines.append((f"{path}:{line_no}", raw[1:]))
            line_no += 1
    return found + list(scan(lines))


def history():
    found = [(f"history path {n}", "a private file's name")
             for n in set(_git("log", "--all", "--reflog", "--full-history", "--name-only", "--pretty=format:").splitlines())
             if n and private_name(n)]
    objects = {}
    for line in _git("rev-list", "--objects", "--all", "--reflog").splitlines():
        oid, _, path = line.partition(" ")
        objects[oid] = path
    # Scan full blobs and commit metadata, not just additions. A batch process avoids
    # thousands of git invocations and never emits raw content to the terminal.
    with subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
        for oid, path in objects.items():
            proc.stdin.write((oid + "\n").encode())
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3:
                raise RuntimeError("Could not inspect a Git object")
            raw = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)
            if header[1] not in (b"blob", b"commit", b"tag"):
                continue
            found.extend(scan((f"{oid[:12]} {path or header[1].decode()}:{n}", line)
                              for n, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1)))
        proc.stdin.close()
        proc.wait()
        if proc.returncode:
            raise RuntimeError("Git object scan failed")
    return found


def worktree():
    found = []
    names = set(_git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")) - {""}
    for name in sorted(names):
        path = Path(name)
        if private_name(name):
            found.append((name, "a private file's name"))
        if path.is_symlink():
            found.append((name, "unreviewed symlink (not followed)"))
        elif path.is_file():
            found.extend(scan((f"{name}:{n}", line) for n, line in enumerate(
                path.read_bytes().decode("utf-8", "replace").splitlines(), 1)))
    return found


def ignored_sources():
    extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".sh", ".rb", ".json", ".toml"}
    names = _git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--",
                 "src", "tests", "scripts", ".githooks", "packaging").split("\0")
    return [(name, "ignored project source") for name in names if name and "__pycache__" not in Path(name).parts
            and (Path(name).suffix in extensions or name.startswith(".githooks/"))]


def main() -> int:
    findings = history() if "--history" in sys.argv else staged()
    if "--worktree" in sys.argv:
        findings.extend(worktree())
        findings.extend(ignored_sources())
    findings = sorted(set(findings))
    if not findings:
        print("Secret check: nothing found.")
        return 0
    print("Secret check: these look like secrets (values not shown):")
    for where, kind in findings:
        print(f"  {where}: {kind}")
    print("Remove confirmed secrets; construct synthetic test values at runtime. Fake-marker comments do not bypass this check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
