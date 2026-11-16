#!/usr/bin/env python3
"""v5 column precompute: one signal set, four rebalancing frequencies.

usage: v5-prep.py SPLIT PAIR M5.csv.gz RATES.csv SPREAD_PIPS [--conv D1.csv] [--costmult K]
(--costmult scales spread and slippage, for the 2x-cost sensitivity run)

Signals (computed on 5-minute closes, so every frequency sees the same
signal values; vol = EWMA of |5m log return|, half-life 1 day):
  mom L   log return over L bars / (vol * sqrt L)
  mr  L   -(log close - mean of the last L log closes) / (vol * sqrt L)
  brk L   position in the L-bar high-low channel, scaled to [-1, 1]
  L = 12, 48, 288, 1440 bars (1 hour, 4 hours, 1 day, 5 days)
Rule: at each rebalance (the 5m bar closing on a multiple of R minutes,
R = 5, 15, 60, 240), go sign(s) when |s| > theta; go flat when s turns
against the position; otherwise keep. theta: 0.5 / 1.0 (mom, mr) and
0.6 / 0.9 (brk). The position chosen at a bar's close is held over the
next bar (no look-ahead). 4 frequencies x 3 families x 4 L x 2 theta = 96.
Costs per unit traded: half the spread + 0.2 pip slippage. Rollover on
positions held through 22:00 UTC: (policy-rate difference, previous
month, minus 1% p.a. markup) / 360, 3 nights on Wednesdays. Lot 10,000
base units; P&L converted to USD (xxx/USD: 1; EUR/GBP: previous day's
GBP/USD close from --conv). Trading days end at 22:00 UTC; weekend
labels go to Monday.

Writes data/v5/<split>-<pair>-net.csv (day, unit cost in USD per unit of
position change, then one net P&L column per config), -pos.csv (end-of-day
position per config), -parts.json (gross / cost / rollover / entries per
config and year).
"""
import datetime as dt, gzip, json, sys
from multiprocessing import Pool
import numpy as np, pandas as pd

LOT, SLIP, MARKUP = 10000, 0.2, 1.0
FREQS = [("m5", 1), ("m15", 3), ("h1", 12), ("h4", 48)]
LS = [12, 48, 288, 1440]
FAMS = [("mom", (0.5, 1.0)), ("mr", (0.5, 1.0)), ("brk", (0.6, 0.9))]
AREA = {"EUR": "XM", "USD": "US", "GBP": "GB", "JPY": "JP"}
CONFIGS = [(f, r, fam, L, th) for f, r in FREQS for fam, ths in FAMS for L in LS for th in ths]
def cname(c): return f"{c[0]}-{c[2]}{c[3]}-{c[4]}"

G = {}

def positions(args):
    k, = args
    f, r, fam, L, th = CONFIGS[k]
    s = G["sig"][(fam, L)]; t = G["t"]
    dec = ((t + 300) % (r * 300) == 0) & ~np.isnan(s)
    p = np.zeros(len(s), dtype=np.int8)
    cur = 0
    idx = np.flatnonzero(dec)
    sv = s[idx]
    out = np.zeros(len(idx), dtype=np.int8)
    for j in range(len(idx)):
        x = sv[j]
        if x > th: cur = 1
        elif x < -th: cur = -1
        elif cur * x < 0: cur = 0
        out[j] = cur
    # forward-fill decisions
    fill = np.zeros(len(s), dtype=np.int64)
    fill[idx] = np.arange(1, len(idx) + 1)
    fill = np.maximum.accumulate(fill)
    has = fill > 0
    p[has] = out[fill[has] - 1]
    return k, p

def main():
    split, pair, m5, rates_csv, spread = sys.argv[1:6]
    spread = float(spread)
    conv_csv = sys.argv[sys.argv.index("--conv") + 1] if "--conv" in sys.argv else None
    cm = float(sys.argv[sys.argv.index("--costmult") + 1]) if "--costmult" in sys.argv else 1.0
    df = pd.read_csv(m5)
    t = df["t"].to_numpy(np.int64); c = df["close"].to_numpy(float)
    lc = np.log(c)
    lr = np.diff(lc, prepend=lc[0])
    vol = pd.Series(np.abs(lr)).ewm(halflife=288, min_periods=288).mean().to_numpy()
    vol = np.where(vol > 0, vol, np.nan)
    sig = {}
    lcs = pd.Series(lc); cs = pd.Series(c)
    for L in LS:
        sig[("mom", L)] = (lc - lcs.shift(L).to_numpy()) / (vol * np.sqrt(L))
        sig[("mr", L)] = -(lc - lcs.rolling(L).mean().to_numpy()) / (vol * np.sqrt(L))
        hi = cs.rolling(L).max().to_numpy(); lo = cs.rolling(L).min().to_numpy()
        rng = np.where(hi - lo > 0, hi - lo, np.nan)
        sig[("brk", L)] = 2 * (c - lo) / rng - 1
    for key in sig:
        sig[key][:1440] = np.nan
    G.update(sig=sig, t=t)

    # trading day labels
    lab = [(dt.datetime.fromtimestamp(x + 7200, dt.timezone.utc).date()) for x in t[::1]]
    lab = np.array([d + dt.timedelta(days=(7 - d.weekday()) % 7) if d.weekday() >= 5 else d for d in lab])
    days, di = np.unique(lab, return_inverse=True)
    nd = len(days)
    # rates (previous month) and nights per day
    rates = {r["month"]: r for _, r in pd.read_csv(rates_csv, dtype=str).iterrows()}
    base, quote = pair[:3], pair[3:]
    def pm(d): y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12); return f"{y}-{m:02d}"
    diff = np.array([float(rates[pm(d)][AREA[base]]) - float(rates[pm(d)][AREA[quote]]) for d in days])
    nights = np.array([3 if d.weekday() == 2 else 1 for d in days])
    # conversion of quote currency to USD, per day (previous day's close)
    if quote == "USD":
        conv = np.ones(nd)
    else:
        cv = pd.read_csv(conv_csv)
        cmap = dict(zip(cv["day"], cv["close"]))
        conv = np.zeros(nd); last = None
        for i, d in enumerate(days):
            prev = [x for x in [(d - dt.timedelta(days=k)).isoformat() for k in range(1, 8)] if x in cmap]
            conv[i] = cmap[prev[0]] if prev else np.nan
        assert not np.isnan(conv).any()
    pip = 0.01 if quote == "JPY" else 0.0001
    hc = cm * (spread / 2 + SLIP) * pip            # quote currency per unit traded
    unit_cost = hc * LOT * conv               # USD per unit of position change, per day
    dc = np.diff(c, prepend=c[0])             # bar i's price change (from bar i-1)
    cross = np.r_[di[1:] != di[:-1], False]   # bar i is the last bar of its day
    with Pool(8) as pool:
        res = dict(pool.map(positions, [(k,) for k in range(len(CONFIGS))]))
    net = np.zeros((nd, len(CONFIGS))); eod = np.zeros((nd, len(CONFIGS)), dtype=np.int8)
    parts = {}
    years = np.array([d.year for d in days])
    for k in range(len(CONFIGS)):
        p = res[k].astype(float)
        held = np.r_[0.0, p[:-1]]                       # position over bar i
        gross_q = held * dc
        dp = np.abs(np.diff(p, prepend=0.0))
        cost_q = dp * hc
        carry_q = np.where(cross, (p * diff[di] - np.abs(p) * MARKUP) / 100 / 360 * c * nights[di], 0.0)
        g = np.bincount(di, gross_q, nd) * LOT * conv
        co = np.bincount(di, cost_q, nd) * LOT * conv
        ca = np.bincount(di, carry_q, nd) * LOT * conv
        entries = ((p != 0) & (p != np.r_[0.0, p[:-1]])).astype(float)
        en = np.bincount(di, entries, nd)
        net[:, k] = g - co + ca
        lastbar = np.r_[np.flatnonzero(cross), len(p) - 1]
        eod[:, k] = res[k][lastbar[:nd]] if len(lastbar) >= nd else 0
        parts[cname(CONFIGS[k])] = {str(y): [round(float(g[years == y].sum()), 2), round(float(co[years == y].sum()), 2),
                                             round(float(ca[years == y].sum()), 2), int(en[years == y].sum())]
                                    for y in np.unique(years)}
    names = [cname(x) for x in CONFIGS]
    out = f"data/v5/{split}-{pair.lower()}"
    with open(out + "-net.csv", "w") as f:
        f.write("day,unitcost," + ",".join(names) + "\n")
        for i, d in enumerate(days):
            f.write(d.isoformat() + f",{unit_cost[i]:.4f}," + ",".join(f"{x:.2f}" for x in net[i]) + "\n")
    with open(out + "-pos.csv", "w") as f:
        f.write("day," + ",".join(names) + "\n")
        for i, d in enumerate(days):
            f.write(d.isoformat() + "," + ",".join(str(int(x)) for x in eod[i]) + "\n")
    json.dump({"pair": pair, "spread": spread, "slip": SLIP, "costmult": cm, "parts-format": "year: [gross, cost, rollover, entries]",
               "configs": parts}, open(out + "-parts.json", "w"))
    print(f"PREP_OK {out} days={nd} from={days[0]} to={days[-1]} configs={len(CONFIGS)}", flush=True)

if __name__ == "__main__":
    main()
