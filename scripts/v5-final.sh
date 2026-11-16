#!/usr/bin/env bash
# frozen-v5 final test. Run ONCE, only after the freeze commit is pushed.
#  1. checks the frozen hashes (frozen/v5.sha256)
#  2. downloads Dukascopy minute data for EUR/GBP 2023-06-01 .. 2026-10-31
#     (never downloaded before the freeze; 2023 is window history only)
#  3. column precompute at 1x and 2x costs (GBP -> USD with the previous
#     day's GBP/USD close from data/v3, already seen in v3)
#  4. v5-final.aura (adaptive runs in Aura), then scripts/v5-report.py
set -euo pipefail
cd "$(dirname "$0")/.."
AURA="${AURA:-aura}"
sha256sum -c frozen/v5.sha256
python3 scripts/v5-fetch.py final 2023-06-01 2026-10-31 EURGBP
python3 scripts/v5-prep.py final EURGBP data/v5/eurgbp-final-m5.csv.gz data/v4/rates-final.csv 1.1 --conv data/v3/gbpusd-final-d1.csv
python3 scripts/v5-prep.py final2x EURGBP data/v5/eurgbp-final-m5.csv.gz data/v4/rates-final.csv 1.1 --conv data/v3/gbpusd-final-d1.csv --costmult 2
mkdir -p out
python3 scripts/meter.py "$AURA" run v5-final.aura --quiet
python3 scripts/v5-report.py
