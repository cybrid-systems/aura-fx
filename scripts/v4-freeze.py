#!/usr/bin/env python3
"""Freeze v4: out/v4/select.json + run-*.json -> frozen/v4.json,
frozen/v4-runs.json and frozen/v4.sha256 (covers the frozen files and the
code the final test runs). Needs no data after 2023.

usage: v4-freeze.py PROTOCOL_COMMIT
"""
import glob, hashlib, json, os, subprocess, sys

PIP = {"USD/CHF": 0.0001, "USD/CAD": 0.0001, "NZD/USD": 0.0001, "EUR/JPY": 0.01,
       "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01, "AUD/USD": 0.0001}

COLLINS = ("compareforexbrokers.com/our-methodology/forex-fees/standard-spreads/ "
           "(Ross Collins, MT4 standard-account test; FXCM measured EUR/USD 0.93)")
PUBLISHED = "FXCM published Standard-account spreads (EUR/USD 1.3 in the same table)"
FINAL = [
    ("USD/CHF", "usdchf", 2.57, f"{COLLINS}: USD/CHF 1.84 x (1.3/0.93) = 2.57"),
    ("USD/CAD", "usdcad", 2.74, f"{COLLINS}: USD/CAD 1.96 x (1.3/0.93) = 2.74"),
    ("NZD/USD", "nzdusd", 1.9, f"{PUBLISHED}, mytradingaid.com/san-forex/fxcm: NZD/USD 1.9 x (1.3/1.3); "
                               "published, not measured (no measured figure found)"),
    ("EUR/JPY", "eurjpy", 1.9, f"{PUBLISHED}, FXCM row on {COLLINS.split(' ')[0]}: EUR/JPY 1.9 x (1.3/1.3); "
                               "published, not measured (no measured figure found)"),
]
REF = [("EUR/USD", "eurusd", 1.3, "v2"), ("GBP/USD", "gbpusd", 1.85, "v3"),
       ("USD/JPY", "usdjpy", 1.46, "v3"), ("AUD/USD", "audusd", 1.61, "v3")]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    protocol = sys.argv[1]
    sel = json.load(open("out/v4/select.json"))
    runs = {}
    for f in sorted(glob.glob("out/v4/run-*.json")):
        d = json.load(open(f))
        d.pop("val-champion", None); d.pop("val-best", None)
        runs[f"{d['fold']}-{d['arm']}"] = d
    assert len(runs) == 12, len(runs)
    asif = sel["as-if"]
    # multiple-testing count: every evaluated rule of the 12 runs (GP children,
    # ES tuning points, single-feature probes, gated LLM proposals) plus the
    # LLM proposals refused before evaluation, plus the LLM proposals made in
    # the train-only smoke runs before the protocol commit (counted, not used).
    smoke_props, smoke_calls = 108, 29
    trials = dict(sel["trials"])
    trials["evaluated"] = trials["candidates"]
    trials["llm-refused"] = sel["counts"]["llm-bad"]
    trials["smoke-llm-proposals"] = smoke_props
    trials["smoke-llm-calls"] = smoke_calls
    trials["llm-calls-total"] = sel["counts"]["llm-calls"] + smoke_calls
    trials["candidates"] = trials["evaluated"] + trials["llm-refused"] + smoke_props
    rule = lambda x: x["rule"] if x else "flat"
    configs = [{"name": "deploy", "rule": sel["deploy"]["rule"]}] + \
              [{"name": k, "rule": rule(asif[k])} for k in ("hybrid-champion", "hybrid-best", "gp-champion", "llm-champion")]
    periods = ["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01", "2026-11-01"]
    spec = {
        "version": "frozen-v4",
        "protocol-commit": protocol,
        "aura": subprocess.run([os.environ.get("AURA", "aura"), "--version"], capture_output=True, text=True).stdout.strip(),
        "test-from": "2024-01-01", "test-to": "2026-10-31", "periods": periods,
        "lot": 10000, "rollover-markup-pct": 1.0,
        "rates": "BIS WS_CBPOL monthly end-of-period policy rates, previous month; US XM GB JP AU CH CA NZ",
        "spread-rule": "same ratio as the train spreads: FXCM Standard public figures scaled to EUR/USD 1.3",
        "pairs": [{"name": n, "file": f"data/v4/final-{t}.csv", "spread-pips": s, "pip": PIP[n], "basis": b}
                  for n, t, s, b in FINAL],
        "reference": [{"name": n, "file": f"data/v4/ref-{t}.csv", "spread-pips": s, "pip": PIP[n], "seen-in": v,
                       "note": "already seen; reference only"} for n, t, s, v in REF],
        "deploy": sel["deploy"],
        "configs": configs,
        "trials": trials,
        "counts": sel["counts"],
        "as-if": asif,
    }
    os.makedirs("frozen", exist_ok=True)
    json.dump(spec, open("frozen/v4.json", "w"), indent=1, sort_keys=True)
    json.dump(runs, open("frozen/v4-runs.json", "w"), indent=0, sort_keys=True)
    files = ["frozen/v4.json", "frozen/v4-runs.json", "lib/v4.aura", "lib/metrics.aura", "v4-final.aura",
             "scripts/v4-final.sh", "scripts/v4-fetch.py", "scripts/v4-prep.py", "scripts/v4-rates.py", "scripts/v3-bars.py"]
    with open("frozen/v4.sha256", "w") as fh:
        for f in files:
            fh.write(f"{sha(f)}  {f}\n")
    print("deploy", sel["deploy"]["rule"], "trade", sel["deploy"]["trade"])
    print("configs", json.dumps(configs))
    print("trials", trials)


if __name__ == "__main__":
    main()
