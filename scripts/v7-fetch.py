#!/usr/bin/env python3
"""Dukascopy hourly BID/ASK -> data/v7/<pair>-<tag>-d1.csv (and H1, gitignored).

usage: v7-fetch.py TAG FROM_YYYY-MM TO_YYYY-MM PAIR...

Public datafeed, no login. Same decoder as v6-fetch.py, with an explicit
price scale: 1e-3 for JPY and HUF quotes, 1e-4 for CZK, 1e-5 otherwise.
A range check fails the run if a decoded mid is implausible. Raw month
files are cached in data/raw-dukascopy (not committed). D1 closes at
22:00 UTC; weekend hours go to Monday (scripts/v3-bars.py).

The current calendar month may be incomplete; callers must drop any D1
whose 22:00 UTC close has not yet occurred.
"""
import calendar, datetime as dt, lzma, os, struct, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

# Wide historical bands so a genuine decode error still fails, but
# 2015-2026 extremes of these pairs do not.
RANGE = {
    "EURUSD": (0.8, 1.7), "GBPUSD": (0.9, 2.2), "USDJPY": (70, 200), "AUDUSD": (0.4, 1.2),
    "USDCHF": (0.6, 1.3), "USDCAD": (1.0, 1.8), "NZDUSD": (0.4, 1.1),
    "AUDJPY": (50, 150), "GBPJPY": (100, 250), "EURAUD": (1.0, 2.2), "EURCAD": (1.0, 2.0),
    "USDNOK": (5, 16), "USDSEK": (5, 16), "USDMXN": (8, 30), "USDZAR": (8, 30),
    "EURNOK": (8, 16), "EURSEK": (8, 16), "USDHUF": (200, 550), "EURHUF": (250, 550),
    "NZDJPY": (40, 150), "CADJPY": (60, 200), "CHFJPY": (80, 250), "EURNZD": (1.0, 3.0),
    "USDPLN": (2.0, 6.0), "USDCZK": (15, 35),
}
URL = "https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/{side}_candles_hour_1.bi5"
RAW = "data/raw-dukascopy"
OUT = "data/v7"


def scale(pair):
    if pair.endswith("JPY") or pair.endswith("HUF"):
        return 1e3
    if pair.endswith("CZK"):
        return 1e4
    return 1e5


def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def cached(p, y, m, side):
    pref = f"{RAW}/{p}-{y}-{m:02d}-{side}.bi5"
    if os.path.exists(pref) and os.path.getsize(pref) > 200:
        return pref
    if p == "EURUSD":
        alt = f"{RAW}/{y}-{m:02d}-{side}.bi5"
        if os.path.exists(alt) and os.path.getsize(alt) > 200:
            return alt
    return None


def fetch(p, y, m, side):
    hit = cached(p, y, m, side)
    if hit:
        return hit
    path = f"{RAW}/{p}-{y}-{m:02d}-{side}.bi5"
    url = URL.format(p=p, y=y, m=m - 1, side=side)
    err = None
    # Dukascopy frequently closes CPython urllib SSL mid-handshake
    # (UNEXPECTED_EOF_WHILE_READING). curl retries more reliably.
    for attempt in range(30):
        try:
            r = subprocess.run(
                ["curl", "-fsS", "-A", "Mozilla/5.0", "--max-time", "45",
                 "--retry", "2", "--retry-delay", "1", "-o", path + ".tmp", url],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and os.path.exists(path + ".tmp") and os.path.getsize(path + ".tmp") > 200:
                os.replace(path + ".tmp", path)
                return path
            err = r.stderr.strip() or f"curl exit {r.returncode}"
        except Exception as e:
            err = e
        try:
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")
        except OSError:
            pass
        time.sleep(1 + attempt % 5)
    raise RuntimeError(f"failed {url}: {err}")


def decode(path, y, m, sc):
    raw = lzma.decompress(open(path, "rb").read(), format=lzma.FORMAT_ALONE)
    base = calendar.timegm((y, m, 1, 0, 0, 0))
    out = {}
    for k in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack(">5if", raw[k:k + 24])
        out[base + sec] = (c / sc, vol)
    return out


def main():
    tag, a, b = sys.argv[1:4]
    pairs = [p.upper().replace("/", "") for p in sys.argv[4:]]
    a = tuple(map(int, a.split("-")))
    b = tuple(map(int, b.split("-")))
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    for p in pairs:
        if p not in RANGE:
            sys.exit(f"no range band for {p}")
    jobs = [(p, y, m, s) for p in pairs for y, m in months(a, b) for s in ("BID", "ASK")]
    t0 = time.time()
    done = 0
    print(f"FETCH_START jobs={len(jobs)} pairs={pairs} {a}..{b}", flush=True)
    with ThreadPoolExecutor(8) as ex:
        for _ in ex.map(lambda j: fetch(*j), jobs):
            done += 1
            if done % 50 == 0 or done == len(jobs):
                print(f"fetched {done}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    for p in pairs:
        sc = scale(p)
        lo, hi = RANGE[p]
        rows = []
        for y, m in months(a, b):
            bp = cached(p, y, m, "BID") or f"{RAW}/{p}-{y}-{m:02d}-BID.bi5"
            ap = cached(p, y, m, "ASK") or f"{RAW}/{p}-{y}-{m:02d}-ASK.bi5"
            bb = decode(bp, y, m, sc)
            aa = decode(ap, y, m, sc)
            for t in sorted(bb):
                if bb[t][1] > 0 and t in aa:
                    rows.append((t, bb[t][0], aa[t][0]))
        mids = [(x + y) / 2 for _, x, y in rows]
        if not mids or min(mids) < lo or max(mids) > hi:
            sys.exit(f"{p}: decoded mid out of range ({min(mids) if mids else 'empty'}, {max(mids) if mids else 'empty'}) scale={sc:g}")
        out = f"{OUT}/{p.lower()}-{tag}-h1.csv"
        with open(out, "w") as f:
            f.write("time_utc,bid,ask,mid\n")
                for t, x, y in rows:
                f.write(f"{dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:00Z')},{x:.5f},{y:.5f},{(x + y) / 2:.6f}\n")
        subprocess.run([sys.executable, "scripts/v3-bars.py", out, f"{OUT}/{p.lower()}-{tag}"], check=True)
        print(f"FETCH_OK {p} {tag} h1-rows={len(rows)} scale={sc:g} from={rows[0][0]} to={rows[-1][0]}", flush=True)


if __name__ == "__main__":
    main()
