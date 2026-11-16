#!/usr/bin/env python3
"""v5 deploy rule, committed before the search runs.

Candidates on the train pairs (EUR/USD + GBP/USD, one 10k lot each,
daily P&L summed in USD):
  fixed:    the 96 configs (same config on both pairs), net columns
  adaptive: the 27 Aura variants (N x W x method), out/v5/run-*.json
Periods: design 2019-07-01 .. 2021-12-31, validation 2022-01-01 ..
2023-12-31, full 2019-07-01 .. 2023-12-31.

Rule:
  v1 = adaptive variant with the best design-period Sharpe; its
       validation Sharpe is val1 (it is causal, so the full run's 2022-23
       part is exactly what v1 would have done).
  v* = adaptive variant with the best full-period Sharpe.
  N  = 96 + 27 = 123 candidates (plus the smoke-test runs, counted in
       trials["smoke"]), SR0 from the variance of their full-period daily
       Sharpes.
  Trade v* in the final test only if val1 > 0 and SR(v*) - SR0 > 0;
  otherwise do not trade. Also reported as-if: v*, the best fixed config
  f* (full period), flat.
Writes out/v5/select.json.
"""
import csv, glob, json, math, statistics as st
from statistics import NormalDist

SMOKE = 3                      # adaptive runs on partial 2019 EUR/USD data while writing the code
D0, D1, V0, V1 = "2019-07-01", "2022-01-01", "2022-01-01", "2024-01-01"

def sharpe(xs):
    if len(xs) < 2: return 0.0
    sd = st.pstdev(xs)
    return 0.0 if sd < 1e-12 else st.fmean(xs) / sd

def sr0(n, var):
    if n < 2 or var <= 0: return 0.0
    e = 0.5772156649015329; z = NormalDist().inv_cdf
    return math.sqrt(var) * ((1 - e) * z(1 - 1 / n) + e * z(1 - 1 / (n * math.e)))

def dsr(xs, n, var):
    s = sharpe(xs); s0 = sr0(n, var); t = len(xs)
    m = st.fmean(xs); sd = st.pstdev(xs) or 1e-12
    g3 = st.fmean([((x - m) / sd) ** 3 for x in xs]); g4 = st.fmean([((x - m) / sd) ** 4 for x in xs])
    den = math.sqrt(max(1e-9, 1 - g3 * s + (g4 - 1) / 4 * s * s))
    return {"sr-daily": s, "sr0": s0, "deflated": s - s0, "dsr": NormalDist().cdf((s - s0) * math.sqrt(t - 1) / den), "n": n}

def load_fixed(pair):
    rows = list(csv.reader(open(f"data/v5/train-{pair}-net.csv")))
    names = rows[0][2:]
    days = [r[0] for r in rows[1:]]
    cols = {nm: [float(r[2 + k]) for r in rows[1:]] for k, nm in enumerate(names)}
    return days, names, cols

def main():
    days, names, a = load_fixed("eurusd")
    days2, _, b = load_fixed("gbpusd")
    assert days == days2
    fixed = {nm: dict(zip(days, [x + y for x, y in zip(a[nm], b[nm])])) for nm in names}
    adaptive = {}
    meta = {}
    for f in glob.glob("out/v5/run-*.json"):
        r = json.load(open(f))
        nm = f"{r['method']}-N{r['N']}-W{r['W']}"
        ps = r["pairs"]
        adaptive[nm] = dict(zip(r["days"], [x + y for x, y in zip(ps[0]["daily"], ps[1]["daily"])]))
        meta[nm] = {"variant": r["variant"], "N": r["N"], "W": r["W"], "method": r["method"],
                    "switches": [p["switches"] for p in ps], "heals": [p["heals"] for p in ps],
                    "swap-fail": [p["swap-fail"] for p in ps], "decisions": [p["decisions"] for p in ps],
                    "switch-cost": [p["switch-cost"] for p in ps]}
    assert len(adaptive) == 27, len(adaptive)
    def per(series, lo, hi): return [v for d, v in sorted(series.items()) if lo <= d < hi]
    def summ(series, lo, hi):
        xs = per(series, lo, hi)
        return {"sum": round(sum(xs), 2), "sharpe-ann": round(sharpe(xs) * math.sqrt(252), 3), "days": len(xs)}
    table = {}
    for kind, group in (("fixed", fixed), ("adaptive", adaptive)):
        for nm, s in group.items():
            table[nm] = {"kind": kind, "design": summ(s, D0, D1), "validation": summ(s, V0, V1), "full": summ(s, D0, V1)}
    v1 = max(adaptive, key=lambda k: sharpe(per(adaptive[k], D0, D1)))
    f1 = max(fixed, key=lambda k: sharpe(per(fixed[k], D0, D1)))
    vs = max(adaptive, key=lambda k: sharpe(per(adaptive[k], D0, V1)))
    fs = max(fixed, key=lambda k: sharpe(per(fixed[k], D0, V1)))
    srs = [sharpe(per(s, D0, V1)) for s in list(fixed.values()) + list(adaptive.values())]
    n = len(srs) + SMOKE; var = st.pvariance(srs)
    dv = dsr(per(adaptive[vs], D0, V1), n, var)
    val1 = sharpe(per(adaptive[v1], V0, V1))
    trade = val1 > 0 and dv["deflated"] > 0
    out = {"v1": v1, "v1-validation-sharpe-daily": val1, "f1": f1, "f1-validation-sharpe-daily": sharpe(per(fixed[f1], V0, V1)),
           "v*": vs, "f*": fs, "v*-deflated": dv, "f*-deflated": dsr(per(fixed[fs], D0, V1), n, var),
           "deploy": {"trade": trade, "variant": vs if trade else "flat", "meta": meta[vs] if trade else None},
           "as-if": {"adaptive": meta[vs], "fixed": fs},
           "trials": {"fixed": len(fixed), "adaptive": len(adaptive), "smoke": SMOKE, "n": n, "sr-var": var},
           "table": table, "meta": meta}
    json.dump(out, open("out/v5/select.json", "w"), indent=1)
    print("V5S v1", v1, table[v1]["design"], "validation", table[v1]["validation"])
    print("V5S f1", f1, table[f1]["design"], "validation", table[f1]["validation"])
    print("V5S v*", vs, table[vs]["full"], "deflated", {k: round(v, 4) for k, v in dv.items()})
    print("V5S f*", fs, table[fs]["full"])
    print("V5S deploy", out["deploy"]["variant"], "trade", trade)
    print("V5_SELECT_OK")

if __name__ == "__main__":
    main()
