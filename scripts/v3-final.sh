#!/bin/sh
# Final test of frozen-v3: verify the frozen hashes, fetch the never-used
# pairs (GBPUSD, USDJPY, AUDUSD 2023-01..2026-10; 2023 warm-up only),
# build the EUR/USD reference bars, run once.
set -eu
cd "$(dirname "$0")/.."
command -v aura >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
sha256sum -c frozen/v3.sha256
[ -f data/v3/gbpusd-final-d1.csv ] || python3 scripts/v3-fetch-final.py
python3 scripts/v3-bars.py data/dukascopy-eurusd-h1.csv data/v3/eurusd-final 2023-01-01 2026-11-01
mkdir -p out
aura run v3-final.aura --quiet | tee out/log-v3-final.txt
grep -q '^V3_FINAL_OK$' out/log-v3-final.txt
