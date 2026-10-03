"""Store the MCX commodity futures contracts the MCX page reads (set ``mcx_futures`` in data/market.db).

Run this **manually**, about monthly: each commodity lists new expiries as old ones lapse, and the
page warns once the stored list is about to run out. The dashboard never downloads it itself.

    python scripts/fetch_mcx_futures.py
    python scripts/fetch_mcx_futures.py --use-cached    # reuse today's saved master CSV

Sources, both public (no credentials needed):
  - Dhan's instrument master (the same 35 MB CSV ``fetch_instrument_master.py`` reads). Every MCX
    ``FUTCOM`` row is kept: 164 contracts across 28 commodities on 2026-10-03. Options (``OPTFUT``)
    and MCX index futures (``FUTIDX``) are left out.
  - Kite's ``/instruments/MCX`` list (1.3 MB), for the fallback. Its ids are matched to Dhan's
    contracts on commodity and expiry. If it cannot be fetched, the contracts are stored without
    Kite ids and the page simply has no fallback.

This script places no orders and reads no account data.
"""

import argparse
import csv
import io
import logging
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from fetch_instrument_master import SCRIP_MASTER_URL, download  # noqa: E402
from market import mcx_futures, reference_store, state_store  # noqa: E402

logger = logging.getLogger("fetch_mcx_futures")

KITE_MCX_URL = "https://api.kite.trade/instruments/MCX"
#: The set's name before Kite ids were added (2026-10-03); removed on every run.
OLD_SET = "dhan_mcx_futures"


def kite_rows():
    """Kite's public MCX instrument list as CSV rows, or [] if it cannot be fetched."""
    try:
        response = requests.get(KITE_MCX_URL, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Kite's MCX list could not be fetched (%s); storing without Kite ids.", exc)
        return []
    return list(csv.DictReader(io.StringIO(response.text)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None, help="Database file (default: the shared data/market.db)")
    parser.add_argument("--keep-raw", action="store_true", help="Also save Dhan's unedited CSV under data/instruments/")
    parser.add_argument("--use-cached", action="store_true", help="Reuse today's saved CSV instead of downloading")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        text = download(use_cached=args.use_cached, keep_raw=args.keep_raw)
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED to fetch the instrument master: %s", exc)
        return 1

    contracts = mcx_futures.contracts_from_master(csv.DictReader(io.StringIO(text)))
    if not contracts:
        logger.error("No MCX futures in the master; refusing to store an empty list.")
        return 1

    contracts = mcx_futures.attach_kite(contracts, kite_rows())
    per_commodity = Counter(c.commodity for c in contracts)
    on_kite = Counter(c.commodity for c in contracts if c.kite_token)
    for commodity, count in sorted(per_commodity.items()):
        logger.info("  %-12s %2d contracts, %2d on Kite", commodity, count, on_kite[commodity])
    unmatched = [c.name for c in contracts if not c.kite_token]
    if unmatched:
        logger.warning("No Kite id for %d contract(s): %s", len(unmatched), ", ".join(unmatched))
    mcx_futures.save_contracts(contracts, (SCRIP_MASTER_URL, KITE_MCX_URL), path=args.db)
    reference_store.delete_document(OLD_SET, args.db)
    logger.info("Stored %d MCX futures (%d commodities, %d with Kite ids, last expiry %s) as %s in %s",
                len(contracts), len(per_commodity), len(contracts) - len(unmatched),
                mcx_futures.last_expiry(contracts), mcx_futures.MCX_SET, args.db or state_store.db_path())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
