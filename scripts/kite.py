"""Everything this project fetches from Zerodha Kite, in one command.

    python scripts/kite.py                    # daily: F&O close history, then the 1-minute backfill
    python scripts/kite.py history            # just one data job (history | intraday)
    python scripts/kite.py --master           # refresh the reference data first, then the data jobs
    python scripts/kite.py --master-only      # only the reference data (needs no Kite login)

Jobs, in the order they run:

  --master   NSE index constituents   -> index_constituents  (jobs/index_constituents.py)
             Kite instrument ids      -> kite_instruments    (jobs/kite_instruments.py)
  history    F&O universe + daily closes -> fno_universe, daily_bars  (jobs/fno_history.py)
  intraday   1-minute bars + daily bars  -> minute_bars, daily_bars   (jobs/intraday.py)

Run the data jobs once a day after 16:00 IST (or weekly - one run fills every missing day);
run ``--master`` about monthly, after an NSE index reconstitution, or when a symbol stops
resolving. The data jobs need today's Kite session (``python scripts/kite_login.py``); the
reference data is public and needs none.

The F&O stock list is refreshed by ``history`` on every run, not only with ``--master``:
it costs two small public downloads and keeps a newly listed F&O stock from being missed.

A failing job is reported and the next one still runs. Exit code: 0 all ok, 2 something
partly done (some symbols failed), 1 a job failed. Read-only: no orders, no account data.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs import common  # noqa: E402  (sets up the import path)

DATA_JOBS = ("history", "intraday")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jobs", nargs="*", metavar="JOB",
                        help=f"Data jobs to run: {', '.join(DATA_JOBS)} (default: all)")
    master = parser.add_mutually_exclusive_group()
    master.add_argument("--master", action="store_true", help="Refresh the reference data, then run the data jobs")
    master.add_argument("--master-only", action="store_true", help="Refresh the reference data and stop")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument("--keep-raw", action="store_true", help="--master: also save Kite's unedited CSV under data/instruments/")
    data = parser.add_argument_group("data jobs")
    data.add_argument("--symbols", help="Comma-separated subset of F&O stocks (default: all)")
    data.add_argument("--full", action="store_true", help="Re-fetch the whole window even where rows are stored (after a split)")
    data.add_argument("--history-days", type=int, default=30, help="history: calendar days for a stock with no history (default 30)")
    data.add_argument("--fix-splits", action="store_true",
                      help="history: re-fetch only the stocks with a split-like fall, and report which were corporate actions")
    data.add_argument("--intraday-days", type=int, default=60, help="intraday: calendar days for a stock with no bars (default 60)")
    args = parser.parse_args(argv)
    unknown = [job for job in args.jobs if job not in DATA_JOBS]
    if unknown:
        parser.error(f"unknown job {', '.join(unknown)} (choose from {', '.join(DATA_JOBS)})")
    if args.master_only and args.jobs:
        parser.error("--master-only runs no data jobs; drop the job names or use --master")
    args.db = None
    return args


def kite_session_error():
    """Why the data jobs cannot run, or None when today's Kite session is there."""
    from market.providers.kite import KiteProvider

    provider = KiteProvider()
    if not provider.is_configured():
        return "No Kite session for today - run 'python scripts/kite_login.py' first."
    try:
        provider.connect()
    except RuntimeError as exc:
        return str(exc)
    return None


def main(argv=None) -> int:
    args = parse_args(argv)
    common.setup(args.verbose)
    from jobs import fno_history, index_constituents, intraday, kite_instruments

    plan = []
    if args.master or args.master_only:
        plan += [("NSE index constituents", lambda: index_constituents.run(args.db)),
                 ("Kite instrument ids", lambda: kite_instruments.run(args))]
    if not args.master_only:
        wanted = args.jobs or list(DATA_JOBS)
        jobs = {"history": ("F&O daily close history", lambda: fno_history.run(args)),
                "intraday": ("1-minute backfill", lambda: intraday.run(args))}
        error = kite_session_error()
        if error:
            # Reported in its place in the run, once, instead of by every data job.
            def no_session():
                common.logger.error("%s Skipped: %s.", error, ", ".join(wanted))
                return 1

            plan.append(("Kite data jobs", no_session))
        else:
            plan += [jobs[name] for name in DATA_JOBS if name in wanted]
    return common.run_jobs(plan)


if __name__ == "__main__":
    raise SystemExit(main())
