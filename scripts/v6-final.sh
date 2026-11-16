#!/usr/bin/env bash
# frozen-v6 final test. Run ONCE, only after the freeze commit is pushed.
#  1. checks the frozen hashes (frozen/v6.sha256)
#  2. downloads Dukascopy H1->H4/D1 for the 8 never-downloaded pairs
#     2023-01-01 .. 2026-10-31 (2023 is window / signal history only)
#  3. policy rates (including NO/SE/MX/ZA, first download of those)
#     and VIX for 2022-01 .. 2026-10
#  4. column precompute at 1x and 2x costs
#  5. materialize frozen blends; run v6-final.aura; report
set -euo pipefail
cd "$(dirname "$0")/.."
AURA="${AURA:-aura}"
sha256sum -c frozen/v6.sha256
PAIRS=(USDNOK USDSEK USDMXN USDZAR AUDJPY GBPJPY EURAUD EURCAD)
python3 scripts/v6-fetch.py final 2023-01 2026-10 "${PAIRS[@]}"
python3 scripts/v6-rates.py data/v6/rates-final.csv data/v6/vix-final.csv 2022-12 2026-10 US XM GB JP AU CA NO SE MX ZA
python3 - <<'PY'
import json, os
spec = json.load(open("frozen/v6.json"))
os.makedirs("out/v6", exist_ok=True)
json.dump(spec["evolved"], open("out/v6/evolved.json", "w"))
print("EVOLVED_RESTORED")
PY
python3 scripts/v6-prep.py final data/v6/rates-final.csv data/v6/vix-final.csv --data final --helper-dir data/v4 "${PAIRS[@]}"
python3 scripts/v6-prep.py final2x data/v6/rates-final.csv data/v6/vix-final.csv --data final --costmult 2 --helper-dir data/v4 "${PAIRS[@]}"
python3 scripts/v6-blend.py final
python3 scripts/v6-blend.py final2x
mkdir -p out
python3 scripts/meter.py "$AURA" run v6-final.aura --quiet
python3 scripts/v6-report.py
