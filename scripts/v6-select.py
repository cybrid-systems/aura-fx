#!/usr/bin/env python3
"""v6 deploy rule, committed before the search runs.

Universe (training only): the 7 G10 USD crosses already seen in earlier
versions — EUR/USD, GBP/USD, USD/JPY, AUD/USD, NZD/USD, USD/CAD, USD/CHF
— 10k lots of base each, daily P&L summed in USD.

Candidates:
  fixed:    the 26 committed basket configs (data/v6/train-net.csv)
  evolved:  nsga2-blend and es-blend, weights fitted on the design
            period only (24 evaluations total: 16 NSGA-II + 8 ES);
            design-period Sharpe of a blend is in-sample
  adaptive: the 24 Aura variants (N x W x method) in out/v6/run-*.json

Periods: design 2016-07-01 .. 2020-12-31, validation 2021-01-01 ..
2023-12-31 (walk-forward years 2021, 2022, 2023), full 2016-07-01 ..
2023-12-31.

Rule:
  v1 = adaptive variant with the best design-period Sharpe; its
       validation Sharpe is val1 (causal: the full run's 2021-23 part
       is exactly what v1 would have done).
  v* = adaptive variant with the best full-period Sharpe.
  f* = best static candidate (26 fixed + 2 blends) by full-period Sharpe.
  N  = 26 + 24 evolved evaluations + 24 adaptive + smoke tests,
       SR0 from the variance of the 26+2+24 candidates' full-period
       daily Sharpes (the 22 evolved genomes that were not selected
       still count in N, but do not enter the SR0 variance panel —
       they were discarded on design-period information only).
  Trade v* in the final test only if val1 > 0 and SR(v*) - SR0 > 0;
  otherwise do not trade. Also reported as-if: v*, f*, the equal-weight
  carry baseline carry-eq-d1, the v5-best-fixed transfer
  v5fixed-h4-mr5d-1.0, and flat.

Writes out/v6/select.json.
"""
import csv, glob, json, math, statistics as st
from statistics import NormalDist

SMOKE = 0
D0, D1, V0, V1 = "2016-07-01", "2021-01-01", "2021-01-01", "2024-01-01"
BASELINE = "carry-eq-d1"
V5FIXED = "v5fixed-h4-mr5d-1.0"
EVO_EVALS = 24


def sharpe(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return 0.0 if sd < 1e-12 else st.fmean(xs) / sd


def sr0(n, var):
    if n < 2 or var <= 0:
        return 0.0
    e = 0.5772156649015329
    z = NormalDist().inv_cdf
    return math.sqrt(var) * ((1 - e) * z(1 - 1 / n) + e * z(1 - 1 / (n * math.e)))


def dsr(xs, n, var):
    s = sharpe(xs)
    s0 = sr0(n, var)
    t = len(xs)
    m = st.fmean(xs)
    sd = st.pstdev(xs) or 1e-12
    g3 = st.fmean([((x - m) / sd) ** 3 for x in xs])
    g4 = st.fmean([((x - m) / sd) ** 4 for x in xs])
    den = math.sqrt(max(1e-9, 1 - g3 * s + (g4 - 1) / 4 * s * s))
    return {"sr-daily": s, "sr0": s0, "deflated": s - s0,
            "dsr": NormalDist().cdf((s - s0) * math.sqrt(t - 1) / den), "n": n}


def load_net(path):
    rows = list(csv.reader(open(path)))
    names = rows[0][1:]
    days = [r[0] for r in rows[1:]]
    cols = {nm: [float(r[1 + k]) for r in rows[1:]] for k, nm in enumerate(names)}
    return days, names, cols


def main():
    days, names, cols = load_net("data/v6/train-net.csv")
    assert BASELINE in names and V5FIXED in names, names
    assert len(names) == 26, len(names)
    fixed = {nm: dict(zip(days, cols[nm])) for nm in names}
    bdays, bnames, bcols = load_net("data/v6/train-blend-net.csv")
    assert bdays == days
    evolved = {nm: dict(zip(bdays, bcols[nm])) for nm in bnames}
    adaptive, meta = {}, {}
    for f in glob.glob("out/v6/run-*.json"):
        r = json.load(open(f))
        nm = f"{r['method']}-N{r['N']}-W{r['W']}"
        adaptive[nm] = dict(zip(r["days"], r["daily"]))
        meta[nm] = {"variant": r["variant"], "N": r["N"], "W": r["W"], "method": r["method"],
                    "switches": r["switches"], "heals": r["heals"], "swap-fail": r["swap-fail"],
                    "decisions": r["decisions"], "switch-cost": r["switch-cost"],
                    "trial-fail": r.get("trial-fail", 0), "drift-alarms": r.get("drift-alarms", 0)}
    assert len(adaptive) == 24, len(adaptive)

    def per(series, lo, hi):
        return [v for d, v in sorted(series.items()) if lo <= d < hi]

    def summ(series, lo, hi):
        xs = per(series, lo, hi)
        return {"sum": round(sum(xs), 2), "sharpe-ann": round(sharpe(xs) * math.sqrt(252), 3), "days": len(xs)}

    table = {}
    for kind, group in (("fixed", fixed), ("evolved", evolved), ("adaptive", adaptive)):
        for nm, s in group.items():
            table[nm] = {"kind": kind, "design": summ(s, D0, D1),
                         "validation": summ(s, V0, V1), "full": summ(s, D0, V1)}
            for y in (2021, 2022, 2023):
                table[nm][str(y)] = summ(s, f"{y}-01-01", f"{y+1}-01-01")

    v1 = max(adaptive, key=lambda k: sharpe(per(adaptive[k], D0, D1)))
    vs = max(adaptive, key=lambda k: sharpe(per(adaptive[k], D0, V1)))
    static = {**fixed, **evolved}
    f1 = max(static, key=lambda k: sharpe(per(static[k], D0, D1)))
    fs = max(static, key=lambda k: sharpe(per(static[k], D0, V1)))
    srs = [sharpe(per(s, D0, V1)) for s in list(static.values()) + list(adaptive.values())]
    n = len(fixed) + EVO_EVALS + len(adaptive) + SMOKE
    var = st.pvariance(srs)
    dv = dsr(per(adaptive[vs], D0, V1), n, var)
    val1 = sharpe(per(adaptive[v1], V0, V1))
    trade = val1 > 0 and dv["deflated"] > 0
    ev = json.load(open("out/v6/evolved.json")) if evolved else {}
    out = {
        "v1": v1, "v1-validation-sharpe-daily": val1,
        "f1": f1, "f1-validation-sharpe-daily": sharpe(per(static[f1], V0, V1)),
        "v*": vs, "f*": fs,
        "baseline": BASELINE, "v5fixed": V5FIXED,
        "v*-deflated": dv, "f*-deflated": dsr(per(static[fs], D0, V1), n, var),
        "baseline-deflated": dsr(per(fixed[BASELINE], D0, V1), n, var),
        "deploy": {"trade": trade, "variant": vs if trade else "flat",
                   "meta": meta[vs] if trade else None},
        "as-if": {"adaptive": meta[vs], "fixed": fs, "baseline": BASELINE, "v5fixed": V5FIXED},
        "trials": {"fixed": len(fixed), "evolved-selected": len(evolved),
                   "evolved-evals": EVO_EVALS, "adaptive": len(adaptive),
                   "smoke": SMOKE, "n": n, "sr-var": var,
                   "sr-panel": len(srs)},
        "evolved": ev,
        "table": table, "meta": meta,
    }
    json.dump(out, open("out/v6/select.json", "w"), indent=1)
    print("V6S v1", v1, table[v1]["design"], "validation", table[v1]["validation"])
    print("V6S f1", f1, table[f1]["design"], "validation", table[f1]["validation"])
    print("V6S v*", vs, table[vs]["full"], "deflated", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in dv.items()})
    print("V6S f*", fs, table[fs]["full"])
    print("V6S baseline", BASELINE, table[BASELINE]["full"], "validation", table[BASELINE]["validation"])
    print("V6S v5fixed", V5FIXED, table[V5FIXED]["full"], "validation", table[V5FIXED]["validation"])
    print("V6S deploy", out["deploy"]["variant"], "trade", trade, "n", n)
    print("V6_SELECT_OK")


if __name__ == "__main__":
    main()
