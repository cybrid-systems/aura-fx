#!/usr/bin/env python3
"""Broker side of the Aura order pipe.

paper  replays out/session.json with the same fill rule as lib/book.aura.
       Aura's pnl and this pnl have to match or the pipe is not connected.
probe  says whether a ForexConnect Demo login can run in this process.
login  reads the Demo balance and the EUR/USD quote. It sends no orders.
live   sends TRUE_MARKET_OPEN orders. It does not run unless FXCM_LIVE=1,
       and this tree does not call it.

The intent fields match ForexConnect create_order_request:
  order_type OM, buy_sell B|S, amount in base units, rate is the decision mid.
  Live resolves the instrument to SYMBOL via Common.get_offer. Amount is
  already in base units. Do not multiply by base_unit_size again.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def demo_only():
    connection = os.environ.get("FXCM_CONNECTION", "Demo")
    if connection.lower() == "real":
        print("blocked: this tree refuses a Real connection")
        return None
    return connection


def apply_fill(pos, avg, realized, q, price):
    if q == 0:
        return pos, avg, realized
    same = pos == 0 or (q > 0) == (pos > 0)
    if same:
        newpos = pos + q
        avg = (avg * pos + price * q) / newpos
        return newpos, avg, realized
    closing = min(abs(q), abs(pos))
    if pos > 0:
        realized += (price - avg) * closing
    else:
        realized += (avg - price) * closing
    newpos = pos + q
    if newpos == 0:
        return 0.0, 0.0, realized
    if (pos > 0) == (newpos > 0):
        return newpos, avg, realized
    return newpos, price, realized


def mark_pnl(realized, pos, avg, mid):
    if pos == 0:
        return realized
    if pos > 0:
        return realized + (mid - avg) * pos
    return realized + (avg - mid) * abs(pos)


def replay(session):
    half = float(session["half-spread"])
    mark = float(session["mark"])
    pos = 0.0
    avg = 0.0
    realized = 0.0
    for order in session["orders"]:
        amount = float(order["amount"])
        if amount <= 0:
            raise SystemExit(f"amount must be positive, got {amount}")
        side = order["buy_sell"]
        if side == "B":
            q = amount
            price = float(order["rate"]) + half
        elif side == "S":
            q = -amount
            price = float(order["rate"]) - half
        else:
            raise SystemExit(f"buy_sell must be B or S, got {side}")
        if order.get("order_type") != "OM":
            raise SystemExit(f"paper only fills OM, got {order.get('order_type')}")
        if order.get("instrument") != session.get("instrument"):
            raise SystemExit("instrument mismatch")
        pos, avg, realized = apply_fill(pos, avg, realized, q, price)
    return mark_pnl(realized, pos, avg, mark), pos


def forexconnect_state():
    try:
        import forexconnect  # noqa: F401
    except Exception:
        return "missing"
    return "present"


def cmd_probe(_args):
    arch = platform.machine()
    mod = forexconnect_state()
    user = os.environ.get("FXCM_USER", "")
    password = os.environ.get("FXCM_PASSWORD", "")
    if mod == "missing":
        live = "blocked"
        reason = (
            f"forexconnect is not installed. FXCM's Linux SDK is x86_64; "
            f"this process is {arch}. Paper is the path that runs here."
        )
    elif user and password:
        live = "credentials-present"
        reason = "module and credentials are present. live sends only with FXCM_LIVE=1."
    else:
        live = "needs-credentials"
        reason = "module imports. Set FXCM_USER and FXCM_PASSWORD. live also needs FXCM_LIVE=1."
    print("mode=probe")
    print(f"arch={arch}")
    print(f"forexconnect={mod}")
    print(f"credentials={'present' if user and password else 'absent'}")
    print(f"live={live}")
    print(f"reason={reason}")
    print("PROBE_OK")
    return 0


def cmd_paper(args):
    with open(args.session, encoding="utf-8") as fh:
        session = json.load(fh)
    pnl, pos = replay(session)
    aura_pnl = float(session["pnl"])
    aura_pos = float(session["pos"])
    pnl_ok = abs(pnl - aura_pnl) < 1e-4
    pos_ok = abs(pos - aura_pos) < 1e-4
    print("mode=paper")
    print(f"orders={len(session['orders'])}")
    print(f"pnl={pnl}")
    print(f"pos={pos}")
    print(f"aura-pnl={aura_pnl}")
    print(f"aura-pos={aura_pos}")
    print(f"match={1 if pnl_ok and pos_ok else 0}")
    if not pnl_ok or not pos_ok:
        print("PIPE_MISMATCH")
        return 1
    print("PIPE_OK")
    return 0


def session_status_changed(*args):
    status = args[-1] if args else ""
    print(f"fxcm-status={status}")


def cmd_login(_args):
    """Read the Demo account and EUR/USD quote. Sends no orders."""
    connection = demo_only()
    if connection is None:
        return 2
    user = os.environ.get("FXCM_USER", "")
    password = os.environ.get("FXCM_PASSWORD", "")
    if not user or not password:
        print("login blocked: set FXCM_USER and FXCM_PASSWORD")
        return 2
    url = os.environ.get("FXCM_URL", "https://www.fxcorporate.com/Hosts.jsp")
    try:
        from forexconnect import ForexConnect
    except Exception as exc:
        print(f"login blocked: forexconnect is not installed ({exc})")
        return 2
    with ForexConnect() as fx:
        fx.login(user, password, url, connection, None, None, session_status_changed)
        try:
            for account in fx.get_table(ForexConnect.ACCOUNTS):
                print(f"account={account.account_id} balance={account.balance}")
            for offer in fx.get_table(ForexConnect.OFFERS):
                if offer.instrument == "EUR/USD":
                    print(f"EUR/USD bid={offer.bid:.6f} ask={offer.ask:.6f}")
                    break
        finally:
            fx.logout()
    print("LOGIN_OK")
    return 0


def cmd_live(args):
    if os.environ.get("FXCM_LIVE") != "1":
        print("live submit blocked: set FXCM_LIVE=1 to send Demo orders")
        return 2
    user = os.environ.get("FXCM_USER", "")
    password = os.environ.get("FXCM_PASSWORD", "")
    if not user or not password:
        print("live submit blocked: set FXCM_USER and FXCM_PASSWORD")
        return 2
    url = os.environ.get("FXCM_URL", "https://www.fxcorporate.com/Hosts.jsp")
    connection = demo_only()
    if connection is None:
        return 2
    account_id = os.environ.get("FXCM_ACCOUNT", "")
    try:
        from forexconnect import Common, ForexConnect, fxcorepy
    except Exception as exc:
        print(f"live submit blocked: forexconnect is not installed ({exc})")
        return 2

    with open(args.session, encoding="utf-8") as fh:
        session = json.load(fh)

    with ForexConnect() as fx:
        fx.login(user, password, url, connection, None, None, session_status_changed)
        try:
            account = Common.get_account(fx, account_id or None)
            if account is None:
                raise RuntimeError("no account")
            account_id = account.account_id
            print(f"account={account_id}")
            for order in session["orders"]:
                offer = Common.get_offer(fx, order["instrument"])
                if offer is None:
                    raise RuntimeError(f"no offer for {order['instrument']}")
                request = fx.create_order_request(
                    order_type=fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
                    ACCOUNT_ID=account_id,
                    BUY_SELL=order["buy_sell"],
                    AMOUNT=int(order["amount"]),
                    SYMBOL=offer.instrument,
                )
                if request is None:
                    raise RuntimeError(f"no request for seq {order.get('seq')}")
                resp = fx.send_request(request)
                print(f"sent seq={order.get('seq')} order_id={getattr(resp, 'order_id', '')}")
        finally:
            fx.logout()
    print("LIVE_SENT")
    return 0


def main(argv):
    load_dotenv()
    parser = argparse.ArgumentParser(description="Aura to ForexConnect order pipe")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    sub.add_parser("login")
    paper = sub.add_parser("paper")
    paper.add_argument("--session", default="out/session.json")
    live = sub.add_parser("live")
    live.add_argument("--session", default="out/session.json")
    args = parser.parse_args(argv)
    if args.cmd == "probe":
        return cmd_probe(args)
    if args.cmd == "login":
        return cmd_login(args)
    if args.cmd == "paper":
        return cmd_paper(args)
    if args.cmd == "live":
        return cmd_live(args)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
