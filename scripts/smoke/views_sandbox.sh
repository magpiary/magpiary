#!/bin/bash
# A sandbox hub for clicking through the contextual post tabs: one fictional post per category (tests/fixtures/views),
# in a fresh temporary library, Private mode, every background step paused, no worker loops (no AI, no network, no
# lookups). Never reads or writes ~/Magpiary or ~/.config/magpiary: MAGPIARY_HOME and MAGPIARY_CONFIG point into the
# temp folder, and the script checks the real database is untouched when it stops. Ctrl-C stops it and deletes the temp folder.
# Usage: scripts/smoke/views_sandbox.sh [port]      (default: the first free port from 8790; never 8765, the real hub)
set -uo pipefail
cd "$(dirname "$0")/../.."
port="${1:-}"
if [ -z "$port" ]; then
  for p in $(seq 8790 8830); do
    if ! lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then port=$p; break; fi
  done
fi
[ -n "$port" ] || { echo "FAIL no free port between 8790 and 8830"; exit 1; }
[ "$port" = 8765 ] && { echo "FAIL 8765 is the real hub's port; pick another"; exit 1; }

real_db="$HOME/Magpiary/magpiary.db"
stamp() { [ -e "$1" ] && stat -f '%m %z' "$1" || echo "none"; }
before="$(stamp "$real_db")"
data="$(mktemp -d -t magpiary-views-sandbox)"
pid=""
cleanup() {
  [ -n "$pid" ] && kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null
  rm -rf "$data"
  after="$(stamp "$real_db")"
  [ "$before" = "$after" ] && echo "ok   the real database was not touched" || echo "WARN the real database changed while the sandbox ran ($before -> $after); the running hub may have written it"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

export MAGPIARY_HOME="$data/home" MAGPIARY_CONFIG="$data/cfg"
uv run python scripts/smoke/views_sandbox_hub.py "$data" "$port" > "$data/hub.log" 2>&1 & pid=$!
for _ in $(seq 1 60); do grep -q READY "$data/hub.log" 2>/dev/null && break; kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
grep -q READY "$data/hub.log" || { echo "FAIL the sandbox hub did not start"; cat "$data/hub.log"; exit 1; }
echo "Sandbox hub (fictional fixtures, Private mode, temp library in $data)"
echo "Open: http://127.0.0.1:$port/"
grep '^POSTS' "$data/hub.log" | sed 's/^POSTS /Posts (category: id, open \/item\/<id>): /'
echo "Ctrl-C to stop and delete it."
wait "$pid"
