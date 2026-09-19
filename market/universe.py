"""Instrument universes for the sector heatmap.

A universe is a named list of constituents plus their sector classification.
Add NIFTY NEXT 50 by filling in ``NIFTY_NEXT_50_SECTORS`` in
``market/sector_mapping.py`` - no other code needs to change.

Two kinds of universe exist:

* **Cash equity** (``SEGMENT_CASH``) - Nifty 50 members, aggregated into
  sectors by the heatmap.
* **Index** (``SEGMENT_INDEX``) - NSE indices, where each constituent *is*
  its own tile and no aggregation happens. See ``market/index_mapping.py``.

The segment travels with each constituent so providers can address the right
exchange segment without anything above them knowing broker specifics.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from market.index_mapping import ALL_INDICES
from market.sector_mapping import NIFTY_50_SECTORS, NIFTY_NEXT_50_SECTORS

# All cash-equity constituents trade on NSE in the CASH segment.
DEFAULT_EXCHANGE = "NSE"
SEGMENT_CASH = "CASH"
SEGMENT_INDEX = "INDEX"
DEFAULT_SEGMENT = SEGMENT_CASH


@dataclass(frozen=True)
class Constituent:
    """One index member, before any market data is attached."""

    symbol: str
    sector: str
    exchange: str = DEFAULT_EXCHANGE
    segment: str = DEFAULT_SEGMENT


@dataclass(frozen=True)
class Universe:
    """A named set of constituents the dashboard can track."""

    key: str
    label: str
    constituents: Tuple[Constituent, ...]
    #: CASH universes are aggregated into sectors; INDEX universes are not -
    #: each constituent is already a sector-level number.
    segment: str = DEFAULT_SEGMENT

    @property
    def is_index_board(self) -> bool:
        return self.segment == SEGMENT_INDEX

    @property
    def symbols(self) -> List[str]:
        return [c.symbol for c in self.constituents]

    @property
    def sectors(self) -> List[str]:
        return sorted({c.sector for c in self.constituents})

    def __len__(self) -> int:
        return len(self.constituents)


def _build(key: str, label: str, sector_map: Dict[str, str]) -> Universe:
    constituents = tuple(
        Constituent(symbol=symbol, sector=sector)
        for symbol, sector in sorted(sector_map.items())
    )
    return Universe(key=key, label=label, constituents=constituents)


def _build_index_universe() -> Universe:
    """One constituent per index; ``sector`` is the tile label.

    Grouping by label means the standard aggregation produces exactly one
    row per index carrying that index's own change - no averaging happens,
    because each group has a single member.
    """
    constituents = tuple(
        Constituent(
            symbol=definition.symbol,
            sector=definition.label,
            segment=SEGMENT_INDEX,
        )
        for definition in ALL_INDICES
    )
    return Universe(
        key="NSESECTORALINDICES",
        label="NSE Sectoral Indices",
        constituents=constituents,
        segment=SEGMENT_INDEX,
    )


NIFTY_50 = _build("NIFTY50", "Nifty 50", NIFTY_50_SECTORS)
NIFTY_NEXT_50 = _build("NIFTYNEXT50", "Nifty Next 50", NIFTY_NEXT_50_SECTORS)
SECTORAL_INDICES = _build_index_universe()

UNIVERSES: Dict[str, Universe] = {
    NIFTY_50.key: NIFTY_50,
    NIFTY_NEXT_50.key: NIFTY_NEXT_50,
    SECTORAL_INDICES.key: SECTORAL_INDICES,
}

#: Key of the index board, used by the dashboard's second page.
INDEX_UNIVERSE_KEY = SECTORAL_INDICES.key

DEFAULT_UNIVERSE_KEY = NIFTY_50.key


def get_universe(key: str = DEFAULT_UNIVERSE_KEY) -> Universe:
    """Look up a universe by key, raising a clear error for unknown keys."""
    normalised = (key or DEFAULT_UNIVERSE_KEY).upper().replace(" ", "").replace("_", "")
    universe = UNIVERSES.get(normalised)
    if universe is None:
        raise KeyError(
            f"Unknown universe {key!r}. Available: {', '.join(sorted(UNIVERSES))}"
        )
    if not universe.constituents:
        raise ValueError(
            f"Universe {universe.key!r} has no constituents configured. "
            "Populate its sector mapping in market/sector_mapping.py first."
        )
    return universe


def available_universes() -> List[Universe]:
    """Universes that actually have constituents configured."""
    return [u for u in UNIVERSES.values() if u.constituents]
