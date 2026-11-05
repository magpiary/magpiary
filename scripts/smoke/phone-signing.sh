#!/bin/bash
# Smoke check: the installed hub refuses phone requests that are not properly signed (a made-up device, a signature from
# an hour ago, a key that is not a phone's), and still answers ping. A real signed send is checked on the iPhone.
# Usage: scripts/smoke/phone-signing.sh [port]   (no AI, no network beyond localhost)
set -uo pipefail
port="${1:-8765}"; url="http://127.0.0.1:${port}"; fail=0
now="$(date +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/')"
old="$(date -v-1H +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/')"
check() {  # label, wanted code, curl args...
  local label="$1" want="$2"; shift 2
  local got; got="$(curl -s -o /dev/null -w "%{http_code}" "$@")"
  if [ "$got" = "$want" ]; then echo "ok   $label ($got)"; else echo "FAIL $label: $got, wanted $want"; fail=1; fi
}
check "ping answers" 200 "$url/v1/ping"
check "made-up device refused" 401 -H "X-Magpiary-Device: 000000000000000000000000" -H "X-Magpiary-Time: $now" -H "X-Magpiary-Signature: 00" "$url/v1/boards"
check "hour-old signature refused" 401 -H "X-Magpiary-Device: 000000000000000000000000" -H "X-Magpiary-Time: $old" -H "X-Magpiary-Signature: 00" "$url/v1/boards"
check "unknown key refused" 401 -X POST -H "Authorization: Bearer not-a-key" --data '{"items":[]}' "$url/v1/items"
exit $fail
