#!/usr/bin/env python3
"""Download Dukascopy EUR/USD hourly candles (public datafeed, no login).

For each month in [START, END] fetches BID_candles_hour_1.bi5 and
ASK_candles_hour_1.bi5 (LZMA, 24-byte big-endian records: seconds from
the month start, open, close, low, high as int * 1e-5, volume float32;
months are 0-based in the URL). Writes data/dukascopy-eurusd-h1.csv with
one row per hour that traded (bid volume > 0):
    time_utc,bid,ask,mid
where bid/ask are the hour's closes and mid = (bid + ask) / 2.
"""
import calendar, datetime as dt, lzma, os, struct, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

START = (2019, 1)
END = (2026, 10)
URL = "https://datafeed.dukascopy.com/datafeed/EURUSD/{y}/{m:02d}/{side}_candles_hour_1.bi5"
RAW = "data/raw-dukascopy"
OUT = "data/dukascopy-eurusd-h1.csv"

def months():
    y, m = START
    while (y, m) <= END:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

def fetch(y, m, side):
    path = f"{RAW}/{y}-{m:02d}-{side}.bi5"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    url = URL.format(y=y, m=m - 1, side=side)
    for attempt in range(30):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            if data:
                open(path, "wb").write(data)
                return path
        except Exception as e:
            err = e
        time.sleep(1 + attempt % 5)
    raise RuntimeError(f"failed {url}: {err}")

def decode(path, y, m):
    raw = lzma.decompress(open(path, "rb").read(), format=lzma.FORMAT_ALONE)
    base = calendar.timegm((y, m, 1, 0, 0, 0))
    out = {}
    for k in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack(">5if", raw[k:k + 24])
        out[base + sec] = (c / 1e5, vol)
    return out

def main():
    os.makedirs(RAW, exist_ok=True)
    jobs = [(y, m, s) for y, m in months() for s in ("BID", "ASK")]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda j: fetch(*j), jobs))
    rows = []
    for y, m in months():
        b = decode(f"{RAW}/{y}-{m:02d}-BID.bi5", y, m)
        a = decode(f"{RAW}/{y}-{m:02d}-ASK.bi5", y, m)
        for t in sorted(b):
            bid, vol = b[t]
            if vol <= 0 or t not in a:
                continue
            ask = a[t][0]
            rows.append((t, bid, ask))
    with open(OUT, "w") as f:
        f.write("time_utc,bid,ask,mid\n")
        for t, bid, ask in rows:
            ts = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:00Z")
            f.write(f"{ts},{bid:.5f},{ask:.5f},{(bid + ask) / 2:.6f}\n")
    print(f"DUKASCOPY_OK rows={len(rows)} from={rows[0][0]} to={rows[-1][0]}")

if __name__ == "__main__":
    sys.exit(main())
