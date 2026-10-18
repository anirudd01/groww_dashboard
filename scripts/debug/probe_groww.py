"""Which Groww API calls work on the current plan, and the open questions behind them. Read-only.

Places, modifies and cancels nothing. Run it after any change to the Groww subscription:

    python scripts/debug/probe_groww.py                # every read call, OK/ERR and timing
    python scripts/debug/probe_groww.py --socket 20    # also listen to the live socket for 20 s

Each line is ``[OK ]`` or ``[ERR]``, the time taken, the call and the start of its answer. The
``CHECK`` lines answer the questions listed in docs/GROWW_PAID_PLAN_CHECKS.md (free plan on
2026-10-17: every market-data call answered "Access forbidden for this request.").
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env", override=True)
logging.basicConfig(level=logging.WARNING)
logging.getLogger("growwapi.groww.nats_client").setLevel(logging.CRITICAL)


def short(value, n=300):
    try:
        text = json.dumps(value, default=str)
    except Exception:
        text = repr(value)
    return text[:n]


def probe(name, fn, *args, **kwargs):
    started = time.monotonic()
    try:
        out, ok = fn(*args, **kwargs), True
    except Exception as e:  # noqa: BLE001 - every failure is the answer here
        out, ok = f"{type(e).__name__}: {e}", False
    print(f"[{'OK ' if ok else 'ERR'}] {time.monotonic() - started:6.2f}s {name}: {short(out)}")
    return out if ok else None


def check(question, answer):
    print(f"CHECK {question}: {answer}")


def last_weekday(now):
    day = now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--socket", type=int, default=0, metavar="SECONDS",
                        help="listen to the live socket for this long (best during market hours)")
    args = parser.parse_args()

    from growwapi import GrowwAPI as G
    from groww_api.client import GrowwAPIClient

    client = GrowwAPIClient.get_instance()
    if not client.session:
        print("Login failed:", client.auth_error)
        return 1
    g = client.session

    print("\n== Account and orders (worked on the free plan) ==")
    probe("get_user_profile", g.get_user_profile, timeout=15)
    probe("get_available_margin_details", g.get_available_margin_details, timeout=15)
    holdings = probe("get_holdings_for_user", g.get_holdings_for_user, timeout=15)
    positions = probe("get_positions_for_user", g.get_positions_for_user, timeout=15)
    for seg in (G.SEGMENT_CASH, G.SEGMENT_FNO, G.SEGMENT_COMMODITY):
        probe(f"get_order_list({seg})", g.get_order_list, segment=seg, timeout=15)
    for kind in (G.SMART_ORDER_TYPE_GTT, G.SMART_ORDER_TYPE_OCO):
        probe(f"get_smart_order_list({kind})", g.get_smart_order_list, smart_order_type=kind,
              segment=G.SEGMENT_FNO, page=0, page_size=10, timeout=15)

    print("\n== Instrument list ==")
    inst = probe("get_all_instruments", g.get_all_instruments)
    if inst is None:
        return 1
    today = datetime.now().strftime("%Y-%m-%d")

    def nearest(exchange, underlying, kind="FUT"):
        rows = inst[(inst.exchange == exchange) & (inst.underlying_symbol == underlying)
                    & (inst.instrument_type == kind) & (inst.expiry_date >= today)].sort_values("expiry_date")
        return rows.iloc[0].to_dict() if len(rows) else None

    fut, gold = nearest("NSE", "NIFTY"), nearest("MCX", "GOLD")
    option = nearest("NSE", "NIFTY", "CE")

    print("\n== Market data (refused on the free plan) ==")
    probe("get_ltp CASH", g.get_ltp, ("NSE_RELIANCE", "NSE_INFY"), G.SEGMENT_CASH, timeout=15)
    ohlc = probe("get_ohlc CASH", g.get_ohlc, ("NSE_RELIANCE",), G.SEGMENT_CASH, timeout=15)
    quote = probe("get_quote CASH RELIANCE", g.get_quote, "RELIANCE", "NSE", G.SEGMENT_CASH, timeout=15)
    if fut:
        probe("get_ltp FNO", g.get_ltp, (f"NSE_{fut['trading_symbol']}",), G.SEGMENT_FNO, timeout=15)
    if gold:
        probe("get_quote MCX", g.get_quote, gold["trading_symbol"], "MCX", G.SEGMENT_COMMODITY, timeout=15)
        mcx_ltp = probe("get_ltp MCX (batched)", g.get_ltp, (f"MCX_{gold['trading_symbol']}",),
                        G.SEGMENT_COMMODITY, timeout=15)
        check("1. batched get_ltp for MCX works", bool(mcx_ltp))

    end = datetime.combine(last_weekday(datetime.now()), datetime.min.time()).replace(hour=15, minute=30)
    fmt = "%Y-%m-%d %H:%M:%S"
    daily = probe("get_historical_candles 1day", g.get_historical_candles, "NSE", "CASH", "NSE-RELIANCE",
                  (end - timedelta(days=10)).strftime(fmt), end.strftime(fmt), G.CANDLE_INTERVAL_DAY, timeout=30)
    probe("get_historical_candles 5minute", g.get_historical_candles, "NSE", "CASH", "NSE-RELIANCE",
          (end - timedelta(days=3)).strftime(fmt), end.strftime(fmt), G.CANDLE_INTERVAL_MIN_5, timeout=30)
    if gold:
        probe("get_historical_candles MCX 15minute", g.get_historical_candles, "MCX", "COMMODITY", gold["groww_symbol"],
              (end - timedelta(days=3)).strftime(fmt), end.strftime(fmt), G.CANDLE_INTERVAL_MIN_15, timeout=30)

    candles = (daily or {}).get("candles") or []
    if candles:
        check("2. daily candles carry an open", f"last candle {candles[-1]} (open is field 2)")
    if ohlc and candles:
        close = (ohlc.get("NSE_RELIANCE") or {}).get("close")
        last_two = [c[4] for c in candles[-2:]]
        check("3. get_ohlc close is the previous close",
              f"ohlc close {close}; last two daily closes {last_two} (run during the session to tell them apart)")
    if quote:
        check("4. get_quote has market_cap / 52-week range",
              {k: quote.get(k) for k in ("last_price", "market_cap", "week_52_high", "week_52_low")})

    print("\n== Options ==")
    if option:
        probe("get_expiries", g.get_expiries, "NSE", "NIFTY", timeout=15)
        probe("get_option_chain", g.get_option_chain, "NSE", "NIFTY", option["expiry_date"], timeout=20)
        greeks = probe("get_greeks", g.get_greeks, "NSE", "NIFTY", option["trading_symbol"], option["expiry_date"])
        check("5. get_greeks shape is {'greeks': {delta, gamma, theta, vega, rho, iv}}", short(greeks))

    rows = (holdings or {}).get("holdings") or []
    mtf = [p for p in (positions or {}).get("positions", []) if p.get("product") == "MTF"]
    check("6. holdings include MTF stocks",
          f"{len(rows)} holdings, {len(mtf)} MTF positions; compare the symbols: "
          f"{sorted({h.get('trading_symbol') for h in rows} & {p.get('trading_symbol') for p in mtf})}")

    from groww_api.position_processor import open_entry_price

    fields = ("quantity", "credit_quantity", "credit_price", "debit_quantity", "debit_price",
              "carry_forward_credit_quantity", "carry_forward_credit_price", "carry_forward_debit_quantity",
              "carry_forward_debit_price", "net_carry_forward_quantity", "net_carry_forward_price",
              "net_price", "realised_pnl")
    for p in (positions or {}).get("positions", []):
        if p.get("quantity"):
            check(f"9. open cost of {p.get('trading_symbol')} (compare entry and P&L with the Groww app)",
                  f"open_entry_price {open_entry_price(p):.2f}; " + short({k: p.get(k) for k in fields}, 600))

    if args.socket:
        print(f"\n== Live socket, {args.socket} s ==")
        from growwapi import GrowwFeed
        from market.providers.groww import GrowwFeedHandle

        started = time.monotonic()
        feed = probe("GrowwFeed handshake", GrowwFeed, g)
        if feed is not None:
            print(f"handshake {time.monotonic() - started:.1f}s")
            feed.subscribe_ltp([{"exchange": "NSE", "segment": "CASH", "exchange_token": "2885"}], lambda meta: None)
            time.sleep(args.socket)
            check("7. the socket streams ticks", short(feed.get_ltp()))
            GrowwFeedHandle._disconnect(feed)

    print("\nNot checked here (needs one real order, with the account holder's approval): "
          "OCO smart order with GTC on an F&O / MCX carry-forward position.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
