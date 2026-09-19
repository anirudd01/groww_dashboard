"""Generate the constituent weights file used for market-cap sector weighting.

Run this **manually**, weekly or monthly - never from the dashboard. Share
counts move slowly, so weights that are a few weeks old are a rounding error,
whereas a live fundamentals lookup during market hours would add a network
dependency that can fail or stall exactly when the dashboard is being used.

    python scripts/fetch_index_weights.py
    python scripts/fetch_index_weights.py --out data/index_weights.json --verbose

Source
------
Yahoo Finance's public ``quoteSummary`` API. No API key and no account are
needed; it does require a session cookie plus a "crumb", which this script
obtains automatically. **NSE is not contacted.**

It reads ``floatShares`` (shares genuinely available to trade) and the last
price, and records free-float market capitalisation - the same basis NSE uses
for index weighting - alongside full market cap so either can be used.

If Yahoo ever changes or blocks this, the output file is plain JSON and can be
filled in by hand from NSE's published index factsheet. Only the ratios within
a sector matter, so any consistent unit works.

This script places no orders and reads no account data. It needs no broker
credentials at all.
"""

import argparse
import http.cookiejar
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market.sector_mapping import NIFTY_50_SECTORS  # noqa: E402
from market.weights import DEFAULT_WEIGHTS_PATH  # noqa: E402

logger = logging.getLogger("fetch_index_weights")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIE_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
MODULES = "price,defaultKeyStatistics"

#: NSE equities carry the .NS suffix on Yahoo.
YAHOO_SUFFIX = ".NS"

#: Be a polite client. This runs monthly over 50 symbols, so there is no reason
#: to hurry and every reason not to get rate limited.
REQUEST_DELAY_SECONDS = 0.4
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3

SOURCE_LABEL = "Yahoo Finance quoteSummary (public, no API key)"


def yahoo_symbol(symbol: str) -> str:
    return f"{symbol}{YAHOO_SUFFIX}"


def _raw(value) -> Optional[float]:
    """Yahoo wraps numbers as {'raw': ..., 'fmt': ...}; accept either shape."""
    if isinstance(value, dict):
        value = value.get("raw")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class YahooSession:
    """Cookie + crumb session. Yahoo rejects quoteSummary without both."""

    def __init__(self) -> None:
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar)
        )
        self._crumb: Optional[str] = None

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return self._opener.open(request, timeout=REQUEST_TIMEOUT).read()

    def authenticate(self) -> None:
        try:
            self._get(COOKIE_URL)
        except urllib.error.HTTPError:
            # fc.yahoo.com answers 404 but still sets the cookie we need.
            pass
        if not list(self._jar):
            raise RuntimeError("Yahoo did not return a session cookie")
        crumb = self._get(CRUMB_URL).decode("utf-8").strip()
        if not crumb or "<" in crumb:
            raise RuntimeError(f"Yahoo returned an unusable crumb: {crumb[:40]!r}")
        self._crumb = crumb
        logger.debug("Authenticated with Yahoo (crumb acquired)")

    def quote_summary(self, symbol: str) -> dict:
        if self._crumb is None:
            raise RuntimeError("authenticate() must be called first")
        url = SUMMARY_URL.format(symbol=urllib.parse.quote(symbol)) + "?" + (
            urllib.parse.urlencode({"modules": MODULES, "crumb": self._crumb})
        )
        payload = json.loads(self._get(url))
        results = (payload.get("quoteSummary") or {}).get("result") or []
        if not results:
            raise LookupError(f"no quoteSummary result for {symbol}")
        return results[0]


def fetch_one(session: YahooSession, symbol: str) -> Tuple[Optional[dict], str]:
    """Figures for one symbol, or (None, reason). Never raises."""
    target = yahoo_symbol(symbol)
    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = session.quote_summary(target)
            price = result.get("price") or {}
            stats = result.get("defaultKeyStatistics") or {}

            market_cap = _raw(price.get("marketCap"))
            float_shares = _raw(stats.get("floatShares"))
            shares_out = _raw(stats.get("sharesOutstanding"))
            last_price = _raw(price.get("regularMarketPrice"))

            free_float_cap = None
            if float_shares and last_price:
                free_float_cap = float_shares * last_price
            elif market_cap and float_shares and shares_out:
                free_float_cap = market_cap * (float_shares / shares_out)

            if not market_cap and not free_float_cap:
                return None, "no market cap or float data returned"

            return (
                {
                    "yahoo_symbol": target,
                    "market_cap": market_cap,
                    "free_float_market_cap": free_float_cap,
                    "float_shares": float_shares,
                    "shares_outstanding": shares_out,
                    "price_at_fetch": last_price,
                },
                "",
            )
        except LookupError as exc:
            return None, str(exc)
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES:
                time.sleep(attempt)
    return None, last_error or "unknown error"


def build_payload(symbols, verbose: bool = False) -> dict:
    session = YahooSession()
    session.authenticate()

    weights: Dict[str, dict] = {}
    failures: Dict[str, str] = {}

    for index, symbol in enumerate(sorted(symbols), start=1):
        figures, reason = fetch_one(session, symbol)
        if figures:
            weights[symbol] = figures
            if verbose:
                cap = figures.get("free_float_market_cap") or figures["market_cap"]
                logger.info("  %2d/%d  %-12s %.2e", index, len(symbols), symbol, cap)
        else:
            failures[symbol] = reason
            logger.warning("  %2d/%d  %-12s FAILED: %s", index, len(symbols), symbol, reason)
        time.sleep(REQUEST_DELAY_SECONDS)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_LABEL,
        "universe": "NIFTY50",
        "weight_basis": "free_float_market_cap",
        "currency": "INR",
        "note": (
            "Generated offline by scripts/fetch_index_weights.py. The dashboard "
            "reads this file and never fetches weights at runtime. Regenerate "
            "weekly or monthly, or edit by hand from NSE's index factsheet."
        ),
        "symbol_count": len(weights),
        "failures": failures,
        "weights": weights,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_WEIGHTS_PATH, help="Output JSON path")
    parser.add_argument("--verbose", action="store_true", help="Log every symbol")
    parser.add_argument(
        "--symbol", action="append", help="Fetch only these symbols (repeatable)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    symbols = args.symbol or sorted(NIFTY_50_SECTORS)
    logger.info("Fetching weights for %d symbols from Yahoo Finance...", len(symbols))

    try:
        payload = build_payload(symbols, verbose=args.verbose)
    except Exception as exc:  # noqa: BLE001 - a CLI should explain, not traceback
        logger.error("FAILED: %s", exc)
        logger.error(
            "If Yahoo is unreachable or has changed, fill in %s by hand from "
            "NSE's published index factsheet - the format is documented in "
            "market/weights.py.",
            args.out,
        )
        return 1

    if not payload["weights"]:
        logger.error("No weights were retrieved; refusing to write an empty file.")
        return 1

    directory = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    logger.info("")
    logger.info("Wrote %s", args.out)
    logger.info("  %d of %d symbols have weights", len(payload["weights"]), len(symbols))
    if payload["failures"]:
        logger.warning(
            "  %d symbol(s) missing - they will be excluded from the weighted "
            "average, and the dashboard will show reduced weight coverage:",
            len(payload["failures"]),
        )
        for symbol, reason in sorted(payload["failures"].items()):
            logger.warning("    %-12s %s", symbol, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
