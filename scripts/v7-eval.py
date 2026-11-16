#!/usr/bin/env python3
"""v7 Demo-recommendation rule, committed before any official paper day.

Official ledger only (kind=official). As-if replay and any day strictly
before freeze-date do not count. Primary sleeve is carry-eq-d1; the
control carry-vix-20-d1 is reported but cannot by itself justify Demo.

Calendar:
  freeze-date is the official start (first D1 close on or after it).
  Interim look: 3 full months later, descriptive only, cannot recommend.
  First Demo decision: 6 full months later AND at least 120 official days.
  Later reviews: every 3 months after that (9m, 12m, ...).

Gates, all required of the primary at 1x AND 2x costs:
  net P&L > 0
  t vs flat (daily Sharpe * sqrt(n)) >= 1.96
  deflated Sharpe (SR - SR0) > 0
  DSR >= 0.95
Trial count n and sr-var are the frozen v6 values (74 and the v6 panel
variance). carry-eq-d1 and carry-vix-20-d1 were already inside that 74;
using n=2 would understate selection. Frozen parameters must be
unchanged (script hashes match frozen/v7.sha256).

If any gate fails, or the review is not yet due: stay on paper, do not
change parameters, do not recommend Demo.
"""
import datetime as dt
from calendar import monthrange
import math
import statistics as st
from statistics import NormalDist

PRIMARY = "carry-eq-d1"
CONTROL = "carry-vix-20-d1"
INTERIM_MONTHS = 3
DECISION_MONTHS = 6
REVIEW_EVERY_MONTHS = 3
MIN_OFFICIAL_DAYS = 120
T_MIN = 1.96
DSR_MIN = 0.95


def add_months(d, n):
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, min(d.day, monthrange(y, m)[1]))


def sharpe(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return 0.0 if sd < 1e-12 else st.fmean(xs) / sd


def sr0(n, var):
    if n < 2 or var <= 0:
        return 0.0
    e = 0.5772156649015329
    z = NormalDist().inv_cdf
    return math.sqrt(var) * ((1 - e) * z(1 - 1 / n) + e * z(1 - 1 / (n * math.e)))


def dsr(xs, n, var):
    s = sharpe(xs)
    s0 = sr0(n, var)
    t = len(xs)
    if t < 2 or not any(abs(x) > 0 for x in xs):
        return {"sr-daily": s, "sr0": s0, "deflated": s - s0, "dsr": 0.0, "n": n,
                "t-vs-flat": 0.0}
    m = st.fmean(xs)
    sd = st.pstdev(xs) or 1e-12
    g3 = st.fmean([((x - m) / sd) ** 3 for x in xs])
    g4 = st.fmean([((x - m) / sd) ** 4 for x in xs])
    den = math.sqrt(max(1e-9, 1 - g3 * s + (g4 - 1) / 4 * s * s))
    return {"sr-daily": s, "sr0": s0, "deflated": s - s0,
            "dsr": NormalDist().cdf((s - s0) * math.sqrt(t - 1) / den), "n": n,
            "t-vs-flat": s * math.sqrt(t)}


def maxdd(xs):
    peak = cum = dd = 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def metrics(xs, trials):
    d = dsr(xs, trials["n"], trials["sr-var"])
    return {
        "sum": round(sum(xs), 2),
        "days": len(xs),
        "sharpe-ann": round(d["sr-daily"] * math.sqrt(252), 3),
        "t-vs-flat": round(d["t-vs-flat"], 2),
        "max-dd": round(maxdd(xs), 2),
        "dsr": round(d["dsr"], 3),
        "deflated": round(d["deflated"], 4),
        "sr-daily": round(d["sr-daily"], 6),
        "sr0": round(d["sr0"], 4),
    }


def review_dates(freeze):
    interim = add_months(freeze, INTERIM_MONTHS)
    first = add_months(freeze, DECISION_MONTHS)
    return {"interim": interim.isoformat(), "first-decision": first.isoformat(),
            "review-every-months": REVIEW_EVERY_MONTHS,
            "min-official-days": MIN_OFFICIAL_DAYS}


def decision_due(freeze, today, official_days):
    first = add_months(freeze, DECISION_MONTHS)
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    if today < first or official_days < MIN_OFFICIAL_DAYS:
        return False
    # due on first-decision and every 3 months thereafter
    cur = first
    while cur <= today:
        if cur == today or (cur <= today < add_months(cur, REVIEW_EVERY_MONTHS)
                            and today >= cur):
            # "due" once we have reached a review date; status may be
            # recomputed every day after first-decision, which is intended
            return True
        cur = add_months(cur, REVIEW_EVERY_MONTHS)
    return False


def gates(m):
    return {
        "net-pnl>0": m["sum"] > 0,
        "t-vs-flat>=1.96": m["t-vs-flat"] >= T_MIN,
        "deflated>0": m["deflated"] > 0,
        "dsr>=0.95": m["dsr"] >= DSR_MIN,
    }


def recommend(spec, official, today):
    """official: {('1', 'carry-eq-d1'): [daily pnl], ('2', ...): ...}"""
    freeze = spec["freeze-date"]
    cal = review_dates(freeze)
    xs1 = official.get(("1", PRIMARY), [])
    xs2 = official.get(("2", PRIMARY), [])
    due = decision_due(freeze, today, len(xs1))
    today_i = dt.date.fromisoformat(today) if isinstance(today, str) else today
    interim_due = today_i >= dt.date.fromisoformat(cal["interim"])
    m1 = metrics(xs1, spec["trials"]) if xs1 else None
    m2 = metrics(xs2, spec["trials"]) if xs2 else None
    g1 = gates(m1) if m1 else {}
    g2 = gates(m2) if m2 else {}
    ok = due and m1 and m2 and all(g1.values()) and all(g2.values())
    reason = []
    if not due:
        reason.append("formal Demo review is not yet due (need "
                      f"{cal['first-decision']} and {MIN_OFFICIAL_DAYS} official days)")
    if m1:
        reason.extend(f"1x {k}={v}" for k, v in g1.items() if not v)
    else:
        reason.append("no official 1x primary days")
    if m2:
        reason.extend(f"2x {k}={v}" for k, v in g2.items() if not v)
    else:
        reason.append("no official 2x primary days")
    return {
        "recommend-demo": bool(ok),
        "decision-due": due,
        "interim-look-due": interim_due and not due,
        "calendar": cal,
        "primary": PRIMARY,
        "control": CONTROL,
        "gates-1x": g1, "gates-2x": g2,
        "metrics-1x": m1, "metrics-2x": m2,
        "reason": "pass" if ok else "; ".join(reason),
        "note": "control is reported separately and cannot by itself justify Demo; "
                "as-if and pre-freeze days are excluded",
    }


if __name__ == "__main__":
    print("v7-eval is a library used by scripts/v7-book.py")
