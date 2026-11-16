#!/usr/bin/env python3
"""Public policy rates (BIS WS_CBPOL, monthly) and a daily VIX series.

usage: v6-rates.py RATES.csv VIX.csv FROM_YYYY-MM TO_YYYY-MM AREA...

No credentials. Rates: https://stats.bis.org/api/v1/data/WS_CBPOL/...
The rate of month m is the end-of-month policy rate; strategy code only
uses it from month m+1 on (no look-ahead). VIX: the public
datasets/finance-vix CBOE daily close (GitHub / jsDelivr), with FRED
VIXCLS and Stooq ^VIX as fallbacks. --cutoff YYYY-MM-DD drops any
observation on or after that date, so a training fetch cannot
accidentally include the test period.
"""
import csv, io, json, os, sys, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0"}


def get(url, timeout=90):
    err = None
    for attempt in range(6):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            err = e
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"GET {url}: {err}")


def bis_rates(areas, a, b):
    url = ("https://stats.bis.org/api/v1/data/WS_CBPOL/M." + "+".join(areas) +
           f"/all?format=csv&startPeriod={a}&endPeriod={b}")
    txt = get(url, 90).decode()
    vals = {}
    for r in csv.DictReader(io.StringIO(txt)):
        if r.get("OBS_VALUE"):
            vals.setdefault(r["TIME_PERIOD"], {})[r["REF_AREA"]] = float(r["OBS_VALUE"])
    months = sorted(m for m in vals if a <= m <= b)
    return months, vals


def parse_vix_close(txt):
    """FRED (DATE,VIXCLS), CBOE/datasets (DATE,CLOSE), or Stooq (Date,Close)."""
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        keys = {k.lower(): k for k in r}
        d = r.get(keys.get("date") or keys.get("observation_date") or "", None)
        v = None
        for name in ("vixcls", "close", "value"):
            if name in keys:
                v = r[keys[name]]
                break
        if not d or not v or v in (".", "null", ""):
            continue
        rows.append((d[:10], float(v)))
    return rows


def fetch_vix():
    # FRED VIXCLS is the official series but has been unreachable from this
    # box. datasets/finance-vix is a public CBOE VIX mirror (no login).
    sources = [
        ("datasets/finance-vix CBOE close", "https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv", parse_vix_close, 30),
        ("datasets/finance-vix via jsDelivr", "https://cdn.jsdelivr.net/gh/datasets/finance-vix/data/vix-daily.csv", parse_vix_close, 30),
        ("FRED VIXCLS", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS", parse_vix_close, 20),
        ("Stooq ^VIX", "https://stooq.com/q/d/l/?s=^vix&i=d", parse_vix_close, 20),
    ]
    errs = []
    for name, url, parse, timeout in sources:
        try:
            rows = parse(get(url, timeout).decode())
            if len(rows) < 2000:
                raise RuntimeError(f"too few rows ({len(rows)})")
            return name, url, rows
        except Exception as e:
            errs.append(f"{name}: {e}")
    raise RuntimeError("VIX fetch failed: " + " | ".join(errs))


def addm(ms):
    y, mo = map(int, ms.split("-"))
    y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return f"{y}-{mo:02d}"


def main():
    out_r, out_v, a, b = sys.argv[1:5]
    areas = []
    cutoff = None
    args = sys.argv[5:]
    i = 0
    while i < len(args):
        if args[i] == "--cutoff":
            cutoff = args[i + 1]; i += 2
        else:
            areas.append(args[i]); i += 1
    months, vals = bis_rates(areas, a, b)
    if cutoff:
        months = [m for m in months if (m if len(cutoff) == 7 else m + "-01") < cutoff]

    want = []
    cur = a
    last = months[-1] if months else a
    while cur <= last:
        want.append(cur)
        cur = addm(cur)

    # Japan, Apr 2013-Sep 2016: BIS publishes no policy rate (BoJ QQE,
    # compilation: "from 4 Apr 2013 to 20 Sep 2016: no policy rate").
    # Fill those months with 0.0 (overnight call rate was at the zero
    # floor). Official -0.1 starts 2016-09. Any other hole fails the run.
    JP_GAP_END = "2016-08"
    filled = []
    for m in want:
        row = dict(vals.get(m, {}))
        if "JP" in areas and "JP" not in row and m <= JP_GAP_END:
            row["JP"] = 0.0
            filled.append(m)
        miss = [x for x in areas if x not in row]
        if miss:
            sys.exit(f"missing rate {m} miss={miss} have={sorted(row)}")
        vals[m] = row
    months = want
    with open(out_r, "w") as f:
        f.write("month," + ",".join(areas) + "\n")
        for m in months:
            f.write(m + "," + ",".join(f"{vals[m][x]:.4f}" for x in areas) + "\n")
    if filled:
        print(f"RATES_JP_GAP_FILL months={len(filled)} from={filled[0]} to={filled[-1]} value=0.0 (BIS has no JP policy rate in QQE)")

    src, url, rows = fetch_vix()
    if cutoff:
        rows = [(d, v) for d, v in rows if d < cutoff]
    lo = f"{int(a[:4]) - 1}-01-01"
    rows = [(d, v) for d, v in rows if d >= lo]
    rows.sort()
    if len(rows) < 200:
        sys.exit(f"VIX too short after filters: {len(rows)}")
    with open(out_v, "w") as f:
        f.write("day,vix\n")
        for d, v in rows:
            f.write(f"{d},{v:.4f}\n")
    json.dump({"source": src, "url": url, "from": rows[0][0], "to": rows[-1][0], "days": len(rows)},
              open(os.path.splitext(out_v)[0] + "-source.json", "w"), indent=1)
    print(f"RATES_OK {out_r} months={len(months)} from={months[0]} to={months[-1]}")
    print(f"VIX_OK {out_v} source={src} url={url} days={len(rows)} from={rows[0][0]} to={rows[-1][0]}")


if __name__ == "__main__":
    main()
