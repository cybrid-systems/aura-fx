#!/usr/bin/env python3
"""Broker side of the Aura order pipe.

paper  replays out/session.json with the same fill rule as lib/book.aura.
       Aura's pnl and this pnl have to match or the pipe is not connected.
probe  says whether a ForexConnect Demo login can run in this process.
login  reads the Demo balance and the EUR/USD quote. It sends no orders.
live   nets the session's orders into Demo: TRUE_MARKET_CLOSE with TRADE_ID
       for opposite trades, TRUE_MARKET_OPEN with OFFER_ID for the rest.
       --offline and --dry-run print that plan and send nothing. Sending
       needs FXCM_LIVE=1 plus --max N or --all, and an open market: FXCM
       rejects orders while forex is closed (Friday 17:00 to Sunday 17:15
       New York time), so live refuses with MARKET_CLOSED. See cmd_live.

The intent fields match ForexConnect create_order_request:
  order_type OM, buy_sell B|S, amount in base units, rate is the decision mid.
  Live finds the offer by instrument in OFFERS (Common.get_offer skips any
  offer that is not subscription "T"). Amount is already in base units. Do
  not multiply by base_unit_size again.

Login retries the SDK's 30 s "Wait timeout exceeded" up to 3 times. That
error means the session never left CONNECTING within the SDK's fixed 30 s
wait. On the box the first session of a process took about 72 s to reach
CONNECTED, and a fresh session after logging the stuck one out connected on
the next try. FXCM's own refusals arrive through on_login_failed and are not
retried.
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


LOGIN_ATTEMPTS = 3
LOGIN_BACKOFF = (5.0, 20.0)


class LoginError(RuntimeError):
    pass


def session_status_changed(*args):
    status = args[-1] if args else ""
    print(f"fxcm-status={status}", flush=True)


def credentials():
    user = os.environ.get("FXCM_USER", "")
    password = os.environ.get("FXCM_PASSWORD", "")
    url = os.environ.get("FXCM_URL", "https://www.fxcorporate.com/Hosts.jsp")
    return user, password, url


def transport_hint(url, connection):
    """Ask Hosts.jsp which trade server it hands out and whether it answers.

    Diagnostic only, it does not log in and does not decide anything. The
    SDK takes the pdas URL from Hosts.jsp; for Demo it is plain http
    (secure=false). The result is printed with the final login error so a
    network problem on the way to that server is visible.
    """
    import re
    import urllib.error
    import urllib.request

    query = f"{url}?ID=0&PN={connection}&SN={connection}&MV=1"
    try:
        with urllib.request.urlopen(query, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return f"hosts=unreachable ({exc})"
    m = re.search(r'urlString="pdas:([^"]+)"[^>]*secure="(\w+)"[^>]*params="[^"]*http-servlet-path=([^;"]+)', body)
    if not m:
        return "hosts=no-pdas-url"
    base, secure, path = m.group(1), m.group(2), m.group(3)
    target = base + path
    try:
        with urllib.request.urlopen(target, timeout=10) as resp:
            code, server = resp.status, resp.headers.get("Server", "")
    except urllib.error.HTTPError as exc:
        code, server = exc.code, exc.headers.get("Server", "")
    except Exception as exc:
        return f"pdas={target} secure={secure} reach=fail ({exc})"
    return f"pdas={target} secure={secure} reach=http-{code} server={server or '-'}"


def fx_login(ForexConnect, attempts=LOGIN_ATTEMPTS):
    """Log in with retries. Returns a logged-in ForexConnect.

    Each attempt uses a fresh ForexConnect and logs the old one out, so a
    session stuck in CONNECTING is not reused. FXCM's own failure reasons
    (bad password, account locked) come through on_login_failed and are not
    retried. Only the SDK's 30 s "Wait timeout exceeded" is retried.
    """
    import time

    user, password, url = credentials()
    connection = demo_only()
    if connection is None:
        raise LoginError("Real connection refused")
    last = None
    for attempt in range(1, attempts + 1):
        fx = ForexConnect()
        try:
            fx.login(user, password, url, connection, None, None, session_status_changed)
            print(f"login attempt={attempt} ok", flush=True)
            return fx
        except Exception as exc:
            last = str(exc)
            reason = None
            listener = getattr(fx, "_status_listener", None)
            if listener is not None and listener.last_error:
                reason = listener.last_error
            try:
                fx.logout()
            except Exception:
                pass
            if reason:
                raise LoginError(f"FXCM refused the login: {reason}")
            print(f"login attempt={attempt} failed: {last}", flush=True)
            if attempt < attempts:
                delay = LOGIN_BACKOFF[min(attempt - 1, len(LOGIN_BACKOFF) - 1)]
                time.sleep(delay)
    hint = transport_hint(url, connection)
    raise LoginError(
        f"login failed after {attempts} attempts ({last}). The session never reached "
        f"CONNECTED within the SDK's 30 s wait. Trade server from Hosts.jsp: {hint}"
    )


def cmd_login(_args):
    """Read the Demo account and EUR/USD quote. Sends no orders."""
    user, password, _url = credentials()
    if not user or not password:
        print("login blocked: set FXCM_USER and FXCM_PASSWORD")
        return 2
    try:
        from forexconnect import ForexConnect
    except Exception as exc:
        print(f"login blocked: forexconnect is not installed ({exc})")
        return 2
    try:
        fx = fx_login(ForexConnect)
    except LoginError as exc:
        print(f"LOGIN_FAILED {exc}")
        return 1
    try:
        for account in fx.get_table(ForexConnect.ACCOUNTS):
            print(f"account={account.account_id} maintenance={account.maintenance_type} balance={account.balance}")
        for offer in fx.get_table(ForexConnect.OFFERS):
            if offer.instrument == "EUR/USD":
                print(
                    f"EUR/USD offer_id={offer.offer_id} bid={offer.bid:.6f} ask={offer.ask:.6f} "
                    f"subscription={offer.subscription_status} trading={offer.trading_status}"
                )
                break
    finally:
        fx.logout()
    print("LOGIN_OK")
    return 0


def signed(side, amount):
    return amount if side == "B" else -amount


def plan_order(trades, side, amount, new_id="new"):
    """Netting plan for one order against open trades.

    trades is a list of (trade_id, buy_sell, amount). Opposite trades are
    closed oldest first with TRUE_MARKET_CLOSE + TRADE_ID. What is left opens
    with TRUE_MARKET_OPEN. Returns (requests, trades_after); trades_after is
    the expected table after the fills, with new_id for an opened trade.
    """
    remaining = int(amount)
    requests = []
    after = []
    for trade_id, tside, tamount in trades:
        if remaining > 0 and tside != side:
            close = min(remaining, int(tamount))
            requests.append(("CM", side, close, trade_id))
            remaining -= close
            if tamount - close > 0:
                after.append((trade_id, tside, tamount - close))
        else:
            after.append((trade_id, tside, tamount))
    if remaining > 0:
        requests.append(("OM", side, remaining, None))
        after.append((new_id, side, remaining))
    return requests, after


def plan_session(orders, trades):
    """Plan every order in turn from a starting trade list. Pure, no I/O."""
    steps = []
    current = list(trades)
    for order in orders:
        new_id = f"<opened-by-seq-{order.get('seq')}>"
        requests, current = plan_order(current, order["buy_sell"], int(order["amount"]), new_id)
        pos = sum(signed(s, a) for _i, s, a in current)
        steps.append((order, requests, pos))
    return steps


def open_trades(fx, ForexConnect, account_id, offer_id):
    rows = []
    for t in fx.get_table(ForexConnect.TRADES):
        if t.account_id == account_id and t.offer_id == offer_id:
            rows.append((getattr(t, "open_time", None), t.trade_id, t.buy_sell, int(t.amount)))
    rows.sort(key=lambda r: (r[0] is None, r[0] or 0, r[1]))
    return [(trade_id, side, amount) for _t, trade_id, side, amount in rows]


def net_of(trades):
    return sum(signed(s, a) for _i, s, a in trades)


def wait_position(fx, ForexConnect, account_id, offer_id, want, timeout=20.0):
    import time
    deadline = time.time() + timeout
    while True:
        trades = open_trades(fx, ForexConnect, account_id, offer_id)
        pos = net_of(trades)
        if pos == want or time.time() > deadline:
            return pos, trades
        time.sleep(0.25)


def find_offer(fx, ForexConnect, instrument):
    for offer in fx.get_table(ForexConnect.OFFERS):
        if offer.instrument == instrument:
            return offer
    return None


def refreshed_status(fx, ForexConnect, instrument):
    """Subscription status from a fresh OFFERS refresh, not the table manager."""
    factory = fx.session.request_factory
    request = factory.create_refresh_table_request(ForexConnect.OFFERS)
    for offer in fx.send_request(request):
        if offer.instrument == instrument:
            return offer.subscription_status
    return None


def ensure_tradable(fx, ForexConnect, fxcorepy, instrument, timeout=15.0):
    """Make the offer tradable ("T"). Sends SET_SUBSCRIPTION_STATUS once.

    Common.get_offer returns None for any offer that is not "T", which is why
    it cannot be used to find a "V" (view only) offer. send_request is
    synchronous: it returns once the server completes the request and raises
    RequestFailedError if the server refuses it. After that the code waits on
    the table manager row and also asks for a fresh OFFERS refresh, because
    the status change does not always arrive as a table manager update.
    Returns (offer, status, note).
    """
    import time
    from forexconnect.errors import RequestFailedError

    offer = find_offer(fx, ForexConnect, instrument)
    if offer is None:
        return None, None, f"{instrument} is not in OFFERS"
    if offer.subscription_status == "T":
        return offer, "T", "already tradable"
    offer_id = offer.offer_id
    request = fx.create_request({
        fxcorepy.O2GRequestParamsEnum.COMMAND: fxcorepy.Constants.Commands.SET_SUBSCRIPTION_STATUS,
        fxcorepy.O2GRequestParamsEnum.OFFER_ID: offer_id,
        fxcorepy.O2GRequestParamsEnum.SUBSCRIPTION_STATUS: fxcorepy.Constants.SubscriptionStatuses.TRADABLE,
    })
    try:
        fx.send_request(request)
        print(f"subscription request accepted offer_id={offer_id} from={offer.subscription_status}", flush=True)
    except RequestFailedError as exc:
        return offer, offer.subscription_status, f"server refused SET_SUBSCRIPTION_STATUS: {exc}"
    deadline = time.time() + timeout
    status = offer.subscription_status
    while time.time() < deadline:
        row = find_offer(fx, ForexConnect, instrument)
        status = row.subscription_status if row is not None else None
        if status == "T":
            return row, "T", "table manager shows T"
        time.sleep(0.5)
    try:
        status = refreshed_status(fx, ForexConnect, instrument) or status
    except Exception as exc:
        return find_offer(fx, ForexConnect, instrument), status, f"refresh failed: {exc}"
    note = "refresh shows T" if status == "T" else f"still {status} after {timeout:.0f}s and a refresh"
    return find_offer(fx, ForexConnect, instrument), status, note


QUOTE_MAX_AGE = 300.0


def market_state(offer):
    """Return (open, reason). Closed if trading_status is not "O" or the quote is stale.

    On a Saturday the Demo offer still showed trading_status "O", bid/ask
    tradable "T" and market orders PERMISSION_ENABLED, with the quote time
    frozen at Friday's close. The quote age is the check that catches that.
    """
    import datetime as dt

    if offer.trading_status != "O":
        return False, f"trading_status={offer.trading_status}"
    quote = getattr(offer, "time", None)
    if isinstance(quote, dt.datetime):
        if quote.tzinfo is not None:
            quote = quote.astimezone(dt.timezone.utc).replace(tzinfo=None)
        age = (dt.datetime.utcnow() - quote).total_seconds()
        if age > QUOTE_MAX_AGE:
            return False, f"quote is {age / 3600:.1f} h old (last {quote:%Y-%m-%d %H:%M:%S} UTC)"
        return True, f"quote age {age:.0f} s"
    return True, "quote time unknown"


def describe(request):
    kind, side, amount, trade_id = request
    if kind == "CM":
        return f"TRUE_MARKET_CLOSE {side} {amount} TRADE_ID={trade_id}"
    return f"TRUE_MARKET_OPEN {side} {amount}"


def print_plan(steps, start_pos):
    print(f"plan start-pos={start_pos} orders={len(steps)}")
    for order, requests, pos in steps:
        reqs = "; ".join(describe(r) for r in requests)
        print(f"plan seq={order.get('seq')} {order['buy_sell']} {int(order['amount'])} -> {reqs} | pos={pos}")
    end = steps[-1][2] if steps else start_pos
    print(f"plan end-pos={end}")
    return end


def select_orders(session, args):
    orders = session["orders"]
    if args.skip:
        orders = orders[args.skip:]
    if args.max is not None:
        orders = orders[: args.max]
    return orders


def cmd_live(args):
    """Send the session's orders to Demo with netting semantics.

    FXCM Demo accounts are often hedging (maintenance_type Y): an opposite
    open would add a hedge instead of reducing the position. The paper fill
    rule nets, so live first closes opposite trades (TRUE_MARKET_CLOSE with
    TRADE_ID, oldest first) and opens only the rest (TRUE_MARKET_OPEN with
    OFFER_ID).

    --dry-run logs in, reads the open trades and prints the close/open
    requests for every selected order without sending anything, not even the
    subscription change. --offline does the same without logging in, from a
    flat account. Neither needs FXCM_LIVE.

    Sending needs FXCM_LIVE=1 and --max N (or --all). --skip K drops the first
    K orders so a 1-order test can be followed by the rest of the session.

    The market has to be open. FXCM forex trades from Sunday 17:15 to Friday
    17:00 New York time (about Monday 06:15 to Saturday 06:00 Asia/Shanghai
    in winter). While it is closed the server rejects market orders. The
    Demo offer can still say trading_status "O" then, so live also treats a
    quote older than 5 minutes as closed, refuses to send and prints
    MARKET_CLOSED. If an order is still rejected or does not fill, live stops
    at that order and prints how far it got.
    """
    with open(args.session, encoding="utf-8") as fh:
        session = json.load(fh)
    orders = select_orders(session, args)
    if not orders:
        print("live: no orders selected")
        return 2

    if args.offline:
        print("mode=live-offline account=flat (no login)")
        print_plan(plan_session(orders, []), 0)
        print("DRY_RUN_OK")
        return 0

    sending = not args.dry_run
    if sending:
        if os.environ.get("FXCM_LIVE") != "1":
            print("live submit blocked: set FXCM_LIVE=1 to send Demo orders (or use --dry-run)")
            return 2
        if args.max is None and not args.all:
            print("live submit blocked: pass --max N (start with --max 1) or --all")
            return 2
    user, password, _url = credentials()
    if not user or not password:
        print("live blocked: set FXCM_USER and FXCM_PASSWORD")
        return 2
    try:
        from forexconnect import Common, ForexConnect, fxcorepy
        from forexconnect.errors import RequestFailedError
    except Exception as exc:
        print(f"live blocked: forexconnect is not installed ({exc})")
        return 2

    try:
        fx = fx_login(ForexConnect)
    except LoginError as exc:
        print(f"LOGIN_FAILED {exc}")
        return 1
    done = 0
    try:
        wanted = os.environ.get("FXCM_ACCOUNT", "") or None
        account = Common.get_account(fx, wanted)
        if account is None:
            print(f"live blocked: account {wanted or '(first)'} not found")
            return 2
        account_id = account.account_id
        print(f"account={account_id} maintenance={account.maintenance_type} balance={account.balance}")
        instrument = session["instrument"]
        offer = find_offer(fx, ForexConnect, instrument)
        if offer is None:
            print(f"live blocked: {instrument} is not in OFFERS")
            return 2
        offer_id = offer.offer_id
        is_open, why = market_state(offer)
        print(
            f"offer {instrument} id={offer_id} subscription={offer.subscription_status} "
            f"trading={offer.trading_status} bid={offer.bid:.5f} ask={offer.ask:.5f} "
            f"market={'open' if is_open else 'closed'} ({why})"
        )
        trades = open_trades(fx, ForexConnect, account_id, offer_id)
        start = net_of(trades)
        print(f"open-trades={len(trades)} start-pos={start}")
        steps = plan_session(orders, trades)
        planned_end = print_plan(steps, start)
        if not sending:
            print("DRY_RUN_OK")
            return 0

        if not is_open:
            print(f"MARKET_CLOSED {why}; no order sent")
            return 3
        offer, status, note = ensure_tradable(fx, ForexConnect, fxcorepy, instrument)
        print(f"subscription={status} ({note})")
        if status != "T" and not args.allow_view:
            print("live blocked: offer is not tradable; rerun with --allow-view to let the server decide")
            return 3

        pos = start
        for order in orders:
            side = order["buy_sell"]
            amount = int(order["amount"])
            want = pos + signed(side, amount)
            trades = open_trades(fx, ForexConnect, account_id, offer_id)
            requests, _after = plan_order(trades, side, amount)
            for kind, rside, ramount, trade_id in requests:
                params = dict(OFFER_ID=offer_id, ACCOUNT_ID=account_id, BUY_SELL=rside, AMOUNT=ramount)
                if kind == "CM":
                    params["TRADE_ID"] = trade_id
                    order_type = fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE
                else:
                    order_type = fxcorepy.Constants.Orders.TRUE_MARKET_OPEN
                request = fx.create_order_request(order_type=order_type, **params)
                try:
                    fx.send_request(request)
                except RequestFailedError as exc:
                    print(f"REJECTED seq={order.get('seq')} {describe((kind, rside, ramount, trade_id))}: {exc}")
                    print(f"stopped after {done} of {len(orders)} orders, pos={pos}")
                    return 1
            pos, _ = wait_position(fx, ForexConnect, account_id, offer_id, want)
            print(f"sent seq={order.get('seq')} {side} {amount} pos={pos}", flush=True)
            if pos != want:
                print(f"NO_FILL seq={order.get('seq')} pos={pos} expected={want}")
                print(f"stopped after {done} of {len(orders)} orders")
                return 1
            done += 1
        account = Common.get_account(fx, account_id)
        print(f"end-pos={pos} expected-pos={planned_end} balance={account.balance}")
        if pos != planned_end:
            print("LIVE_MISMATCH")
            return 1
    finally:
        fx.logout()
    print("LIVE_OK")
    return 0


def main(argv):
    load_dotenv()
    parser = argparse.ArgumentParser(description="Aura to ForexConnect order pipe")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True
    sub.add_parser("probe")
    sub.add_parser("login")
    paper = sub.add_parser("paper")
    paper.add_argument("--session", default="out/session.json")
    live = sub.add_parser("live")
    live.add_argument("--session", default="out/session.json")
    live.add_argument("--max", type=int, default=None, help="send at most N orders")
    live.add_argument("--skip", type=int, default=0, help="drop the first K orders")
    live.add_argument("--all", action="store_true", help="send every selected order")
    live.add_argument("--dry-run", action="store_true", help="log in, print the plan, send nothing")
    live.add_argument("--offline", action="store_true", help="print the plan from a flat account, no login")
    live.add_argument("--allow-view", action="store_true", help="send even if the offer is not T")
    args = parser.parse_args(argv)
    if args.cmd == "live":
        if args.max is not None and args.max < 1:
            parser.error("--max must be at least 1")
        if args.skip < 0:
            parser.error("--skip must be >= 0")
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
