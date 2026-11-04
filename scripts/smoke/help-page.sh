#!/bin/bash
# Smoke check: the installed hub's /help page has every chapter in its list, every chapter and guide link lands on
# exactly one element, and no id is shared with the top bar (that sent the Nest and Digest links nowhere).
# Usage: scripts/smoke/help-page.sh [port]   (no AI, no network beyond localhost)
set -uo pipefail
port="${1:-8765}"
curl -s "http://127.0.0.1:${port}/help" | python3 -c '
import re, sys
from collections import Counter
body = sys.stdin.read()
ids = Counter(re.findall(r" id=\"([^\"]+)\"", body))
jumps = re.findall(r"href=\"#(help-[^\"]+)\"", body)
chapters = re.findall(r"<li data-t=\"([a-z]+)\">", body)
bad = [i for i, n in ids.items() if n > 1]
missing = [j for j in jumps if ids[j] != 1]
ok = True
for good, text in ((len(chapters) >= 15, f"{len(chapters)} chapters in the list"), (not bad, f"no shared ids {bad or chr(32)}".strip()),
                   (jumps and not missing, f"{len(jumps)} chapter and guide links land {missing or chr(32)}".strip())):
    print(("ok   " if good else "FAIL ") + text); ok = ok and bool(good)
sys.exit(0 if ok else 1)
'
