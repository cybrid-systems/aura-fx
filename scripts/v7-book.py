#!/usr/bin/env python3
"""Book v7 paper fills from Aura positions and write the ledger + status.

Official days are D1 closes on or after freeze-date. Incoming position
on the first official day is flat (no pre-freeze hold is inherited).
As-if replay (asif-from .. day before freeze-date) is written to a
separate file and labelled REFERENCE ONLY. Re-running recomputes the
whole official series (idempotent).
"""
import csv, datetime as dt, json, os, sys
import numpy as np
sys.path.insert(0, "scripts")
from importlib.machinery import SourceFileLoader
ev = SourceFileLoader("v7eval", "scripts/v7-eval.py").load_module()


LEDGER = "paper/v7-ledger.csv"
ASIF = "paper/v7-asif-ledger.csv"
STATUS = "paper/v7-status.json"
POS = "out/v7/positions.csv"
MONITOR = "out/v7/monitor.json"
COLS = ["day", "kind", "costmult", "config", "net", "gross", "cost", "rollover",
        "entries", "nav"]


def load_positions(path, pairs):
    rows = list(csv.DictReader(open(path)))
    days = [r["day"] for r in rows]
    out = {"carry-eq-d1": np.zeros((len(days), len(pairs))),
           "carry-vix-20-d1": np.zeros((len(days), len(pairs)))}
    for i, r in enumerate(rows):
        for cfg in out:
            for j, p in enumerate(pairs):
                out[cfg][i, j] = float(r[f"{cfg}|{p}"])
    return days, out


def load_market():
    meta = json.load(open("data/v7/market-meta.json"))
    pairs = meta["pairs"]
    days, close, diff, conv, nights = [], [], [], [], []
    day_rows = {r["day"]: r for r in csv.DictReader(open("data/v7/market-day.csv"))}
    closes = list(csv.DictReader(open("data/v7/market-close.csv")))
    diffs = list(csv.DictReader(open("data/v7/market-diff.csv")))
    convs = list(csv.DictReader(open("data/v7/market-conv.csv")))
    assert [r["day"] for r in closes] == [r["day"] for r in diffs] == [r["day"] for r in convs]
    for r, d, c in zip(closes, diffs, convs):
        day = r["day"]
        days.append(day)
        close.append([float(r[p]) for p in pairs])
        diff.append([float(d[p]) for p in pairs])
        conv.append([float(c[p]) for p in pairs])
        nights.append(float(day_rows[day]["nights"]))
    return meta, pairs, days, np.array(close), np.array(diff), np.array(conv), np.array(nights)


def book_segment(pos, C, conv, diff, nights, unit_pip, lot, markup, cm, start_held=None):
    """pos[i] decided at close i, held over i+1. start_held is incoming
    position before the first row (official start is flat)."""
    n, m = pos.shape
    if start_held is None:
        held = np.vstack([np.zeros((1, m)), pos[:-1]])
    else:
        held = np.vstack([np.asarray(start_held, float).reshape(1, m), pos[:-1]])
    dc = np.diff(C, axis=0, prepend=C[:1])
    # The first row's dc would be vs a prepended close we do not want if
    # held is flat: gross is held*dc, and held[0]=0, so first gross is 0
    # regardless of prepend. Good.
    gross_q = held * dc
    dp = np.abs(pos - held)
    cost_q = dp * (unit_pip * cm)
    carry_q = (pos * diff - np.abs(pos) * markup) / 100.0 / 360.0 * C * nights[:, None]
    g = (gross_q * lot * conv).sum(axis=1)
    co = (cost_q * lot * conv).sum(axis=1)
    ca = (carry_q * lot * conv).sum(axis=1)
    entries = ((pos != 0) & (held != pos)).sum(axis=1)
    net = g - co + ca
    return net, g, co, ca, entries, pos


def write_ledger(path, rows, pairs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    extra = [f"pos.{p}" for p in pairs]
    with open(path, "w") as f:
        f.write(",".join(COLS + extra) + "\n")
        for r in rows:
            f.write(",".join(r) + "\n")


def rows_for(days, kind, cm, cfg, net, g, co, ca, en, pos, pairs):
    nav = 0.0
    out = []
    for i, d in enumerate(days):
        nav += float(net[i])
        rec = [d, kind, str(int(cm) if cm == int(cm) else cm), cfg,
               f"{net[i]:.4f}", f"{g[i]:.4f}", f"{co[i]:.4f}", f"{ca[i]:.4f}",
               str(int(en[i])), f"{nav:.4f}"]
        rec += [f"{pos[i, j]:.4f}" for j in range(len(pairs))]
        out.append(rec)
    return out


def latest_pos(days, pos, pairs, day):
    if day not in days:
        return {}
    i = days.index(day)
    return {p: float(pos[i, j]) for j, p in enumerate(pairs)}


def main():
    spec = json.load(open("frozen/v7.json"))
    meta, pairs, days, C, diff, conv, nights = load_market()
    pos_days, posmap = load_positions(POS, pairs)
    if pos_days != days:
        sys.exit(f"Aura positions days mismatch market: {pos_days[0] if pos_days else None}.. vs {days[0]}..")
    unit = np.array(meta["unit_pip"])
    lot, markup = spec["lot"], spec["rollover-markup-pct"]
    freeze, asif_from = spec["freeze-date"], spec["asif-from"]
    official_idx = [i for i, d in enumerate(days) if d >= freeze]
    asif_idx = [i for i, d in enumerate(days) if asif_from <= d < freeze]

    official_rows = []
    asif_rows = []
    official_pnl = {}
    asif_pnl = {}
    for cfg, pos in posmap.items():
        for cm in (1, 2):
            if official_idx:
                sl = slice(official_idx[0], official_idx[-1] + 1)
                net, g, co, ca, en, p = book_segment(
                    pos[sl], C[sl], conv[sl], diff[sl], nights[sl],
                    unit, lot, markup, cm, start_held=np.zeros(len(pairs)))
                official_pnl[(str(cm), cfg)] = list(map(float, net))
                official_rows += rows_for([days[i] for i in official_idx], "official",
                                          cm, cfg, net, g, co, ca, en, p, pairs)
            if asif_idx:
                sl = slice(asif_idx[0], asif_idx[-1] + 1)
                net, g, co, ca, en, p = book_segment(
                    pos[sl], C[sl], conv[sl], diff[sl], nights[sl],
                    unit, lot, markup, cm, start_held=np.zeros(len(pairs)))
                asif_pnl[(str(cm), cfg)] = list(map(float, net))
                asif_rows += rows_for([days[i] for i in asif_idx], "as-if-reference",
                                      cm, cfg, net, g, co, ca, en, p, pairs)

    # stable order: day, costmult, config
    def key(r):
        return (r[0], r[2], r[3])
    official_rows.sort(key=key)
    asif_rows.sort(key=key)
    write_ledger(LEDGER, official_rows, pairs)
    write_ledger(ASIF, asif_rows, pairs)

    mon = json.load(open(MONITOR)) if os.path.exists(MONITOR) else {
        "alarm": False, "days": 0, "reason": "monitor not run yet", "action": "alert-only"}
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    rec = ev.recommend(spec, official_pnl, today)
    last = days[-1]
    preview = {cfg: latest_pos(days, posmap[cfg], pairs, last) for cfg in posmap}
    tz = dt.datetime.now(dt.timezone.utc).astimezone()
    # Asia/Shanghai label for generated-at
    shanghai = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    status = {
        "version": "frozen-v7",
        "generated-at": shanghai.strftime("%Y-%m-%dT%H:%M:%S+08:00") + " (Asia/Shanghai)",
        "now-utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "freeze-date": freeze,
        "asif-from": asif_from,
        "latest-complete-day": last,
        "official-days": len(official_idx),
        "awaiting-official": len(official_idx) == 0,
        "note": ("最新完整交易日在冻结日之前，官方账本尚无记录。冻结日前的 as-if 回放仅供参考，不计入纸面成绩。"
                 if not official_idx else
                 "官方纸面成绩只含冻结日当天及之后的完整 D1；as-if 回放仅供参考，不计入成绩，也不用于 Demo 建议。"),
        "primary": spec["primary"],
        "control": spec["control"],
        "official": {
            "1x": {cfg: ev.metrics(official_pnl.get(("1", cfg), []), spec["trials"])
                   for cfg in posmap} if official_idx else None,
            "2x": {cfg: ev.metrics(official_pnl.get(("2", cfg), []), spec["trials"])
                   for cfg in posmap} if official_idx else None,
            "flat": ev.metrics([0.0] * len(official_idx), spec["trials"]) if official_idx else None,
        },
        "as-if-reference": {
            "label": "REFERENCE ONLY, not used for Demo decision or official paper performance",
            "from": days[asif_idx[0]] if asif_idx else None,
            "to": days[asif_idx[-1]] if asif_idx else None,
            "days": len(asif_idx),
            "1x": {cfg: ev.metrics(asif_pnl.get(("1", cfg), []), spec["trials"])
                   for cfg in posmap} if asif_idx else None,
            "2x": {cfg: ev.metrics(asif_pnl.get(("2", cfg), []), spec["trials"])
                   for cfg in posmap} if asif_idx else None,
        },
        "positions-preview": {"day": last, "note": "decided at this close; official book inherits them only if the day is on or after freeze-date",
                              "positions": preview},
        "drift": mon,
        "eval": rec,
        "aura": spec.get("aura"),
        "basket": pairs,
    }
    json.dump(status, open(STATUS, "w"), indent=1, ensure_ascii=False)
    print(f"BOOK_OK official-days={len(official_idx)} last={last} as-if-days={len(asif_idx)} "
          f"awaiting={status['awaiting-official']} drift={mon.get('alarm')} "
          f"recommend-demo={rec['recommend-demo']}", flush=True)


if __name__ == "__main__":
    main()
