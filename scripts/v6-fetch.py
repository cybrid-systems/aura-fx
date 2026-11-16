#!/usr/bin/env python3
"""Dukascopy hourly BID/ASK -> data/v6/<pair>-<tag>-h4.csv and -d1.csv.

usage: v6-fetch.py TAG FROM_YYYY-MM TO_YYYY-MM PAIR...

Public datafeed, no login. Writes H1 to data/v6 (gitignored) and then
H4/D1 via scripts/v3-bars.py. D1 closes at 22:00 UTC; weekend hours go
to Monday. Dukascopy stores integers: 1e-3 for JPY quotes, 1e-5 otherwise.
A range check fails the run if a decoded mid is implausible. Raw month
files are cached in data/raw-dukascopy (not committed). The unprefixed
EURUSD cache from the original v2 fetch is reused when present.
"""
import calendar, datetime as dt, lzma, os, struct, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

# Wide historical bands so a genuine decode error still fails, but
# 2015-2026 extremes of these pairs do not.
RANGE = {
    "EURUSD": (0.8, 1.7), "GBPUSD": (0.9, 2.2), "USDJPY": (70, 200), "AUDUSD": (0.4, 1.2),
    "USDCHF": (0.6, 1.3), "USDCAD": (1.0, 1.8), "NZDUSD": (0.4, 1.1),
    "AUDJPY": (50, 150), "GBPJPY": (100, 250), "EURAUD": (1.0, 2.2), "EURCAD": (1.0, 2.0),
    "USDNOK": (5, 16), "USDSEK": (5, 16), "USDMXN": (8, 30), "USDZAR": (8, 30),
}
URL = "https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/{side}_candles_hour_1.bi5"
RAW = "data/raw-dukascopy"


def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def cached(p, y, m, side):
    pref = f"{RAW}/{p}-{y}-{m:02d}-{side}.bi5"
    if os.path.exists(pref) and os.path.getsize(pref) > 0:
        return pref
    if p == "EURUSD":
        alt = f"{RAW}/{y}-{m:02d}-{side}.bi5"
        if os.path.exists(alt) and os.path.getsize(alt) > 0:
            return alt
    return None


def fetch(p, y, m, side):
    hit = cached(p, y, m, side)
    if hit:
        return hit
    path = f"{RAW}/{p}-{y}-{m:02d}-{side}.bi5"
    url = URL.format(p=p, y=y, m=m - 1, side=side)
    err = None
    for attempt in range(30):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
            if data:
                open(path + ".tmp", "wb").write(data)
                os.replace(path + ".tmp", path)
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
    tag, a, b = sys.argv[1:4]
    pairs = sys.argv[4:]
    a = tuple(map(int, a.split("-")))
    b = tuple(map(int, b.split("-")))
    os.makedirs(RAW, exist_ok=True)
    os.makedirs("data/v6", exist_ok=True)
    jobs = [(p, y, m, s) for p in pairs for y, m in months(a, b) for s in ("BID", "ASK")]
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(8) as ex:
        for _ in ex.map(lambda j: fetch(*j), jobs):
            done += 1
            if done % 100 == 0:
                print(f"fetched {done}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    for p in pairs:
        scale = 1e3 if p.endswith("JPY") else 1e5
        lo, hi = RANGE[p]
        rows = []
        for y, m in months(a, b):
            bp = cached(p, y, m, "BID") or f"{RAW}/{p}-{y}-{m:02d}-BID.bi5"
            ap = cached(p, y, m, "ASK") or f"{RAW}/{p}-{y}-{m:02d}-ASK.bi5"
            bb = decode(bp, y, m, scale)
            aa = decode(ap, y, m, scale)
            for t in sorted(bb):
                if bb[t][1] > 0 and t in aa:
                    rows.append((t, bb[t][0], aa[t][0]))
        mids = [(x + y) / 2 for _, x, y in rows]
        if not mids or min(mids) < lo or max(mids) > hi:
            sys.exit(f"{p}: decoded mid out of range ({min(mids) if mids else 'empty'}, {max(mids) if mids else 'empty'})")
        out = f"data/v6/{p.lower()}-{tag}-h1.csv"
        with open(out, "w") as f:
            f.write("time_utc,bid,ask,mid\n")
            for t, x, y in rows:
                f.write(f"{dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:00Z')},{x:.5f},{y:.5f},{(x + y) / 2:.6f}\n")
        subprocess.run([sys.executable, "scripts/v3-bars.py", out, f"data/v6/{p.lower()}-{tag}"], check=True)
        print(f"FETCH_OK {p} {tag} h1-rows={len(rows)} from={rows[0][0]} to={rows[-1][0]}", flush=True)


if __name__ == "__main__":
    main()
