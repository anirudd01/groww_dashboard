"""Generate the Zerodha Kite instrument-id file the dashboard reads.

Run this **manually** - monthly, or whenever a symbol stops resolving. The
dashboard never downloads an instrument master itself.

    python scripts/fetch_kite_instruments.py
    python scripts/fetch_kite_instruments.py --verbose
    python scripts/fetch_kite_instruments.py --keep-raw     # also save the CSV

Kite's NSE dump (``/instruments/NSE``) is public - it needs no API key or
login - and is small: ~0.7 MB, ~10,300 rows, cash equities plus 136 NSE
indices in the ``INDICES`` segment. Zerodha regenerates it once a day.

Two ids per row matter, because Kite uses both:

* ``instrument_token`` - the websocket and historical-candle id. Stored as
  ``security_id`` so the shared loader (``market/instruments.py``) reads it.
* ``tradingsymbol`` - REST quotes are keyed ``NSE:<tradingsymbol>``, so an
  index is ``NSE:NIFTY BANK``, not a number.

Index names are the one thing that cannot be derived. The dashboard knows an
index by its Dhan-style symbol (``BANKNIFTY``, ``NIFTYIT``); Kite files most
indices under the same name, and ``INDEX_NAMES`` below lists the four that
differ. Anything not listed is looked up by its own name.

Output: ``data/kite_instruments.json``, same shape as
``data/dhan_instruments.json``. Loaded by ``market/providers/kite.py``.

This script places no orders and reads no account data.
"""

import argparse
import csv
import io
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Dict, Set

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from fetch_instrument_master import tracked_symbols  # noqa: E402
from market.instruments import KITE_INSTRUMENTS_PATH  # noqa: E402
from market.providers.base import SEGMENT_CASH, SEGMENT_INDEX  # noqa: E402

logger = logging.getLogger("fetch_kite_instruments")

INSTRUMENTS_URL = "https://api.kite.trade/instruments/NSE"

RAW_DIR = os.path.join("data", "instruments")
RAW_PREFIX = "kite-instruments-NSE-"

#: Dashboard index symbol -> Kite ``tradingsymbol``, where the two differ.
#: Checked against the dump on 2026-09-25.
INDEX_NAMES: Dict[str, str] = {
    "BANKNIFTY": "NIFTY BANK",
    # Not "NIFTY FINSRV25 50" (the capped 25/50 variant) or "NIFTY FINSEREXBNK"
    # (Financial Services ex-Bank).
    "FINNIFTY": "NIFTY FIN SERVICE",
    "NIFTYIT": "NIFTY IT",
    "NIFTYNXT50": "NIFTY NEXT 50",
    "NIFTY": "NIFTY 50",
}


def kite_index_name(symbol: str) -> str:
    """The Kite tradingsymbol for a dashboard index symbol."""
    return INDEX_NAMES.get(symbol, symbol)


def download(keep_raw: bool) -> str:
    logger.info("Downloading %s", INSTRUMENTS_URL)
    response = requests.get(INSTRUMENTS_URL, headers={"X-Kite-Version": "3"}, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    text = response.content.decode("utf-8-sig")
    logger.info("  %.1f MB", len(text) / 1e6)
    if keep_raw:
        os.makedirs(RAW_DIR, exist_ok=True)
        path = os.path.join(RAW_DIR, f"{RAW_PREFIX}{date.today().isoformat()}.csv")
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        logger.info("  saved unedited response to %s", path)
    return text


def _row_fields(row: dict) -> dict:
    return {
        "security_id": (row.get("instrument_token") or "").strip(),
        "exchange_token": (row.get("exchange_token") or "").strip(),
        "tradingsymbol": (row.get("tradingsymbol") or "").strip(),
        "name": (row.get("name") or "").strip(),
    }


def extract(text: str, wanted: Dict[str, Set[str]]) -> Dict[str, Dict[str, dict]]:
    """``{segment: {symbol: fields}}`` for the wanted cash and index symbols."""
    equities: Dict[str, dict] = {}
    indices_by_name: Dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("exchange") or "").strip() != "NSE":
            continue
        segment = (row.get("segment") or "").strip()
        tradingsymbol = (row.get("tradingsymbol") or "").strip()
        if not tradingsymbol or not (row.get("instrument_token") or "").strip():
            continue
        if segment == "INDICES":
            indices_by_name[tradingsymbol.upper()] = _row_fields(row)
        elif segment == "NSE" and (row.get("instrument_type") or "").strip() == "EQ":
            equities.setdefault(tradingsymbol, _row_fields(row))

    cash = {s: equities[s] for s in wanted.get(SEGMENT_CASH, set()) if s in equities}
    index = {}
    for symbol in wanted.get(SEGMENT_INDEX, set()):
        fields = indices_by_name.get(kite_index_name(symbol).upper())
        if fields:
            index[symbol] = fields
    return {SEGMENT_CASH: cash, SEGMENT_INDEX: index}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=KITE_INSTRUMENTS_PATH, help="Output JSON path")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument(
        "--keep-raw", action="store_true", help="Also save the unedited CSV under data/instruments/"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Universes to resolve:")
    wanted, universes = tracked_symbols()

    try:
        instruments = extract(download(args.keep_raw), wanted)
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED to fetch Kite's instrument list: %s", exc)
        return 1

    missing = {
        segment: sorted(wanted.get(segment, set()) - set(rows))
        for segment, rows in instruments.items()
        if wanted.get(segment, set()) - set(rows)
    }
    if args.verbose:
        for segment, rows in instruments.items():
            for symbol, fields in sorted(rows.items()):
                logger.info(
                    "  %-6s %-18s -> %-8s (%s)",
                    segment, symbol, fields["security_id"], fields["tradingsymbol"],
                )

    resolved = sum(len(rows) for rows in instruments.values())
    logger.info("Resolved %d/%d symbols", resolved, sum(len(s) for s in wanted.values()))
    if not resolved:
        logger.error("Nothing resolved; refusing to write an empty file.")
        return 1
    for segment, symbols in missing.items():
        logger.warning("  %s: %d unresolved - %s", segment, len(symbols), ", ".join(symbols))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": INSTRUMENTS_URL,
        "provider": "kite",
        "universes": sorted(universes),
        "note": (
            "Generated offline by scripts/fetch_kite_instruments.py. The "
            "dashboard reads this file and never downloads an instrument "
            "master at runtime. security_id is Kite's instrument_token."
        ),
        "symbol_count": resolved,
        "missing": missing,
        "instruments": {
            segment: dict(sorted(rows.items()))
            for segment, rows in sorted(instruments.items())
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    logger.info("Wrote %s (%.1f KB, %d instruments)", args.out, os.path.getsize(args.out) / 1024, resolved)
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
