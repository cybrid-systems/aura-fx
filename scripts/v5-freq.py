#!/usr/bin/env python3
"""v5 frequency table from the -parts.json files.

usage: v5-freq.py YEARS PARTS.json ...   (YEARS e.g. 2019-2023)
Per rebalancing frequency (24 rules each, one 10k lot, summed over the
given pairs and years): gross, cost, rollover, net, entries (independent
trades: a position opened from flat or flipped), gross and cost per
entry, rules with gross > 0 / net > 0, the best rule by net.
"""
import json, sys

def main():
    y0, y1 = map(int, sys.argv[1].split("-"))
    years = [str(y) for y in range(y0, y1 + 1)]
    per = {}
    for p in sys.argv[2:]:
        for nm, py in json.load(open(p))["configs"].items():
            g = per.setdefault(nm, [0.0, 0.0, 0.0, 0])
            for y in years:
                if y in py:
                    for k in range(4): g[k] += py[y][k]
    out = {}
    for f in ("m5", "m15", "h1", "h4"):
        rs = {nm: v for nm, v in per.items() if nm.startswith(f + "-")}
        G = sum(v[0] for v in rs.values()); C = sum(v[1] for v in rs.values()); R = sum(v[2] for v in rs.values())
        E = sum(v[3] for v in rs.values())
        best = max(rs, key=lambda k: rs[k][0] - rs[k][1] + rs[k][2])
        b = rs[best]
        out[f] = {"rules": len(rs), "gross": round(G), "cost": round(C), "rollover": round(R), "net": round(G - C + R),
                  "entries": E, "gross/entry": round(G / max(E, 1), 2), "cost/entry": round(C / max(E, 1), 2),
                  "gross>0": sum(v[0] > 0 for v in rs.values()), "net>0": sum(v[0] - v[1] + v[2] > 0 for v in rs.values()),
                  "best": best, "best-net": round(b[0] - b[1] + b[2]), "best-gross": round(b[0]), "best-cost": round(b[1]), "best-entries": b[3]}
        print("V5Q", f, out[f])
    json.dump(out, open("out/v5-freq-" + sys.argv[1] + ".json", "w"), indent=1)

if __name__ == "__main__":
    main()
