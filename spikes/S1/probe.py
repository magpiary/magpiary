# /// script
# requires-python = ">=3.12"
# dependencies = ["yt-dlp"]
# ///
"""S1 spike: logged-out fetch success rate across sources.

Throwaway. Reads links.txt, runs yt-dlp WITHOUT cookies on each link (metadata
only, nothing downloaded), classifies the outcome, and writes results.jsonl plus
a summary table. Requests are serial with jitter per host.

    uv run spikes/S1/probe.py                 # uses spikes/S1/links.txt
    uv run spikes/S1/probe.py other.txt

Share links carry identifiers, so each URL is cleaned before use; the raw line
is never written to the results.
"""

import json
import random
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).parent
TIMEOUT_S = 90
JITTER_S = (3.0, 8.0)

SOURCES = {
    "instagram.com": "instagram",
    "threads.net": "threads",
    "threads.com": "threads",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "reddit.com": "reddit",
    "redd.it": "reddit",
}

# (substring in yt-dlp stderr, lowercase) -> outcome. First match wins.
FAILURES = [
    ("rate-limit reached or login required", "login_wall"),
    ("login required", "login_wall"),
    ("requested content is not available", "login_wall"),
    ("sign in to confirm", "login_wall"),
    ("private", "private"),
    ("429", "rate_limited"),
    ("too many requests", "rate_limited"),
    ("there is no video in this post", "no_video"),
    ("no video formats found", "no_video"),
    ("no video could be found", "no_video"),
    ("unsupported url", "unsupported"),
    ("404", "deleted"),
    ("not found", "deleted"),
    ("removed", "deleted"),
    ("unavailable", "deleted"),
]


def source_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").removeprefix("www.").removeprefix("m.")
    return SOURCES.get(host, "other")


def clean(url: str) -> str:
    """Throwaway cleaner: keep YouTube's v=, drop everything else."""
    parts = urlsplit(url.strip())
    query = ""
    if source_of(url) == "youtube" and "youtube.com" in (parts.hostname or ""):
        v = parse_qs(parts.query).get("v", [""])[0]
        query = f"?v={v}" if v else ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}{query}"


def is_short(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    path = parts.path
    return (
        host in ("youtu.be", "redd.it")
        or (host.startswith("threads.") and path.startswith("/share/"))
        or (host == "instagram.com" and path.startswith("/share/"))
        or (host == "reddit.com" and "/s/" in path)
    )


def expand(url: str) -> tuple[str, str]:
    """Follow redirects with no cookies. Returns (final_url, status)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.geturl(), f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        return e.geturl() or url, f"http_{e.code}"
    except Exception as e:  # network errors: record and carry on
        return url, type(e).__name__


def read_links(path: Path) -> list[tuple[str, str]]:
    links = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label = ""
        if "\t" in line:
            line, label = line.split("\t", 1)
        elif " # " in line:
            line, label = line.split(" # ", 1)
        links.append((line.strip(), label.strip()))
    return links


def classify(returncode: int, stderr: str) -> str:
    if returncode == 0:
        return "ok"
    low = stderr.lower()
    for needle, outcome in FAILURES:
        if needle in low:
            return outcome
    return "unknown"


def probe(url: str) -> dict:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ignore-config", "--no-cookies", "--no-playlist", "--skip-download",
        "--dump-single-json", "--no-warnings", url,
    ]
    start = time.monotonic()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        outcome = classify(run.returncode, run.stderr)
        stderr_tail = run.stderr.strip().splitlines()[-1][:300] if run.stderr.strip() else ""
        info = json.loads(run.stdout) if run.returncode == 0 and run.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        outcome, stderr_tail, info = "timeout", "", {}
    return {
        "outcome": outcome,
        "seconds": round(time.monotonic() - start, 1),
        "error": stderr_tail,
        "has_caption": bool(info.get("description") or info.get("title")),
        "has_duration": info.get("duration") is not None,
        "n_formats": len(info.get("formats") or []),
        "n_entries": len(info.get("entries") or []),
    }


def main() -> None:
    links_file = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "links.txt"
    links = read_links(links_file)
    if not links:
        sys.exit(f"No links in {links_file}. Add one URL per line.")

    out = HERE / "results.jsonl"
    rows, last_hit = [], defaultdict(float)
    for i, (raw, label) in enumerate(links, 1):
        url = clean(raw)
        source = source_of(url)
        wait = last_hit[source] + random.uniform(*JITTER_S) - time.monotonic()
        if wait > 0 and last_hit[source]:
            time.sleep(wait)
        expansion = None
        if is_short(url):
            final, status = expand(url)
            expansion = {"status": status, "changed": clean(final) != url}
            url = clean(final)
            source = source_of(url) if source_of(url) != "other" else source
        result = probe(url)
        last_hit[source] = time.monotonic()
        row = {"n": i, "source": source, "url": url, "label": label, "expansion": expansion, **result}
        rows.append(row)
        print(f"[{i}/{len(links)}] {source:9} {row['outcome']:12} {url}", flush=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    print("\nSummary (logged out, yt-dlp only)\n")
    by_source = defaultdict(Counter)
    for r in rows:
        by_source[r["source"]][r["outcome"]] += 1
    for source, counts in sorted(by_source.items()):
        total = sum(counts.values())
        detail = ", ".join(f"{k} {v}" for k, v in counts.most_common())
        print(f"{source:10} {counts['ok']}/{total} ok   ({detail})")
    print(f"\nPer-link results: {out}")


if __name__ == "__main__":
    main()
