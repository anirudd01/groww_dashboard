"""Live market-data domain layer for the sector heatmap dashboard.

Layering (no upward dependencies):

    groww_api  ->  market.live_feed  ->  market.market_state/models
                                     ->  market.sector_aggregation
                                     ->  ui / Streamlit
"""

from market.config import HeatmapConfig, ORDER_BY_IMPACT, ORDER_BY_PERFORMANCE, ORDER_BY_SIZE
from market.live_feed import LiveMarketDataService
from market.models import (
    FeedStatus,
    MarketSnapshot,
    SectorMarketData,
    StockMarketData,
)
from market.sector_aggregation import (
    aggregate_sectors,
    compute_change_pct,
    rank_constituents,
    rank_sectors,
)
from market.sector_impact import order_sectors
from market.providers.base import InstrumentRef, MarketDataProvider
from market.providers.registry import available_provider_names, build_providers
from market.universe import Universe, get_universe

__all__ = [
    "HeatmapConfig",
    "ORDER_BY_IMPACT",
    "ORDER_BY_PERFORMANCE",
    "ORDER_BY_SIZE",
    "LiveMarketDataService",
    "FeedStatus",
    "MarketSnapshot",
    "SectorMarketData",
    "StockMarketData",
    "aggregate_sectors",
    "compute_change_pct",
    "rank_constituents",
    "rank_sectors",
    "order_sectors",
    "InstrumentRef",
    "MarketDataProvider",
    "available_provider_names",
    "build_providers",
    "Universe",
    "get_universe",
]
