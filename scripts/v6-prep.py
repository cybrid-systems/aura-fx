#!/usr/bin/env python3
"""v6 column precompute: carry + cross-section on a currency basket.

usage: v6-prep.py OUT RATES.csv VIX.csv [--data TAG] [--costmult K] [--helper-dir DIR] PAIR...

Reads data/v6/<pair.lower()>-<TAG>-h4.csv and -d1.csv (TAG defaults to
OUT). Helper D1 closes in --helper-dir (and data/v6, data/v4, data/v3)
are used only to convert a non-USD quote into USD (previous day's
close); they are not traded.

26 committed configs, all basket-level (one daily P&L column each):

  carry-eq-{d1,h4}       equal-weight: long the top half of pairs by
                         i_base - i_quote, short the bottom half
  carry-z-{d1,h4}        dollar-neutral z-score weights, same gross
  carry-vol-{d1,h4}      eq-carry, flatten a pair if its 21-day vol
                         exceeds 1.5x its 252-day median of 21-day vol
  carry-mom63-{d1,h4}    eq-carry, keep a pair only if its 63-day return
                         agrees with the carry sign
  carry-mom252-{d1,h4}   same with 252-day momentum
  xsmom-{21,63}-{d1,h4}  cross-sectional momentum, top/bottom half
  xsmom-{126,252}-d1     longer lookbacks, daily only
  usd-tsmom-{63,252}-d1  time-series momentum of the basket dollar
                         factor (equal-weight, + = USD up)
  resid-mom-{63,252}-d1  cross-sectional momentum of dollar-residual
                         returns
  resid-mr-{60,120}-d1   fade the residual vs the dollar index when
                         |z| > 1.0 (60d) or 1.5 (120d)
  carry-vix-med-d1       eq-carry when previous VIX < 1y median, else flat
  carry-vix-20-d1        eq-carry when previous VIX < 20, else flat
  carry-vix-rev-d1       eq-carry when previous VIX < 1y median, else reverse
  v5fixed-h4-mr5d-1.0    v5's best fixed rule (H4 mean-reversion, 5-day
                         lookback, theta 1.0) on each pair, P&L summed

Costs per unit traded: half the published spread + 0.2 pip slippage.
Rollover on the last bar of each trading day (22:00 UTC, weekends to
Monday): (policy-rate difference of the *previous* month, minus 1% p.a.
markup) / 360, 3 nights on Wednesday. Public swap-point series were not
found, so the interest differential is the approximation; this is
stated, not measured. Lot = 10,000 base units. P&L is converted to USD
with the previous day's quote-to-USD close. Positions decided at a
bar's close are held over the next bar (no look-ahead). VIX used on
day t is the last close strictly before t.

Writes data/v6/<OUT>-net.csv, -pos.csv, -unit.csv, -parts.json.
"""
import argparse, datetime as dt, json, os, sys
import numpy as np, pandas as pd

LOT, SLIP, MARKUP = 10000, 0.2, 1.0
AREA = {"EUR": "XM", "USD": "US", "GBP": "GB", "JPY": "JP", "AUD": "AU",
        "NZD": "NZ", "CAD": "CA", "CHF": "CH", "NOK": "NO", "SEK": "SE",
        "MXN": "MX", "ZAR": "ZA"}
# FXCM published typical spreads, FXCM Malaysia "Kos Sebaran" page,
# last updated June 2024 (EUR/USD 1.3 matches the v5 Standard-account
# anchor). Published, not measured.
SPREAD = {
    "EURUSD": 1.3, "GBPUSD": 1.7, "USDJPY": 1.4, "AUDUSD": 1.8,
    "NZDUSD": 2.0, "USDCAD": 2.2, "USDCHF": 1.6,
    "AUDJPY": 2.1, "GBPJPY": 2.7, "EURAUD": 2.5, "EURCAD": 2.9,
    "USDNOK": 45.6, "USDSEK": 39.1, "USDMXN": 48.2, "USDZAR": 91.5,
}
SLEEVES = ("carry-eq-d1", "xsmom-63-d1", "resid-mr-60-d1", "usd-tsmom-63-d1")

CONFIGS = [
    ("carry-eq-d1",        "carry-eq",    "d1", {}),
    ("carry-eq-h4",        "carry-eq",    "h4", {}),
    ("carry-z-d1",         "carry-z",     "d1", {}),
    ("carry-z-h4",         "carry-z",     "h4", {}),
    ("carry-vol-d1",       "carry-vol",   "d1", {"mult": 1.5}),
    ("carry-vol-h4",       "carry-vol",   "h4", {"mult": 1.5}),
    ("carry-mom63-d1",     "carry-mom",   "d1", {"L": 63}),
    ("carry-mom63-h4",     "carry-mom",   "h4", {"L": 63}),
    ("carry-mom252-d1",    "carry-mom",   "d1", {"L": 252}),
    ("carry-mom252-h4",    "carry-mom",   "h4", {"L": 252}),
    ("xsmom-21-d1",        "xsmom",       "d1", {"L": 21}),
    ("xsmom-21-h4",        "xsmom",       "h4", {"L": 21}),
    ("xsmom-63-d1",        "xsmom",       "d1", {"L": 63}),
    ("xsmom-63-h4",        "xsmom",       "h4", {"L": 63}),
    ("xsmom-126-d1",       "xsmom",       "d1", {"L": 126}),
    ("xsmom-252-d1",       "xsmom",       "d1", {"L": 252}),
    ("usd-tsmom-63-d1",    "usd-tsmom",   "d1", {"L": 63}),
    ("usd-tsmom-252-d1",   "usd-tsmom",   "d1", {"L": 252}),
    ("resid-mom-63-d1",    "resid-mom",   "d1", {"L": 63}),
    ("resid-mom-252-d1",   "resid-mom",   "d1", {"L": 252}),
    ("resid-mr-60-d1",     "resid-mr",    "d1", {"L": 60, "th": 1.0}),
    ("resid-mr-120-d1",    "resid-mr",    "d1", {"L": 120, "th": 1.5}),
    ("carry-vix-med-d1",   "carry-vix",   "d1", {"mode": "med"}),
    ("carry-vix-20-d1",    "carry-vix",   "d1", {"mode": "20"}),
    ("carry-vix-rev-d1",   "carry-vix",   "d1", {"mode": "rev"}),
    ("v5fixed-h4-mr5d-1.0","v5fixed",    "h4", {"L": 30, "th": 1.0, "hl": 6}),
]


def rank_pos(sig):
    """Long top half, short bottom half among finite values; odd middle is flat."""
    p = np.zeros(len(sig))
    ok = np.isfinite(sig)
    n = int(ok.sum())
    if n < 2:
        return p
    idx = np.where(ok)[0]
    order = idx[np.argsort(sig[idx])]
    k = n // 2
    p[order[:k]] = -1.0
    p[order[-k:]] = 1.0
    return p


def z_pos(sig):
    """Dollar-neutral z-weights, scaled so gross matches rank_pos."""
    p = np.zeros(len(sig))
    ok = np.isfinite(sig)
    n = int(ok.sum())
    if n < 2:
        return p
    x = sig[ok]
    sd = x.std()
    z = (x - x.mean()) / sd if sd > 1e-12 else np.zeros(n)
    z = z - z.mean()
    target = 2 * (n // 2)
    s = np.abs(z).sum()
    if s < 1e-12:
        return p
    p[ok] = z * (target / s)
    return p


def usd_sign(pair):
    """+1 if a rising pair is USD up (USDXXX), -1 if XXXUSD."""
    return 1.0 if pair.startswith("USD") else -1.0 if pair.endswith("USD") else 0.0


def pip_size(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


def prev_month(d):
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return f"{y}-{m:02d}"


def find_d1(pair, tag, helper_dir):
    candidates = [
        f"data/v6/{pair.lower()}-{tag}-d1.csv",
        f"data/v6/{pair.lower()}-train-d1.csv",
        f"data/v6/{pair.lower()}-final-d1.csv",
    ]
    dirs = [helper_dir, "data/v6", "data/v4", "data/v3"]
    for d in dirs:
        if not d:
            continue
        candidates += [
            os.path.join(d, f"{pair.lower()}-{s}-d1.csv")
            for s in ("train", "final", tag)
        ]
        candidates += [
            os.path.join(d, f"{pair.lower()}-train-d1.csv"),
            os.path.join(d, f"{pair.lower()}-final-d1.csv"),
            os.path.join(d, f"ref-{pair.lower()}.csv"),
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def quote_usd_map(pair, tag, helper_dir, own_d1):
    """day -> quote-to-USD close (used as the previous day's value later)."""
    base, quote = pair[:3], pair[3:]
    if quote == "USD":
        return None
    raw = {}
    if base == "USD":
        for _, r in own_d1.iterrows():
            raw[r["day"]] = 1.0 / float(r["close"])
        return raw
    for helper, invert in ((f"USD{quote}", True), (f"{quote}USD", False)):
        path = find_d1(helper, tag, helper_dir)
        if path:
            df = pd.read_csv(path)
            for _, r in df.iterrows():
                c = float(r["close"])
                raw[r["day"]] = (1.0 / c) if invert else c
            return raw
    raise SystemExit(f"{pair}: no quote-to-USD series for {quote} (looked for USD{quote} / {quote}USD)")


def align_prev(raw, days):
    """For each trading day, the last available value strictly before that day."""
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


def xs_apply(sig_row, kind, retL=None, vol_ratio=None, vix_ok=None, vix_mode=None):
    n = len(sig_row)
    if kind in ("carry-eq", "xsmom", "resid-mom"):
        p = rank_pos(sig_row)
    elif kind == "carry-z":
        p = z_pos(sig_row)
    else:
        p = rank_pos(sig_row)
    if kind == "carry-vol" and vol_ratio is not None:
        p = np.where(vol_ratio > 1.0, 0.0, p)
    if kind == "carry-mom" and retL is not None:
        p = np.where(p * retL > 0, p, 0.0)
    if kind.startswith("carry-vix") or vix_mode:
        if vix_ok is False:
            p = (-p) if vix_mode == "rev" else np.zeros(n)
    return p


def positions_for_config(cfg, pack):
    name, kind, freq, params = cfg
    if freq == "d1":
        C, carry = pack["C"], pack["carry"]
        vix, vix_med = pack["vix"], pack["vix_med"]
        n, m = C.shape
        pos = np.zeros((n, m))
        L = int(params.get("L", 63))
        for i in range(n):
            if i < 2:
                continue
            if kind in ("carry-eq", "carry-z", "carry-vol", "carry-mom", "carry-vix"):
                sig = carry[i]
                vol_ratio = retL = None
                vix_ok = None
                vix_mode = params.get("mode")
                if kind == "carry-vol":
                    if i < 252:
                        continue
                    vol_ratio = pack["vol_ratio"][i]
                if kind == "carry-mom":
                    if i < L:
                        continue
                    retL = C[i] / C[i - L] - 1.0
                if kind == "carry-vix":
                    if not np.isfinite(vix[i]):
                        continue
                    if vix_mode == "20":
                        vix_ok = vix[i] < 20.0
                    else:
                        if not np.isfinite(vix_med[i]):
                            continue
                        vix_ok = vix[i] < vix_med[i]
                pos[i] = xs_apply(sig, kind, vol_ratio=vol_ratio, retL=retL,
                                  vix_ok=vix_ok, vix_mode=vix_mode)
            elif kind == "xsmom":
                if i < L:
                    continue
                pos[i] = rank_pos(C[i] / C[i - L] - 1.0)
            elif kind == "usd-tsmom":
                if i < L:
                    continue
                mom = pack["dollar_cum"][i] - pack["dollar_cum"][i - L]
                signs = pack["usd_signs"]
                pos[i] = np.where(signs == 0, 0.0, signs if mom > 0 else -signs)
            elif kind == "resid-mom":
                if i < L:
                    continue
                mom = pack["resid_cum"][i] - pack["resid_cum"][i - L]
                pos[i] = rank_pos(mom)
            elif kind == "resid-mr":
                if i < L:
                    continue
                th = params["th"]
                window = pack["resid_cum"][i - L + 1:i + 1]
                mu = window.mean(axis=0)
                sd = window.std(axis=0)
                z = np.where(sd > 1e-12, (pack["resid_cum"][i] - mu) / sd, 0.0)
                p = np.zeros(m)
                p[z > th] = -1.0
                p[z < -th] = 1.0
                pos[i] = p
        return pos
    return positions_h4(cfg, pack)


def positions_h4(cfg, pack):
    name, kind, freq, params = cfg
    C, days4 = pack["C4"], pack["days4"]
    carry4 = pack["carry4"]
    n, m = C.shape
    pos = np.zeros((n, m))
    L = int(params.get("L", 63))
    if kind == "v5fixed":
        Lh, th, hl = params["L"], params["th"], params["hl"]
        lc = np.log(C)
        lr = np.diff(lc, axis=0, prepend=lc[:1])
        alpha = 1.0 - np.exp(np.log(0.5) / hl)
        vol = np.full_like(C, np.nan)
        for j in range(m):
            v = 0.0
            started = False
            for i in range(n):
                a = abs(lr[i, j])
                if not started:
                    if i >= hl:
                        v = np.mean(np.abs(lr[i - hl + 1:i + 1, j]))
                        started = True
                    else:
                        continue
                else:
                    v = alpha * a + (1 - alpha) * v
                vol[i, j] = v if v > 0 else np.nan
        out = np.zeros((n, m))
        for j in range(m):
            cur = 0
            for i in range(n):
                if i < Lh or not np.isfinite(vol[i, j]):
                    out[i, j] = cur
                    continue
                s = -(lc[i, j] - lc[i - Lh + 1:i + 1, j].mean()) / (vol[i, j] * np.sqrt(Lh))
                if s > th:
                    cur = 1
                elif s < -th:
                    cur = -1
                elif cur * s < 0:
                    cur = 0
                out[i, j] = cur
        return out

    def bars_ago(i, Ldays):
        d = days4[i]
        di = pack["day_to_i"][d]
        if di < Ldays:
            return None
        target = pack["days"][di - Ldays]
        return pack["day_last_bar"][target]

    for i in range(n):
        d = days4[i]
        di = pack["day_to_i"].get(d)
        if di is None or di < 2:
            continue
        if kind in ("carry-eq", "carry-z", "carry-vol", "carry-mom"):
            sig = carry4[i]
            vol_ratio = retL = None
            if kind == "carry-vol":
                if bars_ago(i, 252) is None:
                    continue
                vol_ratio = pack["vol_ratio4"][i]
            if kind == "carry-mom":
                j0 = bars_ago(i, L)
                if j0 is None:
                    continue
                retL = C[i] / C[j0] - 1.0
            pos[i] = xs_apply(sig, kind, vol_ratio=vol_ratio, retL=retL)
        elif kind == "xsmom":
            j0 = bars_ago(i, L)
            if j0 is None:
                continue
            pos[i] = rank_pos(C[i] / C[j0] - 1.0)
        else:
            raise SystemExit(f"h4 not implemented for {kind}")
    return pos


def book(pos, pack, freq, cm):
    """Book daily net P&L (USD), eod positions, and year parts.

    pos[i] is the position decided at the close of bar i, held over bar i+1.
    """
    if freq == "d1":
        C, days = pack["C"], pack["days"]
        conv, nights, diff = pack["conv"], pack["nights"], pack["diff"]
        unit_pip = pack["unit_pip"]
        n, m = C.shape
        held = np.vstack([np.zeros((1, m)), pos[:-1]])
        dc = np.diff(C, axis=0, prepend=C[:1])
        gross_q = held * dc
        dp = np.abs(np.diff(pos, axis=0, prepend=np.zeros((1, m))))
        cost_q = dp * (unit_pip * cm)
        carry_q = (pos * diff - np.abs(pos) * MARKUP) / 100.0 / 360.0 * C * nights[:, None]
        g = (gross_q * LOT * conv).sum(axis=1)
        co = (cost_q * LOT * conv).sum(axis=1)
        ca = (carry_q * LOT * conv).sum(axis=1)
        entries = ((pos != 0) & (held != pos)).sum(axis=1)
        return g - co + ca, pos, g, co, ca, entries, days
    C, days4 = pack["C4"], pack["days4"]
    conv4, unit_pip = pack["conv4"], pack["unit_pip"]
    n, m = C.shape
    held = np.vstack([np.zeros((1, m)), pos[:-1]])
    dc = np.diff(C, axis=0, prepend=C[:1])
    gross_q = held * dc
    dp = np.abs(np.diff(pos, axis=0, prepend=np.zeros((1, m))))
    cost_q = dp * (unit_pip * cm)
    last = pack["is_last_bar"]
    nights4, diff4 = pack["nights4"], pack["diff4"]
    carry_q = np.where(last[:, None],
                       (pos * diff4 - np.abs(pos) * MARKUP) / 100.0 / 360.0 * C * nights4[:, None],
                       0.0)
    g_b = gross_q * LOT * conv4
    co_b = cost_q * LOT * conv4
    ca_b = carry_q * LOT * conv4
    ent_b = ((pos != 0) & (held != pos)).astype(float)
    days = pack["days"]
    di = pack["bar_to_day"]
    nd = len(days)
    g = np.bincount(di, g_b.sum(axis=1), nd)
    co = np.bincount(di, co_b.sum(axis=1), nd)
    ca = np.bincount(di, ca_b.sum(axis=1), nd)
    ent = np.bincount(di, ent_b.sum(axis=1), nd)
    eod = np.zeros((nd, m))
    eod[di] = pos
    return g - co + ca, eod, g, co, ca, ent, days


def build_pack(pairs, tag, rates_csv, vix_csv, helper_dir, cm):
    d1s = {p: pd.read_csv(f"data/v6/{p.lower()}-{tag}-d1.csv") for p in pairs}
    h4s = {p: pd.read_csv(f"data/v6/{p.lower()}-{tag}-h4.csv") for p in pairs}
    days = sorted(set.intersection(*[set(d1s[p]["day"]) for p in pairs]))
    h4_times = sorted(set.intersection(*[set(h4s[p]["time_utc"]) for p in pairs]))
    if len(days) < 400 or len(h4_times) < 1000:
        raise SystemExit(f"alignment too short: days={len(days)} h4={len(h4_times)}")
    m = len(pairs)
    C = np.column_stack([d1s[p].set_index("day").loc[days, "close"].to_numpy(float) for p in pairs])
    C4 = np.column_stack([h4s[p].set_index("time_utc").loc[h4_times, "close"].to_numpy(float) for p in pairs])
    day_of = {p: dict(zip(h4s[p]["time_utc"], h4s[p]["day"])) for p in pairs}
    days4 = [day_of[pairs[0]][t] for t in h4_times]

    day_dates = [dt.date.fromisoformat(d) for d in days]
    rates = {r["month"]: r for _, r in pd.read_csv(rates_csv, dtype=str).iterrows()}

    def rate_diff(d, p):
        row = rates[prev_month(d)]
        b, q = p[:3], p[3:]
        return float(row[AREA[b]]) - float(row[AREA[q]])

    diff = np.array([[rate_diff(d, p) for p in pairs] for d in day_dates])
    nights = np.array([3 if d.weekday() == 2 else 1 for d in day_dates])
    carry = diff.copy()

    conv = np.ones((len(days), m))
    raw_maps = [quote_usd_map(p, tag, helper_dir, d1s[p]) for p in pairs]
    for j, p in enumerate(pairs):
        if raw_maps[j] is None:
            conv[:, j] = 1.0
        else:
            conv[:, j] = align_prev(raw_maps[j], days)
            # Leading NaNs (no previous close yet) back-fill from the first
            # available close; this only affects warmup days before 2016-07-01.
            if np.isnan(conv[:, j]).any():
                conv[:, j] = pd.Series(conv[:, j]).bfill().to_numpy()
                if np.isnan(conv[:, j]).any():
                    raise SystemExit(f"{p}: quote-to-USD missing")

    vf = pd.read_csv(vix_csv)
    vix_raw = dict(zip(vf["day"], vf["vix"].astype(float)))
    vix = align_prev(vix_raw, days)
    vix_med = pd.Series(vix).rolling(252, min_periods=252).median().to_numpy()

    R = np.zeros_like(C)
    R[1:] = C[1:] / C[:-1] - 1.0
    usd_signs = np.array([usd_sign(p) for p in pairs])
    n_usd = max(int((usd_signs != 0).sum()), 1)
    dollar_r = (R * usd_signs).sum(axis=1) / n_usd
    dollar_cum = np.cumsum(dollar_r)
    resid_r = R - usd_signs[None, :] * dollar_r[:, None]
    resid_cum = np.cumsum(resid_r, axis=0)

    vol21 = pd.DataFrame(R).rolling(21, min_periods=21).std().to_numpy()
    vol_med = pd.DataFrame(vol21).rolling(252, min_periods=252).median().to_numpy()
    vol_ratio = np.where(vol_med > 0, vol21 / (1.5 * vol_med), np.nan)

    unit_pip = np.array([(SPREAD[p] / 2 + SLIP) * pip_size(p) for p in pairs])

    day_to_i = {d: i for i, d in enumerate(days)}
    keep4 = [i for i, d in enumerate(days4) if d in day_to_i]
    if len(keep4) != len(days4):
        C4 = C4[keep4]
        days4 = [days4[i] for i in keep4]
        h4_times = [h4_times[i] for i in keep4]
    bar_to_day = np.array([day_to_i[d] for d in days4])
    is_last = np.r_[bar_to_day[1:] != bar_to_day[:-1], True]
    day_last_bar = {}
    for i, d in enumerate(days4):
        day_last_bar[d] = i
    nights4 = nights[bar_to_day]
    diff4 = diff[bar_to_day]
    conv4 = conv[bar_to_day]
    carry4 = carry[bar_to_day]
    vol_ratio4 = np.full((len(h4_times), m), np.nan)
    for i, d in enumerate(days4):
        di = day_to_i[d]
        if di >= 1:
            vol_ratio4[i] = vol_ratio[di - 1]

    return dict(days=days, C=C, R=R, carry=carry, vix=vix, vix_med=vix_med,
                dollar_r=dollar_r, dollar_cum=dollar_cum, resid_r=resid_r,
                resid_cum=resid_cum, usd_signs=usd_signs, vol_ratio=vol_ratio,
                conv=conv, nights=nights, diff=diff, unit_pip=unit_pip,
                C4=C4, days4=days4, h4_times=h4_times, carry4=carry4,
                day_to_i=day_to_i, bar_to_day=bar_to_day, is_last_bar=is_last,
                day_last_bar=day_last_bar, nights4=nights4, diff4=diff4,
                conv4=conv4, vol_ratio4=vol_ratio4, pairs=pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("rates")
    ap.add_argument("vix")
    ap.add_argument("pairs", nargs="+")
    ap.add_argument("--data", default=None)
    ap.add_argument("--costmult", type=float, default=1.0)
    ap.add_argument("--helper-dir", default=None)
    args = ap.parse_args()
    tag = args.data or args.out
    pairs = [p.upper().replace("/", "") for p in args.pairs]
    for p in pairs:
        if p not in SPREAD:
            sys.exit(f"no published spread for {p}")
        if p[:3] not in AREA or p[3:] not in AREA:
            sys.exit(f"no policy-rate area for {p}")
    pack = build_pack(pairs, tag, args.rates, args.vix, args.helper_dir, args.costmult)
    days = pack["days"]
    nd, m = len(days), len(pairs)
    net = np.zeros((nd, len(CONFIGS)))
    eod = np.zeros((nd, len(CONFIGS), m))
    parts = {}
    years = np.array([int(d[:4]) for d in days])
    for k, cfg in enumerate(CONFIGS):
        pos = positions_for_config(cfg, pack)
        n, e, g, co, ca, en, ds = book(pos, pack, cfg[2], args.costmult)
        assert list(ds) == list(days)
        net[:, k] = n
        eod[:, k, :] = e
        parts[cfg[0]] = {str(y): [round(float(g[years == y].sum()), 2),
                                  round(float(co[years == y].sum()), 2),
                                  round(float(ca[years == y].sum()), 2),
                                  int(en[years == y].sum())]
                         for y in np.unique(years)}
        print(f"CONFIG {cfg[0]} sum={n.sum():.1f}", flush=True)

    names = [c[0] for c in CONFIGS]
    os.makedirs("data/v6", exist_ok=True)
    stem = f"data/v6/{args.out}"
    with open(stem + "-net.csv", "w") as f:
        f.write("day," + ",".join(names) + "\n")
        for i, d in enumerate(days):
            f.write(d + "," + ",".join(f"{x:.4f}" for x in net[i]) + "\n")
    with open(stem + "-pos.csv", "w") as f:
        cols = [f"{c}|{p}" for c in names for p in pairs]
        f.write("day," + ",".join(cols) + "\n")
        for i, d in enumerate(days):
            vals = [eod[i, k, j] for k in range(len(CONFIGS)) for j in range(m)]
            f.write(d + "," + ",".join(f"{x:.4f}" for x in vals) + "\n")
    unit = pack["unit_pip"][None, :] * args.costmult * LOT * pack["conv"]
    with open(stem + "-unit.csv", "w") as f:
        f.write("day," + ",".join(pairs) + "\n")
        for i, d in enumerate(days):
            f.write(d + "," + ",".join(f"{x:.6f}" for x in unit[i]) + "\n")
    meta = {
        "pairs": pairs, "costmult": args.costmult, "lot": LOT, "slip": SLIP,
        "markup": MARKUP, "spreads": {p: SPREAD[p] for p in pairs},
        "parts-format": "year: [gross, cost, rollover, entries]",
        "sleeves": list(SLEEVES),
        "configs": parts,
        "days": {"n": nd, "from": days[0], "to": days[-1]},
        "spread-basis": "FXCM published typical spreads, FXCM Malaysia Kos Sebaran page, last updated June 2024; published, not measured",
        "rollover": "policy-rate difference (BIS WS_CBPOL, previous month) minus 1% p.a. markup, /360, 3 nights on Wednesday; swap points approximated, not measured",
    }
    json.dump(meta, open(stem + "-parts.json", "w"), indent=1)
    print(f"PREP_OK {stem} days={nd} from={days[0]} to={days[-1]} configs={len(CONFIGS)} pairs={','.join(pairs)}", flush=True)


if __name__ == "__main__":
    main()
