#!/usr/bin/env python3
"""Align D1 closes, previous-month carry differentials, VIX and USD conversion.

usage: v7-market.py

Reads frozen/v7.json, data/v7/<pair>-paper-d1.csv, rates and VIX, and
writes data/v7/market-*.csv plus market-meta.json for Aura. Drops any
D1 whose 22:00 UTC close has not yet occurred, so a mid-day rerun does
not book a partial day. Positions themselves are not computed here.
"""
import datetime as dt, json, os, sys
import numpy as np, pandas as pd

AREA = {"EUR": "XM", "USD": "US", "GBP": "GB", "JPY": "JP", "AUD": "AU",
        "NZD": "NZ", "CAD": "CA", "CHF": "CH", "NOK": "NO", "SEK": "SE",
        "MXN": "MX", "ZAR": "ZA", "PLN": "PL", "HUF": "HU", "CZK": "CZ"}
# Same convention as frozen v6: 0.01 for JPY quotes, 0.0001 otherwise
# (including HUF / NOK / SEK). Published FXCM spreads are applied in
# those units.
SLIP, LOT, MARKUP = 0.2, 10000, 1.0


def pip_size(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


def prev_month(d):
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return f"{y}-{m:02d}"


def find_d1(pair, tag="paper"):
    candidates = [
        f"data/v7/{pair.lower()}-{tag}-d1.csv",
        f"data/v7/{pair.lower()}-paper-d1.csv",
        f"data/v6/{pair.lower()}-final-d1.csv",
        f"data/v6/{pair.lower()}-train-d1.csv",
        f"data/v4/{pair.lower()}-final-d1.csv",
        f"data/v3/{pair.lower()}-final-d1.csv",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def quote_usd_map(pair, own_d1):
    base, quote = pair[:3], pair[3:]
    if quote == "USD":
        return None
    raw = {}
    if base == "USD":
        for _, r in own_d1.iterrows():
            raw[r["day"]] = 1.0 / float(r["close"])
        return raw
    for helper, invert in ((f"USD{quote}", True), (f"{quote}USD", False)):
        path = find_d1(helper)
        if path:
            df = pd.read_csv(path)
            for _, r in df.iterrows():
                c = float(r["close"])
                raw[r["day"]] = (1.0 / c) if invert else c
            return raw
    raise SystemExit(f"{pair}: no quote-to-USD series for {quote} (looked for USD{quote} / {quote}USD)")


def align_prev(raw, days):
    keys = sorted(raw)
    out = np.full(len(days), np.nan)
    j = 0
    last = np.nan
    for i, d in enumerate(days):
        while j < len(keys) and keys[j] < d:
            last = raw[keys[j]]
            j += 1
        out[i] = last
    return out


def complete_days(d1s, pairs, now):
    """Intersection of pair days whose 22:00 UTC close has already passed."""
    common = set.intersection(*[set(d1s[p]["day"]) for p in pairs])
    last_bar = {}
    for p in pairs:
        for _, r in d1s[p].iterrows():
            last_bar.setdefault(r["day"], {})[p] = r["time_utc"]
    keep = []
    for d in sorted(common):
        close = dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc) + dt.timedelta(hours=22)
        if now < close:
            continue
        keep.append(d)
    return keep


def main():
    spec = json.load(open("frozen/v7.json"))
    pairs = list(spec["basket"]["primary"])
    tag = "paper"
    d1s = {}
    for p in pairs:
        path = f"data/v7/{p.lower()}-{tag}-d1.csv"
        if not os.path.exists(path):
            sys.exit(f"missing {path}")
        d1s[p] = pd.read_csv(path)
    now = dt.datetime.now(dt.timezone.utc)
    days = complete_days(d1s, pairs, now)
    if len(days) < 200:
        sys.exit(f"alignment too short after dropping incomplete D1: days={len(days)}")
    rates = {r["month"]: r for _, r in pd.read_csv(spec["paths"]["rates"], dtype=str).iterrows()}
    day_dates = [dt.date.fromisoformat(d) for d in days]
    miss = []
    for d in day_dates:
        pm = prev_month(d)
        if pm not in rates:
            miss.append(pm)
    if miss:
        sys.exit(f"missing previous-month BIS rates for {sorted(set(miss))}")
    for d in day_dates:
        row = rates[prev_month(d)]
        for p in pairs:
            b, q = p[:3], p[3:]
            if AREA[b] not in row or AREA[q] not in row:
                sys.exit(f"rate row {prev_month(d)} missing {AREA[b]}/{AREA[q]} for {p}")

    m = len(pairs)
    C = np.column_stack([d1s[p].set_index("day").loc[days, "close"].to_numpy(float) for p in pairs])
    diff = np.array([[float(rates[prev_month(d)][AREA[p[:3]]]) - float(rates[prev_month(d)][AREA[p[3:]]])
                      for p in pairs] for d in day_dates])
    nights = np.array([3 if d.weekday() == 2 else 1 for d in day_dates])

    conv = np.ones((len(days), m))
    raw_maps = [quote_usd_map(p, d1s[p]) for p in pairs]
    for j, p in enumerate(pairs):
        if raw_maps[j] is None:
            conv[:, j] = 1.0
        else:
            conv[:, j] = align_prev(raw_maps[j], days)
            if np.isnan(conv[:, j]).any():
                conv[:, j] = pd.Series(conv[:, j]).bfill().to_numpy()
                if np.isnan(conv[:, j]).any():
                    sys.exit(f"{p}: quote-to-USD missing")

    vf = pd.read_csv(spec["paths"]["vix"])
    vix = align_prev(dict(zip(vf["day"], vf["vix"].astype(float))), days)
    spreads = spec["spreads"]
    unit_pip = [(spreads[p] / 2 + spec["slippage-pips-per-side"]) * pip_size(p) for p in pairs]

    os.makedirs("data/v7", exist_ok=True)
    with open("data/v7/market-day.csv", "w") as f:
        f.write("day,vix,nights\n")
        for i, d in enumerate(days):
            vv = vix[i]
            vs = "" if not np.isfinite(vv) else f"{vv:.4f}"
            f.write(f"{d},{vs},{int(nights[i])}\n")
    def write_mat(path, mat):
        with open(path, "w") as f:
            f.write("day," + ",".join(pairs) + "\n")
            for i, d in enumerate(days):
                f.write(d + "," + ",".join(f"{x:.8f}" for x in mat[i]) + "\n")
    write_mat("data/v7/market-close.csv", C)
    write_mat("data/v7/market-diff.csv", diff)
    write_mat("data/v7/market-conv.csv", conv)
    meta = {
        "pairs": pairs, "lot": spec["lot"], "slip": spec["slippage-pips-per-side"],
        "markup": spec["rollover-markup-pct"], "unit_pip": unit_pip,
        "spreads": spreads, "n": len(days), "from": days[0], "to": days[-1],
        "freeze-date": spec["freeze-date"], "asif-from": spec["asif-from"],
        "primary": spec["primary"], "control": spec["control"],
        "now-utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incomplete-dropped": True,
    }
    json.dump(meta, open("data/v7/market-meta.json", "w"), indent=1)
    print(f"MARKET_OK days={len(days)} from={days[0]} to={days[-1]} now={meta['now-utc']}", flush=True)


if __name__ == "__main__":
    main()
