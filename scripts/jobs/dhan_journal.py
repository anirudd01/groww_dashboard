"""Sync the Dhan trade journal: fills and ledger into data/market.db.

    python scripts/dhan.py --journal                      # from a few days before the last sync to today
    python scripts/dhan.py --journal --since 2026-04-01   # refetch from a date

The first sync starts at the beginning of the financial year. Each later one refetches the last few
days (Dhan can correct a day's fills) and replaces them, so running it twice changes nothing. Today's
fills have no charges until the next day's sync. The Journal page's "Sync now" button runs the same
code. See market/dhan_journal.py and docs/DHAN_JOURNAL.md.

Reads account statements only: no orders. Needs the Dhan credentials in .env.
"""

from datetime import date

from market import dhan_journal as journal
from market.market_hours import now_ist


def add_arguments(parser) -> None:
    group = parser.add_argument_group("journal")
    group.add_argument("--journal", action="store_true", help="Only sync the trade journal (fills and ledger)")
    group.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD",
                       help="With --journal: refetch from this date instead of the last few days")


def run(args) -> int:
    try:
        account = journal.DhanAccount()
        result = journal.sync(account, now_ist().date(), since=args.since)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"Journal sync failed: {exc}")
        return 1
    print(f"Stored {result.summary()}.")
    return 2 if result.price_error else 0
