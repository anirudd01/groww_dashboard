"""The daily market-data jobs, in one command: what the server runs unattended after the close.

    python scripts/daily.py                      # all jobs below, in order
    python scripts/daily.py dhan-daily movers    # just some of them
    python scripts/daily.py dhan-daily --full --daily-days 1830      # 5-year refetch of the daily history
    python scripts/daily.py groww-intraday --full --intraday-days 100

Jobs, in the order they run:

  dhan-daily      daily candles (raw prices)  -> daily_bars           (jobs/dhan_daily.py)
  groww-intraday  1-minute bars 09:15-15:14   -> minute_bars          (jobs/groww_intraday.py)
  movers          Dhan gainers/losers close   -> dhan_movers, dhan_movers_breadth  (jobs/dhan_movers.py)

Source per table (decided 2026-11-07, evidence in docs/PROVIDER_COMPARISON_LOG.md): Dhan for daily
candles, Groww for 1-minute bars. Neither needs a daily login, so the run is unattended. Kite is
not part of it; ``scripts/kite.py`` still works by hand.

dhan-daily runs before groww-intraday because the minute job takes each day's official open from
``daily_bars``. Run once a day after 16:00 IST (or later: every job catches up missing days).

A failing job is reported and the next one still runs. Exit code: 0 all ok, 2 something partly
done, 1 a job failed. Read-only: no orders, no account data.

``--scheduled`` is how the server runs it (scripts/job_trigger.py). It adds two things a manual
run does not want:

* It first asks the broker whether NSE traded today (scripts never read a holiday calendar; see
  market/exchange_status.py). Only when three checks a minute apart all say "no trade today" is
  the run skipped, as a success. A failed check counts as "maybe": the jobs run.
* A job that fails is run again at most twice, 10 minutes apart. Never more: a job that fails
  because the broker has no data must give up rather than loop.
"""

import argparse
import logging
import os
import sys
import time
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs import common  # noqa: E402  (sets up the import path)
from jobs import dhan_daily, dhan_movers, groww_intraday  # noqa: E402

JOBS = ("dhan-daily", "groww-intraday", "movers")

#: Scheduled runs: re-runs of a failed job, and the wait before each.
RETRIES, RETRY_GAP_S = 2, 600
#: Scheduled runs: no retry may run past this many seconds after the start. The trigger kills a run
#: at 45 minutes (scripts/job_trigger.py TIMEOUT_S); this leaves a margin.
RUN_BUDGET_S = 40 * 60
#: Scheduled runs: "did NSE trade today?" checks before skipping, and the wait between them.
MARKET_CHECKS, MARKET_CHECK_GAP_S = 3, 60

logger = logging.getLogger("jobs")


def nse_traded_today(probe: Optional[Callable] = None, checks: int = MARKET_CHECKS,
                     gap: float = MARKET_CHECK_GAP_S, sleep: Callable[[float], None] = time.sleep) -> Optional[bool]:
    """True / False from the broker, or None when it could not say (then the jobs should run).

    False only when every one of ``checks`` fresh answers says so: one bad reply must not cost
    a day. Any True ends the checking at once.
    """
    from market import exchange_status

    status = exchange_status.ExchangeStatus(probe=probe, ttl=0)  # ttl 0: every check asks afresh
    verdicts = []
    for attempt in range(checks):
        if attempt:
            sleep(gap)
        verdict = status.traded_today(exchange_status.NSE)
        logger.info("NSE trading today? check %d of %d: %s", attempt + 1, checks,
                    {True: "yes", False: "no trade today"}.get(verdict, "could not tell"))
        if verdict is True:
            return True
        verdicts.append(verdict)
    return False if all(v is False for v in verdicts) else None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jobs", nargs="*", metavar="JOB", help=f"Jobs to run: {', '.join(JOBS)} (default: all)")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument("--scheduled", action="store_true",
                        help="Server mode: skip a day NSE did not trade, retry a failed job up to twice")
    parser.add_argument("--symbols", help="dhan-daily / groww-intraday: comma-separated subset of stocks")
    parser.add_argument("--full", action="store_true",
                        help="dhan-daily / groww-intraday: re-fetch the whole window and replace what is stored")
    dhan_daily.add_arguments(parser)
    groww_intraday.add_arguments(parser)
    dhan_movers.add_arguments(parser)
    args = parser.parse_args(argv)
    unknown = [job for job in args.jobs if job not in JOBS]
    if unknown:
        parser.error(f"unknown job {', '.join(unknown)} (choose from {', '.join(JOBS)})")
    if args.full and not ({"dhan-daily", "groww-intraday"} & set(args.jobs)):
        parser.error("--full re-fetches history: name the job (dhan-daily or groww-intraday) to be sure")
    dhan_movers.check_arguments(args, parser)
    args.db = None
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    common.setup(args.verbose)
    plan = {"dhan-daily": ("Dhan daily candles", lambda: dhan_daily.run(args)),
            "groww-intraday": ("Groww 1-minute bars", lambda: groww_intraday.run(args)),
            "movers": ("Dhan movers close", lambda: dhan_movers.run(args))}
    wanted = args.jobs or list(JOBS)
    jobs = [plan[name] for name in JOBS if name in wanted]
    if not args.scheduled:
        return common.run_jobs(jobs)
    deadline = time.monotonic() + RUN_BUDGET_S
    if nse_traded_today() is False:
        logger.info("NSE did not trade today (a holiday) - nothing to fetch, skipping the run.")
        return 0
    return common.run_jobs(jobs, retries=RETRIES, retry_gap=RETRY_GAP_S, deadline=deadline)


if __name__ == "__main__":
    raise SystemExit(main())
