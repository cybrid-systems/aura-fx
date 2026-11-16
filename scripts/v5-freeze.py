#!/usr/bin/env python3
"""Freeze v5: out/v5/select.json -> frozen/v5.json, frozen/v5-select.json,
frozen/v5.sha256 (frozen files + the code the final test runs).

usage: v5-freeze.py PROTOCOL_COMMIT
"""
import hashlib, json, os, shutil, subprocess, sys

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def main():
    sel = json.load(open("out/v5/select.json"))
    vs = sel["as-if"]["adaptive"]
    runs = []
    if sel["deploy"]["trade"]:
        m = sel["deploy"]["meta"]; runs.append({"name": "deploy", "N": m["N"], "W": m["W"], "method": m["method"]})
    runs.append({"name": "as-if " + sel["v*"], "N": vs["N"], "W": vs["W"], "method": vs["method"]})
    spec = {
        "version": "frozen-v5", "protocol-commit": sys.argv[1],
        "aura": subprocess.run([os.environ.get("AURA", "aura"), "--version"], capture_output=True, text=True).stdout.strip(),
        "pair": "EUR/GBP", "test-from": "2024-01-01", "test-to": "2026-10-31", "history-from": "2023-06-01",
        "spread-pips": 1.1, "slippage-pips-per-side": 0.2, "lot": 10000, "rollover-markup-pct": 1.0,
        "spread-basis": "FXCM published Standard-account spreads (compareforexbrokers.com standard-spreads page, "
                        "FXCM row: EUR/USD 1.3, EUR/GBP 1.1); same 1.3 EUR/USD anchor as the train spreads, so x1.0; "
                        "published, not measured",
        "conversion": "GBP -> USD with the previous day's GBP/USD close (data/v3/gbpusd-final-d1.csv, seen in v3)",
        "deploy": sel["deploy"], "adaptive-runs": runs, "fixed": sel["f*"],
        "trials": sel["trials"], "v*-deflated": sel["v*-deflated"], "f*-deflated": sel["f*-deflated"],
        "v1": sel["v1"], "f1": sel["f1"],
    }
    os.makedirs("frozen", exist_ok=True)
    json.dump(spec, open("frozen/v5.json", "w"), indent=1, sort_keys=True)
    shutil.copy("out/v5/select.json", "frozen/v5-select.json")
    files = ["frozen/v5.json", "frozen/v5-select.json", "lib/v5.aura", "lib/metrics.aura", "lib/drift.aura", "lib/engine.aura",
             "v5-final.aura", "scripts/v5-final.sh", "scripts/v5-fetch.py", "scripts/v5-prep.py", "scripts/v5-report.py",
             "scripts/v5-select.py", "data/v4/rates-final.csv", "data/v3/gbpusd-final-d1.csv"]
    with open("frozen/v5.sha256", "w") as fh:
        for f in files: fh.write(f"{sha(f)}  {f}\n")
    print("deploy", sel["deploy"]["variant"], "runs", runs, "fixed", sel["f*"], "trials", sel["trials"])

if __name__ == "__main__":
    main()
