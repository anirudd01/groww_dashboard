"""Generate the INDmoney (INDstocks) instrument ids the dashboard reads (stored in the database).

This is ``python scripts/indmoney.py --master`` - monthly, or whenever a symbol
stops resolving. The dashboard never downloads an instrument master itself.

    python scripts/indmoney.py --master
    python scripts/indmoney.py --master --keep-raw     # also save the CSVs

Unlike Dhan's public scrip master, INDmoney's needs an access token, taken
from the shared INDmoney session (minted from the TOTP credentials in ``.env``
by ``market/providers/indmoney_session.py`` if none is saved). It is two files:

* ``/market/instruments?source=equity`` - 3 MB, ~22,700 rows, 26 columns.
* ``/market/instruments?source=index``  - ~130 rows and **three columns only**
  (``EXCH, SEGMENT, SECURITY_ID``), where the column labelled ``SEGMENT``
  actually holds the index *name*. It is read positionally for that reason.

Index names are the one thing that cannot be derived. The dashboard knows an
index by its Dhan-style symbol (``BANKNIFTY``, ``NIFTYIT``); INDmoney files
the same index as ``BANK NIFTY`` / ``NIFTY IT``. ``INDEX_NAMES`` below is that
translation, and every entry was checked on 2026-09-25 against Dhan's live
value *and* previous close for the same index - so a wrong mapping shows up as
a number that disagrees with Dhan, not as a plausible-looking wrong tile.

Output: the ``indmoney_instruments`` set in ``data/market.db``, same shape as
the ``dhan_instruments`` set. Loaded by ``market/providers/indmoney.py``.

This script places no orders and reads no account data.
"""

import csv
import io
import logging
import os
from datetime import date, datetime, timezone
from typing import Dict, Set

import requests

from jobs.dhan_instruments import log_universes
from market import reference_store, state_store
from market.instruments import INDMONEY_SET
from market.providers.base import SEGMENT_CASH, SEGMENT_INDEX
from market.universe import tracked_symbols

logger = logging.getLogger("indmoney_instruments")

INSTRUMENTS_URL = "https://api.indstocks.com/market/instruments"

RAW_DIR = os.path.join("data", "instruments")
RAW_PREFIX = "indmoney-instruments-"

#: Dashboard index symbol -> INDmoney index-file name (matched case-insensitively).
INDEX_NAMES: Dict[str, str] = {
    "NIFTY AUTO": "Nifty Auto",
    "BANKNIFTY": "BANK NIFTY",
    "NIFTY CONSR DURBL": "Nifty Consumer Durables",
    # Not "NiftyFinSrv25 50", which is the capped Financial Services 25/50.
    "FINNIFTY": "Nifty Financial",
    "NIFTY FMCG": "Nifty FMCG",
    "NIFTY HEALTHCARE": "Nifty Healthcare",
    "NIFTYIT": "NIFTY IT",
    "NIFTY MEDIA": "Nifty Media",
    "NIFTY METAL": "Nifty Metal",
    # Listed (40000104) but INDmoney serves no quote, candle or tick for it as
    # of 2026-09-25. Kept so it starts working the day INDmoney fixes it; until
    # then the dashboard reports it as a data gap rather than a fake number.
    "NIFTY OIL AND GAS": "Nifty Oil & Gas",
    "NIFTY PHARMA": "NIFTY PHARMA",
    "NIFTY PVT BANK": "Nifty Private Bank",
    "NIFTY PSU BANK": "Nifty PSU Bank",
    "NIFTY REALTY": "Nifty Realty",
    "NIFTY": "NIFTY 50",
    "NIFTYNXT50": "Nifty Next 50",
    "NIFTY 500": "Nifty 500",
}


def download(source: str, token: str, keep_raw: bool) -> str:
    logger.info("Downloading %s?source=%s", INSTRUMENTS_URL, source)
    response = requests.get(
        INSTRUMENTS_URL,
        params={"source": source},
        headers={"Authorization": token},
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    text = response.content.decode("utf-8-sig")
    logger.info("  %.1f MB", len(text) / 1e6)
    if keep_raw:
        os.makedirs(RAW_DIR, exist_ok=True)
        path = os.path.join(RAW_DIR, f"{RAW_PREFIX}{source}-{date.today().isoformat()}.csv")
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        logger.info("  saved unedited response to %s", path)
    return text


def extract_equities(text: str, wanted: Set[str]) -> Dict[str, dict]:
    """NSE cash-equity rows for the wanted trading symbols."""
    found: Dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("EXCH") != "NSE" or row.get("SEGMENT") != "E":
            continue
        if row.get("INSTRUMENT_NAME") != "EQUITY":
            continue
        symbol = (row.get("TRADING_SYMBOL") or "").strip()
        if symbol not in wanted or symbol in found:
            continue
        security_id = (row.get("SECURITY_ID") or "").strip()
        if not security_id:
            continue
        found[symbol] = {
            "security_id": security_id,
            "isin": (row.get("ISIN") or "").strip(),
            "name": (row.get("SYMBOL_NAME") or "").strip(),
            "series": (row.get("SERIES") or "").strip(),
            "lot_size": (row.get("LOT_UNITS") or "").strip(),
        }
    return found


def extract_indices(text: str, wanted: Set[str]) -> Dict[str, dict]:
    """NSE index rows, read positionally (see module docstring)."""
    by_name: Dict[str, str] = {}
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header, whose second label is wrong
    for row in reader:
        if len(row) < 3 or row[0].strip() != "NSE":
            continue
        by_name[row[1].strip().lower()] = row[2].strip()

    found: Dict[str, dict] = {}
    for symbol in wanted:
        name = INDEX_NAMES.get(symbol)
        if name is None:
            logger.warning("  %s has no entry in INDEX_NAMES - add one", symbol)
            continue
        security_id = by_name.get(name.lower())
        if security_id:
            found[symbol] = {"security_id": security_id, "name": name}
    return found


def run(args) -> int:
    # Imported here, not at module level: the tests import this module for its parsers.
    from market.providers.indmoney import IndMoneyProvider

    provider = IndMoneyProvider()
    try:
        provider.connect()  # the saved token, or a new one from TOTP
    except RuntimeError as exc:
        logger.error("INDmoney login failed - the instrument files need an access token: %s", exc)
        return 1
    token = provider.auth_headers()["Authorization"]

    wanted, universes = tracked_symbols(args.db)
    log_universes(universes)

    try:
        equities = extract_equities(
            download("equity", token, args.keep_raw), wanted.get(SEGMENT_CASH, set())
        )
        indices = extract_indices(
            download("index", token, args.keep_raw), wanted.get(SEGMENT_INDEX, set())
        )
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED to fetch INDmoney's instrument lists: %s", exc)
        logger.error("A 401/403 means the access token was revoked - run this again to take a new one.")
        return 1

    instruments = {SEGMENT_CASH: equities, SEGMENT_INDEX: indices}
    missing = {
        segment: sorted(wanted.get(segment, set()) - set(rows))
        for segment, rows in instruments.items()
        if wanted.get(segment, set()) - set(rows)
    }
    if args.verbose:
        for segment, rows in instruments.items():
            for symbol, fields in sorted(rows.items()):
                logger.info("  %-6s %-18s -> %s", segment, symbol, fields["security_id"])

    resolved = len(equities) + len(indices)
    logger.info("Resolved %d/%d symbols", resolved, sum(len(s) for s in wanted.values()))
    if not resolved:
        logger.error("Nothing resolved; refusing to write an empty file.")
        return 1
    for segment, symbols in missing.items():
        logger.warning("  %s: %d unresolved - %s", segment, len(symbols), ", ".join(symbols))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": f"{INSTRUMENTS_URL}?source=equity|index",
        "provider": "indmoney",
        "universes": sorted(u.key for u in universes),
        "note": (
            "Generated offline by scripts/indmoney.py --master. The "
            "dashboard reads this set and never downloads an instrument "
            "master at runtime."
        ),
        "symbol_count": resolved,
        "missing": missing,
        "instruments": {
            segment: dict(sorted(rows.items()))
            for segment, rows in sorted(instruments.items())
        },
    }
    reference_store.save_document(INDMONEY_SET, payload, nested=("instruments",), path=args.db)
    logger.info("Stored %d instruments as %s in %s", resolved, INDMONEY_SET, args.db or state_store.db_path())
    return 2 if missing else 0

