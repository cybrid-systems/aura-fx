#!/bin/sh
# The frozen real-data check v2. Verifies that every file it depends on
# (and the data) still has the sha256 recorded at the freeze commit,
# then runs once.
set -eu
cd "$(dirname "$0")/.."
command -v aura >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
[ -f data/dukascopy-eurusd-h1.csv ] || python3 scripts/fetch-dukascopy.py
sha256sum -c frozen/v2.sha256
mkdir -p out
aura run frozen-eval2.aura --quiet | tee out/log-frozen2.txt
grep -q '^FZ2_OK$' out/log-frozen2.txt
