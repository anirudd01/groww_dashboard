"""Generate the Dhan instrument ids the dashboard reads at startup (stored in the database).

Part of ``python scripts/dhan.py --master`` - run it monthly, or whenever a symbol
stops resolving. The dashboard never downloads an instrument master itself.

    python scripts/dhan.py --master-only                 # constituents, these ids, MCX futures, weights
    python scripts/dhan.py --master-only --keep-raw      # also save the CSV
    python scripts/dhan.py --master-only --use-cached    # reuse today's CSV

Why this is a script and not a startup step
-------------------------------------------
Dhan publishes instrument ids only as ``api-scrip-master-detailed.csv``: 35 MB,
206,659 rows, served **uncompressed** with no zip or gzip variant (verified
2026-09-18 - the CDN ignores ``Accept-Encoding: gzip`` because it serves the
file as ``application/octet-stream``, and ``.zip``/``.gz`` URLs return 403).

Of those rows the dashboard needs about sixty, and it needs two fields from
each: the trading symbol and the broker's numeric security id. Everything else
in the file is F&O contracts - every strike of every expiry.

Security ids of existing instruments are stable. What changes is the *set* of
constituents, and NSE reconstitutes the Nifty indices twice a year (effective
end of March and end of September) plus ad-hoc changes for mergers, demergers
and suspensions. So this is monthly-or-on-demand work, not per-boot work.

When to re-run
--------------
- After an NSE index reconstitution.
- After adding an index to ``market/index_constituents.py``.
- When the dashboard's "Data gaps" panel reports unresolved symbols, or the
  logs say a symbol is missing from the stored instrument ids.

Output
------
the ``dhan_instruments`` set in ``data/market.db`` - a plain ``segment -> symbol -> fields`` map,
small enough to read and to diff in a commit, so a reconstitution shows up as a
handful of changed lines. Loaded by ``market/instruments.py``.

This script places no orders and reads no account data. The instrument master
is a public file, so it needs no broker credentials at all.
"""

import csv
import io
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Dict, Iterable, Set

import requests

from market import reference_store, state_store
from market.instruments import DHAN_SET
from market.providers.base import SEGMENT_CASH, SEGMENT_INDEX
from market.universe import tracked_symbols

logger = logging.getLogger("dhan_instruments")

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

#: Where a ``--keep-raw`` copy of Dhan's response is written, unedited.
RAW_DIR = os.path.join("data", "instruments")
RAW_PREFIX = "dhan-scrip-master-detailed-"

#: How Dhan files each universe segment: (SEGMENT, INSTRUMENT) in the CSV.
SEGMENT_ROWS = {
    SEGMENT_CASH: ("E", "EQUITY"),
    SEGMENT_INDEX: ("I", "INDEX"),
}

#: The columns kept per instrument. ``security_id`` is the only one the
#: dashboard needs; the rest are there to make the file diagnosable by eye -
#: ISIN is how you confirm a demerged entity is the continuing one (TATAMOTORS
#: -> TMPV kept the original ISIN), and name/series/lot size confirm the row is
#: the tradable equity rather than a lookalike.
KEPT_COLUMNS = (
    ("security_id", "SECURITY_ID"),
    ("isin", "ISIN"),
    ("name", "SYMBOL_NAME"),
    ("series", "SERIES"),
    ("lot_size", "LOT_SIZE"),
)


def raw_path(day: date) -> str:
    return os.path.join(RAW_DIR, f"{RAW_PREFIX}{day.isoformat()}.csv")


def download(use_cached: bool, keep_raw: bool) -> str:
    """The master CSV as text, from today's saved copy if one exists."""
    today = date.today()
    cached = raw_path(today)
    if use_cached and os.path.exists(cached):
        logger.info("Reusing today's saved copy: %s", cached)
        with io.open(cached, encoding="utf-8") as handle:
            return handle.read()

    logger.info("Downloading %s", SCRIP_MASTER_URL)
    logger.info("  (35 MB, uncompressed - this is the slow part, ~15-40s)")
    started = time.monotonic()
    response = requests.get(SCRIP_MASTER_URL, timeout=300)
    response.raise_for_status()
    text = response.text
    logger.info(
        "  downloaded %.1f MB in %.1fs", len(text) / 1e6, time.monotonic() - started
    )

    if keep_raw or use_cached:
        os.makedirs(RAW_DIR, exist_ok=True)
        with io.open(cached, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        logger.info("  saved unedited response to %s", cached)
    return text


def extract(text: str, wanted: Dict[str, Set[str]], verbose: bool = False):
    """Pull the wanted symbols out of the master CSV.

    Streams with ``csv.DictReader`` rather than loading a DataFrame: this walks
    206,659 rows once and keeps only the handful that match, so it needs no
    pandas and no meaningful memory.

    Returns ``(instruments, missing)``.
    """
    found: Dict[str, Dict[str, dict]] = {segment: {} for segment in wanted}
    remaining = {segment: set(symbols) for segment, symbols in wanted.items()}
    scanned = 0

    for row in csv.DictReader(io.StringIO(text)):
        scanned += 1
        if row.get("EXCH_ID") != "NSE":
            continue
        symbol = (row.get("UNDERLYING_SYMBOL") or "").strip()
        if not symbol:
            continue
        for segment, (seg_code, instrument) in SEGMENT_ROWS.items():
            if symbol not in remaining.get(segment, ()):
                continue
            if row.get("SEGMENT") != seg_code or row.get("INSTRUMENT") != instrument:
                continue
            security_id = (row.get("SECURITY_ID") or "").strip()
            if not security_id:
                continue
            found[segment][symbol] = {
                key: (row.get(column) or "").strip() for key, column in KEPT_COLUMNS
            }
            remaining[segment].discard(symbol)
            if verbose:
                logger.info("  %-8s %-14s -> %s", segment, symbol, security_id)

    logger.info("Scanned %d rows", scanned)
    missing = {
        segment: sorted(symbols) for segment, symbols in remaining.items() if symbols
    }
    return found, missing


def build_payload(instruments, missing, universes: Iterable[str]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SCRIP_MASTER_URL,
        "provider": "dhan",
        "universes": sorted(universes),
        "note": (
            "Generated offline by scripts/dhan.py --master. The dashboard "
            "reads this set and never downloads an instrument master at "
            "runtime. Regenerate after an NSE index reconstitution or when a "
            "symbol stops resolving."
        ),
        "symbol_count": sum(len(rows) for rows in instruments.values()),
        "missing": missing,
        "instruments": {
            segment: dict(sorted(rows.items()))
            for segment, rows in sorted(instruments.items())
        },
    }


def log_universes(universes) -> None:
    logger.info("Universes to resolve:")
    for universe in universes:
        logger.info("  %-20s %3d symbols (%s)", universe.key, len(universe), universe.segment)


def run(args, text: str) -> int:
    """Resolve every tracked symbol in ``text`` (Dhan's master CSV, see ``download``) and store the ids."""
    wanted, universes = tracked_symbols(args.db)
    log_universes(universes)
    total = sum(len(symbols) for symbols in wanted.values())
    if not total:
        logger.error("No universes have constituents stored - nothing to do.")
        return 1

    instruments, missing = extract(text, wanted, verbose=args.verbose)
    resolved = sum(len(rows) for rows in instruments.values())
    logger.info("Resolved %d/%d symbols", resolved, total)

    if not resolved:
        logger.error("Nothing resolved; refusing to write an empty file.")
        return 1

    for segment, symbols in missing.items():
        logger.warning(
            "  %s: %d unresolved - %s", segment, len(symbols), ", ".join(symbols)
        )

    payload = build_payload(instruments, missing, [u.key for u in universes])
    reference_store.save_document(DHAN_SET, payload, nested=("instruments",), path=args.db)
    logger.info("Stored %d instruments as %s in %s", resolved, DHAN_SET, args.db or state_store.db_path())
    if missing:
        logger.warning(
            "Some symbols did not resolve. Check them against NSE - a renamed "
            "or delisted constituent shows up in NSE's list before the broker's."
        )
        return 2
    return 0
