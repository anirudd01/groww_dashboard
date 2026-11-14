"""Treemap and tables for the rise-from-low page (Plotly).

Rendering only. The rises come from ``market.rally``. Each tile is a stock coloured by how far it
trades above its low: red at the low, through pale to dark green at ``limit`` and beyond. Tiles can
sit inside sector boxes, and the outer box is the whole universe. A box's colour is its stocks'
weighted rise. The mirror of ``ui/drawdown_treemap.py``.
"""

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

from market.rally import Rally, weighted_rise

#: Rise (%) at which the colour stops getting darker. Fixed, not fitted to the data, so the same
#: green means the same rise on every window and every day.
DEFAULT_LIMIT_PCT = 50.0

#: Positions on a scale running from 0% (0.0) to +limit (1.0). At 50%: at the low is red, 2% light
#: red, 5% pale, 10% light green, 25% green, 50% and beyond dark green.
RISE_COLOURSCALE = [
    [0.00, "#8b1a1a"],
    [0.04, "#e08a84"],
    [0.10, "#f2f2f2"],
    [0.20, "#b2ddb8"],
    [0.50, "#3f9a4f"],
    [1.00, "#0b4a17"],
]

UNKNOWN_SECTOR = "Other"


def _node_text(name: str, rise: float) -> str:
    return f"<b>{name}</b><br>{rise:+.1f}%"


def _stock_hover(row: Rally, sector: str) -> str:
    notes = []
    if row.reset_on:
        notes.append(f"Measured from {row.reset_on} (suspected split/demerger)")
    if row.partial:
        notes.append(f"History starts {row.first_date}: partial window")
    order = (f"Low came after the high: {row.recovered_pct:.0f}% of the fall won back"
             if row.recovered_pct is not None else "Low came before the high")
    return (
        f"<b>{row.symbol}</b> · {sector}<br>"
        f"Close {row.close:,.2f} ({row.last_date})<br>"
        f"Low {row.low:,.2f} on {row.low_date}, {row.sessions_since_low} sessions ago<br>"
        f"<b>{row.rise_pct:+.2f}%</b> from the low · {row.from_high_pct:+.1f}% from the high "
        f"({row.high:,.2f} on {row.high_date})<br>{order}"
        + "".join(f"<br><i>{n}</i>" for n in notes)
    )


def build_rally_treemap(rows: Sequence[Rally], root: str, sectors: dict[str, str] | None = None,
                        weights: dict[str, float] | None = None, limit: float = DEFAULT_LIMIT_PCT,
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

    def add(node_id, label, parent, value, rise, text, hover):
        ids.append(node_id)
        labels.append(label)
        parents.append(parent)
        values.append(value)
        colours.append(rise)
        texts.append(text)
        hovers.append(hover)

    root_rise = weighted_rise(rows, weights)
    add("root", root, "", 0, root_rise, _node_text(root, root_rise),
        f"<b>{root}</b><br>{len(rows)} stocks, weighted rise {root_rise:+.2f}%")
    if sectors is not None:
        groups: dict[str, list[Rally]] = {}
        for row in rows:
            groups.setdefault(sectors.get(row.symbol) or UNKNOWN_SECTOR, []).append(row)
        for name, members in sorted(groups.items()):
            rise = weighted_rise(members, weights)
            add(f"sector:{name}", name, "root", 0, rise, _node_text(name, rise),
                f"<b>{name}</b><br>{len(members)} stocks, weighted rise {rise:+.2f}%<br>"
                f"Biggest rise: {max(members, key=lambda r: r.rise_pct).symbol}")
    for row in rows:
        sector = (sectors or {}).get(row.symbol) or UNKNOWN_SECTOR
        parent = f"sector:{sector}" if sectors is not None else "root"
        flag = " *" if row.reset_on or row.partial else ""
        add(row.symbol, row.symbol, parent, size[row.symbol], row.rise_pct,
            _node_text(row.symbol + flag, row.rise_pct), _stock_hover(row, sector))

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
                "colorscale": RISE_COLOURSCALE,
                "cmin": 0,
                "cmax": limit,
                "line": {"width": 1, "color": "rgba(0,0,0,0.25)"},
                "showscale": True,
                "colorbar": {"title": {"text": "From low"}, "ticksuffix": "%", "thickness": 12},
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


def stocks_frame(rows: Sequence[Rally], sectors: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per stock, biggest rise first, for the table and the CSV."""
    return pd.DataFrame([{
        "Symbol": r.symbol,
        "Sector": (sectors or {}).get(r.symbol) or UNKNOWN_SECTOR,
        "From low %": round(r.rise_pct, 2),
        "Close": r.close,
        "Low": r.low,
        "Low on": r.low_date,
        "Sessions since low": r.sessions_since_low,
        "High": r.high,
        "High on": r.high_date,
        "From high %": round(r.from_high_pct, 2),
        "Low came": "after the high" if r.low_after_high else "before the high",
        "Fall won back %": None if r.recovered_pct is None else round(r.recovered_pct, 1),
        "Close on": r.last_date,
        "Measured from": r.first_date,
        "Note": ("after a suspected split/demerger" if r.reset_on
                 else "partial window (history starts later)" if r.partial else ""),
    } for r in rows])


def sectors_frame(summaries) -> pd.DataFrame:
    """``market.rally.by_sector`` as a table."""
    return pd.DataFrame([{
        "Sector": s.name,
        "Stocks": s.count,
        "Weighted from low %": round(s.weighted_rise_pct, 2),
        "Median from low %": round(s.median_rise_pct, 2),
        "Within 5% of low": s.near_low,
        "Up 20%+": s.strong_rise,
        "Biggest rise": s.best,
    } for s in summaries])
