#!/usr/bin/env bash
# Daily v7 paper book. Idempotent. Run only after frozen/v7 is pushed.
# Does not connect to FXCM and refuses to run if FXCM_LIVE is set.
#
#   AURA=/workspace/aura-src/dist/aura-7167490ea-linux-x86_64/bin/aura \
#     bash scripts/v7-paper.sh
set -euo pipefail
cd "$(dirname "$0")/.."
AURA="${AURA:-aura}"

if [ -n "${FXCM_LIVE:-}" ]; then
  echo "v7-paper: refusing to run because FXCM_LIVE is set (paper only)" >&2
  exit 1
fi

# Original freeze record (29dd074): the protocol file itself must not have changed.
grep '  frozen/v7.json$' frozen/v7.sha256 | sha256sum -c
# v7.1 is a download-only patch (see frozen/v7.1.json). This is the runnable set.
sha256sum -c frozen/v7.1.sha256

FROM=2023-01
TO="$(date -u +%Y-%m)"
PAIRS=(EURNOK EURSEK USDHUF EURHUF NZDJPY CADJPY CHFJPY EURNZD)
HELPERS=(USDJPY USDNOK USDSEK NZDUSD)

python3 scripts/v7-fetch.py paper "$FROM" "$TO" "${PAIRS[@]}" "${HELPERS[@]}"
# Previous month of 2023-01 is 2022-12. End at the current UTC month.
python3 scripts/v6-rates.py data/v7/rates-paper.csv data/v7/vix-paper.csv \
  2022-12 "$TO" US XM NO SE HU NZ JP CA CH

mkdir -p out/v7 paper
python3 scripts/v7-market.py
python3 scripts/meter.py "$AURA" run v7-paper.aura --quiet
python3 scripts/v7-book.py
python3 scripts/meter.py "$AURA" run v7-monitor.aura --quiet
python3 scripts/v7-book.py
echo V7_PAPER_OK
