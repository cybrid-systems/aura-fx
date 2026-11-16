#!/usr/bin/env bash
# v6 train search (2016-07..2023, 7 G10 USD crosses, H4/D1).
# Run only after the protocol commit. Does not download the final-test
# basket. Steps:
#  1. column precompute (26 committed configs)
#  2. nsga2 + search:init ES on the design period (24 evaluations)
#  3. 24 Aura adaptive variants (JOBS processes)
#  4. materialize the two selected blends
#  5. pre-committed selection (scripts/v6-select.py)
set -euo pipefail
cd "$(dirname "$0")/.."
export AURA="${AURA:-aura}"
JOBS="${JOBS:-4}"
mkdir -p out/v6 .aura/evo
PAIRS=(EURUSD GBPUSD USDJPY AUDUSD NZDUSD USDCAD USDCHF)
python3 scripts/meter.py python3 scripts/v6-prep.py train data/v6/rates-train.csv data/v6/vix-train.csv "${PAIRS[@]}"
python3 scripts/meter.py "$AURA" run v6-nsga.aura --quiet
python3 scripts/v6-blend.py train
for j in $(seq 0 $((JOBS - 1))); do
  seq $j $JOBS 23 | paste -sd, -
done | xargs -P "$JOBS" -I{} bash -c 'VARIANTS={} AURA_EVO_LOG=.aura/evo/v6-$(echo {} | cut -d, -f1).jsonl python3 scripts/meter.py "$AURA" run v6-search.aura --quiet > out/v6/log-$(echo {} | cut -d, -f1).txt 2>&1; tail -1 out/v6/log-$(echo {} | cut -d, -f1).txt'
python3 scripts/v6-select.py
