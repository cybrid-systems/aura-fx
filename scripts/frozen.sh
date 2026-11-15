#!/bin/sh
# The frozen out-of-sample check. Verifies that every file it depends on
# still has the sha256 recorded at the freeze commit, then runs once.
set -eu
cd "$(dirname "$0")/.."
command -v aura >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
sha256sum -c frozen/v1.sha256
mkdir -p out
[ -f data/ecb-eurusd.csv ] || python3 scripts/fetch-ecb.py
aura run frozen-eval.aura --quiet | tee out/log-frozen.txt
grep -q '^FZ_OK$' out/log-frozen.txt
