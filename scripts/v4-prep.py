#!/usr/bin/env python3
"""v4 feature tables (D1) on a common trading-day calendar.

usage: v4-prep.py SPLIT RATES.csv FROM TO PAIR=D1.csv ... [--basket PAIR=D1.csv ...]

For every traded PAIR writes data/v4/SPLIT-<pair>.csv with one row per
trading day in [FROM, TO) (union calendar of the traded pairs; a missing
close is carried forward). Every feature at row i uses closes <= i only:

  close, conv    conv = quote-currency units per USD (1 for xxx/USD, the
                 close for USD/xxx, the USD/JPY close for EUR/JPY)
  carry          policy rate(base) - policy rate(quote), percent, BIS
                 month-end value of the PREVIOUS month
  nights         rollover nights for holding through this day's close
                 (3 on Wednesday, else 1)
  zretL          (c_i - c_{i-L}) / (sig_i sqrt L), L in 5 10 20 60 120
  zsmaL          (c_i - SMA_L) / (sig_i sqrt L), L in 10 20 50 100 200
  dposN          position in the N-day close range, -1..1, N in 10 20 55 120
  vr             sig / sig_long (EWMA |dc| spans 20 / 200)
  usdL           USD strength: mean over the basket of USD-oriented
                 log returns over L days in vol units, times +1 when USD
                 is the base, -1 when USD is the quote, 0 for crosses;
                 L in 5 20 60
  upL            2 * share of up closes over L days - 1, L in 10 20 60
  r1             (c_i - c_{i-1}) / sig_{i-1}
A feature without enough history is 0 (vr 1).
"""
import csv, datetime as dt, math, sys

AREA = {"USD": "US", "EUR": "XM", "GBP": "GB", "JPY": "JP", "AUD": "AU", "CHF": "CH", "CAD": "CA", "NZD": "NZ"}
ZRET = [5, 10, 20, 60, 120]; ZSMA = [10, 20, 50, 100, 200]; DPOS = [10, 20, 55, 120]; USD = [5, 20, 60]; UP = [10, 20, 60]
COLS = (["day", "close", "conv", "carry", "nights"] + [f"zret{l}" for l in ZRET] + [f"zsma{l}" for l in ZSMA]
        + [f"dpos{l}" for l in DPOS] + ["vr"] + [f"usd{l}" for l in USD] + [f"up{l}" for l in UP] + ["r1"])

def load(path):
    out = {}
    for r in csv.DictReader(open(path)):
        out[r["day"]] = float(r["close"])
    return out

def ewma_abs(xs, span):
    a = 2.0 / (span + 1.0); s = 0.0; out = [0.0] * len(xs)
    for i in range(1, len(xs)):
        d = abs(xs[i] - xs[i - 1]); s = d if i == 1 else a * d + (1 - a) * s; out[i] = s
    return out

def ffill(series, days):
    out, last = [], None
    for d in days:
        if d in series: last = series[d]
        out.append(last)
    first = next(x for x in out if x is not None)
    return [first if x is None else x for x in out]

def main():
    args = sys.argv[1:]
    split, rates_path, lo, hi = args[:4]
    rest = args[4:]
    basket_at = rest.index("--basket") if "--basket" in rest else len(rest)
    pairs = [a.split("=") for a in rest[:basket_at]]
    basket = [a.split("=") for a in rest[basket_at + 1:]]
    rates = {r["month"]: r for r in csv.DictReader(open(rates_path))}
    raw = {p: load(f) for p, f in pairs + basket}
    days = sorted(d for d in set().union(*[set(raw[p]) for p, _ in pairs]) if lo <= d < hi)
    closes = {p: ffill(raw[p], days) for p in raw}
    n = len(days)
    # USD-oriented log returns in vol units, averaged over the basket
    usd = {}
    for L in USD:
        acc = [0.0] * n
        for p in raw if not basket else [b for b, _ in basket]:
            pass
        names = [b for b, _ in basket] or [p for p, _ in pairs]
        for b in names:
            c = closes[b]; lc = [math.log(x) for x in c]; sg = ewma_abs(lc, 20)
            o = 1.0 if b.startswith("USD") else -1.0
            for i in range(n):
                if i >= L and sg[i] > 0:
                    acc[i] += o * (lc[i] - lc[i - L]) / (sg[i] * math.sqrt(L)) / len(names)
        usd[L] = acc
    for p, _ in pairs:
        base, quote = p[:3], p[3:]
        c = closes[p]; sg = ewma_abs(c, 20); sl = ewma_abs(c, 200)
        if quote == "USD": conv = [1.0] * n
        elif base == "USD": conv = c
        else: conv = closes["USDJPY"]
        orient = 1.0 if base == "USD" else (-1.0 if quote == "USD" else 0.0)
        rows = []
        for i, d in enumerate(days):
            y, m = int(d[:4]), int(d[5:7])
            pm = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
            r = rates[pm]
            carry = float(r[AREA[base]]) - float(r[AREA[quote]])
            nights = 3 if dt.date.fromisoformat(d).weekday() == 2 else 1
            s = sg[i]
            row = [d, f"{c[i]:.6f}", f"{conv[i]:.6f}", f"{carry:.4f}", str(nights)]
            for L in ZRET:
                row.append(f"{(c[i] - c[i - L]) / (s * math.sqrt(L)):.4f}" if i >= L and s > 0 else "0")
            for L in ZSMA:
                row.append(f"{(c[i] - sum(c[i - L + 1:i + 1]) / L) / (s * math.sqrt(L)):.4f}" if i >= L - 1 and i >= 20 and s > 0 else "0")
            for N in DPOS:
                if i >= N - 1:
                    w = c[i - N + 1:i + 1]; h, l = max(w), min(w)
                    row.append(f"{(c[i] - (h + l) / 2) / ((h - l) / 2):.4f}" if h > l else "0")
                else:
                    row.append("0")
            row.append(f"{s / sl[i]:.4f}" if i >= 200 and sl[i] > 0 else "1")
            for L in USD:
                row.append(f"{orient * usd[L][i]:.4f}")
            for L in UP:
                row.append(f"{2.0 * sum(1 for k in range(i - L + 1, i + 1) if c[k] > c[k - 1]) / L - 1.0:.4f}" if i >= L else "0")
            row.append(f"{(c[i] - c[i - 1]) / sg[i - 1]:.4f}" if i >= 2 and sg[i - 1] > 0 else "0")
            rows.append(row)
        out = f"data/v4/{split}-{p.lower()}.csv"
        with open(out, "w") as f:
            f.write(",".join(COLS) + "\n")
            for row in rows:
                f.write(",".join(row) + "\n")
        print(f"PREP_OK {out} rows={len(rows)} from={days[0]} to={days[-1]}")

if __name__ == "__main__":
    main()
