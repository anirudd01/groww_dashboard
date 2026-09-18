"""Screen 2: constituent table for one sector.

Rendering helpers only - sorting lives in ``market.sector_aggregation``.

The table keeps ``Change %`` numeric so it can be both formatted and colour
graded; ``style_constituent_table`` applies the same diverging scale the
heatmap tiles use, so the strongest mover in a sector is the darkest row.
"""

from typing import List, Optional

import pandas as pd

from market.models import StockMarketData
from market.sector_aggregation import rank_constituents
from ui.colours import MIN_SCALE_PCT, change_background, scale_limit

COLUMNS = ["Rank", "Stock", "LTP", "Change %", "Previous Close", "Last Updated"]


def _fmt_time(value) -> str:
    return "-" if value is None else value.strftime("%H:%M:%S")


def build_constituent_table(stocks: List[StockMarketData]) -> pd.DataFrame:
    """Constituent rows sorted by live percentage change, descending.

    Numeric columns stay numeric (``NaN`` where unknown) so they can be styled
    and formatted; stocks with no computable change sort to the bottom rather
    than being hidden, so a data gap stays visible.
    """
    ranked = rank_constituents(stocks)
    frame = pd.DataFrame(
        [
            {
                "Rank": position,
                "Stock": stock.symbol,
                "LTP": stock.ltp if stock.ltp and stock.ltp > 0 else None,
                "Change %": stock.change_pct,
                "Previous Close": (
                    stock.previous_close
                    if stock.previous_close and stock.previous_close > 0
                    else None
                ),
                "Last Updated": _fmt_time(stock.last_update),
            }
            for position, stock in enumerate(ranked, start=1)
        ],
        columns=COLUMNS,
    )
    return frame


def style_constituent_table(
    frame: pd.DataFrame, min_colour_scale_pct: float = MIN_SCALE_PCT
):
    """Format the table and colour-grade the ``Change %`` column.

    Shades run light-to-dark with the size of the move: the strongest advance
    in the sector is the darkest green, the steepest decline the darkest red,
    and anything without data stays neutral instead of looking flat.
    """
    limit = scale_limit(list(frame["Change %"]), min_colour_scale_pct)

    styler = (
        frame.style.format(
            {
                "LTP": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
                "Previous Close": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
                "Change %": lambda v: "-" if pd.isna(v) else f"{v:+.2f}%",
            }
        )
        .map(
            lambda v: change_background(None if pd.isna(v) else float(v), limit),
            subset=["Change %"],
        )
    )
    return styler


def change_pct_series(stocks: List[StockMarketData]) -> List[Optional[float]]:
    """Raw percentage changes in the same order as ``build_constituent_table``."""
    return [s.change_pct for s in rank_constituents(stocks)]
