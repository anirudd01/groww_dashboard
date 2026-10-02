"""Save the close of Dhan's stock gainers and losers to the SQLite database, so there is a history.

    python scripts/store_dhan_movers.py --dry-run      # fetch and show, write nothing (any time)
    python scripts/store_dhan_movers.py                # store the latest finished session's close
    python scripts/store_dhan_movers.py --top 20 --universes "Nifty 50,Nifty Bank"
    python scripts/store_dhan_movers.py --intraday --every 15   # also snapshots while open (off by default)

Dhan's ranking endpoint only answers "today against the previous close", so a history exists
only if it is saved as it happens. Each capture adds to two tables of data/market.db (git-ignored,
shared with the F&O history; see market/dhan_movers_store.py), in one transaction:

  dhan_movers          one row per ranked stock: session date, universe, gainer/loser, rank, symbol, price, % change
  dhan_movers_breadth  one row per universe: how many stocks are up and down

Volume and open interest are left out. See market/dhan_movers_history.py for the columns and
docs/DHAN_MOVERS.md for how to read the files.

The date in the files is the session the prices belong to, not the day the script ran. Dhan
answers with the last session at the weekend, on a holiday and before the open, so the date is
read from the feed (the latest trade time of a few heavy stocks). Run on a Saturday it files
Friday; run on a holiday it files the day before. The close is stored once per session date,
and not before 16:00 IST on a trading day (the figures settle after 15:30).

Each universe is two calls (~21 universes, ~1.1 s per call), so a capture takes about 50 s.
Run it once a day after 16:00, or any time later: one run stores the latest finished session.
Needs the Dhan credentials in .env, like the dashboards.

Read-only: it calls one ranking endpoint and places no orders. Never prints tokens.
"""

import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except ImportError:
    pass

from market import dhan_movers_history as history  # noqa: E402
from market import dhan_movers_store as store  # noqa: E402
from market.market_hours import now_ist  # noqa: E402

DEFAULT_UNTIL = "16:05"
#: Dhan returns at most 100 per side and has no paging, so 100 keeps everything it gives.
DEFAULT_TOP = 100


def until_today(text: str):
    hour, minute = (int(part) for part in text.split(":"))
    return now_ist().replace(hour=hour, minute=minute, second=0, microsecond=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help=f"Stocks kept per side per universe (default {DEFAULT_TOP}, which is the most Dhan returns)")
    parser.add_argument("--universes", help="Comma-separated universe keys or labels (default: all of them)")
    parser.add_argument("--intraday", action="store_true", help="Also store snapshots while the market is open (off by default)")
    parser.add_argument("--every", type=int, metavar="MINUTES", help="With --intraday, keep capturing at this interval")
    parser.add_argument("--until", default=DEFAULT_UNTIL, help=f"With --every, stop at this IST time (default {DEFAULT_UNTIL})")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarise, but write nothing and ignore the session")
    args = parser.parse_args()
    if not 1 <= args.top <= 100:
        parser.error("--top must be between 1 and 100")
    if args.every is not None and not args.intraday:
        parser.error("--every needs --intraday: without it only the close is stored, once per session")
    if args.every is not None and args.every < 2:
        parser.error("--every must be at least 2 minutes: one capture already takes about 50 s")
    try:
        universes = history.resolve_universes(args.universes.split(",") if args.universes else None)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.WARNING)

    from market.providers.dhan import DhanProvider

    provider = DhanProvider()
    try:
        if not provider.is_configured():
            print("Dhan is not configured - set DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in .env.")
            return 2
        provider.connect()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"Could not connect to Dhan: {exc}")
        return 2

    db_path = os.path.join(ROOT, store.DB_PATH)
    stop_at = until_today(args.until) if args.every else None

    while True:
        now = now_ist()
        result = history.capture(provider, universes, top=args.top, now=now, intraday=args.intraday, db_path=db_path,
                                 dry_run=args.dry_run)
        print(f"{now:%a %d %b %H:%M:%S} IST  {result.status.upper():8} {result.message}")
        for universe, error in result.failed:
            print(f"    {universe}: {error}")
        if result.status in (history.DRY_RUN, history.STORED):
            for row in result.breadth_rows:
                print(f"    {row['universe']:20} advancing {row['advancing']:>3}{'+' if row['advancing_capped'] else ' '}"
                      f"  declining {row['declining']:>3}{'+' if row['declining_capped'] else ' '}")

        if not args.every:
            return 1 if result.status == history.FAILED else 0
        done = result.kind == history.KIND_CLOSE and result.status in (history.STORED, history.SKIPPED)
        if done or now.weekday() >= 5 or now_ist() >= stop_at:
            return 0
        wait = min(args.every * 60, max((stop_at - now_ist()).total_seconds(), 0))
        print(f"    next capture in {wait / 60:.0f} min (Ctrl+C to stop)")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("Stopped.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
