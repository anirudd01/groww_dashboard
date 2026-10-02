"""Date x symbol tables from the stored F&O history, shared by the insight pages.

``market.fno_movers.load_closes`` returns ``{(date, symbol): row}``, which suits
upserts. Breadth, rotation and the overnight/intraday split all need whole
columns at once ("every stock's 50-day average on each day"), so this turns it
into a pandas frame indexed by date with one column per symbol.

Days a stock has no row are NaN, never forward-filled: a gap stays a gap, the
same rule as ``daily_changes``.
"""

from typing import Dict, Iterable, Optional, Set, Tuple

import numpy as np
import pandas as pd

UNIVERSE_NIFTY50 = "Nifty 50"
UNIVERSE_ALL = "All F&O"
UNIVERSE_EX_NIFTY = "F&O outside Nifty 50"
UNIVERSES = (UNIVERSE_NIFTY50, UNIVERSE_ALL, UNIVERSE_EX_NIFTY)


def price_panel(rows: Dict[Tuple[str, str], dict], field: str = "close") -> pd.DataFrame:
    """``field`` (open/high/low/close/volume) as a date x symbol frame, dates ascending."""
    records = []
    for (day, symbol), row in rows.items():
        try:
            value = float(row.get(field))
        except (TypeError, ValueError):
            continue
        if value > 0:
            records.append((day, symbol, value))
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame.from_records(records, columns=["date", "symbol", field])
    panel = frame.pivot(index="date", columns="symbol", values=field).sort_index()
    panel.index = pd.to_datetime(panel.index)
    panel.columns.name = None
    return panel


def blank_out(panel: pd.DataFrame, pairs: Iterable[Tuple[str, str]]) -> pd.DataFrame:
    """Copy of ``panel`` with each (symbol, date) pair set to NaN (for suspected splits)."""
    out = panel.copy()
    for symbol, day in pairs:
        stamp = pd.Timestamp(day)
        if symbol in out.columns and stamp in out.index:
            out.loc[stamp, symbol] = np.nan
    return out


def daily_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Close-to-close simple returns; NaN where either day is missing (no spanning a gap)."""
    return closes / closes.shift(1) - 1


def equal_weight_index(closes: pd.DataFrame, base: float = 100.0) -> pd.Series:
    """Chain the average daily return of whatever stocks traded both days, starting at ``base``.

    The repo stores no index series, so "the market" is built from its members.
    Equal weight answers "how did the average stock do", the same default as the
    sector heatmap.
    """
    if closes.empty:
        return pd.Series(dtype=float)
    mean = daily_returns(closes).mean(axis=1, skipna=True).fillna(0.0)
    mean.iloc[0] = 0.0
    return base * (1 + mean).cumprod()


def universe_sets(fno_symbols: Iterable[str], nifty50: Iterable[str]) -> Dict[str, Set[str]]:
    """Label -> symbols, for the universe selectors on every insight page."""
    fno = set(fno_symbols)
    n50 = set(nifty50) & fno
    return {UNIVERSE_NIFTY50: n50, UNIVERSE_ALL: fno, UNIVERSE_EX_NIFTY: fno - n50}


def restrict(panel: pd.DataFrame, symbols: Optional[Iterable[str]]) -> pd.DataFrame:
    """Only the columns in ``symbols`` (all of them if None), alphabetical."""
    if symbols is None:
        return panel
    keep = sorted(set(symbols) & set(panel.columns))
    return panel[keep]
