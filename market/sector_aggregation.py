"""Percentage-change and sector-aggregation logic.

Pure functions only - no Groww API calls, no Streamlit, no Plotly. This is the
layer the tests exercise.

Two aggregation methods are available, both explicit about what they mean:

``equal_weight``
    Unweighted mean of the constituent percentage changes. Every stock counts
    the same, so the number answers "how did the average stock in this sector
    do". This is the default.

``market_cap``
    Mean weighted by each constituent's market capitalisation, normalised
    *within the sector*. The number answers "how did this sector's big names
    do". It is a cap-weighted basket of our own constituents - it is **not**
    an attempt to reproduce an NSE sector index, whose constituent list is
    wider than the Nifty 50 members we track.

Weights come from a file generated offline (see ``market/weights.py``), never
from a live scrape, so a weighting run is reproducible and the dashboard has
no extra network dependency.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from market.models import SectorMarketData, StockMarketData

EQUAL_WEIGHT = "equal_weight"
MARKET_CAP = "market_cap"


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


def weighted_change_pct(
    changes: Sequence[float], weights: Sequence[Optional[float]]
) -> Optional[float]:
    """Mean of ``changes`` weighted by ``weights``, normalised over what is usable.

    Only pairs where both the change and a positive weight are present count,
    so one constituent missing a weight shrinks the basket rather than
    silently contributing zero. Returns ``None`` when nothing usable remains -
    the caller decides whether to fall back, and says so when it does.
    """
    usable = [
        (float(change), float(weight))
        for change, weight in zip(changes, weights)
        if change is not None and weight is not None and weight > 0
    ]
    if not usable:
        return None
    total_weight = sum(weight for _, weight in usable)
    if total_weight <= 0:
        return None
    return sum(change * weight for change, weight in usable) / total_weight


# Each strategy takes the constituent percentage changes alongside their
# weights (``None`` where a weight is unknown) and returns the sector's
# percentage change, or ``None`` when it cannot be computed honestly.
# Adding "index_weight" later means adding one entry here; the UI is untouched.
AggregationStrategy = Callable[
    [Sequence[float], Sequence[Optional[float]]], Optional[float]
]


def _equal_weight_strategy(
    changes: Sequence[float], weights: Sequence[Optional[float]]
) -> Optional[float]:
    """Equal weighting ignores the weights by definition."""
    return equal_weight_change_pct(changes)


AGGREGATION_STRATEGIES: Dict[str, AggregationStrategy] = {
    EQUAL_WEIGHT: _equal_weight_strategy,
    MARKET_CAP: weighted_change_pct,
}

#: Human-readable labels for the UI, so the screen always states which
#: definition produced the number on it.
AGGREGATION_LABELS: Dict[str, str] = {
    EQUAL_WEIGHT: "Equal weighted",
    MARKET_CAP: "Market-cap weighted",
}


def get_aggregation_strategy(method: str = EQUAL_WEIGHT) -> AggregationStrategy:
    try:
        return AGGREGATION_STRATEGIES[method]
    except KeyError:
        raise KeyError(
            f"Unknown aggregation method {method!r}. "
            f"Available: {', '.join(sorted(AGGREGATION_STRATEGIES))}"
        ) from None


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    usable = [v for v in values if v is not None]
    return sum(usable) / len(usable) if usable else None


def aggregate_sectors(
    stocks: Iterable[StockMarketData],
    method: str = EQUAL_WEIGHT,
    weights: Optional[Dict[str, float]] = None,
) -> List[SectorMarketData]:
    """Collapse constituent-level data into one row per sector.

    Constituents without a usable percentage change are counted but excluded
    from the average, so one missing instrument does not distort its sector.

    ``weights`` maps symbol to a positive weight (market capitalisation, in
    any consistent unit - only ratios within a sector matter). When a weighted
    method is requested and a sector has no usable weight at all, the sector
    falls back to an equal-weighted mean and is flagged, so the UI can say so
    rather than presenting an unweighted number as weighted.
    """
    strategy = get_aggregation_strategy(method)
    weights = weights or {}

    grouped: Dict[str, List[StockMarketData]] = {}
    for stock in stocks:
        grouped.setdefault(stock.sector, []).append(stock)

    sectors: List[SectorMarketData] = []
    for sector, members in grouped.items():
        priced = [m for m in members if m.change_pct is not None]
        changes = [m.change_pct for m in priced]
        member_weights = [weights.get(m.symbol) for m in priced]

        change_pct = strategy(changes, member_weights)
        fell_back = False
        if change_pct is None and changes and method != EQUAL_WEIGHT:
            # The weighted method could not be applied here; be explicit.
            change_pct = equal_weight_change_pct(changes)
            fell_back = change_pct is not None

        weighted_members = sum(1 for w in member_weights if w is not None and w > 0)
        coverage = 1.0
        if method != EQUAL_WEIGHT and priced:
            coverage = weighted_members / len(priced)

        ranges = [
            m.range_position_pct
            for m in members
            if m.range_position_pct is not None
        ]

        sectors.append(
            SectorMarketData(
                sector=sector,
                change_pct=change_pct,
                constituent_count=len(members),
                priced_count=len(changes),
                positive_count=sum(1 for c in changes if c > 0),
                negative_count=sum(1 for c in changes if c < 0),
                unchanged_count=sum(1 for c in changes if c == 0),
                aggregation_method=method,
                weight_coverage=coverage,
                fell_back_to_equal_weight=fell_back,
                avg_range_position_pct=_mean(ranges),
                range_count=len(ranges),
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


# --------------------------------------------------------------------------
# Sector highlights: the single best / worst mover inside each sector
# --------------------------------------------------------------------------


@dataclass
class SectorHighlight:
    """One sector paired with a single notable constituent.

    Feeds the two tables under the heatmap: for each advancing sector its
    strongest stock, and for each declining sector its weakest.
    """

    sector: str
    sector_change_pct: Optional[float]
    symbol: str
    change_pct: Optional[float]
    ltp: Optional[float]
    previous_close: Optional[float]


def _by_sector(
    stocks: Iterable[StockMarketData],
) -> Dict[str, List[StockMarketData]]:
    grouped: Dict[str, List[StockMarketData]] = {}
    for stock in stocks:
        grouped.setdefault(stock.sector, []).append(stock)
    return grouped


def _highlight(
    sector: SectorMarketData,
    members: List[StockMarketData],
    best: bool,
) -> Optional[SectorHighlight]:
    """Best (or worst) priced constituent of one sector, or None if none are priced."""
    priced = [m for m in members if m.change_pct is not None]
    if not priced:
        return None
    ranked = rank_constituents(priced)
    pick = ranked[0] if best else ranked[-1]
    return SectorHighlight(
        sector=sector.sector,
        sector_change_pct=sector.change_pct,
        symbol=pick.symbol,
        change_pct=pick.change_pct,
        ltp=pick.ltp,
        previous_close=pick.previous_close,
    )


def leading_sector_highlights(
    stocks: Iterable[StockMarketData],
    sectors: Iterable[SectorMarketData],
    limit: Optional[int] = None,
) -> List[SectorHighlight]:
    """Advancing sectors, strongest first, each with its best constituent.

    Only sectors with a positive change appear: a "top performers" table that
    listed a sector which fell would be misleading. One row per sector, so the
    table never shows two stocks from the same sector.
    """
    members = _by_sector(stocks)
    rows = [
        _highlight(sector, members.get(sector.sector, []), best=True)
        for sector in rank_sectors(sectors)
        if sector.change_pct is not None and sector.change_pct > 0
    ]
    found = [row for row in rows if row is not None]
    return found[:limit] if limit else found


def lagging_sector_highlights(
    stocks: Iterable[StockMarketData],
    sectors: Iterable[SectorMarketData],
    limit: Optional[int] = None,
) -> List[SectorHighlight]:
    """Declining sectors, weakest first, each with its worst constituent."""
    members = _by_sector(stocks)
    declining = [
        sector
        for sector in rank_sectors(sectors)
        if sector.change_pct is not None and sector.change_pct < 0
    ]
    rows = [
        _highlight(sector, members.get(sector.sector, []), best=False)
        for sector in reversed(declining)
    ]
    found = [row for row in rows if row is not None]
    return found[:limit] if limit else found
