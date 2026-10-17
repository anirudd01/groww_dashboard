"""Instrument universes for the sector heatmap.

A universe is a named list of constituents plus their sector classification.

Two kinds of universe exist:

* **Cash equity** (``SEGMENT_CASH``) - an NSE index's members (Nifty 50, Nifty
  Next 50), aggregated into sectors by the heatmap. The members and their
  sectors come from NSE's published lists, stored in ``data/market.db`` by
  ``python scripts/<broker>.py --master`` (see ``market/index_constituents.py``).
  They are read from the database on every lookup, so a ``--master`` run is
  picked up without a code change.
* **Index** (``SEGMENT_INDEX``) - NSE indices, where each constituent *is*
  its own tile and no aggregation happens. See ``market/index_mapping.py``.

The segment travels with each constituent so providers can address the right
exchange segment without anything above them knowing broker specifics.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from market import index_constituents
from market.index_mapping import ALL_INDICES

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


SECTORAL_INDICES = _build_index_universe()

#: Key of the index board, used by the dashboard's second page.
INDEX_UNIVERSE_KEY = SECTORAL_INDICES.key

DEFAULT_UNIVERSE_KEY = "NIFTY50"

MASTER_HINT = "Run 'python scripts/kite.py --master' (or dhan.py / indmoney.py) to download NSE's lists."


def universes(path: Optional[str] = None) -> Dict[str, Universe]:
    """Every known universe, keyed by key: the stored NSE indices, then the index board.

    An index in ``INDEX_FILES`` that is not stored yet is still listed, with no
    constituents, so asking for it explains what to run rather than "unknown".
    ``path`` is a database file, for tests; the default is the shared one.
    """
    document = index_constituents.load(path) or {}
    stored = document.get("indices") or {}
    labels = document.get("labels") or {}
    found: Dict[str, Universe] = {}
    for key in list(index_constituents.INDEX_FILES) + [k for k in stored if k not in index_constituents.INDEX_FILES]:
        label = labels.get(key) or index_constituents.INDEX_FILES.get(key, (key, ""))[0]
        members = stored.get(key) or {}
        found[key] = _build(key, label, {symbol: row.get("sector", "") for symbol, row in members.items()})
    found[SECTORAL_INDICES.key] = SECTORAL_INDICES
    return found


def get_universe(key: str = DEFAULT_UNIVERSE_KEY, path: Optional[str] = None) -> Universe:
    """Look up a universe by key, raising a clear error for unknown keys."""
    normalised = (key or DEFAULT_UNIVERSE_KEY).upper().replace(" ", "").replace("_", "")
    known = universes(path)
    universe = known.get(normalised)
    if universe is None:
        raise KeyError(
            f"Unknown universe {key!r}. Available: {', '.join(sorted(known))}"
        )
    if not universe.constituents:
        raise ValueError(
            f"Universe {universe.key!r} has no constituents stored. {MASTER_HINT}"
        )
    return universe


def available_universes(path: Optional[str] = None) -> List[Universe]:
    """Universes that actually have constituents stored."""
    return [u for u in universes(path).values() if u.constituents]


def tracked_symbols(path: Optional[str] = None) -> Tuple[Dict[str, Set[str]], List[Universe]]:
    """Symbols the instrument-id sets must resolve, grouped by segment, and the universes they came from.

    Shared by every broker's ``--master`` run. An index with no constituents
    stored is left out: there is nothing to resolve for it.
    """
    wanted: Dict[str, Set[str]] = {SEGMENT_CASH: set(), SEGMENT_INDEX: set()}
    included = available_universes(path)
    for universe in included:
        wanted.setdefault((universe.segment or SEGMENT_CASH).upper(), set()).update(universe.symbols)
    return wanted, included
