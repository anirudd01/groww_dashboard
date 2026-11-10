"""Daily candles for every F&O stock (plus the Nifty 100 members without futures) from Dhan.

    python scripts/daily.py dhan-daily                              # catch up every stock
    python scripts/daily.py dhan-daily --symbols RELIANCE,TCS
    python scripts/daily.py dhan-daily --full --daily-days 1830     # re-fetch 5 years, replacing what is stored

Dhan's daily candles are the official ones (open, high, low, close, volume equal Kite's field for field)
but **raw**: not adjusted for splits, bonuses or dividends, like NSE's own 52-week figures. That is
the basis ``daily_bars`` is kept in (decided 2026-11-07, docs/PROVIDER_COMPARISON_LOG.md). The
drawdown page flags suspected splits instead of relying on adjusted history.

Cost: one ``/charts/historical`` request per stock, whatever the range - five years came back in one
call in 0.5 s (RELIANCE, 2026-11-08). About 225 stocks at Dhan's history rate (4/s) is ~1 minute.

Re-runs are incremental: each stock restarts from its last stored day, so a value that settled late
is corrected. Today's candle is stored only after 16:00 IST. ``--full`` deletes the stock's rows in
the fetched window before writing, so no row from another source survives inside it.

Writes ``daily_bars`` in data/market.db. Read-only against the broker: no orders, no account data.
Security ids come from the stored ``dhan_instruments`` set (``scripts/dhan.py --master``).
"""

import logging
import time
from datetime import timedelta

from market import state_store
from market.fno_movers import load_universe
from market.instruments import load_instruments
from market.intraday_store import connect, dhan_daily_rows, upsert_daily
from market.market_hours import now_ist
from market.providers.base import SEGMENT_CASH, InstrumentRef
from market.universe import universes

logger = logging.getLogger("dhan_daily")

#: Today's candle is trusted as the close only after this IST time.
SETTLED_AFTER = (16, 0)
#: Indices whose non-F&O members also get daily bars (the drawdown page's Nifty 100).
EXTRA_INDICES = ("NIFTY50", "NIFTYNEXT50")


def add_arguments(parser) -> None:
    group = parser.add_argument_group("dhan-daily")
    group.add_argument("--daily-days", type=int, default=30,
                       help="Calendar days for a stock with no history, or the --full window (default 30)")


def wanted_symbols(symbols_arg=None):
    """F&O stocks plus the Nifty 50 / Next 50 members without futures, optionally narrowed."""
    names = set(load_universe().tokens)
    for key in EXTRA_INDICES:
        universe = universes().get(key)
        if universe:
            names.update(universe.symbols)
    if symbols_arg:
        asked = {s.strip().upper() for s in symbols_arg.split(",") if s.strip()}
        names &= asked
    return sorted(names)


def last_days(conn):
    return dict(conn.execute("SELECT symbol, MAX(date) FROM daily_bars GROUP BY symbol"))


def run(args) -> int:
    from market.providers.dhan import DhanProvider

    symbols = wanted_symbols(args.symbols)
    if not symbols:
        logger.error("No stocks to fetch: store the F&O universe first (scripts/kite.py history or --master).")
        return 1
    ids = load_instruments().security_ids(SEGMENT_CASH)
    missing = [s for s in symbols if s not in ids]
    if missing:
        logger.warning("No Dhan security id, skipped (run scripts/dhan.py --master-only): %s", ", ".join(missing))

    provider = DhanProvider()
    if not provider.is_configured():
        logger.error("Dhan is not configured - set DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET.")
        return 1
    provider.connect()

    now = now_ist()
    today = now.date()
    settled = (now.hour, now.minute) >= SETTLED_AFTER
    exclude = None if settled else today.isoformat()
    default_first = today - timedelta(days=args.daily_days)

    conn = connect(args.db or state_store.db_path())
    stored = last_days(conn)
    todo = [s for s in symbols if s in ids]
    logger.info("Fetching Dhan daily candles for %d stocks (~%.0f s) ...", len(todo), len(todo) * 0.3)
    started = time.monotonic()
    written, failed, without_today = 0, [], []
    for i, symbol in enumerate(todo, 1):
        last = None if args.full else stored.get(symbol)
        first = last or default_first.isoformat()
        ref = InstrumentRef(symbol=symbol, provider_id=ids[symbol], segment=SEGMENT_CASH)
        window = {"fromDate": first, "toDate": (today + timedelta(days=1)).isoformat()}  # toDate is exclusive
        payload = provider._post_historical(ref, window)
        rows = dhan_daily_rows(symbol, payload, exclude_date=exclude)
        if not rows:
            # An up-to-date stock asked from its last day still gets that day back, so empty means trouble.
            failed.append(symbol)
            logger.warning("  %s: no candles from Dhan", symbol)
            continue
        with conn:
            if args.full:
                conn.execute("DELETE FROM daily_bars WHERE symbol = ? AND date >= ?", (symbol, first))
            upsert_daily(conn, rows)
        written += len(rows)
        if settled and rows[-1][1] != today.isoformat() and today.weekday() < 5:
            without_today.append(symbol)
        if i % 50 == 0:
            logger.info("  %d/%d", i, len(todo))

    first_day, last_day, count = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_bars").fetchone()
    conn.close()
    logger.info("Done in %.0f s: %d candles written. daily_bars holds %d rows (%s .. %s).",
                time.monotonic() - started, written, count, first_day, last_day)
    if not settled:
        logger.info("Today's candle was left out (before %02d:%02d IST it is only the live price).", *SETTLED_AFTER)
    if without_today and len(without_today) < len(todo):
        logger.warning("%d stock(s) have no candle for today (halted, or a holiday): %s",
                       len(without_today), ", ".join(without_today[:20]))
    elif without_today:
        logger.info("No stock has a candle for today yet: a holiday, or Dhan has not published it.")
    if failed:
        logger.warning("%d stock(s) failed and can be retried by re-running: %s", len(failed), ", ".join(failed))
        return 2 if written else 1
    return 0
