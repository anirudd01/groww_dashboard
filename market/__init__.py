"""Live market-data domain layer for the sector heatmap dashboard.

Layering (no upward dependencies):

    groww_api  ->  market.live_feed  ->  market.market_state/models
                                     ->  market.sector_aggregation
                                     ->  ui / Streamlit
"""

from market.config import HeatmapConfig, ORDER_ALPHABETICAL, ORDER_BY_PERFORMANCE
from market.live_feed import LiveMarketDataService
from market.models import (
    FeedStatus,
    MarketSnapshot,
    SectorMarketData,
    StockMarketData,
)
from market.sector_aggregation import (
    EQUAL_WEIGHT,
    aggregate_sectors,
    compute_change_pct,
    rank_constituents,
    rank_sectors,
    sort_sectors_alphabetically,
)
from market.providers.base import InstrumentRef, MarketDataProvider
from market.providers.registry import available_provider_names, build_providers
from market.universe import Universe, get_universe

__all__ = [
    "HeatmapConfig",
    "ORDER_ALPHABETICAL",
    "ORDER_BY_PERFORMANCE",
    "LiveMarketDataService",
    "FeedStatus",
    "MarketSnapshot",
    "SectorMarketData",
    "StockMarketData",
    "EQUAL_WEIGHT",
    "aggregate_sectors",
    "compute_change_pct",
    "rank_constituents",
    "rank_sectors",
    "sort_sectors_alphabetically",
    "InstrumentRef",
    "MarketDataProvider",
    "available_provider_names",
    "build_providers",
    "Universe",
    "get_universe",
]
