"""Generate the broker instrument-id file the dashboard reads at startup.

Run this **manually** - monthly, or whenever a symbol stops resolving. The
dashboard never downloads an instrument master itself.

    python scripts/fetch_instrument_master.py
    python scripts/fetch_instrument_master.py --verbose
    python scripts/fetch_instrument_master.py --keep-raw      # also save the CSV
    python scripts/fetch_instrument_master.py --use-cached    # reuse today's CSV

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
- After editing ``market/sector_mapping.py`` or adding a universe.
- When the dashboard's "Data gaps" panel reports unresolved symbols, or the
  logs say a symbol is missing from the instruments file.

Output
------
``data/dhan_instruments.json`` - a plain ``segment -> symbol -> fields`` map,
small enough to read and to diff in a commit, so a reconstitution shows up as a
handful of changed lines. Loaded by ``market/instruments.py``.

This script places no orders and reads no account data. The instrument master
is a public file, so it needs no broker credentials at all.
"""

import argparse
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from typing import Dict, Iterable, Set, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market.instruments import DEFAULT_INSTRUMENTS_PATH  # noqa: E402
from market.providers.base import SEGMENT_CASH, SEGMENT_INDEX  # noqa: E402
from market.universe import UNIVERSES, get_universe  # noqa: E402

logger = logging.getLogger("fetch_instrument_master")

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


def tracked_symbols() -> Tuple[Dict[str, Set[str]], list]:
    """Symbols to resolve, grouped by segment, across every configured universe.

    A universe that has no constituents yet (Nifty Next 50) is skipped rather
    than treated as an error - it is a placeholder, not a failure.
    """
    wanted: Dict[str, Set[str]] = {SEGMENT_CASH: set(), SEGMENT_INDEX: set()}
    included = []
    for key in UNIVERSES:
        try:
            universe = get_universe(key)
        except (KeyError, ValueError) as exc:
            logger.info("Skipping universe %s: %s", key, exc)
            continue
        segment = (universe.segment or SEGMENT_CASH).upper()
        wanted.setdefault(segment, set()).update(universe.symbols)
        included.append(key)
        logger.info("  %-20s %3d symbols (%s)", key, len(universe), segment)
    return wanted, included


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
            "Generated offline by scripts/fetch_instrument_master.py. The "
            "dashboard reads this file and never downloads an instrument "
            "master at runtime. Regenerate after an NSE index reconstitution, "
            "after editing market/sector_mapping.py, or when a symbol stops "
            "resolving."
        ),
        "symbol_count": sum(len(rows) for rows in instruments.values()),
        "missing": missing,
        "instruments": {
            segment: dict(sorted(rows.items()))
            for segment, rows in sorted(instruments.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=DEFAULT_INSTRUMENTS_PATH, help="Output JSON path"
    )
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Also save Dhan's unedited CSV under data/instruments/",
    )
    parser.add_argument(
        "--use-cached",
        action="store_true",
        help="Reuse today's saved CSV instead of downloading again",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )

    logger.info("Universes to resolve:")
    wanted, universes = tracked_symbols()
    total = sum(len(symbols) for symbols in wanted.values())
    if not total:
        logger.error("No universes have constituents configured - nothing to do.")
        return 1

    try:
        text = download(use_cached=args.use_cached, keep_raw=args.keep_raw)
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED to fetch the instrument master: %s", exc)
        logger.error(
            "The file is public, so this is a network problem rather than a "
            "credentials one. %s can also be filled in by hand: it is a plain "
            "symbol -> security_id map and the ids are visible in Dhan's own "
            "instrument list.",
            args.out,
        )
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

    payload = build_payload(instruments, missing, universes)
    directory = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    size_kb = os.path.getsize(args.out) / 1024
    logger.info("Wrote %s (%.1f KB, %d instruments)", args.out, size_kb, resolved)
    if missing:
        logger.warning(
            "Some symbols did not resolve. Check them against NSE - a renamed "
            "or delisted constituent needs market/sector_mapping.py updating too."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
