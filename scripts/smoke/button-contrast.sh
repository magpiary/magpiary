#!/bin/bash
# Smoke check: no button on any hub page, in any state or theme, has text below WCAG contrast (4.5:1; 3:1 for large text and icons),
# and no button style the CSS defines does either in any context it is styled in (--matrix). Born from dark-on-dark buttons
# (Cancel on the profile ticket, Update in the banner), 10 Nov 2026. Runs a throwaway hub on fictional data, never the real library.
# Usage: scripts/smoke/button-contrast.sh [port]      Needs: uv, Playwright's Chromium (uv run --with playwright).
set -uo pipefail
cd "$(dirname "$0")/../.."
port="${1:-8791}"
data="$(mktemp -d)"
uv run python scripts/smoke/demo_hub.py "$data" "$port" > "$data/hub.log" 2>&1 &
hub=$!
trap 'kill $hub 2>/dev/null; rm -rf "$data"' EXIT
for _ in $(seq 1 60); do grep -q READY "$data/hub.log" 2>/dev/null && break; sleep 0.5; done
grep -q READY "$data/hub.log" || { echo "FAIL the demo hub did not start"; cat "$data/hub.log"; exit 1; }
status=0
uv run --with playwright python scripts/button_contrast_scan.py "http://127.0.0.1:${port}" || status=1
uv run --with playwright python scripts/button_contrast_scan.py "http://127.0.0.1:${port}" --matrix || status=1
[ $status -eq 0 ] && echo "ok   every button passes" || echo "FAIL some buttons are below contrast (list above)"
exit $status
