#!/usr/bin/env python3
"""Dukascopy hourly BID/ASK -> data/v4/<pair>-<tag>-h1.csv and D1 closes.

usage: v4-fetch.py TAG FROM_YYYY-MM TO_YYYY-MM BARS_FROM BARS_TO PAIR...
Writes data/v4/<pair>-<tag>-h1.csv ("time_utc,bid,ask,mid") and
data/v4/<pair>-<tag>-d1.csv / -h4.csv via scripts/v3-bars.py (D1 closes
at 22:00 UTC, weekend hours go to Monday). Dukascopy stores integers:
1e-5 for non-JPY pairs, 1e-3 for JPY pairs; a range check fails the run
if a decoded mid is implausible. Raw files are cached in
data/raw-dukascopy (not committed).
"""
import calendar, datetime as dt, lzma, os, struct, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

RANGE = {"EURUSD": (0.8, 1.7), "GBPUSD": (0.9, 2.2), "USDJPY": (70, 200), "AUDUSD": (0.4, 1.2),
         "USDCHF": (0.6, 1.3), "USDCAD": (1.0, 1.7), "NZDUSD": (0.4, 1.0), "EURJPY": (90, 220)}
URL = "https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/{side}_candles_hour_1.bi5"

def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

def fetch(p, y, m, side):
    path = f"data/raw-dukascopy/{p}-{y}-{m:02d}-{side}.bi5"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    url = URL.format(p=p, y=y, m=m - 1, side=side)
    err = None
    for attempt in range(30):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
            if data:
                open(path, "wb").write(data)
                return path
        except Exception as e:
            err = e
        time.sleep(1 + attempt % 5)
    raise RuntimeError(f"failed {url}: {err}")

def decode(path, y, m, scale):
    raw = lzma.decompress(open(path, "rb").read(), format=lzma.FORMAT_ALONE)
    base = calendar.timegm((y, m, 1, 0, 0, 0))
    out = {}
    for k in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack(">5if", raw[k:k + 24])
        out[base + sec] = (c / scale, vol)
    return out

def main():
    tag, a, b, bfrom, bto = sys.argv[1:6]
    pairs = sys.argv[6:]
    a = tuple(map(int, a.split("-"))); b = tuple(map(int, b.split("-")))
    os.makedirs("data/raw-dukascopy", exist_ok=True)
    jobs = [(p, y, m, s) for p in pairs for y, m in months(a, b) for s in ("BID", "ASK")]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda j: fetch(*j), jobs))
    for p in pairs:
        scale = 1e3 if p.endswith("JPY") else 1e5
        lo, hi = RANGE[p]
        rows = []
        for y, m in months(a, b):
            bb = decode(f"data/raw-dukascopy/{p}-{y}-{m:02d}-BID.bi5", y, m, scale)
            aa = decode(f"data/raw-dukascopy/{p}-{y}-{m:02d}-ASK.bi5", y, m, scale)
            for t in sorted(bb):
                if bb[t][1] > 0 and t in aa:
                    rows.append((t, bb[t][0], aa[t][0]))
        mids = [(x + y) / 2 for _, x, y in rows]
        if not mids or min(mids) < lo or max(mids) > hi:
            sys.exit(f"{p}: decoded mid out of range")
        out = f"data/v4/{p.lower()}-{tag}-h1.csv"
        with open(out, "w") as f:
            f.write("time_utc,bid,ask,mid\n")
            for t, x, y in rows:
                f.write(f"{dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:00Z')},{x:.5f},{y:.5f},{(x + y) / 2:.6f}\n")
        subprocess.run([sys.executable, "scripts/v3-bars.py", out, f"data/v4/{p.lower()}-{tag}", bfrom, bto], check=True)
        print(f"FETCH_OK {p} {tag} rows={len(rows)}")

if __name__ == "__main__":
    main()
