"""Consistent gap-ups and gap-downs over the last N trading days.

The Gap Fills page asks what happens *after* one gap. This asks which stocks
gap the same way **day after day**: a run of opens above the previous close
(persistent overnight demand, often news or flows outside market hours) or below
it (persistent overnight supply).

Each day's gap is ``ln(open / previous close)``, from ``session_split.split_returns``.
A day counts only if the stock also traded the day before. Scoring reuses
``market.fno_consistency.ConsistencyRow``:

* **consistency**: net gap ÷ total gap distance, -100..+100 (+100 = gapped up every day);
* **gap-up / gap-down days**: days whose gap clears ``flat_below`` % either way;
* **streak**: consecutive gap-ups (+) or gap-downs (-) ending on the last day.

``session_after_pct`` says whether the gaps *held*: the same days' open-to-close
moves compounded. A stock that gaps up daily but sells off every session nets out.

Data: ``open`` and ``close`` in the stored daily closes (``daily_bars``). No API call.
"""

import math
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from market.fno_consistency import ConsistencyRow
from market.session_split import last_days

#: Gaps smaller than this (in %) count as flat by default. NSE opens rarely match the close exactly.
DEFAULT_FLAT_BELOW = 0.1


def gap_rows(
    overnight: pd.DataFrame,
    window: int,
    symbols: Optional[Iterable[str]] = None,
    flat_below: float = DEFAULT_FLAT_BELOW,
) -> Tuple[List[ConsistencyRow], List[str]]:
    """One row per stock with a gap on **every** day of the last ``window`` days.

    ``overnight`` is a date x symbol frame of log gaps. Returns ``(rows, left_out)``.
    ``left_out`` lists symbols missing a day (a suspended day, or a blanked split
    day), the same rule as the F&O Heatmap.
    """
    frame = last_days(overnight, window)
    if window and len(frame) < window:
        return [], []
    if symbols is not None:
        frame = frame[[s for s in sorted(set(symbols)) if s in frame.columns]]
    dates = [d.strftime("%Y-%m-%d") for d in frame.index]
    rows, left_out = [], []
    for symbol in sorted(frame.columns):
        column = frame[symbol]
        if column.isna().any():
            left_out.append(symbol)
            continue
        rows.append(ConsistencyRow(symbol, dates, steps=column.tolist(), flat_below=flat_below))
    return rows, left_out


def session_after(intraday: pd.DataFrame, window: int) -> Dict[str, float]:
    """Each stock's open-to-close moves over the same window, compounded, in %."""
    total = last_days(intraday, window).sum(min_count=1)
    return {symbol: math.expm1(value) * 100 for symbol, value in total.items() if value == value}


def streak_table(rows: List[ConsistencyRow], session: Dict[str, float]) -> pd.DataFrame:
    """Per stock: current streak, gap-up/down days, net gap, average gap, consistency, session after."""
    records = []
    for r in rows:
        records.append({
            "symbol": r.symbol,
            "streak": r.streak,
            "gap_up_days": r.up_days,
            "gap_down_days": r.down_days,
            "net_gap_pct": r.net_change_pct,
            "avg_gap_pct": sum(r.changes) / r.days if r.days else 0.0,
            "consistency": r.score,
            "session_after_pct": session.get(r.symbol, float("nan")),
        })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).set_index("symbol")
