#!/usr/bin/env python3
"""Freeze v6: out/v6/select.json -> frozen/v6.json, frozen/v6-select.json,
frozen/v6.sha256 (frozen files + the code the final test runs).

usage: v6-freeze.py PROTOCOL_COMMIT
"""
import hashlib, json, os, shutil, subprocess, sys


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    sel = json.load(open("out/v6/select.json"))
    vs = sel["as-if"]["adaptive"]
    runs = []
    if sel["deploy"]["trade"]:
        m = sel["deploy"]["meta"]
        runs.append({"name": "deploy", "N": m["N"], "W": m["W"], "method": m["method"]})
    runs.append({"name": "as-if " + sel["v*"], "N": vs["N"], "W": vs["W"], "method": vs["method"]})
    vix_src = "data/v6/vix-train-source.json"
    spec = {
        "version": "frozen-v6", "protocol-commit": sys.argv[1],
        "aura": subprocess.run([os.environ.get("AURA", "aura"), "--version"],
                               capture_output=True, text=True).stdout.strip(),
        "train-universe": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF"],
        "final-basket": {
            "primary": ["USDNOK", "USDSEK", "USDMXN", "USDZAR", "AUDJPY", "GBPJPY", "EURAUD", "EURCAD"],
            "sub-em": ["USDNOK", "USDSEK", "USDMXN", "USDZAR"],
            "sub-g10x": ["AUDJPY", "GBPJPY", "EURAUD", "EURCAD"],
            "note": "All eight pairs were never downloaded before this freeze. sub-em introduces new currencies (NOK, SEK, MXN, ZAR). sub-g10x uses currencies seen in training (AUD, JPY, GBP, EUR, CAD) but new pairings. Official test is the primary 8-pair basket; sub-baskets are descriptive and are not used for the deploy decision.",
        },
        "test-from": "2024-01-01", "test-to": "2026-10-31", "history-from": "2023-01-01",
        "slippage-pips-per-side": 0.2, "lot": 10000, "rollover-markup-pct": 1.0,
        "spread-basis": "FXCM published typical spreads, FXCM Malaysia Kos Sebaran page, last updated June 2024 (EUR/USD 1.3 matches the v5 Standard-account anchor); published, not measured",
        "spreads": {"USDNOK": 45.6, "USDSEK": 39.1, "USDMXN": 48.2, "USDZAR": 91.5,
                    "AUDJPY": 2.1, "GBPJPY": 2.7, "EURAUD": 2.5, "EURCAD": 2.9},
        "rollover": "policy-rate difference (BIS WS_CBPOL, previous month; Japan 2013-05..2016-08 filled at 0.0 because BIS has no policy rate under QQE) minus 1% p.a. markup, /360, 3 nights on Wednesday. Swap points approximated by the interest differential; not measured.",
        "conversion": "Quote to USD with the previous day's close. USDXXX uses 1/close of the traded pair. Crosses use already-seen helper D1 series: USDJPY, AUDUSD, USDCAD (downloaded in v3/v4, not new final-test instruments).",
        "vix-source": json.load(open(vix_src)) if os.path.exists(vix_src) else "see rates script log",
        "deploy": sel["deploy"], "adaptive-runs": runs,
        "fixed": sel["f*"], "baseline": sel["baseline"], "v5fixed": sel["v5fixed"],
        "trials": sel["trials"], "v*-deflated": sel["v*-deflated"], "f*-deflated": sel["f*-deflated"],
        "baseline-deflated": sel["baseline-deflated"],
        "v1": sel["v1"], "f1": sel["f1"],
        "evolved": sel.get("evolved", {}),
    }
    os.makedirs("frozen", exist_ok=True)
    json.dump(spec, open("frozen/v6.json", "w"), indent=1, sort_keys=True)
    shutil.copy("out/v6/select.json", "frozen/v6-select.json")
    files = ["frozen/v6.json", "frozen/v6-select.json",
             "lib/v6.aura", "lib/metrics.aura",
             "v6-final.aura", "scripts/v6-final.sh",
             "scripts/v6-fetch.py", "scripts/v6-rates.py", "scripts/v6-prep.py",
             "scripts/v6-report.py", "scripts/v6-select.py", "scripts/v6-blend.py"]
    with open("frozen/v6.sha256", "w") as fh:
        for f in files:
            fh.write(f"{sha(f)}  {f}\n")
    print("deploy", sel["deploy"]["variant"], "runs", runs, "fixed", sel["f*"], "trials", sel["trials"])


if __name__ == "__main__":
    main()
