"""Store the free-float weights used for market-cap sector weighting (the ``index_weights`` set).

Part of ``python scripts/dhan.py --master``, after the Dhan instrument ids (it needs them).
Weights move slowly, so monthly is plenty; the dashboard warns when they are over 45 days old.

Source: Dhan's ``POST /v2/data/companyinfo`` (Data API), one call per stock, sections
``CO`` (``MARKET_CAP``, in Rs crore) and ``SHP`` (``PROMOTER_HOLDING``, %):

    free_float_market_cap = market_cap x (1 - promoter holding)

NSE's own free float also leaves out a few other locked-in holdings, so this is an
approximation. Checked on 2026-10-15 against the earlier Yahoo ``floatShares`` figures for
ten Nifty 50 stocks: within-index weights agreed to about a percentage point (ITC and LT,
which have no promoter, differed most). Only the ratios within a sector matter.

Read-only: no orders, no account data. Needs the Dhan credentials in ``.env``.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import requests

from market import reference_store, state_store
from market.instruments import DHAN_SET, load_instruments
from market.providers.base import SEGMENT_CASH
from market.universe import available_universes
from market.weights import BASIS_FREE_FLOAT, WEIGHTS_SET

logger = logging.getLogger("index_weights")

COMPANY_INFO_URL = "https://api.dhan.co/v2/data/companyinfo"
CRORE = 1e7
TRIES = 3
#: Spacing between calls. ~100 stocks, about a minute in all.
PAUSE_SECONDS = 0.2


def figures_from(body: dict) -> Optional[dict]:
    """``companyinfo``'s answer -> the stored figures, or None when it has no market cap."""
    data = (body or {}).get("data") or {}
    overview, holding = data.get("CO") or {}, data.get("SHP") or {}
    try:
        market_cap = float(overview.get("MARKET_CAP")) * CRORE
    except (TypeError, ValueError):
        return None
    if not market_cap > 0:
        return None
    try:
        promoter = float(holding.get("PROMOTER_HOLDING") or 0)
    except (TypeError, ValueError):
        promoter = 0.0
    promoter = min(max(promoter, 0.0), 100.0)
    return {
        "market_cap": market_cap,
        "promoter_holding_pct": promoter,
        BASIS_FREE_FLOAT: market_cap * (1 - promoter / 100),
        "dhan_sector": overview.get("SECTOR"),
    }


def fetch_one(headers: dict, security_id: str) -> Tuple[Optional[dict], str]:
    body = {"securityId": security_id, "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "metrics": ["CO", "SHP"]}
    error = ""
    for attempt in range(TRIES):
        try:
            response = requests.post(COMPANY_INFO_URL, headers=headers, json=body, timeout=30)
            if response.status_code == 200:
                figures = figures_from(response.json())
                return (figures, "") if figures else (None, "no market cap in the answer")
            error = f"HTTP {response.status_code}: {response.text[:120]}"
        except (requests.RequestException, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        time.sleep(1 + attempt)
    return None, error


def run(args) -> int:
    universes = [u for u in available_universes(args.db) if not u.is_index_board]
    symbols = sorted({s for u in universes for s in u.symbols})
    if not symbols:
        logger.error("No index constituents stored - nothing to weigh.")
        return 1
    ids = load_instruments(DHAN_SET, path=args.db).security_ids(SEGMENT_CASH)
    unknown = [s for s in symbols if s not in ids]
    if unknown:
        logger.warning("No Dhan id for %s - skipped", ", ".join(unknown))

    from market.providers.dhan import DhanProvider

    provider = DhanProvider()
    try:
        if not provider.is_configured():
            logger.error("Dhan is not configured - set DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in .env.")
            return 1
        provider.connect()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        logger.error("Could not connect to Dhan: %s", exc)
        return 1
    headers = provider.auth_headers()

    weights: Dict[str, dict] = {}
    failures: Dict[str, str] = dict.fromkeys(unknown, "no Dhan security id")
    wanted = [s for s in symbols if s in ids]
    logger.info("Fetching market cap and promoter holding for %d stocks (~%.0f s) ...",
                len(wanted), len(wanted) * (0.45 + PAUSE_SECONDS))
    for i, symbol in enumerate(wanted, 1):
        figures, error = fetch_one(headers, ids[symbol])
        if figures:
            weights[symbol] = {"dhan_security_id": ids[symbol], **figures}
            logger.debug("  %-12s %.3e", symbol, figures[BASIS_FREE_FLOAT])
        else:
            failures[symbol] = error
            logger.warning("  %s: %s", symbol, error)
        if i % 25 == 0:
            logger.info("  %d/%d", i, len(wanted))
        time.sleep(PAUSE_SECONDS)

    if not weights:
        logger.error("No weights fetched; keeping the stored set.")
        return 1
    reference_store.save_document(WEIGHTS_SET, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Dhan /v2/data/companyinfo (market cap x (1 - promoter holding))",
        "universe": ",".join(u.key for u in universes),
        "weight_basis": BASIS_FREE_FLOAT,
        "currency": "INR",
        "note": "Generated offline by scripts/dhan.py --master. The dashboard reads this set and never "
                "fetches weights at runtime.",
        "symbol_count": len(weights),
        "failures": failures,
        "weights": weights,
    }, sections=("weights",), path=args.db)
    logger.info("Stored %d weights as %s in %s", len(weights), WEIGHTS_SET, args.db or state_store.db_path())
    return 2 if failures else 0
