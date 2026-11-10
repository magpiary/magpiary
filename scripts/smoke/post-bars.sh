#!/bin/bash
# Smoke check: on the post view, nothing shows through the post's top bar or the sticky tab row at any scroll position, the bar is the page behind
# it (no darker band), and the tab row has a fill only while it is stuck. Both themes, a long and a short post, every tab, wide and narrow
# windows. Born from text scrolling through the tab names and a band-coloured top bar, 10 Nov 2026. Throwaway hub on fictional data.
# Usage: scripts/smoke/post-bars.sh [port] [--shots DIR]     Needs: uv, Playwright's Chromium.
set -uo pipefail
cd "$(dirname "$0")/../.."
port="${1:-8795}"; shift || true
data="$(mktemp -d)"; status=0; pids=()
trap 'kill ${pids[@]} 2>/dev/null; rm -rf "$data"' EXIT
n=0
for theme in indigo dark; do
  uv run python scripts/smoke/post_bars_hub.py "$data/$theme" $((port + n)) "$theme" > "$data/$theme.log" 2>&1 & pids+=($!); n=$((n + 1))
done
for theme in indigo dark; do for _ in $(seq 1 60); do grep -q READY "$data/$theme.log" 2>/dev/null && break; sleep 0.5; done
  grep -q READY "$data/$theme.log" || { echo "FAIL the demo hub ($theme) did not start"; cat "$data/$theme.log"; exit 1; }; done
n=0
for theme in indigo dark; do
  uv run --with playwright --with pillow python scripts/smoke/post_bars_check.py "http://127.0.0.1:$((port + n))" "$theme" "$@" || status=1; n=$((n + 1))
done
[ $status -eq 0 ] && echo "ok   post bars are solid and match the page" || echo "FAIL see above"
exit $status
