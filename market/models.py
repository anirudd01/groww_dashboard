"""Internal data models for the live sector heatmap.

These are deliberately plain dataclasses: the whole universe is ~50 rows, so
there is no need for anything heavier.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


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

    @property
    def change_pct(self) -> Optional[float]:
        """Percentage change vs the previous trading day's close."""
        from market.sector_aggregation import compute_change_pct

        return compute_change_pct(self.ltp, self.previous_close)

    @property
    def has_live_price(self) -> bool:
        return self.change_pct is not None


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
