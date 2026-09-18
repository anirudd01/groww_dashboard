"""Percentage-change and sector-aggregation logic.

Pure functions only - no Groww API calls, no Streamlit, no Plotly. This is the
layer the tests exercise.

Phase 1 aggregates sectors with an equal-weighted average of the constituent
percentage changes. Market-cap and index weighting are deliberately *not*
implemented, but the strategy registry below is the seam where Phase 2 adds
them without touching the UI.
"""

from typing import Callable, Dict, Iterable, List, Optional, Sequence

from market.models import SectorMarketData, StockMarketData

EQUAL_WEIGHT = "equal_weight"


def compute_change_pct(
    ltp: Optional[float], previous_close: Optional[float]
) -> Optional[float]:
    """Percentage change of ``ltp`` against the previous trading day's close.

    Returns ``None`` when the change cannot be computed honestly - a missing
    price, a missing/zero previous close, or a non-numeric value. Callers must
    treat ``None`` as "no data", never as 0%.
    """
    if ltp is None or previous_close is None:
        return None
    try:
        ltp = float(ltp)
        previous_close = float(previous_close)
    except (TypeError, ValueError):
        return None
    if previous_close == 0 or ltp <= 0 or previous_close < 0:
        return None
    return ((ltp - previous_close) / previous_close) * 100.0


def equal_weight_change_pct(changes: Sequence[float]) -> Optional[float]:
    """Unweighted mean of the supplied percentage changes."""
    usable = [c for c in changes if c is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


# Phase 2 hook: add "market_cap" / "index_weight" entries here. Each strategy
# takes the list of constituent percentage changes and returns the sector's
# percentage change (or None when it cannot be computed).
AggregationStrategy = Callable[[Sequence[float]], Optional[float]]

AGGREGATION_STRATEGIES: Dict[str, AggregationStrategy] = {
    EQUAL_WEIGHT: equal_weight_change_pct,
}


def get_aggregation_strategy(method: str = EQUAL_WEIGHT) -> AggregationStrategy:
    try:
        return AGGREGATION_STRATEGIES[method]
    except KeyError:
        raise KeyError(
            f"Unknown aggregation method {method!r}. "
            f"Available: {', '.join(sorted(AGGREGATION_STRATEGIES))}"
        ) from None


def aggregate_sectors(
    stocks: Iterable[StockMarketData], method: str = EQUAL_WEIGHT
) -> List[SectorMarketData]:
    """Collapse constituent-level data into one row per sector.

    Constituents without a usable percentage change are counted but excluded
    from the average, so one missing instrument does not distort its sector.
    """
    strategy = get_aggregation_strategy(method)

    grouped: Dict[str, List[StockMarketData]] = {}
    for stock in stocks:
        grouped.setdefault(stock.sector, []).append(stock)

    sectors: List[SectorMarketData] = []
    for sector, members in grouped.items():
        changes = [m.change_pct for m in members if m.change_pct is not None]
        sectors.append(
            SectorMarketData(
                sector=sector,
                change_pct=strategy(changes),
                constituent_count=len(members),
                priced_count=len(changes),
                positive_count=sum(1 for c in changes if c > 0),
                negative_count=sum(1 for c in changes if c < 0),
                unchanged_count=sum(1 for c in changes if c == 0),
                aggregation_method=method,
            )
        )
    return sectors


def _sort_key(value: Optional[float]) -> float:
    """Push rows with no data to the bottom of any descending sort."""
    return float("-inf") if value is None else value


def rank_sectors(sectors: Iterable[SectorMarketData]) -> List[SectorMarketData]:
    """Strongest sector first; ties and unpriced sectors fall back to name."""
    return sorted(
        sectors, key=lambda s: (-_sort_key(s.change_pct), s.sector)
    )


def sort_sectors_alphabetically(
    sectors: Iterable[SectorMarketData],
) -> List[SectorMarketData]:
    """Deterministic ordering that never moves a tile between refreshes."""
    return sorted(sectors, key=lambda s: s.sector)


def rank_constituents(stocks: Iterable[StockMarketData]) -> List[StockMarketData]:
    """Highest percentage change first; never alphabetical, never by price."""
    return sorted(stocks, key=lambda s: (-_sort_key(s.change_pct), s.symbol))
