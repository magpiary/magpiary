#!/bin/bash
# Smoke check: on the installed hub's wall, every post Featured leaves out is still listed below it (none in both, none
# in neither), and no stylesheet hides a Featured tile (that once made posts 7-10 vanish at medium and large tiles).
# Usage: scripts/smoke/featured-tiles.sh [port]   (reads only post numbers; no AI, no network beyond localhost)
set -uo pipefail
port="${1:-8765}"; url="http://127.0.0.1:${port}"
{ curl -s "$url/"; printf '\n@@CSS@@\n'; curl -s "$url/static/hub.css"; curl -s "$url/static/indigo.css"; } | python3 -c '
import re, sys
page, css = sys.stdin.read().split("@@CSS@@", 1)
ok = True
def say(good, text):
    global ok
    print(("ok   " if good else "FAIL ") + text); ok = ok and good
m = re.search(r"class=\"grid featgrid\"(.*?)</section>", page, re.S)
feat = set(re.findall(r"data-id=\"(\d+)\"", m.group(1))) if m else set()
listed = set((re.search(r"id=\"wallids\" data-ids=\"([^\"]*)\"", page) or [None, ""])[1].split(",")) - {""}
say(bool(listed), f"wall lists {len(listed)} posts below Featured ({len(feat)} featured)")
say(not feat & listed, "no post is both featured and listed")
say(not re.search(r"\.featgrid[^{]*\.tile[^{]*\{[^}]*display:\s*none", css), "no stylesheet hides a Featured tile")
sys.exit(0 if ok else 1)
'
