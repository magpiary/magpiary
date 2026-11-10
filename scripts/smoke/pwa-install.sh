#!/bin/bash
# Installed-web-app check against a running hub: manifest, icons and service worker are served, and the worker keeps no cache.
# Usage: scripts/smoke/pwa-install.sh [port]   (use a throwaway hub: MAGPIARY_HOME=... MAGPIARY_PORT=8793 MAGPIARY_PWA_PORT=8793 magpiary serve)
# Chrome's own verdict: DevTools > Application > Manifest, or CDP Page.getInstallabilityErrors (must be empty).
set -euo pipefail
P="${1:-8765}"; B="http://localhost:$P"
curl -sf "$B/manifest.webmanifest" | python3 -c 'import json,sys; m=json.load(sys.stdin); assert m["display"]=="standalone" and m["start_url"]=="/"; print("manifest ok:", m["name"])'
for i in icon-192.png icon-512.png maskable-512.png; do curl -sf -o /dev/null "$B/static/$i" && echo "$i ok"; done
JS="$(curl -sf "$B/sw.js")"
grep -q 'addEventListener("fetch"' <<<"$JS"
! grep -qE 'caches\.|indexedDB|localStorage' <<<"$JS"
echo "service worker ok (real fetch handler, no storage)"
