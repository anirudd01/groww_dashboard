"""
==========================================
Gold band strategy - MCX GOLD futures on Dhan
==========================================

    python strategies/dhan_gold_band_strategy.py --long  --dry-run   # -b: BUY LTP-50, target LTP+50, SL entry-50
    python strategies/dhan_gold_band_strategy.py --short --dry-run   # -s: SELL LTP+50, target LTP-50, SL entry+50
    python strategies/dhan_gold_band_strategy.py -b                  # asks you to type "yes" first

What it does (docs/DHAN_GOLD_STRATEGY.md has the details and the risks):
  1. Resolves the contract (default GOLD expiring 2026-12, i.e. "GOLD DEC FUT") from the stored
     ``mcx_futures`` set, with lot and tick size from the raw Dhan instrument master.
  2. Refuses to run if a position in that contract is open (on either side) or a super order on it
     is still pending - it never adds to, closes or reverses an existing trade.
  3. Reads the LTP, the available balance (/fundlimit) and the margin for one lot at the entry
     price (/margincalculator); lots = floor(available / margin per lot), re-checked for that many.
     Refuses if that is less than one lot.
  4. Prints the plan and asks for "yes" (skip with --yes; --dry-run stops here and places nothing).
  5. Places ONE Dhan Super Order: LIMIT entry, target and stop loss together, product MARGIN
     (carry forward). Dhan holds the target and stop-loss legs; the script does not wait or poll.

Exit codes: 0 placed (or dry run), 1 refused or failed, 2 bad arguments.
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from market import dhan_orders as do  # noqa: E402
from market import mcx_futures  # noqa: E402
from market.market_hours import now_ist  # noqa: E402

DEFAULT_SYMBOL = "GOLD"
DEFAULT_MONTH = "2026-12"
DEFAULT_OFFSET = 50.0
DEFAULT_STOP = 50.0

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def month_arg(value: str):
    try:
        when = datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}")
    return when.year, when.month


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MCX GOLD band trade on Dhan: one Super Order with a LIMIT entry offset from the LTP, "
                    "a target on the other side and a stop loss beyond the entry.")
    side = parser.add_mutually_exclusive_group(required=True)
    side.add_argument("--long", "-b", action="store_true",
                      help="BUY at LTP - offset, target LTP + offset, stop loss entry - stop")
    side.add_argument("--short", "-s", action="store_true",
                      help="SELL at LTP + offset, target LTP - offset, stop loss entry + stop")
    parser.add_argument("--offset", type=positive_float, default=DEFAULT_OFFSET,
                        help=f"entry and target: points either side of the LTP (default {DEFAULT_OFFSET:g})")
    parser.add_argument("--stop-loss", type=positive_float, default=DEFAULT_STOP,
                        help=f"stop loss: points beyond the entry price (default {DEFAULT_STOP:g})")
    parser.add_argument("--lots", type=int, help="lots to trade (capped at what the margin allows; default: the maximum)")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help=f"MCX commodity (default {DEFAULT_SYMBOL})")
    parser.add_argument("--month", type=month_arg, default=month_arg(DEFAULT_MONTH), metavar="YYYY-MM",
                        help=f"contract expiry month (default {DEFAULT_MONTH})")
    parser.add_argument("--yes", "-y", action="store_true", help="place without asking for confirmation")
    parser.add_argument("--dry-run", action="store_true", help="run every check and print the order; place nothing")
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.lots is not None and args.lots < 1:
        parser.error("--lots must be at least 1")
    return args


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"), override=True)
    except ImportError:
        pass


def _money(value: float) -> str:
    return f"Rs {value:,.2f}"


def _price(value: float) -> str:
    return f"{value:,.2f}"


def _confirm(ask: Callable[[str], str], out) -> bool:
    try:
        answer = ask('Type "yes" to place this order: ')
    except (EOFError, KeyboardInterrupt):
        out("")
        return False
    return answer.strip().lower() == "yes"


# -- checks ------------------------------------------------------------------


def open_trade_refusal(trading, contract, side: str) -> str:
    """Why a new trade must not be placed now, or "" if nothing is open.

    Any open MCX position blocks it (it also holds the margin this trade would be sized on); one in
    the same contract on the other side gets its own message, since that order would close it.
    """
    positions = trading.open_positions()
    same = [p for p in positions if str(p.get("securityId")) == str(contract.security_id)]
    if same:
        held = sum(int(p.get("netQty") or 0) for p in same)
        product = "/".join(str(p.get("productType") or "?") for p in same)
        holding = f"{'LONG' if held > 0 else 'SHORT'} {abs(held)} lot(s) of {contract.name} ({product})"
        wanted = "LONG" if side == do.BUY else "SHORT"
        if held and (held > 0) != (side == do.BUY):
            return (f"You hold {holding} and asked to go {wanted}. That order would close the open position "
                    f"instead of opening a new trade. Close or exit it yourself first.")
        return f"You already hold {holding}. Only one trade at a time - wait for it to close."
    if positions:
        held = ", ".join(f"{p.get('tradingSymbol') or p.get('securityId')} {int(p.get('netQty') or 0):+d}"
                         for p in positions)
        return f"An MCX position is already open ({held}). Only one trade at a time - wait for it to close."
    pending = do.live_super_orders(trading.super_orders(), contract.security_id)
    if pending:
        ids = ", ".join(f"{o.get('orderId')} ({o.get('transactionType')}, {o.get('orderStatus')})" for o in pending)
        return f"A super order on {contract.name} is still open: {ids}. Cancel it or let it finish first."
    return ""


def size_position(trading, contract, side: str, price: float, requested, out):
    """``(lots, margin_per_lot, available)``: the most lots the balance covers, re-checked as one order."""
    available = trading.available_balance()
    per_lot = float(trading.margin(contract, side, contract.lot_size, price)["totalMargin"])
    computed = do.max_lots(available, per_lot)
    # Margin need not be exactly linear in quantity: confirm the whole order fits, stepping down if not.
    while computed > 1:
        total = float(trading.margin(contract, side, computed * contract.lot_size, price)["totalMargin"])
        if total <= available:
            break
        out(f"  Margin for {computed} lots is {_money(total)} > available; trying {computed - 1}")
        computed -= 1
    lots, warning = do.choose_lots(computed, requested)
    if warning:
        out(f"WARNING: {warning}")
    return lots, per_lot, available


# -- the trade ---------------------------------------------------------------


def run_trade(args, trading, contract, now, ask, out) -> int:
    side = do.BUY if args.long else do.SELL
    refusal = open_trade_refusal(trading, contract, side)
    if refusal:
        out(f"WARNING: {refusal}")
        out("Nothing placed.")
        return EXIT_FAIL

    ltp = trading.ltp(do.MCX_COMM, contract.security_id)
    plan = do.band_prices(side, ltp, args.offset, args.stop_loss, contract.tick)
    lots, per_lot, available = size_position(trading, contract, side, plan.entry, args.lots, out)
    quantity = lots * contract.lot_size
    sign, other = ("-", "+") if side == do.BUY else ("+", "-")

    out("")
    out("=" * 64)
    out(f" {'LONG' if side == do.BUY else 'SHORT'} {contract.name}  (security id {contract.security_id}, "
        f"expiry {contract.expiry})")
    out("=" * 64)
    out(f"  LTP              {_price(ltp)}")
    out(f"  Entry            {side} LIMIT @ {_price(plan.entry)}   (LTP {sign} {args.offset:g})")
    out(f"  Target           {plan.exit_side} @ {_price(plan.target)}   (LTP {other} {args.offset:g})")
    out(f"  Stop loss        {plan.exit_side} @ {_price(plan.stop_loss)}   (entry {sign} {args.stop_loss:g}, not trailing)")
    out(f"  Lots             {lots}  (quantity {quantity}; lot size {contract.lot_size}, tick {contract.tick.normalize()})")
    out(f"  Margin per lot   {_money(per_lot)}")
    out(f"  Available funds  {_money(available)}")
    out(f"  Order            Super Order, product {do.PRODUCT_MARGIN} (carry forward)")
    if not mcx_futures.in_session(now):
        out("  NOTE: outside MCX hours (Mon-Fri 09:00-23:55 IST) - Dhan may reject the order now.")
    if lots < 1:
        out(f"WARNING: available funds {_money(available)} do not cover one lot ({_money(per_lot)}). Nothing placed.")
        return EXIT_FAIL

    correlation = do.entry_correlation(side, now.strftime("%y%m%d%H%M%S"))
    body = do.super_order_body(trading.client_id, contract, plan, quantity, correlation)
    if args.dry_run:
        out("\nDRY RUN - would place:")
        out(f"  POST /v2/super/orders {body}")
        return EXIT_OK
    if not args.yes and not _confirm(ask, out):
        out("Not confirmed. Nothing placed.")
        return EXIT_FAIL

    result = trading.place_super_order(body)
    out(f"Super order placed: order id {result['orderId']} ({result.get('orderStatus', '?')}, "
        f"correlation {correlation}). Dhan now holds the target and stop-loss legs.")
    return EXIT_OK


def main(argv=None, trading=None, resolve=None, now=None, ask=input, out=print) -> int:
    args = parse_args(argv)
    now = now or now_ist()
    try:
        if trading is None:
            trading = do.DhanTrading()
        year, month = args.month
        contract = (resolve or do.resolve_contract)(args.symbol, year, month, now.date())
        return run_trade(args, trading, contract, now, ask, out)
    except do.DhanOrderError as exc:
        out(f"FAILED - {exc}")
        return EXIT_FAIL
    except (ValueError, RuntimeError) as exc:
        out(f"FAILED - {exc}")
        return EXIT_FAIL


if __name__ == "__main__":
    _load_env()  # here, not in main(): tests call main() and must never see the real .env
    sys.exit(main())
