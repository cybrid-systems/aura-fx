#!/usr/bin/env python3
"""Final-test data for frozen-v3 (run only after the freeze commit).

Downloads Dukascopy hourly BID/ASK candles for GBPUSD, USDJPY, AUDUSD,
2023-01 .. 2026-10 (2023 is indicator warm-up only; pnl starts
2024-01-01), writes data/v3/<pair>-h1.csv ("time_utc,bid,ask,mid") and
aggregates H4 / D1 with scripts/v3-bars.py. Dukascopy stores prices as
integers: 1e-5 for these USD pairs, 1e-3 for JPY pairs. A range check
fails the run if a decoded mid is implausible.
"""
import calendar, datetime as dt, lzma, os, struct, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

PAIRS = {"GBPUSD": (1e5, 0.5, 3.0), "USDJPY": (1e3, 50.0, 300.0), "AUDUSD": (1e5, 0.3, 2.0)}
START, END = (2023, 1), (2026, 10)
URL = "https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/{side}_candles_hour_1.bi5"

def months():
    y, m = START
    while (y, m) <= END:
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
    os.makedirs("data/raw-dukascopy", exist_ok=True)
    os.makedirs("data/v3", exist_ok=True)
    jobs = [(p, y, m, s) for p in PAIRS for y, m in months() for s in ("BID", "ASK")]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda j: fetch(*j), jobs))
    for p, (scale, lo, hi) in PAIRS.items():
        rows = []
        for y, m in months():
            b = decode(f"data/raw-dukascopy/{p}-{y}-{m:02d}-BID.bi5", y, m, scale)
            a = decode(f"data/raw-dukascopy/{p}-{y}-{m:02d}-ASK.bi5", y, m, scale)
            for t in sorted(b):
                if b[t][1] > 0 and t in a:
                    rows.append((t, b[t][0], a[t][0]))
        mids = [(bb + aa) / 2 for _, bb, aa in rows]
        if not mids or min(mids) < lo or max(mids) > hi:
            sys.exit(f"{p}: decoded mid out of range")
        out = f"data/v3/{p.lower()}-h1.csv"
        with open(out, "w") as f:
            f.write("time_utc,bid,ask,mid\n")
            for t, bb, aa in rows:
                f.write(f"{dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:00Z')},{bb:.5f},{aa:.5f},{(bb + aa) / 2:.6f}\n")
        subprocess.run([sys.executable, "scripts/v3-bars.py", out, f"data/v3/{p.lower()}-final", "2023-01-01", "2026-11-01"], check=True)
        print(f"FETCH_OK {p} rows={len(rows)}")

if __name__ == "__main__":
    main()
