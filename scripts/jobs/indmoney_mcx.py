"""Store which MCX commodity futures INDmoney lists (set ``indmoney_mcx`` in data/market.db).

Part of ``python scripts/indmoney.py --master``, about monthly. The MCX page asks INDmoney for
these contracts only: one id INDmoney does not list fails its whole quote call with HTTP 400.
The contracts themselves (names, expiries, Kite ids) come from ``scripts/dhan.py --master``;
INDmoney's ``SECURITY_ID`` is MCX's token, the same id Dhan uses, so the two sets join on it.

Source: ``/market/instruments?source=mcx`` (needs an INDmoney access token). On 2026-10-17 it
listed 93 ``FUTCOM`` rows across 19 commodities, against Dhan's 168 across 28.

This script places no orders and reads no account data.
"""

import csv
import io
import logging
from collections import Counter

from jobs.indmoney_instruments import INSTRUMENTS_URL, download
from market import mcx_futures, state_store

logger = logging.getLogger("indmoney_mcx")


def run(args) -> int:
    from market.providers.indmoney import IndMoneyProvider

    provider = IndMoneyProvider()
    try:
        provider.connect()
    except RuntimeError as exc:
        logger.error("INDmoney login failed - the MCX list needs an access token: %s", exc)
        return 1
    try:
        text = download("mcx", provider.auth_headers()["Authorization"], args.keep_raw)
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED to fetch INDmoney's MCX list: %s", exc)
        return 1

    listed = mcx_futures.indmoney_listed(csv.DictReader(io.StringIO(text)))
    if not listed:
        logger.error("No MCX futures in INDmoney's list; refusing to store an empty one.")
        return 1
    per_commodity = Counter(fields["commodity"] for fields in listed.values())
    logger.info("INDmoney lists %d MCX futures across %d commodities: %s", len(listed), len(per_commodity),
                ", ".join(f"{name} {count}" for name, count in sorted(per_commodity.items())))

    contracts, _, error = mcx_futures.load_contracts(args.db)
    if error:
        logger.warning("%s The INDmoney list is stored anyway.", error)
    else:
        missing = sorted({c.commodity for c in contracts} - set(per_commodity))
        unknown = sorted(set(listed) - {c.security_id for c in contracts})
        if missing:
            logger.info("Not on INDmoney (the MCX page shows these from Dhan or Kite only): %s", ", ".join(missing))
        if unknown:
            logger.warning("%d INDmoney id(s) are not in the stored contracts - re-run 'python %s'.",
                           len(unknown), mcx_futures.SCRIPT)
    mcx_futures.save_indmoney_listed(listed, f"{INSTRUMENTS_URL}?source=mcx", path=args.db)
    logger.info("Stored %d INDmoney MCX ids as %s in %s", len(listed), mcx_futures.INDMONEY_SET,
                args.db or state_store.db_path())
    return 0
