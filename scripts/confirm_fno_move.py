"""Tell the F&O pages that a big fall was a real move, not a split or bonus.

    python scripts/confirm_fno_move.py suspected                       # what the pages flag right now
    python scripts/confirm_fno_move.py list                            # what has been confirmed
    python scripts/confirm_fno_move.py add POLICYBZR 2026-09-24 "Real fall, about 40% in 20 days"
    python scripts/confirm_fno_move.py remove POLICYBZR 2026-09-24     # flag it again

The F&O pages flag a one-day fall whose size matches a split or bonus ratio (1/2, 2/3, 1/10, ...),
because Kite adjusts its candles after the ex-date but rows already stored keep the old prices.
A match is only a suspicion: a demerger, a buyback or a genuine crash can look the same. Check one
(``python scripts/update_fno_history.py --fix-splits`` re-fetches the suspects: if Kite's adjusted
candles remove the jump it was a corporate action, otherwise it stays a fall), and if it is a real
move, ``add`` it here with the reason. The note is what a later reader sees.

The confirmations are the ``fno_confirmed_moves`` set in the shared database data/market.db.
Read-only against Kite: it calls no broker.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market.fno_movers import (  # noqa: E402
    confirm_move,
    confirmed_moves,
    load_closes,
    load_confirmed_moves,
    suspected_corporate_actions,
    unconfirm_move,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("suspected", help="Falls the pages currently flag as a possible split or bonus")
    commands.add_parser("list", help="Falls confirmed as real moves")
    add = commands.add_parser("add", help="Confirm a fall as a real move")
    add.add_argument("symbol")
    add.add_argument("date", help="YYYY-MM-DD, the day of the fall")
    add.add_argument("why", help="Why it is a real move (in quotes)")
    remove = commands.add_parser("remove", help="Take a confirmation back, so the fall is flagged again")
    remove.add_argument("symbol")
    remove.add_argument("date")
    args = parser.parse_args()

    if args.command == "suspected":
        rows = load_closes()
        if not rows:
            print("No closes stored yet: run 'python scripts/update_fno_history.py'.")
            return 1
        found = suspected_corporate_actions(rows, load_confirmed_moves())
        if not found:
            print("Nothing is flagged.")
        for action in found:
            print(f"{action.symbol:12} {action.date}  {action.change_pct:+6.1f}%  {action.label}")
        return 0

    if args.command == "list":
        moves = confirmed_moves()
        if not moves:
            print("Nothing confirmed.")
        for symbol, days in sorted(moves.items()):
            for day, why in sorted(days.items()):
                print(f"{symbol:12} {day}  {why}")
        return 0

    if args.command == "add":
        try:
            confirm_move(args.symbol, args.date, args.why)
        except ValueError as exc:
            print(f"Not saved: {exc}")
            return 1
        print(f"Confirmed {args.symbol.upper()} {args.date} as a real move; the pages stop flagging it.")
        return 0

    if unconfirm_move(args.symbol, args.date):
        print(f"Removed. {args.symbol.upper()} {args.date} is flagged again if it still looks like a split.")
        return 0
    print(f"{args.symbol.upper()} {args.date} was not confirmed, so there is nothing to remove.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
