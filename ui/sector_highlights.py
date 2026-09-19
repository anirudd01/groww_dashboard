"""The two tables beneath the heatmap: sector leaders and sector laggards.

One row per sector, never two rows from the same sector:

* **Leading sectors** - every sector that is *up*, strongest first, each paired
  with its own best-performing constituent.
* **Lagging sectors** - every sector that is *down*, weakest first, each paired
  with its own worst-performing constituent.

The point is to answer "which sector is moving, and what is driving it" without
scrolling through 50 stocks. A sector appears in exactly one table or neither;
a flat sector (or one with no data) appears in neither, because calling a
sector that has not moved a "top performer" would be misleading.

These are observations, not recommendations. Nothing here ranks stocks as
things to buy or sell.
"""

from typing import List, Optional

import pandas as pd

from market.sector_aggregation import SectorHighlight
from ui.colours import MIN_SCALE_PCT, change_background, scale_limit

LEADER_COLUMNS = ["Sector", "Sector %", "Best Stock", "Stock %", "LTP"]
LAGGARD_COLUMNS = ["Sector", "Sector %", "Worst Stock", "Stock %", "LTP"]

#: Both tables share one colour scale so a -2% cell in the laggards table is
#: exactly as dark as a +2% cell in the leaders table.
PERCENT_COLUMNS = ("Sector %", "Stock %")


def build_highlight_table(
    highlights: List[SectorHighlight], stock_column: str = "Best Stock"
) -> pd.DataFrame:
    """Rows in the order given - the caller has already ranked them.

    Numeric columns stay numeric (``NaN`` when unknown) so they can be both
    formatted and colour graded.
    """
    columns = ["Sector", "Sector %", stock_column, "Stock %", "LTP"]
    frame = pd.DataFrame(
        [
            {
                "Sector": row.sector,
                "Sector %": row.sector_change_pct,
                stock_column: row.symbol,
                "Stock %": row.change_pct,
                "LTP": row.ltp if row.ltp and row.ltp > 0 else None,
            }
            for row in highlights
        ],
        columns=columns,
    )
    return frame


def style_highlight_table(
    frame: pd.DataFrame,
    min_colour_scale_pct: float = MIN_SCALE_PCT,
    limit: Optional[float] = None,
):
    """Format and colour-grade both percentage columns.

    ``limit`` lets the caller share one scale across the leaders and laggards
    tables; without it each table would normalise to its own strongest mover
    and the two would not be comparable.
    """
    present = [c for c in PERCENT_COLUMNS if c in frame.columns]

    if limit is None:
        values: List[Optional[float]] = []
        for column in present:
            values.extend(list(frame[column]))
        limit = scale_limit(values, min_colour_scale_pct)

    styler = frame.style.format(
        {
            **{c: (lambda v: "-" if pd.isna(v) else f"{v:+.2f}%") for c in present},
            "LTP": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
        }
    )
    if present:
        styler = styler.map(
            lambda v: change_background(None if pd.isna(v) else float(v), limit),
            subset=present,
        )
    return styler


def combined_scale_limit(
    frames: List[pd.DataFrame], min_colour_scale_pct: float = MIN_SCALE_PCT
) -> float:
    """One colour scale spanning several highlight tables."""
    values: List[Optional[float]] = []
    for frame in frames:
        for column in PERCENT_COLUMNS:
            if column in frame.columns:
                values.extend(list(frame[column]))
    return scale_limit(values, min_colour_scale_pct)
