#!/usr/bin/env python3
"""Fetch ECB EUR/USD reference rates and write data/ecb-eurusd.csv per frozen/v1.json.
No credentials. Prints only row counts and the date range."""
import csv, io, json, os, urllib.request, zipfile
spec = json.load(open("frozen/v1.json"))["real"]
raw = urllib.request.urlopen("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip", timeout=60).read()
z = zipfile.ZipFile(io.BytesIO(raw))
rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), "utf-8")))
pts = sorted((r["Date"], r["USD"].strip()) for r in rows if r.get("USD", "").strip() not in ("", "N/A"))
pts = [p for p in pts if p[0] <= spec["last-date"]][-spec["rows"]:]
assert len(pts) == spec["rows"], len(pts)
os.makedirs("data", exist_ok=True)
with open(spec["csv"], "w") as f:
    f.write("date,close\n")
    for d, v in pts:
        f.write(f"{d},{v}\n")
print(f"ECB_OK rows={len(pts)} from={pts[0][0]} to={pts[-1][0]}")
