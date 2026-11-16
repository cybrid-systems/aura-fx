#!/usr/bin/env bash
# Runs the twelve v4 fold-arms (4 folds x 3 arms) as separate processes,
# then v4-select.aura. Each process gets its own evo log. The MiniMax key
# is passed to std/llm as LLM_API_KEY in the environment only.
set -euo pipefail
cd "$(dirname "$0")/.."
export AURA="${AURA:-aura}"
JOBS="${JOBS:-5}"
mkdir -p out/v4 .aura/evo
export LLM_API_KEY="${MINIMAX_API_KEY:?MINIMAX_API_KEY is required}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://api.minimaxi.com/v1}"
export LLM_MODEL="${LLM_MODEL:-MiniMax-M3.1-Flash}"
echo "llm key length ${#LLM_API_KEY}"
for f in 2021 2022 2023 full; do for a in hybrid llm gp; do echo "$f $a"; done; done |
  xargs -P "$JOBS" -L 1 bash -c 'FOLD=$0 ARM=$1 AURA_EVO_LOG=.aura/evo/v4-$0-$1.jsonl python3 scripts/meter.py "$AURA" run v4-search.aura --grant net --quiet > out/v4/log-$0-$1.txt 2>&1; tail -2 out/v4/log-$0-$1.txt'
grep -h "^V4 " out/v4/log-*.txt
"$AURA" run v4-select.aura --quiet
