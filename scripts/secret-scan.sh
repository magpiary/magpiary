#!/usr/bin/env bash
# Secret scan, run before every push (installed as .githooks/pre-push).
# The built-in content/history/private-file checks always run, even without gitleaks.
set -u
cd "$(git rev-parse --show-toplevel)"
fail=0

if ! python3 scripts/secret_check.py --history --worktree; then
  fail=1
fi

if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks git --no-banner --redact=100 --ignore-gitleaks-allow --log-opts='--all --reflog --full-history' . ; then
    echo "secret-scan: gitleaks found possible secrets." >&2; fail=1
  fi
else
  echo "secret-scan: gitleaks unavailable; the built-in content scan remains required." >&2
fi

if [ $fail -ne 0 ]; then echo "secret-scan: push blocked." >&2; exit 1; fi
echo "secret-scan: clean."
