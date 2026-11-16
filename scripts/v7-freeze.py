#!/usr/bin/env python3
"""Write frozen/v7.json and frozen/v7.sha256.

usage: v7-freeze.py PROTOCOL_COMMIT

No search; parameters are the v6 frozen carry values. This must be
committed and pushed before the v7 basket is downloaded and before the
first official paper run.
"""
import hashlib, json, os, subprocess, sys


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    protocol = sys.argv[1]
    aura = subprocess.run([os.environ.get("AURA", "aura"), "--version"],
                          capture_output=True, text=True).stdout.strip()
    # v6 frozen trial count / panel variance. The two v7 sleeves were
    # already inside those 74 candidates.
    v6 = json.load(open("frozen/v6.json"))
    spec = {
        "version": "frozen-v7",
        "protocol-commit": protocol,
        "aura": aura,
        "mode": "paper-only",
        "no-fxcm": True,
        "no-search": True,
        "freeze-date": "2026-11-16",
        "asif-from": "2024-01-01",
        "history-from": "2023-01-01",
        "primary": "carry-eq-d1",
        "control": "carry-vix-20-d1",
        "params": {
            "carry-eq-d1": {"kind": "carry-eq", "freq": "d1"},
            "carry-vix-20-d1": {"kind": "carry-vix", "freq": "d1", "mode": "20",
                                "vix-threshold": 20.0},
        },
        "lot": 10000,
        "slippage-pips-per-side": 0.2,
        "rollover-markup-pct": 1.0,
        "pip-size": "0.01 if the quote is JPY, else 0.0001 (same convention as frozen v6, including HUF/NOK/SEK)",
        "basket": {
            "primary": ["EURNOK", "EURSEK", "USDHUF", "EURHUF",
                        "NZDJPY", "CADJPY", "CHFJPY", "EURNZD"],
            "note": "None of these eight pairs were downloaded in v2-v6 (raw cache and committed CSVs checked). USDPLN and USDCZK have Dukascopy ticks and BIS policy rates, but they are not on the FXCM Malaysia Kos Sebaran table last updated June 2024, so they were replaced by EURHUF (63.6) and EURNZD (4.1) to keep a single published spread source. Availability of the eight was confirmed with a two-month Dukascopy probe (2025-12 and 2026-09) written only to /tmp/v7-probe, not used for P&L.",
        },
        "helpers": {
            "pairs": ["USDNOK", "USDSEK", "USDJPY", "NZDUSD"],
            "note": "Already seen in v3/v4/v6. Used only to convert a non-USD quote into USD (previous day's close) or, for USDHUF, 1/close of the traded pair itself. EURHUF uses the traded USDHUF series. Helpers may be refreshed to the latest complete D1; they are not in the traded basket.",
        },
        "spread-basis": "FXCM published typical spreads, FXCM Malaysia Kos Sebaran page, last updated June 2024 (EUR/USD 1.3 matches the v5 Standard-account anchor); published, not measured",
        "spreads": {
            "EURNOK": 52.4, "EURSEK": 45.2, "USDHUF": 52.0, "EURHUF": 63.6,
            "NZDJPY": 2.3, "CADJPY": 2.5, "CHFJPY": 2.9, "EURNZD": 4.1,
        },
        "rollover": "policy-rate difference (BIS WS_CBPOL, previous month) minus 1% p.a. markup, /360, 3 nights on Wednesday. Swap points approximated by the interest differential; not measured.",
        "conversion": "Quote to USD with the previous day's close. USDXXX uses 1/close of the traded pair. Crosses use already-seen helper D1 series: USDNOK, USDSEK, USDJPY, NZDUSD.",
        "dukascopy-scale": "1e-3 for JPY and HUF quotes, 1e-5 otherwise (CZK would be 1e-4 if ever used).",
        "vix-source": "same public sources as v6 (datasets/finance-vix CBOE close, then jsDelivr, FRED VIXCLS, Stooq ^VIX). VIX used on day t is the last close strictly before t.",
        "rates-areas": ["US", "XM", "NO", "SE", "HU", "NZ", "JP", "CA", "CH"],
        "paths": {
            "rates": "data/v7/rates-paper.csv",
            "vix": "data/v7/vix-paper.csv",
        },
        "official-rule": "Official paper P&L includes only complete D1 closes on or after freeze-date. The incoming position on the first official day is flat. A D1 is complete only after 22:00 UTC on that trading date. Pre-freeze days must not be backfilled into the official ledger.",
        "asif-rule": "An as-if replay from asif-from up to the last complete day strictly before freeze-date may be written to paper/v7-asif-ledger.csv. It is reference only, clearly labelled, and is not used for official performance or the Demo decision.",
        "monitor": "Aura computes target positions (carry-eq-d1 primary, carry-vix-20-d1 control) and runs select:drift? on the official 1x primary ledger. Alarms are recorded. Frozen parameters are never changed; hot-strategy:swap! / heal! are not used to alter the sleeves.",
        "eval": {
            "interim-months": 3,
            "decision-months": 6,
            "review-every-months": 3,
            "min-official-days": 120,
            "t-min": 1.96,
            "dsr-min": 0.95,
            "require-2x": True,
            "primary-only": True,
            "rule": "Recommend Demo only at a formal review (first at 6 full months after freeze-date and >=120 official days; then every 3 months), and only if carry-eq-d1 has net P&L > 0, t vs flat >= 1.96, deflated Sharpe > 0 and DSR >= 0.95 at both 1x and 2x costs, using the frozen trial count. The 3-month look is descriptive only. If any gate fails, remain on paper, do not change parameters, do not recommend Demo.",
        },
        "trials": {
            "n": v6["trials"]["n"],
            "sr-var": v6["trials"]["sr-var"],
            "source": "frozen v6 trial count and SR0 variance. carry-eq-d1 and carry-vix-20-d1 were already among those 74 candidates; v7 does not search again.",
        },
        "deploy-live": False,
    }
    os.makedirs("frozen", exist_ok=True)
    json.dump(spec, open("frozen/v7.json", "w"), indent=1, sort_keys=True)
    files = ["frozen/v7.json",
             "lib/v7.aura", "v7-paper.aura", "v7-monitor.aura",
             "scripts/v7-paper.sh", "scripts/v7-fetch.py", "scripts/v7-market.py",
             "scripts/v7-book.py", "scripts/v7-eval.py", "scripts/v7-freeze.py",
             "scripts/v6-rates.py", "scripts/v3-bars.py"]
    with open("frozen/v7.sha256", "w") as fh:
        for f in files:
            fh.write(f"{sha(f)}  {f}\n")
    print("FROZEN_V7", spec["freeze-date"], "primary", spec["primary"],
          "basket", " ".join(spec["basket"]["primary"]),
          "protocol", protocol, "aura", aura)


if __name__ == "__main__":
    main()
