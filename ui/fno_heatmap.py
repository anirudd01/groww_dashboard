"""Stock x day heatmap for the F&O consistency page (Plotly).

Rendering only. Rows and scores come from ``market.fno_consistency``. Each row
is a stock and each column a trading day, and a cell's colour is that day's %
change. A stock that rose day after day reads as a solid green row.
"""

from typing import List, Sequence

import pandas as pd
import plotly.graph_objects as go

from market.fno_consistency import ConsistencyRow
from ui.sector_heatmap import DIVERGING_COLOURSCALE

#: The colour scale never saturates below this, so a quiet week still shows contrast.
MIN_LIMIT_PCT = 1.0
#: Cells show their % value only up to this many columns; past it the text is unreadable.
MAX_LABELLED_DAYS = 10
ROW_HEIGHT = 26


def colour_limit(rows: Sequence[ConsistencyRow], minimum: float = MIN_LIMIT_PCT) -> float:
    """Symmetric +/- bound: the 95th percentile of |daily move|, so one outlier cannot wash out the rest."""
    magnitudes = sorted(abs(c) for r in rows for c in r.changes)
    if not magnitudes:
        return minimum
    return max(minimum, magnitudes[min(len(magnitudes) - 1, int(len(magnitudes) * 0.95))])


def row_label(row: ConsistencyRow) -> str:
    """Y-axis label: symbol, up days and net change, so the ranking reasons are visible."""
    return f"<b>{row.symbol}</b>  {row.up_days}/{row.days}↑  {row.net_change_pct:+.1f}%"


def build_heatmap(rows: List[ConsistencyRow], limit: float = None, scale_title: str = "Day %") -> go.Figure:
    """One heatmap, rows in the order given (top row first)."""
    if not rows:
        return go.Figure()
    limit = limit or colour_limit(rows)
    dates = rows[0].dates
    x = [pd.Timestamp(d).strftime("%a %d %b") for d in dates]
    # Text is formatted here rather than with Plotly's %{z:+.1f}: the front end Streamlit
    # ships did not apply that format (cells showed the raw float), so nothing is left to it.
    def cell(r: ConsistencyRow, i: int, change: float) -> str:
        close = f" (close {r.closes[i + 1]:,.2f})" if r.closes else ""
        return (f"<b>{r.symbol}</b>  {x[i]}: <b>{change:+.2f}%</b>{close}"
                f"<br>Consistency {r.score:+.0f} · net {r.net_change_pct:+.2f}% · up {r.up_days}/{r.days} days")

    hover = [[cell(r, i, c) for i, c in enumerate(r.changes)] for r in rows]
    labelled = len(dates) <= MAX_LABELLED_DAYS
    figure = go.Figure(
        go.Heatmap(
            z=[r.changes for r in rows],
            x=x,
            y=[row_label(r) for r in rows],
            text=[[f"{c:+.1f}" for c in r.changes] for r in rows],
            hovertext=hover,
            colorscale=DIVERGING_COLOURSCALE,
            zmid=0,
            zmin=-limit,
            zmax=limit,
            xgap=2,
            ygap=2,
            texttemplate="%{text}" if labelled else None,
            textfont={"size": 11},
            colorbar={"title": {"text": scale_title}, "ticksuffix": "%", "thickness": 12},
            hovertemplate="%{hovertext}<extra></extra>",
        )
    )
    figure.update_layout(
        height=max(220, ROW_HEIGHT * len(rows) + 90),
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        xaxis={"side": "top", "type": "category"},
        yaxis={"autorange": "reversed", "type": "category"},
    )
    return figure


def rows_frame(rows: List[ConsistencyRow], up_label: str = "Up days", down_label: str = "Down days") -> pd.DataFrame:
    """The heatmap's rows as a table, one column per day, for display and CSV export."""
    records = []
    for r in rows:
        record = {"Symbol": r.symbol, "Consistency": round(r.score, 1), up_label: r.up_days,
                  down_label: r.down_days, "Net change %": round(r.net_change_pct, 2)}
        record.update({d: round(c, 2) for d, c in zip(r.dates, r.changes)})
        records.append(record)
    return pd.DataFrame(records)
