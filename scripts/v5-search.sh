#!/usr/bin/env bash
# v5 train search (2019-2023, EUR/USD + GBP/USD, 5-minute data).
#  1. column precompute (scripts/v5-prep.py): 96 configs per pair
#  2. 27 adaptive variants in Aura (v5-search.aura), JOBS processes
#  3. pre-committed selection (scripts/v5-select.py)
set -euo pipefail
cd "$(dirname "$0")/.."
export AURA="${AURA:-aura}"
JOBS="${JOBS:-8}"
mkdir -p out/v5
python3 scripts/meter.py python3 scripts/v5-prep.py train EURUSD data/v5/eurusd-train-m5.csv.gz data/v4/rates-train.csv 1.3
python3 scripts/meter.py python3 scripts/v5-prep.py train GBPUSD data/v5/gbpusd-train-m5.csv.gz data/v4/rates-train.csv 1.85
# interleave so that every process gets some N=1 (slow) variants
for j in $(seq 0 $((JOBS - 1))); do
  seq $j $JOBS 26 | paste -sd, -
done | xargs -P "$JOBS" -I{} bash -c 'VARIANTS={} AURA_EVO_LOG=.aura/evo/v5-$(echo {} | cut -d, -f1).jsonl python3 scripts/meter.py "$AURA" run v5-search.aura --quiet > out/v5/log-$(echo {} | cut -d, -f1).txt 2>&1; tail -1 out/v5/log-$(echo {} | cut -d, -f1).txt'
python3 scripts/v5-select.py
