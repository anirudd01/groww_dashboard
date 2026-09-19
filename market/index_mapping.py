"""NSE indices tracked by the sectoral-index heatmap.

This board shows the **real NSE indices**, not an aggregate of the Nifty 50
members we happen to track. The two boards answer different questions and are
expected to disagree:

    Nifty 50 board  -> "how are the Nifty 50's IT names doing"
    Index board     -> "how is the IT sector doing" (a wider constituent list)

A gap between them is informative: it means the large caps in a sector are
moving differently from the sector as a whole.

Editing this list
-----------------
``symbol`` must match the instrument master exactly (Dhan publishes indices
under ``EXCH_ID=NSE, SEGMENT=I, INSTRUMENT=INDEX``). Security ids are resolved
at startup and are never hardcoded, so adding an index means adding one row
here - run ``python scripts/check_heatmap_universe.py --board indices``
afterwards to confirm it resolves.

``sector`` links an index to a sector in ``sector_mapping.py`` for drill-down.
It is the sector whose **Nifty 50 members** are shown when the tile is clicked,
which is deliberately *not* the index's real constituent list - the brokers do
not publish that, and the UI says so. ``None`` means no sensible link exists
(broad benchmarks, and sectors with no Nifty 50 representation).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class IndexDefinition:
    """One index tile on the board."""

    #: Instrument-master symbol. Resolved to a broker id at startup.
    symbol: str
    #: What the tile shows.
    label: str
    #: Sector in ``sector_mapping.py`` whose Nifty 50 members the drill-down
    #: lists, or None when no honest link exists.
    sector: Optional[str] = None
    #: Broad market benchmarks render after the sectoral tiles.
    is_benchmark: bool = False


#: The NSE sectoral indices. Order is the display order.
SECTORAL_INDICES: Tuple[IndexDefinition, ...] = (
    IndexDefinition("NIFTY AUTO", "Nifty Auto", "Automobile"),
    IndexDefinition("BANKNIFTY", "Nifty Bank", "Banks"),
    IndexDefinition("NIFTY CONSR DURBL", "Nifty Consumer Durables", "Consumer Durables"),
    IndexDefinition("FINNIFTY", "Nifty Financial Services", "Financial Services"),
    IndexDefinition("NIFTY FMCG", "Nifty FMCG", "FMCG"),
    IndexDefinition("NIFTY HEALTHCARE", "Nifty Healthcare", "Healthcare"),
    IndexDefinition("NIFTYIT", "Nifty IT", "Information Technology"),
    # No Nifty 50 member is classified under Media or Realty, so these two have
    # no drill-down rather than a misleading one.
    IndexDefinition("NIFTY MEDIA", "Nifty Media", None),
    IndexDefinition("NIFTY METAL", "Nifty Metal", "Metals & Mining"),
    IndexDefinition(
        "NIFTY OIL AND GAS", "Nifty Oil & Gas", "Oil, Gas & Consumable Fuels"
    ),
    # Pharma and Healthcare both drill into our Healthcare bucket - our sector
    # mapping does not separate them. The drill-down names the sector it shows.
    IndexDefinition("NIFTY PHARMA", "Nifty Pharma", "Healthcare"),
    IndexDefinition("NIFTY PVT BANK", "Nifty Private Bank", "Banks"),
    IndexDefinition("NIFTY PSU BANK", "Nifty PSU Bank", "Banks"),
    IndexDefinition("NIFTY REALTY", "Nifty Realty", None),
)

#: Broad benchmarks, shown after the sectoral tiles for context. Nifty Bank is
#: deliberately absent here - it is already a sectoral tile above.
BENCHMARK_INDICES: Tuple[IndexDefinition, ...] = (
    IndexDefinition("NIFTY", "Nifty 50", None, is_benchmark=True),
    IndexDefinition("NIFTYNXT50", "Nifty Next 50", None, is_benchmark=True),
    IndexDefinition("NIFTY 500", "Nifty 500", None, is_benchmark=True),
)

ALL_INDICES: Tuple[IndexDefinition, ...] = SECTORAL_INDICES + BENCHMARK_INDICES


def index_by_symbol() -> Dict[str, IndexDefinition]:
    return {definition.symbol: definition for definition in ALL_INDICES}


def index_by_label() -> Dict[str, IndexDefinition]:
    return {definition.label: definition for definition in ALL_INDICES}


def sector_for_label(label: str) -> Optional[str]:
    """The sector whose Nifty 50 members back this index tile, if any."""
    definition = index_by_label().get(label)
    return definition.sector if definition else None


def index_symbols() -> List[str]:
    return [definition.symbol for definition in ALL_INDICES]
