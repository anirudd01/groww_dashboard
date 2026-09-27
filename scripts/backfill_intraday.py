"""Backfill 1-minute bars and daily open/close for every F&O stock into SQLite.

    python scripts/backfill_intraday.py                  # last 60 days, all F&O stocks
    python scripts/backfill_intraday.py --symbols RELIANCE,TCS
    python scripts/backfill_intraday.py --days 120       # older history: 2 calls per stock
    python scripts/backfill_intraday.py --full           # re-fetch stored days too (after a split)

Needs today's Kite session (``python scripts/kite_login.py``) and
``data/fno_universe.json`` (``python scripts/update_fno_history.py``).

Cost: Kite returns at most **60 days of 1-minute bars per call**, one stock per
call (a 61-day window is rejected with 400; tested 2026-09-27). So a 60-day
backfill is one minute call plus one daily call per stock - ~420 requests,
about 4-5 minutes at Kite's 3 req/s. Why Kite and not Groww, INDmoney or
Dhan: docs/PROVIDER_COMPARISON_LOG.md (2026-09-27).

Re-runs are incremental: each stock restarts from its last stored bar, so a
daily or weekly run costs the same ~420 requests and fills every missing day.
Everything is an upsert, and each stock is committed as it finishes, so an
interrupted run loses nothing - re-run it.

Writes data/market.db (git-ignored; see market/intraday_store.py for the
schema). Read-only against the broker: no orders, no account data.
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from market.fno_movers import UNIVERSE_PATH, load_universe  # noqa: E402
from market.intraday_store import (  # noqa: E402
    DB_PATH,
    connect,
    kite_daily_rows,
    kite_minute_rows,
    last_minute,
    summary,
    upsert_daily,
    upsert_minutes,
)
from market.market_hours import now_ist  # noqa: E402

logger = logging.getLogger("backfill_intraday")

#: Widest 1-minute window Kite accepts in one call (61 days -> HTTP 400).
MAX_MINUTE_DAYS = 60
#: Today's daily candle is trusted as the close only after this IST time.
SETTLED_AFTER = (16, 0)
STAMP = "%Y-%m-%d %H:%M:%S"
#: Bars outside this span do not exist on Kite (pre-open is 09:00-09:08).
SESSION_START, SESSION_END = dtime(9, 0), dtime(16, 0)


def windows(first: date, last: date, days: int = MAX_MINUTE_DAYS):
    """Session windows covering the dates ``first..last``, at most ``days`` dates each.

    Each window runs 09:00 on its first date to 16:00 on its last, so 60 dates
    span 59 days 7 hours - inside Kite's limit however it counts.
    """
    cursor = first
    while cursor <= last:
        stop = min(cursor + timedelta(days=days - 1), last)
        yield (datetime.combine(cursor, SESSION_START), datetime.combine(stop, SESSION_END))
        cursor = stop + timedelta(days=1)


def fetch(provider, token: str, interval: str, start: datetime, end: datetime):
    """One Kite candle request, retried twice on a network error or 5xx."""
    params = {"from": start.strftime(STAMP), "to": end.strftime(STAMP)}
    for attempt in range(3):
        try:
            status, body = provider._get(f"/instruments/historical/{token}/{interval}", params, "historical")
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logger.debug("retrying after %s", exc)
            time.sleep(2)
            continue
        if status == 200:
            return (body.get("data") or {}).get("candles") or []
        if status >= 500 and attempt < 2:
            time.sleep(2)
            continue
        raise RuntimeError(f"HTTP {status}: {body.get('error_type', '')} {body.get('message', '')}".strip())
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=MAX_MINUTE_DAYS,
                        help="Calendar days to fetch for a stock with no stored bars (default 60)")
    parser.add_argument("--full", action="store_true", help="Re-fetch the whole --days window even where bars are stored")
    parser.add_argument("--symbols", help="Comma-separated subset (default: every F&O stock)")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--universe", default=UNIVERSE_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("market").setLevel(logging.WARNING)

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"), override=True)
    except ImportError:
        pass

    universe = load_universe(args.universe)
    if not universe.tokens:
        logger.error("%s", universe.error)
        return 1
    tokens = universe.tokens
    if args.symbols:
        wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in tokens]
        if unknown:
            logger.warning("Not F&O stocks, skipped: %s", ", ".join(unknown))
        tokens = {s: tokens[s] for s in wanted if s in tokens}

    from market.providers.kite import KiteProvider

    provider = KiteProvider()
    if not provider.is_configured():
        logger.error("No Kite session for today - run 'python scripts/kite_login.py' first.")
        return 1
    try:
        provider.connect()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    now = now_ist()
    today = now.date()
    settled = (now.hour, now.minute) >= SETTLED_AFTER
    exclude = None if settled else today.isoformat()
    # --days 60 means 60 calendar dates including today: one call per stock.
    default_first = today - timedelta(days=args.days - 1)

    conn = connect(args.db)
    logger.info("Fetching 1-minute + daily candles for %d stocks into %s ...", len(tokens), args.db)
    started = time.monotonic()
    calls, failed = 0, []
    for i, (symbol, token) in enumerate(sorted(tokens.items()), 1):
        last = None if args.full else last_minute(conn, symbol)
        # Restart from the start of the last stored day, so a day fetched
        # while the session was open is completed on the next run.
        first = date.fromisoformat(last[:10]) if last else default_first
        try:
            bars = 0
            for lo, hi in windows(first, today):
                rows = kite_minute_rows(symbol, fetch(provider, token, "minute", lo, hi))
                calls += 1
                upsert_minutes(conn, rows)
                bars += len(rows)
            daily_window = (datetime.combine(first, SESSION_START), datetime.combine(today, SESSION_END))
            daily = kite_daily_rows(symbol, fetch(provider, token, "day", *daily_window), exclude_date=exclude)
            calls += 1
            upsert_daily(conn, daily)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - one stock must not stop the run
            conn.rollback()
            failed.append(symbol)
            logger.warning("  %s: %s", symbol, exc)
            continue
        if i % 25 == 0 or i == len(tokens):
            logger.info("  %d/%d  (%s: %d bars, %d days)  %.0f s", i, len(tokens), symbol, bars,
                        len(daily), time.monotonic() - started)

    stats = summary(conn)
    conn.close()
    logger.info(
        "Done in %.0f s, %d requests. %s: %d minute bars for %d stocks (%s .. %s), %d daily bars (%s .. %s)",
        time.monotonic() - started, calls, args.db, stats["minute_bars"], stats["symbols"],
        stats["first_bar"], stats["last_bar"], stats["daily_bars"], stats["first_day"], stats["last_day"],
    )
    if not settled:
        logger.info("Today's daily candle was left out (before %02d:%02d IST it is only the live price).", *SETTLED_AFTER)
    if failed:
        logger.warning("%d stock(s) failed and can be retried by re-running: %s", len(failed), ", ".join(failed))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
