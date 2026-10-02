"""Dhan market movers: request building and parsing for ``POST /v2/data/marketmovers``.

Dhan ranks instruments server-side, so one call returns the top N of a whole universe.
The endpoint is in Dhan's Swagger spec but not its docs (docs/API_ENDPOINT_AUDIT.md). What
it does, checked live on 2026-10-02:

* **Stocks** (``NSE_EQ``/``EQUITY``): ``PRICE_GAINERS`` or ``PRICE_LOSERS`` within a
  ``universe`` (F&O stocks, Nifty 50, a sector index, ...). ``limit`` is 1-100.
* **Futures and options** (``NSE_FNO``): ``TOP_VOLUME``, ``OI_GAINERS``, ``OI_LOSERS``, and
  ``HIGHEST_OI`` for options. An ``expiry`` is required, but any date is snapped to the
  monthly contract (asking for 06-Oct, 13-Oct or 29-Oct all returned 27-Oct), so the
  response's own ``expiry`` is the one to show.
* Every move is today against the previous close. There is no multi-day ranking.

Visualisation only - this module reads rankings; it places no orders.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from market.market_hours import now_ist

# -- what can be asked for -----------------------------------------------------

STOCKS = "stocks"
STOCK_FUTURES = "stock_futures"
INDEX_FUTURES = "index_futures"
STOCK_OPTIONS = "stock_options"
INDEX_OPTIONS = "index_options"

#: kind -> (Dhan exchange segment, Dhan instrument types)
KINDS = {
    STOCKS: ("NSE_EQ", ["EQUITY"]),
    STOCK_FUTURES: ("NSE_FNO", ["FUTSTK"]),
    INDEX_FUTURES: ("NSE_FNO", ["FUTIDX"]),
    STOCK_OPTIONS: ("NSE_FNO", ["OPTSTK"]),
    INDEX_OPTIONS: ("NSE_FNO", ["OPTIDX"]),
}

PRICE_GAINERS = "PRICE_GAINERS"
PRICE_LOSERS = "PRICE_LOSERS"
TOP_VOLUME = "TOP_VOLUME"
OI_GAINERS = "OI_GAINERS"
OI_LOSERS = "OI_LOSERS"
HIGHEST_OI = "HIGHEST_OI"

#: Which ranking Dhan documents for which kind of instrument.
CATEGORIES = {
    STOCKS: (PRICE_GAINERS, PRICE_LOSERS),
    STOCK_FUTURES: (TOP_VOLUME, OI_GAINERS, OI_LOSERS),
    INDEX_FUTURES: (TOP_VOLUME, OI_GAINERS, OI_LOSERS),
    STOCK_OPTIONS: (HIGHEST_OI, TOP_VOLUME, OI_GAINERS, OI_LOSERS),
    INDEX_OPTIONS: (HIGHEST_OI, TOP_VOLUME, OI_GAINERS, OI_LOSERS),
}

MAX_LIMIT = 100

#: The month-year token in a derivative's trading symbol: INFY-Oct2026-FUT.
_CONTRACT_MONTH = re.compile(r"-[A-Z][a-z]{2}\d{4}(?:-|$)")

#: Label -> Dhan ``universe`` for the stock rankings. A hand-picked subset of the ~55 Dhan
#: accepts: the broad lists and every NSE sector index.
UNIVERSES = {
    "F&O stocks": "FNO_STOCKS",
    "Nifty 50": "NIFTY_50",
    "Nifty Next 50": "NIFTY_NEXT_50",
    "Nifty 100": "NIFTY_100",
    "Nifty 200": "NIFTY_200",
    "Nifty 500": "NIFTY_500",
    "Nifty Midcap 100": "NIFTY_MIDCAP_100",
    "Nifty Smallcap 100": "NIFTY_SMALLCAP_100",
    "Nifty Bank": "NIFTY_BANK",
    "Nifty Private Bank": "NIFTY_PRIVATE_BANK",
    "Nifty PSU Bank": "NIFTY_PSU_BANK",
    "Nifty IT": "NIFTY_IT",
    "Nifty Auto": "NIFTY_AUTO",
    "Nifty Pharma": "NIFTY_PHARMA",
    "Nifty FMCG": "NIFTY_FMCG",
    "Nifty Metal": "NIFTY_METAL",
    "Nifty Energy": "NIFTY_ENERGY",
    "Nifty Realty": "NIFTY_REALTY",
    "Nifty Infra": "NIFTY_INFRA",
    "Nifty Media": "NIFTY_MEDIA",
    "All NSE stocks": "ALL",
}

# -- request -------------------------------------------------------------------


def build_request(
    kind: str,
    category: str,
    *,
    universe: Optional[str] = None,
    expiry: Optional[date] = None,
    limit: int = 20,
) -> dict:
    """The JSON body for one ranking. Raises ``ValueError`` for a combination Dhan rejects."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}")
    if category not in CATEGORIES[kind]:
        raise ValueError(f"{category} is not a ranking for {kind} (use {', '.join(CATEGORIES[kind])})")
    segment, instruments = KINDS[kind]
    body = {
        "exchangeSegment": segment,
        "instrument": list(instruments),
        "category": category,
        "limit": max(1, min(int(limit), MAX_LIMIT)),
    }
    if kind == STOCKS:
        body["universe"] = universe or UNIVERSES["F&O stocks"]
    else:
        body["expiry"] = (expiry or monthly_expiry(now_ist().date())).isoformat()
    return body


def monthly_expiry(today: date) -> date:
    """The next monthly F&O expiry on or after ``today``: the last Tuesday of the month.

    NSE moved monthly expiries to Tuesday in 2025. Dhan snaps any date to the monthly
    contract anyway, so this only needs to land in the right month.
    """

    def last_tuesday(year: int, month: int) -> date:
        last = date(year, month, calendar.monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - calendar.TUESDAY) % 7)

    expiry = last_tuesday(today.year, today.month)
    if expiry < today:
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        expiry = last_tuesday(year, month)
    return expiry


# -- response ------------------------------------------------------------------


@dataclass(frozen=True)
class Mover:
    """One ranked instrument. Derivative-only fields are None for stocks."""

    symbol: str  # Dhan trading symbol: RELIANCE, INFY-Oct2026-FUT, NIFTY-Oct2026-23000-CE
    name: str
    instrument: str  # EQUITY, FUTSTK, FUTIDX, OPTSTK, OPTIDX
    ltp: float
    change: float
    change_pct: float
    volume: int
    traded_value: float  # rupees
    lot_size: int = 0
    expiry: Optional[str] = None
    strike: Optional[float] = None
    open_interest: Optional[int] = None
    oi_change_pct: Optional[float] = None
    basis_pct: Optional[float] = None  # futures only: futures price over the underlying
    underlying_ltp: Optional[float] = None
    pcr: Optional[float] = None  # options only: Dhan's put-call ratio for the contract

    @property
    def underlying(self) -> str:
        """RELIANCE for ``RELIANCE``; BAJAJ-AUTO for ``BAJAJ-AUTO-Oct2026-10000-PE``."""
        month = _CONTRACT_MONTH.search(self.symbol)
        return self.symbol[: month.start()] if month else self.symbol

    @property
    def side(self) -> Optional[str]:
        """CE or PE for an option, else None."""
        suffix = self.symbol.rsplit("-", 1)[-1]
        return suffix if suffix in ("CE", "PE") else None


def _number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _whole(value, default=0):
    number = _number(value)
    return int(number) if number is not None else default


def parse_movers(payload: dict) -> List[Mover]:
    """Rows of a marketmovers response, in Dhan's ranked order. Unusable rows are skipped."""
    movers = []
    for row in (payload or {}).get("data") or []:
        if not isinstance(row, dict) or not row.get("tradingSymbol"):
            continue
        instrument = str(row.get("instrument") or "")
        ltp, change_pct = _number(row.get("ltp")), _number(row.get("changePercent"))
        if ltp is None or change_pct is None:
            continue
        derivative = instrument != "EQUITY"
        is_future = instrument.startswith("FUT")
        strike = _number(row.get("strikePrice"))
        movers.append(
            Mover(
                symbol=str(row["tradingSymbol"]),
                name=str(row.get("displayName") or row["tradingSymbol"]),
                instrument=instrument,
                ltp=ltp,
                change=_number(row.get("change"), 0.0),
                change_pct=change_pct,
                volume=_whole(row.get("volume")),
                traded_value=_number(row.get("tradedValue"), 0.0),
                lot_size=_whole(row.get("lotSize")),
                expiry=row.get("expiry") or None,
                # Futures and stocks carry -0.01 or 0 here, meaning "no strike".
                strike=strike if instrument.startswith("OPT") and strike and strike > 0 else None,
                open_interest=_whole(row.get("openInterest")) if derivative else None,
                oi_change_pct=_number(row.get("openInterestChangePercent")) if derivative else None,
                basis_pct=_number(row.get("premiumDiscountPercent")) if is_future else None,
                underlying_ltp=_number(row.get("underlyingLtp")) if derivative else None,
                pcr=_number(row.get("putCallRatio")) if instrument.startswith("OPT") else None,
            )
        )
    return movers


#: Dhan's answer when a ranking has no rows (no stock in the universe is up today, say).
#: Its message also says "incorrect parameters", but the same request answers with rows
#: once the day has some, so it is read as empty.
NO_DATA_CODE = "DH-907"


def fetch(provider, kind: str, category: str, **options) -> List[Mover]:
    """One ranking from Dhan, via a connected ``DhanProvider``. Empty when nothing ranks.

    A reply with no ``data`` field at all is not an empty ranking (Dhan sends ``DH-907`` for
    that), so it raises rather than reading as "nothing is up".
    """
    try:
        payload = provider.market_movers(build_request(kind, category, **options))
    except Exception as exc:  # noqa: BLE001 - only Dhan's "no data" code is swallowed
        if getattr(exc, "code", None) == NO_DATA_CODE:
            return []
        raise
    if not isinstance(payload, dict) or "data" not in payload:
        raise RuntimeError("Dhan market movers sent a reply with no data field")
    return parse_movers(payload)


#: Heavy stocks that trade continuously, so the latest trade time among them dates the session.
SESSION_PROBE_SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "ITC", "LT")


def session_date(provider) -> date:
    """The trading day Dhan's current prices belong to.

    Dhan's rankings carry no date, and after the close, at the weekend or on a holiday they
    still answer with the last session. So the date is read from the feed: the most recent
    trade time among a few heavy stocks. On Fri 2 Oct 2026, a holiday, this was Thu 1 Oct.
    Raises ``RuntimeError`` if none of them has a readable trade time.
    """
    refs, _ = provider.resolve_instruments(list(SESSION_PROBE_SYMBOLS))
    times = provider.get_last_trade_times(list(refs.values()))
    if not times:
        raise RuntimeError("Dhan gave no last trade time, so the session date is unknown")
    return max(times.values()).date()


# -- reading futures ------------------------------------------------------------

LONG_BUILDUP = "Long build-up"
SHORT_BUILDUP = "Short build-up"
SHORT_COVERING = "Short covering"
LONG_UNWINDING = "Long unwinding"
BUILDUPS = (LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING, LONG_UNWINDING)


def buildup(price_pct: float, oi_pct: Optional[float]) -> Optional[str]:
    """Name the quadrant a futures contract sits in, from today's price and open-interest change.

    Price up with open interest up is fresh buying (long build-up); price down with open
    interest up is fresh selling (short build-up); price up with open interest down is
    sellers closing out (short covering); price down with open interest down is buyers
    closing out (long unwinding). A description of what happened, not a prediction. None
    when either number is missing or zero.
    """
    if not price_pct or not oi_pct:
        return None
    if price_pct > 0:
        return LONG_BUILDUP if oi_pct > 0 else SHORT_COVERING
    return SHORT_BUILDUP if oi_pct > 0 else LONG_UNWINDING


def merge_by_symbol(*rankings: List[Mover]) -> List[Mover]:
    """Several rankings as one list with each contract once (the first occurrence wins)."""
    seen: Dict[str, Mover] = {}
    for ranking in rankings:
        for mover in ranking:
            seen.setdefault(mover.symbol, mover)
    return list(seen.values())
