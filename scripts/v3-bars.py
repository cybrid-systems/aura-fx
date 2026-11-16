#!/usr/bin/env python3
"""Aggregate an hourly CSV "time_utc,bid,ask,mid" to H4 and D1 closes.

usage: v3-bars.py IN.csv OUT_PREFIX [FROM] [TO]
Keeps hourly rows with FROM <= time < TO (ISO strings, optional), then
writes OUT_PREFIX-h4.csv and OUT_PREFIX-d1.csv as "time_utc,close,day"
(day = the trading day the bar belongs to, as for D1):
  H4: UTC buckets 00-03, 04-07, ...; close = mid of the last hour.
  D1: trading day = UTC date of (time + 2h), so a day closes at 22:00
      UTC (about 17:00 New York); weekend hours go to Monday; close =
      mid of the last hour.
The time written is the time of the last hour in the bucket.
"""
import csv, datetime as dt, sys

def d1key(t):
    d = (dt.datetime.strptime(t, "%Y-%m-%dT%H:00Z") + dt.timedelta(hours=2)).date()
    while d.weekday() >= 5:          # weekend hours belong to Monday
        d += dt.timedelta(days=1)
    return d.isoformat()

def main():
    src, out = sys.argv[1], sys.argv[2]
    lo = sys.argv[3] if len(sys.argv) > 3 else ""
    hi = sys.argv[4] if len(sys.argv) > 4 else "9999"
    rows = [(r["time_utc"], float(r["mid"])) for r in csv.DictReader(open(src)) if lo <= r["time_utc"] < hi]
    for tag, key in (("h4", lambda t: t[:11] + "%02d" % (int(t[11:13]) // 4 * 4)),
                     ("d1", d1key)):
        last = {}
        order = []
        for t, p in rows:
            k = key(t)
            if k not in last:
                order.append(k)
            last[k] = (t, p)
        with open(f"{out}-{tag}.csv", "w") as f:
            f.write("time_utc,close,day\n")
            for k in order:
                t, p = last[k]
                f.write(f"{t},{p:.6f},{d1key(t)}\n")
        print(f"BARS_OK {out}-{tag}.csv rows={len(order)}")

if __name__ == "__main__":
    main()
