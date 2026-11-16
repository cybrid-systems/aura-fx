#!/usr/bin/env python3
"""Materialize nsga2-blend and es-blend daily P&L / positions from sleeves.

usage: v6-blend.py OUT
Reads out/v6/evolved.json (weights on the four committed sleeves) and
data/v6/<OUT>-{net,pos}.csv. Writes data/v6/<OUT>-blend-net.csv,
-blend-pos.csv and -blends.json. Does not modify the 26 committed
columns (adaptive search must not see design-fitted blends).
"""
import json, sys
import pandas as pd
import numpy as np

SLEEVES = ["carry-eq-d1", "xsmom-63-d1", "resid-mr-60-d1", "usd-tsmom-63-d1"]


def norm(w):
    w = np.maximum(np.array(w, float), 0.0)
    s = w.sum()
    return (w / s) if s > 1e-12 else np.zeros_like(w)


def main():
    out = sys.argv[1]
    ev = json.load(open("out/v6/evolved.json"))
    net = pd.read_csv(f"data/v6/{out}-net.csv")
    pos = pd.read_csv(f"data/v6/{out}-pos.csv")
    parts = json.load(open(f"data/v6/{out}-parts.json"))
    pairs = parts["pairs"]
    days = net["day"].tolist()
    years = np.array([int(d[:4]) for d in days])
    sleeve_net = np.column_stack([net[s].to_numpy(float) for s in SLEEVES])

    def sleeve_pos(name):
        return pos[[f"{name}|{p}" for p in pairs]].to_numpy(float)

    blends = {"nsga2-blend": ev["nsga2-blend"]["weights"], "es-blend": ev["es-blend"]["weights"]}
    net_out = pd.DataFrame({"day": days})
    pos_out = pd.DataFrame({"day": days})
    rec = {}
    for name, w in blends.items():
        ww = norm(w)
        col = sleeve_net @ ww
        acc = np.zeros((len(days), len(pairs)))
        for i, s in enumerate(SLEEVES):
            acc += ww[i] * sleeve_pos(s)
        net_out[name] = np.round(col, 4)
        for j, p in enumerate(pairs):
            pos_out[f"{name}|{p}"] = np.round(acc[:, j], 4)
        rec[name] = {
            "weights": {s: float(ww[i]) for i, s in enumerate(SLEEVES)},
            "raw": [float(x) for x in w],
            "sum": round(float(col.sum()), 2),
            "by-year": {str(y): round(float(col[years == y].sum()), 2) for y in np.unique(years)},
        }
        rec[name].update({k: ev[name][k] for k in ev[name] if k not in rec[name]})
        print(f"BLEND {name} w={ww.round(3).tolist()} sum={col.sum():.1f}")
    net_out.to_csv(f"data/v6/{out}-blend-net.csv", index=False)
    pos_out.to_csv(f"data/v6/{out}-blend-pos.csv", index=False)
    json.dump(rec, open(f"data/v6/{out}-blends.json", "w"), indent=1)
    print("V6_BLEND_OK")


if __name__ == "__main__":
    main()
