"""Screen 1: the live sector heatmap (Plotly treemap).

Rendering only. All aggregation happens in ``market.sector_aggregation``; this
module never calls the Groww API.
"""

from typing import List, Optional, Sequence

import plotly.graph_objects as go

from market.models import SectorMarketData

# Diverging red -> neutral -> green, centred on zero. Colour encodes the sector's
# percentage change; it is never assigned per sector name.
DIVERGING_COLOURSCALE = [
    [0.00, "#8b1a1a"],  # strongest decline
    [0.25, "#d4605a"],
    [0.45, "#f0b7b2"],
    [0.50, "#f2f2f2"],  # neutral at exactly 0%
    [0.55, "#b2ddb8"],
    [0.75, "#4fa35c"],
    [1.00, "#12631f"],  # strongest advance
]


def colour_scale_limit(
    sectors: Sequence[SectorMarketData], minimum: float = 0.75
) -> float:
    """Symmetric +/- bound for the colour scale.

    Driven by the widest sector move so intensity is relative to the rest of
    the board, with a floor so a flat day does not render as uniform grey.
    """
    magnitudes = [abs(s.change_pct) for s in sectors if s.change_pct is not None]
    return max([minimum] + magnitudes)


def _tile_text(sector: SectorMarketData) -> str:
    if sector.change_pct is None:
        return f"<b>{sector.sector}</b><br>no data"
    return f"<b>{sector.sector}</b><br>{sector.change_pct:+.2f}%"


def build_sector_treemap(
    sectors: List[SectorMarketData],
    min_colour_scale_pct: float = 0.75,
    height: int = 620,
) -> go.Figure:
    """Build the treemap for the supplied sectors, in the order given.

    Tile *area* is deliberately constant (value=1 for every sector): area
    carries no meaning in Phase 1. Performance is encoded by colour only.
    """
    limit = colour_scale_limit(sectors, min_colour_scale_pct)

    # Sectors without a computable change sit at the neutral midpoint rather
    # than being dropped, so the board always shows the full universe.
    colours = [0.0 if s.change_pct is None else s.change_pct for s in sectors]

    customdata = [
        [
            s.priced_count,
            s.constituent_count,
            s.positive_count,
            s.negative_count,
        ]
        for s in sectors
    ]

    figure = go.Figure(
        go.Treemap(
            labels=[s.sector for s in sectors],
            parents=[""] * len(sectors),
            values=[1] * len(sectors),
            text=[_tile_text(s) for s in sectors],
            textinfo="text",
            customdata=customdata,
            # sort=False makes Plotly lay tiles out in the order supplied
            # instead of re-sorting by value (all values are equal here).
            sort=False,
            tiling={"packing": "squarify", "pad": 3},
            marker={
                "colors": colours,
                "colorscale": DIVERGING_COLOURSCALE,
                "cmid": 0,
                "cmin": -limit,
                "cmax": limit,
                "line": {"width": 2, "color": "rgba(0,0,0,0)"},
                "showscale": False,
            },
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Change: %{color:+.2f}%<br>"
                "Priced: %{customdata[0]}/%{customdata[1]} stocks<br>"
                "Advancing: %{customdata[2]} &nbsp; Declining: %{customdata[3]}"
                "<extra></extra>"
            ),
            textfont={"size": 17, "color": "#111111"},
            textposition="middle center",
        )
    )
    figure.update_layout(
        height=height,
        margin={"t": 10, "l": 10, "r": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        uniformtext={"minsize": 11, "mode": "hide"},
    )
    return figure


def selected_sector_from_event(event, known_sectors: Sequence[str]) -> Optional[str]:
    """Pull a sector name out of a Streamlit Plotly selection event.

    Returns ``None`` when nothing usable was selected. Plotly/Streamlit event
    payload shapes differ between chart types and versions, so every access is
    defensive - the selectbox fallback covers whatever this misses.
    """
    if not event:
        return None
    try:
        selection = event.selection if hasattr(event, "selection") else event.get("selection")
        points = (selection or {}).get("points") or []
    except (AttributeError, TypeError):
        return None

    valid = set(known_sectors)
    for point in points:
        if not isinstance(point, dict):
            continue
        for key in ("label", "id", "text", "x"):
            candidate = point.get(key)
            if isinstance(candidate, str) and candidate in valid:
                return candidate
    return None
