#!/usr/bin/env python3
"""v6 final report: out/v6-final.json + data/v6/final*-net.csv -> tables.

Test period: frozen test-from .. end, official basket = the 8 never-
downloaded pairs. For each run (deploy, as-if adaptive v*, f*,
carry-eq-d1, v5fixed, flat) at 1x and 2x costs: sum, annualised Sharpe,
t against flat (daily), DSR with the frozen trial count and variance,
max drawdown, half-year sums, and the pre-registered sub-baskets
(sub-em, sub-g10x) as a descriptive breakdown only. Plus Aura control
loop latency. Writes out/v6-final-report.json.
"""
import csv, json, math, statistics as st, sys
sys.path.insert(0, "scripts")
from importlib.machinery import SourceFileLoader
sel = SourceFileLoader("sel", "scripts/v6-select.py").load_module()


def maxdd(xs):
    peak = cum = dd = 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def metrics(days, xs, spec):
    tr = spec["trials"]
    s = sel.sharpe(xs)
    halves = {}
    for d, x in zip(days, xs):
        h = d[:4] + ("H1" if d[5:7] <= "06" else "H2")
        halves[h] = round(halves.get(h, 0.0) + x, 2)
    out = {"sum": round(sum(xs), 2), "sharpe-ann": round(s * math.sqrt(252), 3),
           "t-vs-flat": round(s * math.sqrt(len(xs)), 2), "max-dd": round(maxdd(xs), 2),
           "days": len(xs), "halves": halves}
    if any(abs(x) > 0 for x in xs):
        d1 = sel.dsr(xs, tr["n"], tr["sr-var"])
        d2 = sel.dsr(xs, 2, tr["sr-var"])
        out["dsr-all"] = round(d1["dsr"], 3)
        out["sr0-all"] = round(d1["sr0"], 4)
        out["deflated-all"] = round(d1["deflated"], 4)
        out["dsr-2"] = round(d2["dsr"], 3)
    return out


def fixed_col(path, name, lo):
    rows = list(csv.reader(open(path)))
    k = rows[0].index(name)
    return [(r[0], float(r[k])) for r in rows[1:] if r[0] >= lo]


def main():
    spec = json.load(open("frozen/v6.json"))
    fin = json.load(open("out/v6-final.json"))
    lo = spec["test-from"]
    rep = {"runs": {}, "latency": {}, "subs": {}}
    static_names = [spec["fixed"], spec["baseline"], spec["v5fixed"]]
    for res in fin["results"]:
        cost = res["cost"]
        days = res["days"]
        for r in res["runs"]:
            rep["runs"][f"{cost}:{r['name']}"] = metrics(days, r["daily"], spec) | {
                "switches": r["switches"], "heals": r["heals"], "swap-fail": r["swap-fail"],
                "decisions": r["decisions"], "switch-cost": r["switch-cost"],
                "trial-fail": r.get("trial-fail", 0), "drift-alarms": r.get("drift-alarms", 0)}
            ms, sw = r["dec-ms"], r["swap-ms"]
            rep["latency"][f"{cost}:{r['name']}"] = {
                "decisions": len(ms),
                "dec-ms-mean": round(st.fmean(ms), 2) if ms else 0,
                "dec-ms-max": max(ms) if ms else 0,
                "dec-ms-p95": sorted(ms)[int(0.95 * (len(ms) - 1))] if ms else 0,
                "swaps": len(sw),
                "swap-ms-mean": round(st.fmean(sw), 2) if sw else 0,
                "swap-ms-max": max(sw) if sw else 0,
                "run-ms": r["ms"]}
        tag = "final" if cost == "x1" else "final2x"
        for nm in static_names:
            col = fixed_col(f"data/v6/{tag}-net.csv", nm, lo)
            assert [d for d, _ in col] == days, (nm, cost)
            rep["runs"][f"{cost}:{nm}"] = metrics(days, [x for _, x in col], spec)
        rep["runs"][f"{cost}:flat"] = metrics(days, [0.0] * len(days), spec)
        for sub in res.get("subs", []):
            rep["subs"][f"{cost}:{sub['name']}"] = metrics(days, sub["daily"], spec)
    json.dump(rep, open("out/v6-final-report.json", "w"), indent=1)
    for k, v in rep["runs"].items():
        print("V6R", k, {x: v[x] for x in v if x != "halves"}, v.get("halves"))
    for k, v in rep.get("subs", {}).items():
        print("V6R sub", k, {x: v[x] for x in v if x != "halves"})
    for k, v in rep["latency"].items():
        print("V6R latency", k, v)
    print("V6_REPORT_OK")


if __name__ == "__main__":
    main()
