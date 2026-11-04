#!/bin/bash
# Smoke check: the background service starts the hub through the Magpiary launcher (so macOS prompts name Magpiary),
# the hub is its child, and it answers. Usage: scripts/smoke/hub-launcher.sh   (no AI, no network beyond localhost)
set -uo pipefail
PLIST="$HOME/Library/LaunchAgents/org.magpiary.receiver.plist"
first="$(/usr/libexec/PlistBuddy -c "Print :ProgramArguments:0" "$PLIST" 2>/dev/null)"
port="$(/usr/libexec/PlistBuddy -c "Print :ProgramArguments" "$PLIST" | awk '/--port/{getline; print $1}')"
fail=0
case "$first" in */Contents/MacOS/magpiary-hub) echo "ok   service starts through $first" ;; *) echo "FAIL service starts $first directly (prompts will say Python)"; fail=1 ;; esac
launcher="$(pgrep -f "Contents/MacOS/magpiary-hub" | head -1)"
if [ -n "$launcher" ] && ps -A -o ppid=,command= | awk -v p="$launcher" '$1==p' | grep -q "serve"; then echo "ok   hub runs as the launcher's child"; else echo "FAIL hub is not the launcher's child"; fail=1; fi
code="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port:-8765}/v1/ping")"
[ "$code" = 200 ] && echo "ok   hub answers" || { echo "FAIL hub answered $code"; fail=1; }
exit $fail
