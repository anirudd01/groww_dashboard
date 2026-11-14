"""1-minute bars for every F&O stock from Groww, into ``minute_bars``.

    python scripts/daily.py groww-intraday                              # catch up every stock
    python scripts/daily.py groww-intraday --symbols RELIANCE,TCS
    python scripts/daily.py groww-intraday --full --intraday-days 100   # re-fetch 100 days, replacing what is stored

Why Groww: its bars carry the same labels, closes and volumes as Kite's (volume 99.8% equal, close
92.7%), while Dhan's minute bars do not (docs/PROVIDER_COMPARISON_LOG.md, 2026-11-07). It needs no
daily login, unlike Kite.

What is kept: 09:15-15:14 only. Groww also sends a pre-open bar (09:0x, volume only) and bars from
15:15 to 15:59 (closing auction session and after); they are dropped. Groww's first bar opens at the
first continuous trade, so the 09:15 bar's open is replaced by the day's official open from
``daily_bars`` (the Dhan daily job runs first) - see ``market.intraday_store.groww_minute_rows``.

Cost: Groww serves at most 30 days of 1-minute bars per call, one stock per call, so a daily
catch-up is one call per stock (~220 calls; Groww allows 10/s). Each day Groww returns replaces
that day's stored bars for the stock, so no bar from another source survives inside a fetched day.
Re-runs restart from each stock's last stored day.

Writes ``minute_bars`` in data/market.db. Read-only against the broker: no orders, no account data.
"""

import logging
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from market import state_store
from market.fno_movers import load_universe
from market.intraday_store import (
    connect,
    groww_minute_rows,
    last_minute,
    replace_days,
    upsert_minutes,
)
from market.market_hours import now_ist

logger = logging.getLogger("groww_intraday")

#: Widest 1-minute window Groww serves in one call (docs/api/GROWW_API_LIVE_DATA.md).
MAX_MINUTE_DAYS = 30
#: Groww allows 10 requests/s on market data; stay well under it.
MIN_INTERVAL = 0.2
#: A day is complete once the session has closed.
SETTLED_AFTER = (15, 30)
STAMP = "%Y-%m-%d %H:%M:%S"


def add_arguments(parser) -> None:
    group = parser.add_argument_group("groww-intraday")
    group.add_argument("--intraday-days", type=int, default=30,
                       help="Calendar days for a stock with no bars, or the --full window (default 30)")


def windows(first: date, last: date, days: int = MAX_MINUTE_DAYS):
    """``(start, end)`` datetimes covering ``first..last``, at most ``days`` dates each."""
    cursor = first
    while cursor <= last:
        stop = min(cursor + timedelta(days=days - 1), last)
        yield datetime.combine(cursor, dtime(9, 0)), datetime.combine(stop, dtime(16, 0))
        cursor = stop + timedelta(days=1)


def fetch(session, symbol: str, start: datetime, end: datetime):
    """One Groww request, retried twice: its history endpoint times out now and then."""
    for attempt in range(3):
        time.sleep(MIN_INTERVAL)
        try:
            body = session.get_historical_candles("NSE", "CASH", f"NSE-{symbol}", start.strftime(STAMP),
                                                  end.strftime(STAMP), "1minute", timeout=30)
            return (body or {}).get("candles") or []
        except Exception as exc:  # noqa: BLE001 - the SDK raises its own types
            if attempt == 2:
                raise
            logger.debug("  %s: retrying after %s", symbol, exc)
            time.sleep(3)
    return []


def official_opens(conn, symbol: str, first: date):
    return dict(conn.execute("SELECT date, open FROM daily_bars WHERE symbol = ? AND date >= ?",
                             (symbol, first.isoformat())))


def run(args) -> int:
    from groww_api import GrowwAPIClient

    tokens = load_universe().tokens
    if not tokens:
        logger.error("No F&O universe stored - run scripts/kite.py history or scripts/dhan.py --master first.")
        return 1
    symbols = sorted(tokens)
    if args.symbols:
        asked = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        symbols = [s for s in symbols if s in asked]

    client = GrowwAPIClient.get_instance()
    if not client.is_connected:
        logger.error("Groww is not connected: %s", client.auth_error or "check GROWW_API_KEY / GROWW_TOTP_SECRET")
        return 1
    session = client.session

    now = now_ist()
    today = now.date()
    default_first = today - timedelta(days=args.intraday_days - 1)

    conn = connect(args.db or state_store.db_path())
    logger.info("Fetching Groww 1-minute bars for %d stocks ...", len(symbols))
    started = time.monotonic()
    calls, bars_total, failed, no_open = 0, 0, [], 0
    for i, symbol in enumerate(symbols, 1):
        last = None if args.full else last_minute(conn, symbol)
        first = date.fromisoformat(last[:10]) if last else default_first
        opens = official_opens(conn, symbol, first)
        try:
            rows = []
            for lo, hi in windows(first, today):
                rows += groww_minute_rows(symbol, fetch(session, symbol, lo, hi), opens)
                calls += 1
        except Exception as exc:  # noqa: BLE001 - one stock must not stop the run
            failed.append(symbol)
            logger.warning("  %s: %s", symbol, exc)
            continue
        days = {row[1][:10] for row in rows}
        no_open += len(days - set(opens))
        with conn:
            replace_days(conn, "minute_bars", symbol, days)
            upsert_minutes(conn, rows)
        bars_total += len(rows)
        if i % 25 == 0 or i == len(symbols):
            logger.info("  %d/%d  (%s: %d bars, %d days)  %.0f s", i, len(symbols), symbol, len(rows), len(days),
                        time.monotonic() - started)

    bars, stocks, first_bar, last_bar = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(ts), MAX(ts) FROM minute_bars").fetchone()
    conn.close()
    logger.info("Done in %.0f s, %d requests, %d bars written. minute_bars holds %d bars for %d stocks (%s .. %s).",
                time.monotonic() - started, calls, bars_total, bars, stocks, first_bar, last_bar)
    if (now.hour, now.minute) < SETTLED_AFTER and now.weekday() < 5:
        logger.info("The session is still open: today's bars are partial and are completed on the next run.")
    if no_open:
        logger.info("%d stock-day(s) had no daily candle stored, so Groww's own 09:15 open was kept.", no_open)
    if failed:
        logger.warning("%d stock(s) failed and can be retried by re-running: %s", len(failed), ", ".join(failed))
        return 2 if bars_total else 1
    return 0
