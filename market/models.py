"""Internal data models for the live sector heatmap.

These are deliberately plain dataclasses: the whole universe is ~50 rows, so
there is no need for anything heavier.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


# --------------------------------------------------------------------------
# Feed status
# --------------------------------------------------------------------------
STATUS_INITIALISING = "INITIALISING"
STATUS_LIVE = "LIVE"
STATUS_STALE = "STALE"
STATUS_DISCONNECTED = "DISCONNECTED"
STATUS_CLOSED = "CLOSED"  # market is not open; last known values shown
STATUS_ERROR = "ERROR"

# Where the prices in the snapshot actually came from.
SOURCE_NONE = "none"
SOURCE_WEBSOCKET = "websocket"
SOURCE_REST = "rest"

# Where the *previous* closes came from. They are reference data with their own
# path, and which path was used changes what a percentage on the board means,
# so the UI is told rather than left to assume.
PREV_CLOSE_OHLC = "ohlc"  # broker's OHLC block - only valid during the session
PREV_CLOSE_DAILY_CANDLE = "daily_candle"  # prior session's candle, used after 15:30


@dataclass
class StockMarketData:
    """Live state for a single constituent."""

    symbol: str
    sector: str
    exchange: str = "NSE"
    segment: str = "CASH"
    exchange_token: Optional[str] = None
    previous_close: Optional[float] = None
    ltp: Optional[float] = None
    last_update: Optional[datetime] = None

    # Intraday session bar. Only providers whose feed carries it populate these
    # (Dhan quote packets do; the Groww fallback generally does not), so every
    # consumer must treat them as optional rather than assuming a value.
    day_open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[int] = None

    @property
    def change_pct(self) -> Optional[float]:
        """Percentage change vs the previous trading day's close."""
        from market.sector_aggregation import compute_change_pct

        return compute_change_pct(self.ltp, self.previous_close)

    @property
    def has_live_price(self) -> bool:
        return self.change_pct is not None

    @property
    def range_position_pct(self) -> Optional[float]:
        """Where the LTP sits inside the day's range, 0 (low) to 100 (high).

        ``None`` when the range is unknown or degenerate - a stock that has not
        moved all session has no meaningful position within its own range, and
        reporting 0 or 50 would invent information.
        """
        if self.ltp is None or self.day_high is None or self.day_low is None:
            return None
        try:
            high, low, ltp = float(self.day_high), float(self.day_low), float(self.ltp)
        except (TypeError, ValueError):
            return None
        if high <= 0 or low <= 0 or high <= low:
            return None
        return max(0.0, min(100.0, ((ltp - low) / (high - low)) * 100.0))

    @property
    def has_day_range(self) -> bool:
        return self.range_position_pct is not None


@dataclass
class SectorMarketData:
    """Aggregated state for one sector."""

    sector: str
    change_pct: Optional[float]
    constituent_count: int
    priced_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    unchanged_count: int = 0
    aggregation_method: str = "equal_weight"
    #: Share of this sector's priced constituents that carried a usable weight,
    #: 0.0-1.0. Always 1.0 for equal weighting. Below 1.0 it means the
    #: cap-weighted number was computed from only part of the sector.
    weight_coverage: float = 1.0
    #: True when a weighted method was requested but no constituent had a
    #: weight, so this sector silently reverted to an equal-weighted mean.
    #: Surfaced in the UI - a weighted number that is secretly unweighted
    #: would be a lie.
    fell_back_to_equal_weight: bool = False
    #: Mean position within the day's range across constituents that report one.
    avg_range_position_pct: Optional[float] = None
    #: How many constituents supplied a usable day range.
    range_count: int = 0

    @property
    def advancing_pct(self) -> Optional[float]:
        """Share of priced constituents that are up, 0-100.

        ``None`` when nothing in the sector is priced, so an empty sector is
        never reported as 0% advancing.
        """
        if self.priced_count <= 0:
            return None
        return (self.positive_count / self.priced_count) * 100.0

    @property
    def breadth_label(self) -> str:
        """Compact 'advancing vs declining' summary for the UI."""
        if self.priced_count <= 0:
            return "no data"
        return f"{self.positive_count}↑ / {self.negative_count}↓"


@dataclass
class FeedStatus:
    """What the UI needs to honestly describe the state of the feed."""

    state: str = STATUS_INITIALISING
    source: str = SOURCE_NONE
    #: label of the broker currently supplying prices, e.g. "Dhan"
    provider: str = ""
    detail: str = ""
    last_tick_at: Optional[datetime] = None
    subscribed_count: int = 0
    requested_count: int = 0
    priced_count: int = 0
    missing_previous_close: List[str] = field(default_factory=list)
    unresolved_symbols: List[str] = field(default_factory=list)
    market_open: bool = False
    #: One of the PREV_CLOSE_* constants, or "" while nothing has resolved.
    previous_close_source: str = ""

    @property
    def seconds_since_tick(self) -> Optional[float]:
        if self.last_tick_at is None:
            return None
        return max(0.0, (datetime.now() - self.last_tick_at).total_seconds())


@dataclass
class MarketSnapshot:
    """An immutable point-in-time view handed to the UI layer."""

    stocks: List[StockMarketData]
    status: FeedStatus
    taken_at: datetime

    def for_sector(self, sector: str) -> List[StockMarketData]:
        return [s for s in self.stocks if s.sector == sector]
