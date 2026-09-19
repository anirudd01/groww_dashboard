"""Screen 3: the NSE sectoral index heatmap.

Each tile is a **real NSE index**, not an aggregate of the Nifty 50 members we
track. No averaging happens here: the number on a tile is the index's own
percentage change against its own previous close.

The two boards are expected to disagree, and the difference is the point - it
shows where the Nifty 50's large caps are moving differently from the wider
sector. See ``market/index_mapping.py``.
"""

from typing import List, Optional

import pandas as pd

from market.index_mapping import index_by_label
from market.models import SectorMarketData, StockMarketData

INDEX_DETAIL_COLUMNS = ["Index", "LTP", "Change %", "Previous Close", "Open", "Day Range"]


def index_tooltip(sector: SectorMarketData) -> str:
    """Hover text for an index tile.

    Deliberately not the constituent-breadth text used on the Nifty 50 board:
    an index tile has exactly one underlying value, so "1/1 priced" would be
    noise. This says what the tile is and what it drills into instead.
    """
    definition = index_by_label().get(sector.sector)
    if definition is None:
        return "NSE index"

    if sector.priced_count == 0:
        return f"{definition.symbol} - waiting for data"

    if definition.is_benchmark:
        return f"{definition.symbol} - broad market benchmark"
    if definition.sector:
        return f"{definition.symbol} - click for Nifty 50 members of {definition.sector}"
    return f"{definition.symbol} - no Nifty 50 members map to this index"


def format_index_summary(stock: Optional[StockMarketData]) -> str:
    """One-line summary of an index's own numbers, for the drill-down header."""
    if stock is None or stock.ltp is None:
        return "No live value yet."

    parts = [f"**{stock.ltp:,.2f}**"]
    if stock.change_pct is not None:
        parts.append(f"{stock.change_pct:+.2f}%")
    if stock.previous_close:
        parts.append(f"prev close {stock.previous_close:,.2f}")
    if stock.day_low and stock.day_high:
        parts.append(f"day range {stock.day_low:,.2f} - {stock.day_high:,.2f}")
    return "  ·  ".join(parts)


def build_index_table(stocks: List[StockMarketData]) -> pd.DataFrame:
    """All index values in one table, strongest first.

    Numeric columns stay numeric (``NaN`` when unknown) so they can be both
    formatted and colour graded, matching the constituent table's behaviour.
    """
    ordered = sorted(
        stocks,
        key=lambda s: (
            float("-inf") if s.change_pct is None else s.change_pct,
        ),
        reverse=True,
    )
    rows = []
    for stock in ordered:
        low, high = stock.day_low, stock.day_high
        rows.append(
            {
                "Index": stock.sector,
                "LTP": stock.ltp if stock.ltp and stock.ltp > 0 else None,
                "Change %": stock.change_pct,
                "Previous Close": (
                    stock.previous_close
                    if stock.previous_close and stock.previous_close > 0
                    else None
                ),
                "Open": stock.day_open if stock.day_open else None,
                "Day Range": (
                    f"{low:,.2f} - {high:,.2f}" if low and high and high > low else "-"
                ),
            }
        )
    return pd.DataFrame(rows, columns=INDEX_DETAIL_COLUMNS)
