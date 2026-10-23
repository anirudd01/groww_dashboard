"""Treemap and table for the drop-from-high page (Plotly).

Rendering only. The drops come from ``market.drawdown``. Each tile is a stock coloured by how far it
trades below its high: green at the high, through pale to dark red at ``limit`` and beyond. Tiles
can sit inside sector boxes, and the outer box is the whole universe, so the sector and index level
read off the same picture. A box's colour is its stocks' weighted drop.
"""

from typing import Dict, List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go

from market.drawdown import Drawdown, weighted_drop

#: Drop (as a positive %) at which the colour stops getting darker. Fixed, not fitted to the
#: data, so the same red means the same drop on every window and every day.
DEFAULT_LIMIT_PCT = 40.0

#: Positions on a scale running from -limit (0.0) to 0% (1.0). At 40%: under 2% off the high is
#: green, 5% pale, 10% light red, 20% red, 30% and beyond dark red.
DROP_COLOURSCALE = [
    [0.00, "#5c0f0f"],
    [0.25, "#8b1a1a"],
    [0.50, "#d4605a"],
    [0.75, "#f0b7b2"],
    [0.875, "#f2f2f2"],
    [0.95, "#b2ddb8"],
    [1.00, "#12631f"],
]

UNKNOWN_SECTOR = "Other"


def _node_text(name: str, drop: float) -> str:
    return f"<b>{name}</b><br>{drop:+.1f}%"


def _stock_hover(row: Drawdown, sector: str) -> str:
    notes = []
    if row.reset_on:
        notes.append(f"Measured from {row.reset_on} (suspected split/demerger)")
    if row.partial:
        notes.append(f"History starts {row.first_date}: partial window")
    return (
        f"<b>{row.symbol}</b> · {sector}<br>"
        f"Close {row.close:,.2f} ({row.last_date})<br>"
        f"High {row.high:,.2f} on {row.high_date}, {row.sessions_since_high} sessions ago<br>"
        f"<b>{row.drop_pct:+.2f}%</b> from the high · {row.above_low_pct:+.1f}% above the low ({row.low:,.2f})"
        + "".join(f"<br><i>{n}</i>" for n in notes)
    )


def build_drawdown_treemap(rows: Sequence[Drawdown], root: str, sectors: Optional[Dict[str, str]] = None,
                           weights: Optional[Dict[str, float]] = None, limit: float = DEFAULT_LIMIT_PCT,
                           height: int = 720) -> go.Figure:
    """One treemap: ``root`` > (sector >) stock. ``sectors`` None = no sector boxes.

    ``weights`` sizes the tiles (free-float market cap); a stock without one gets the median
    weight, and with no weights every tile is the same size.
    """
    if not rows:
        return go.Figure()
    weights = weights or {}
    known = sorted(w for w in (weights.get(r.symbol) for r in rows) if w)
    fallback = known[len(known) // 2] if known else 1.0
    size = {r.symbol: weights.get(r.symbol) or fallback for r in rows}

    ids, labels, parents, values, colours, texts, hovers = [], [], [], [], [], [], []

    def add(node_id, label, parent, value, drop, text, hover):
        ids.append(node_id)
        labels.append(label)
        parents.append(parent)
        values.append(value)
        colours.append(drop)
        texts.append(text)
        hovers.append(hover)

    root_drop = weighted_drop(rows, weights)
    add("root", root, "", 0, root_drop, _node_text(root, root_drop),
        f"<b>{root}</b><br>{len(rows)} stocks, weighted drop {root_drop:+.2f}%")
    if sectors is not None:
        groups: Dict[str, List[Drawdown]] = {}
        for row in rows:
            groups.setdefault(sectors.get(row.symbol) or UNKNOWN_SECTOR, []).append(row)
        for name, members in sorted(groups.items()):
            drop = weighted_drop(members, weights)
            add(f"sector:{name}", name, "root", 0, drop, _node_text(name, drop),
                f"<b>{name}</b><br>{len(members)} stocks, weighted drop {drop:+.2f}%<br>"
                f"Deepest: {min(members, key=lambda r: r.drop_pct).symbol}")
    for row in rows:
        sector = (sectors or {}).get(row.symbol) or UNKNOWN_SECTOR
        parent = f"sector:{sector}" if sectors is not None else "root"
        flag = " *" if row.reset_on or row.partial else ""
        add(row.symbol, row.symbol, parent, size[row.symbol], row.drop_pct,
            _node_text(row.symbol + flag, row.drop_pct), _stock_hover(row, sector))

    figure = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="remainder",
            text=texts,
            textinfo="text",
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
            tiling={"packing": "squarify", "pad": 2},
            marker={
                "colors": colours,
                "colorscale": DROP_COLOURSCALE,
                "cmin": -limit,
                "cmax": 0,
                "line": {"width": 1, "color": "rgba(0,0,0,0.25)"},
                "showscale": True,
                "colorbar": {"title": {"text": "From high"}, "ticksuffix": "%", "thickness": 12},
            },
            pathbar={"visible": True},
            textfont={"size": 14},
            textposition="middle center",
            maxdepth=3,
        )
    )
    figure.update_layout(
        height=height,
        margin={"t": 30, "l": 5, "r": 5, "b": 5},
        paper_bgcolor="rgba(0,0,0,0)",
        uniformtext={"minsize": 9, "mode": "hide"},
    )
    return figure


def stocks_frame(rows: Sequence[Drawdown], sectors: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """One row per stock, deepest drop first, for the table and the CSV."""
    return pd.DataFrame([{
        "Symbol": r.symbol,
        "Sector": (sectors or {}).get(r.symbol) or UNKNOWN_SECTOR,
        "From high %": round(r.drop_pct, 2),
        "Close": r.close,
        "High": r.high,
        "High on": r.high_date,
        "Sessions since high": r.sessions_since_high,
        "Low": r.low,
        "Above low %": round(r.above_low_pct, 2),
        "Close on": r.last_date,
        "Measured from": r.first_date,
        "Note": ("after a suspected split/demerger" if r.reset_on
                 else "partial window (history starts later)" if r.partial else ""),
    } for r in rows])


def sectors_frame(summaries) -> pd.DataFrame:
    """``market.drawdown.by_sector`` as a table."""
    return pd.DataFrame([{
        "Sector": s.name,
        "Stocks": s.count,
        "Weighted from high %": round(s.weighted_drop_pct, 2),
        "Median from high %": round(s.median_drop_pct, 2),
        "Within 5% of high": s.near_high,
        "Down 20%+": s.deep_drop,
        "Deepest": s.worst,
    } for s in summaries])
