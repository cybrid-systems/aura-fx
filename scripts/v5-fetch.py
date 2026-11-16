#!/usr/bin/env python3
"""Dukascopy minute BID candles -> data/v5/<pair>-<tag>-m5.csv.gz.

usage: v5-fetch.py TAG FROM_YYYY-MM-DD TO_YYYY-MM-DD PAIR...
One request per pair and day (BID_candles_min_1.bi5, empty on weekends).
Writes 5-minute bars ("t,close": t = bar start, unix seconds UTC; close =
last minute close with volume > 0 inside the bar). Costs are modelled
from a fixed spread, so ASK is not needed. Raw files are cached in
data/raw-dukascopy-m1 (not committed). A range check fails the run if a
decoded price is implausible.
"""
import datetime as dt, gzip, lzma, os, struct, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

RANGE = {"EURUSD": (0.8, 1.7), "GBPUSD": (0.9, 2.2), "EURGBP": (0.6, 1.1), "USDSEK": (6, 14)}
URL = "https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
RAW = "data/raw-dukascopy-m1"

def days(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)

def fetch(p, d):
    path = f"{RAW}/{p}-{d.isoformat()}.bi5"
    if os.path.exists(path):
        return path
    url = URL.format(p=p, y=d.year, m=d.month - 1, d=d.day)
    err = None
    for attempt in range(40):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read()
            open(path + ".tmp", "wb").write(data)
            os.replace(path + ".tmp", path)
            return path
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(path, "wb").close()
                return path
            err = e
        except Exception as e:
            err = e
        time.sleep(1 + attempt % 7)
    raise RuntimeError(f"failed {url}: {err}")

def decode(path, d, scale):
    blob = open(path, "rb").read()
    if not blob:
        return []
    raw = lzma.decompress(blob, format=lzma.FORMAT_ALONE)
    base = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
    out = []
    for k in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack(">5if", raw[k:k + 24])
        if vol > 0:
            out.append((base + sec, c / scale))
    return out

def main():
    tag, a, b = sys.argv[1:4]
    pairs = sys.argv[4:]
    a = dt.date.fromisoformat(a); b = dt.date.fromisoformat(b)
    os.makedirs(RAW, exist_ok=True); os.makedirs("data/v5", exist_ok=True)
    jobs = [(p, d) for p in pairs for d in days(a, b) if d.weekday() != 5]
    t0 = time.time(); done = 0
    with ThreadPoolExecutor(32) as ex:
        for _ in ex.map(lambda j: fetch(*j), jobs):
            done += 1
            if done % 200 == 0:
                print(f"fetched {done}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    for p in pairs:
        scale = 1e3 if p.endswith("JPY") else 1e5
        lo, hi = RANGE[p]
        bars = {}
        for d in days(a, b):
            if d.weekday() == 5:
                continue
            for t, c in decode(f"{RAW}/{p}-{d.isoformat()}.bi5", d, scale):
                bars[t - t % 300] = c          # minutes arrive in order: last close wins
        ts = sorted(bars)
        cs = [bars[t] for t in ts]
        if not cs or min(cs) < lo or max(cs) > hi:
            sys.exit(f"{p}: decoded price out of range")
        out = f"data/v5/{p.lower()}-{tag}-m5.csv.gz"
        with gzip.open(out, "wt") as f:
            f.write("t,close\n")
            for t, c in zip(ts, cs):
                f.write(f"{t},{c:.5f}\n")
        print(f"FETCH_OK {p} {tag} m5-bars={len(ts)} from={ts[0]} to={ts[-1]}", flush=True)

if __name__ == "__main__":
    main()
