#!/usr/bin/env python3
"""v5 final report: out/v5-final.json + data/v5/final*-eurgbp-* -> tables.

Test period: frozen test-from .. end. For each run (deploy, as-if
adaptive v*, fixed f*, flat) at 1x and 2x costs: sum, annualised Sharpe,
t against flat (daily), DSR with the frozen trial count and variance,
max drawdown, half-year sums. Plus the frequency table (gross, cost,
rollover, net, entries per frequency, over the 24 rules of each) and the
per-decision latency of the Aura control loop. Writes
out/v5-final-report.json.
"""
import csv, json, math, statistics as st, sys
sys.path.insert(0, "scripts")
from importlib.machinery import SourceFileLoader
sel = SourceFileLoader("sel", "scripts/v5-select.py").load_module()

def maxdd(xs):
    peak = cum = dd = 0.0
    for x in xs:
        cum += x; peak = max(peak, cum); dd = max(dd, peak - cum)
    return dd

def metrics(days, xs, spec):
    tr = spec["trials"]
    s = sel.sharpe(xs)
    halves = {}
    for d, x in zip(days, xs):
        h = d[:4] + ("H1" if d[5:7] <= "06" else "H2")
        halves[h] = round(halves.get(h, 0.0) + x, 2)
    out = {"sum": round(sum(xs), 2), "sharpe-ann": round(s * math.sqrt(252), 3),
           "t-vs-flat": round(s * math.sqrt(len(xs)), 2), "max-dd": round(maxdd(xs), 2), "days": len(xs), "halves": halves}
    if any(abs(x) > 0 for x in xs):
        d1 = sel.dsr(xs, tr["n"], tr["sr-var"]); d2 = sel.dsr(xs, 2, tr["sr-var"])
        out["dsr-all"] = round(d1["dsr"], 3); out["sr0-all"] = round(d1["sr0"], 4)
        out["dsr-2"] = round(d2["dsr"], 3)
    return out

def fixed_col(path, name, lo):
    rows = list(csv.reader(open(path)))
    k = rows[0].index(name)
    return [(r[0], float(r[k])) for r in rows[1:] if r[0] >= lo]

def main():
    spec = json.load(open("frozen/v5.json")); fin = json.load(open("out/v5-final.json"))
    lo = spec["test-from"]
    rep = {"runs": {}, "freq": {}, "latency": {}}
    for res in fin["results"]:
        cost = res["cost"]; days = res["days"]
        for r in res["runs"]:
            rep["runs"][f"{cost}:{r['name']}"] = metrics(days, r["daily"], spec) | {
                "switches": r["switches"], "heals": r["heals"], "swap-fail": r["swap-fail"], "decisions": r["decisions"],
                "switch-cost": r["switch-cost"]}
            ms = r["dec-ms"]; sw = r["swap-ms"]
            rep["latency"][f"{cost}:{r['name']}"] = {
                "decisions": len(ms), "dec-ms-mean": round(st.fmean(ms), 2) if ms else 0, "dec-ms-max": max(ms) if ms else 0,
                "dec-ms-p95": sorted(ms)[int(0.95 * (len(ms) - 1))] if ms else 0,
                "swaps": len(sw), "swap-ms-mean": round(st.fmean(sw), 2) if sw else 0, "swap-ms-max": max(sw) if sw else 0,
                "run-ms": r["ms"]}
        tag = "final" if cost == "x1" else "final2x"
        col = fixed_col(f"data/v5/{tag}-eurgbp-net.csv", spec["fixed"], lo)
        assert [d for d, _ in col] == days
        rep["runs"][f"{cost}:fixed {spec['fixed']}"] = metrics(days, [x for _, x in col], spec)
        rep["runs"][f"{cost}:flat"] = metrics(days, [0.0] * len(days), spec)
        parts = json.load(open(f"data/v5/{tag}-eurgbp-parts.json"))["configs"]
        years = [y for y in ("2024", "2025", "2026")]
        fq = {}
        for nm, py in parts.items():
            f = nm.split("-")[0]
            g = fq.setdefault(f, {"gross": 0.0, "cost": 0.0, "rollover": 0.0, "net": 0.0, "entries": 0, "net-positive": 0, "gross-positive": 0, "rules": 0})
            gg = sum(py[y][0] for y in years if y in py); cc = sum(py[y][1] for y in years if y in py)
            ca = sum(py[y][2] for y in years if y in py); en = sum(py[y][3] for y in years if y in py)
            g["gross"] += gg; g["cost"] += cc; g["rollover"] += ca; g["net"] += gg - cc + ca; g["entries"] += en
            g["net-positive"] += (gg - cc + ca) > 0; g["gross-positive"] += gg > 0; g["rules"] += 1
        rep["freq"][cost] = {f: {k: (round(v, 1) if isinstance(v, float) else v) for k, v in g.items()} for f, g in fq.items()}
    json.dump(rep, open("out/v5-final-report.json", "w"), indent=1)
    for k, v in rep["runs"].items():
        print("V5R", k, {x: v[x] for x in v if x != "halves"}, v["halves"])
    for c, fq in rep["freq"].items():
        for f, g in fq.items(): print("V5R freq", c, f, g)
    for k, v in rep["latency"].items(): print("V5R latency", k, v)
    print("V5_REPORT_OK")

if __name__ == "__main__":
    main()
