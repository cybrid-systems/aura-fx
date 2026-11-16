#!/usr/bin/env python3
"""Central bank policy rates (BIS WS_CBPOL, monthly, end of period).

usage: v4-rates.py OUT.csv FROM_YYYY-MM TO_YYYY-MM AREA...
Public, no credentials: https://stats.bis.org/api/v1/data/WS_CBPOL/...
Writes "month,AREA1,AREA2,..." in percent. The rate of month m is the
end-of-month value; the strategy code only uses it from month m+1 on.
"""
import csv, io, sys, urllib.request

def main():
    out, a, b = sys.argv[1:4]
    areas = sys.argv[4:]
    url = ("https://stats.bis.org/api/v1/data/WS_CBPOL/M." + "+".join(areas) +
           f"/all?format=csv&startPeriod={a}&endPeriod={b}")
    txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
    vals = {}
    for r in csv.DictReader(io.StringIO(txt)):
        if r["OBS_VALUE"]:
            vals.setdefault(r["TIME_PERIOD"], {})[r["REF_AREA"]] = float(r["OBS_VALUE"])
    months = sorted(m for m in vals if a <= m <= b)
    with open(out, "w") as f:
        f.write("month," + ",".join(areas) + "\n")
        for m in months:
            if any(x not in vals[m] for x in areas):
                sys.exit(f"missing rate {m} {vals[m]}")
            f.write(m + "," + ",".join(f"{vals[m][x]:.4f}" for x in areas) + "\n")
    print(f"RATES_OK {out} months={len(months)}")

if __name__ == "__main__":
    main()
