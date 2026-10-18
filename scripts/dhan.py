"""Everything this project fetches from Dhan, in one command.

    python scripts/dhan.py                    # daily: store the close of Dhan's gainers and losers
    python scripts/dhan.py --dry-run          # fetch and show the movers, write nothing
    python scripts/dhan.py --master           # refresh the reference data first, then the movers
    python scripts/dhan.py --master-only      # only the reference data
    python scripts/dhan.py --journal          # only the trade journal: your fills and ledger

Jobs, in the order they run:

  --master   NSE index constituents  -> index_constituents  (jobs/index_constituents.py)
             Dhan instrument ids     -> dhan_instruments    (jobs/dhan_instruments.py)
             MCX futures contracts   -> mcx_futures         (jobs/mcx_futures.py)
             free-float weights      -> index_weights       (jobs/index_weights.py)
  movers     gainers/losers close    -> dhan_movers, dhan_movers_breadth  (jobs/dhan_movers.py)
  --journal  your fills and ledger   -> dhan_fills, dhan_ledger           (jobs/dhan_journal.py)

Dhan's instrument master (35 MB) is downloaded once and read by both the instrument ids and
the MCX futures. Run the movers once a day after 16:00 IST (or any time later - one run stores
the latest finished session); run ``--master`` about monthly, after an NSE index reconstitution,
or when a symbol stops resolving. The weights and the movers need the Dhan credentials in
``.env``; the instrument master and NSE's lists are public.

A failing job is reported and the next one still runs. Exit code: 0 all ok, 2 something
partly done, 1 a job failed. Read-only: no orders. Only ``--journal`` reads account data (your
trade history and ledger); run it after the close, or use the Journal page's "Sync now".
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs import common  # noqa: E402  (sets up the import path)
from jobs import dhan_journal, dhan_movers  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    master = parser.add_mutually_exclusive_group()
    master.add_argument("--master", action="store_true", help="Refresh the reference data, then store the movers")
    master.add_argument("--master-only", action="store_true", help="Refresh the reference data and stop")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument("--keep-raw", action="store_true", help="--master: also save Dhan's unedited CSV under data/instruments/")
    parser.add_argument("--use-cached", action="store_true", help="--master: reuse today's saved CSV instead of downloading")
    dhan_movers.add_arguments(parser)
    dhan_journal.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.journal and (args.master or args.master_only):
        parser.error("--journal runs on its own; run --master separately")
    if args.since and not args.journal:
        parser.error("--since needs --journal")
    dhan_movers.check_arguments(args, parser)
    args.db = None
    return args


def master_jobs(args):
    """The reference-data jobs, sharing one download of Dhan's master."""
    from jobs import dhan_instruments, index_constituents, index_weights, mcx_futures

    master = {}

    def instruments():
        master["text"] = dhan_instruments.download(use_cached=args.use_cached, keep_raw=args.keep_raw)
        return dhan_instruments.run(args, master["text"])

    def mcx():
        if "text" not in master:
            common.logger.error("Dhan's instrument master was not downloaded - skipping.")
            return 1
        return mcx_futures.run(args, master["text"])

    return [("NSE index constituents", lambda: index_constituents.run(args.db)),
            ("Dhan instrument ids", instruments),
            ("MCX futures contracts", mcx),
            ("Free-float weights", lambda: index_weights.run(args))]


def main(argv=None) -> int:
    args = parse_args(argv)
    common.setup(args.verbose)
    if args.journal:
        return common.run_jobs([("Dhan trade journal", lambda: dhan_journal.run(args))])
    plan = master_jobs(args) if args.master or args.master_only else []
    if not args.master_only:
        plan.append(("Dhan movers close", lambda: dhan_movers.run(args)))
    return common.run_jobs(plan)


if __name__ == "__main__":
    raise SystemExit(main())
