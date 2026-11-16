#!/usr/bin/env python3
"""Compose frozen/v3.json from out/v3-select.json and out/v3-runs-full.json
(train-range results only) and copy the search records into frozen/."""
import json, shutil, statistics as st

sel = json.load(open("out/v3-select.json"))
runs = json.load(open("out/v3-runs-full.json"))

def sr(xs):
    sd = st.stdev(xs) if len(xs) > 1 else 0.0
    return st.mean(xs) / sd if sd > 1e-12 else 0.0

procs = sel["procs"]
bis = [f for f in sel["best-in-sample"] if f["year"] == "full"][0]
br = [r for r in runs if r["proc"] == bis["proc"] and r["fold"] == "full"][0]
secondary = {"name": "best-in-sample", "proc": bis["proc"], "tf": br["tf"], "fam": br["fam"], "params": br["params"],
             "genome": br["genome"], "trade": bis["trade"], "is-sharpe": br["is-sharpe"], "is-sum": br["is-sum"],
             "is-fills-per-year": br["is-fills-per-year"]}
val_srs = [sr(sum((r["val-daily"] for r in runs if r["proc"] == p and r["fold"] in ("2021", "2022", "2023")), [])) for p in procs]
cand = [x for r in runs for x in r["trial-srs"]]

FX = "FXCM Standard account (spread only, no commission). brokersprofile.com live FCA Standard account test, Apr-May 2026: EUR/USD 1.08, GBP/USD 1.54, USD/JPY 1.21, AUD/USD 1.34 pips. v2/v3 use 1.3 pips for EUR/USD (the high end of the 2026 third-party range 0.87-1.30); the other pairs get the same markup over the brokersprofile figure (x 1.3/1.08 = 1.204): GBP/USD 1.85, USD/JPY 1.46, AUD/USD 1.61 pips."
spec = {
  "version": "frozen-v3",
  "note": "Frozen after a train-only (EUR/USD 2019-2023) search and before any GBP/USD, USD/JPY or AUD/USD data was downloaded. Do not edit.",
  "deploy": sel["deploy"],
  "secondary": secondary,
  "selection-rule": "recent race (see v3-select.aura): tune:race over the 16 fixed procedures on the 36 validation months 2021-2023; winner's config fitted on 2019-2023; trade flag = validation mean > 0 and validation deflated Sharpe (N = 16) > 0",
  "test-from": "2024-01-01",
  "test-to": "2026-10-31",
  "warm-up": "2023-01-01 .. 2023-12-31 of each new pair, indicators only (no pnl)",
  "periods": ["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-11-01"],
  "lot": 10000,
  "pairs": [
    {"name": "GBP/USD", "prefix": "data/v3/gbpusd-final", "quote": "USD", "spread-pips": 1.85, "pip": 0.0001},
    {"name": "USD/JPY", "prefix": "data/v3/usdjpy-final", "quote": "JPY", "spread-pips": 1.46, "pip": 0.01},
    {"name": "AUD/USD", "prefix": "data/v3/audusd-final", "quote": "USD", "spread-pips": 1.61, "pip": 0.0001}],
  "reference": {"name": "EUR/USD (holdout already seen in v2)", "prefix": "data/v3/eurusd-final", "quote": "USD", "spread-pips": 1.3, "pip": 0.0001},
  "spread-basis": FX,
  "evaluated": "the deploy rule says flat (trade = false), so its realised test pnl is 0 by construction; the final test still runs the race winner's config (primary) and the best-in-sample config (secondary) unchanged to see what they would have done",
  "primary": "race winner config, pooled new pairs (one lot each, daily pnl summed): t of daily pnl against flat (0) and the deflated Sharpe with N = all scored candidates; secondary: per pair, per half-year, N = 16 procedures, twice the spread",
  "trials": {"searches": len(runs), "candidates": len(cand), "candidate-sr-var": st.variance(cand),
             "procedures": len(procs), "procedure-sr-var": st.variance(val_srs)},
  "train-summary": {"table": sel["table"], "recent": sel["recent"], "final-race": sel["final-race"]},
}
json.dump(spec, open("frozen/v3.json", "w"), indent=1)
open("frozen/v3.json", "a").write("\n")
shutil.copy("out/v3-select.json", "frozen/v3-select.json")
slim = [{k: v for k, v in r.items()} for r in runs]
json.dump(slim, open("frozen/v3-runs.json", "w"))
print("FREEZE_OK candidates", len(cand), "procedures", len(procs))
