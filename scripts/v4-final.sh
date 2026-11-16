#!/usr/bin/env bash
# frozen-v4 final test. Run ONCE, only after the freeze commit is pushed.
#  1. checks every frozen hash (frozen/v4.sha256)
#  2. downloads Dukascopy hourly USD/CHF, USD/CAD, NZD/USD, EUR/JPY
#     (2023-01 .. 2026-10; never downloaded before the freeze) and the BIS
#     policy rates 2022-12 .. 2026-10 (US XM GB JP AU CH CA NZ)
#  3. builds the D1 feature tables (the USD basket = the four train pairs,
#     2023-2026 closes from data/v3, already seen in v3)
#  4. runs v4-final.aura
set -euo pipefail
cd "$(dirname "$0")/.."
AURA="${AURA:-aura}"
sha256sum -c frozen/v4.sha256
python3 scripts/v4-fetch.py final 2023-01 2026-10 2023-01-01 2026-11-01 USDCHF USDCAD NZDUSD EURJPY
python3 scripts/v4-rates.py data/v4/rates-final.csv 2022-12 2026-10 US XM GB JP AU CH CA NZ
B="EURUSD=data/v3/eurusd-final-d1.csv GBPUSD=data/v3/gbpusd-final-d1.csv USDJPY=data/v3/usdjpy-final-d1.csv AUDUSD=data/v3/audusd-final-d1.csv"
python3 scripts/v4-prep.py final data/v4/rates-final.csv 2023-01-01 2026-11-01 \
  USDCHF=data/v4/usdchf-final-d1.csv USDCAD=data/v4/usdcad-final-d1.csv NZDUSD=data/v4/nzdusd-final-d1.csv EURJPY=data/v4/eurjpy-final-d1.csv \
  --basket $B
python3 scripts/v4-prep.py ref data/v4/rates-final.csv 2023-01-01 2026-11-01 $B --basket $B
mkdir -p out
python3 scripts/meter.py "$AURA" run v4-final.aura --quiet
