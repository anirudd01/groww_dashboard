"""Everything this project fetches from INDmoney (INDstocks), in one command.

    python scripts/indmoney.py --master       # NSE index constituents, INDmoney's instrument ids, its MCX list

Jobs, in the order they run:

  --master   NSE index constituents   -> index_constituents    (jobs/index_constituents.py)
             INDmoney instrument ids  -> indmoney_instruments  (jobs/indmoney_instruments.py)
             INDmoney MCX futures     -> indmoney_mcx          (jobs/indmoney_mcx.py, read by the MCX page)

INDmoney has no data job: nothing is stored from it day to day (the dashboards read it live).
So unlike ``kite.py`` and ``dhan.py`` there is nothing to run without ``--master``; ``--master-only``
is accepted too and means the same. Run it about monthly, after an NSE index reconstitution, or
when a symbol stops resolving. Needs the INDmoney credentials in ``.env`` (the instrument files
take an access token).

Exit code: 0 all ok, 2 something partly done, 1 a job failed. Read-only: no orders, no account data.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs import common  # noqa: E402  (sets up the import path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--master", "--master-only", dest="master", action="store_true",
                        help="Refresh the reference data (the only job INDmoney has)")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument("--keep-raw", action="store_true", help="Also save the unedited CSVs under data/instruments/")
    args = parser.parse_args(argv)
    args.db = None
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    common.setup(args.verbose)
    if not args.master:
        common.logger.info("INDmoney has no data job - nothing to do. Run with --master to refresh "
                           "the index constituents, INDmoney's instrument ids and its MCX list.")
        return 0
    from jobs import index_constituents, indmoney_instruments, indmoney_mcx

    return common.run_jobs([("NSE index constituents", lambda: index_constituents.run(args.db)),
                            ("INDmoney instrument ids", lambda: indmoney_instruments.run(args)),
                            ("INDmoney MCX futures", lambda: indmoney_mcx.run(args))])


if __name__ == "__main__":
    raise SystemExit(main())
