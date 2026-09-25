"""Build / extend the F&O daily-close history the movers dashboard reads.

    python scripts/update_fno_history.py              # last 30 days for every F&O stock
    python scripts/update_fno_history.py --days 400   # backfill ~a year (same cost)
    python scripts/update_fno_history.py --symbols RELIANCE,TCS
    python scripts/update_fno_history.py --full --days 60   # re-fetch stored days too (after a split)

Run it once to backfill, then once a day after 16:00 IST (or weekly - one run
fills every missing day). It needs today's Kite session
(``python scripts/kite_login.py``).

Cost: **one request per stock, however many days**. Kite's daily-candle
endpoint takes one instrument per call but any date range, so a 7-day catch-up
and a 1-year backfill both cost ~210 requests - about 75 s at Kite's 3 req/s.
That per-stock cost is the whole reason to store the history: afterwards the
dashboard needs no API call for past days, and one bulk quote for today.

Writes (both git-friendly, both only ever written here):
  data/fno_universe.json      F&O stocks + Kite instrument tokens (from public dumps)
  data/fno_daily_closes.csv   date,symbol,open,high,low,close,volume

Today's candle is stored only after 16:00 IST; before that its "close" is just
the live price. Every run re-fetches from each stock's last stored day, so a
value that settled late is corrected on the next run.

Read-only: no orders, no account data.
"""

import argparse
import logging
import os
import sys
import time
from datetime import timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from market.fno_movers import (  # noqa: E402
    CLOSES_PATH,
    UNIVERSE_PATH,
    build_universe,
    candle_rows,
    load_closes,
    save_closes,
    save_universe,
    upsert_closes,
)
from market.market_hours import now_ist  # noqa: E402

logger = logging.getLogger("update_fno_history")

DUMP_URL = "https://api.kite.trade/instruments/{exchange}"
#: Today's candle is trusted as the close only after this IST time.
SETTLED_AFTER = (16, 0)


def download_dump(exchange: str) -> str:
    response = requests.get(DUMP_URL.format(exchange=exchange), headers={"X-Kite-Version": "3"}, timeout=120)
    response.raise_for_status()
    return response.content.decode("utf-8-sig")


def fetch_candles(provider, token: str, start: str, end: str):
    """One stock's daily candles, retried twice on a network error."""
    params = {"from": f"{start} 00:00:00", "to": f"{end} 23:59:59"}
    for attempt in range(3):
        try:
            status, body = provider._get(f"/instruments/historical/{token}/day", params, "historical")
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logger.debug("retrying after %s", exc)
            time.sleep(2)
            continue
        if status == 200:
            return (body.get("data") or {}).get("candles") or []
        raise RuntimeError(f"HTTP {status}: {body.get('error_type', '')} {body.get('message', '')}".strip())
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="Calendar days to fetch for a stock with no history")
    parser.add_argument("--full", action="store_true",
                        help="Re-fetch the whole --days window even where rows are stored (refreshes split-adjusted closes)")
    parser.add_argument("--symbols", help="Comma-separated subset (default: every F&O stock)")
    parser.add_argument("--closes", default=CLOSES_PATH)
    parser.add_argument("--universe", default=UNIVERSE_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("market").setLevel(logging.WARNING)

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"), override=True)
    except ImportError:
        pass

    from market.providers.kite import KiteProvider

    logger.info("Downloading Kite's public NFO and NSE instrument lists ...")
    try:
        tokens, unmatched = build_universe(download_dump("NFO"), download_dump("NSE"))
    except requests.RequestException as exc:
        logger.error("Could not download the instrument lists: %s", exc)
        return 1
    if not tokens:
        logger.error("No F&O stocks found - refusing to overwrite %s", args.universe)
        return 1
    save_universe(tokens, unmatched, args.universe)
    logger.info("  %d F&O stocks -> %s (%d index futures skipped: %s)",
                len(tokens), args.universe, len(unmatched), ", ".join(unmatched))

    if args.symbols:
        wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in tokens]
        if unknown:
            logger.warning("Not F&O stocks, skipped: %s", ", ".join(unknown))
        tokens = {s: tokens[s] for s in wanted if s in tokens}

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

    rows = load_closes(args.closes)
    last_by_symbol = {}
    for day, symbol in rows:
        if day > last_by_symbol.get(symbol, ""):
            last_by_symbol[symbol] = day

    logger.info("Fetching daily candles for %d stocks (~%.0f s) ...", len(tokens), len(tokens) * 0.36)
    started = time.monotonic()
    changed, failed = 0, []
    for i, (symbol, token) in enumerate(sorted(tokens.items()), 1):
        last = last_by_symbol.get(symbol)
        start = last if last and not args.full else (today - timedelta(days=args.days)).isoformat()
        try:
            candles = fetch_candles(provider, token, start, today.isoformat())
        except Exception as exc:  # noqa: BLE001 - one stock must not stop the run
            failed.append(symbol)
            logger.warning("  %s: %s", symbol, exc)
            continue
        changed += upsert_closes(rows, candle_rows(symbol, candles, exclude_date=exclude))
        if i % 50 == 0:
            logger.info("  %d/%d", i, len(tokens))

    save_closes(rows, args.closes)
    days = sorted({d for d, _ in rows})
    logger.info(
        "Done in %.0f s: %d rows added/updated, %d stocks x %d days in %s (%s .. %s)",
        time.monotonic() - started, changed, len({s for _, s in rows}), len(days),
        args.closes, days[0] if days else "-", days[-1] if days else "-",
    )
    if not settled:
        logger.info("Today's candle was left out (before %02d:%02d IST it is only the live price).", *SETTLED_AFTER)
    if failed:
        logger.warning("%d stock(s) failed and can be retried by re-running: %s", len(failed), ", ".join(failed))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
