"""Clickable sector heatmap built from Streamlit buttons.

Why not the Plotly treemap
--------------------------
Streamlit's Plotly component listens for ``plotly_click``, ``plotly_selected``
and ``plotly_deselect``. Plotly.js treemap traces do not emit ``plotly_click`` -
they emit ``plotly_treemapclick``, which Streamlit never wires up. A treemap
tile therefore *cannot* report a click back to Streamlit, no matter how
``on_select`` is configured. (Verified against the shipped frontend bundle.)

So the heatmap is drawn as a grid of real ``st.button`` widgets instead. Each
one is wrapped in ``st.container(key=...)``, which Streamlit renders with a
``st-key-<key>`` CSS class, letting us colour each tile individually from its
percentage change. Clicks are ordinary Streamlit widget events, so drilling
into a sector always works.

The Plotly treemap remains available in ``ui/sector_heatmap.py`` as a
display-only alternative.
"""

from typing import Callable, List, Optional, Sequence

import streamlit as st

from market.models import SectorMarketData
from ui.colours import MIN_SCALE_PCT, change_colours, scale_limit

#: Prefix for the per-tile widget/CSS keys.
TILE_KEY_PREFIX = "sector_tile"


def tile_key(sector: str) -> str:
    """Stable, CSS-safe key for one sector's tile."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in sector.lower())
    return f"{TILE_KEY_PREFIX}_{slug}"


def tile_label(sector: SectorMarketData) -> str:
    """Two-line button label: sector name above its percentage change."""
    if sector.change_pct is None:
        return f"**{sector.sector}**\n\nno data"
    return f"**{sector.sector}**\n\n{sector.change_pct:+.2f}%"


def build_tile_css(
    sectors: Sequence[SectorMarketData],
    min_colour_scale_pct: float = MIN_SCALE_PCT,
    height_px: int = 96,
) -> str:
    """One <style> block colouring every tile from its percentage change.

    Emitted as a single element per render rather than one per tile, so the
    once-a-second refresh stays cheap.
    """
    limit = scale_limit([s.change_pct for s in sectors], min_colour_scale_pct)

    rules = [
        # Shared tile shape. Scoped to our keys so no other widget is affected.
        f"""
        div[class*="{TILE_KEY_PREFIX}_"] button {{
            height: {height_px}px;
            width: 100%;
            border: none !important;
            border-radius: 10px;
            transition: transform 80ms ease, filter 120ms ease;
            white-space: normal;
            line-height: 1.35;
        }}
        div[class*="{TILE_KEY_PREFIX}_"] button:hover {{
            transform: translateY(-2px);
            filter: brightness(1.06);
        }}
        div[class*="{TILE_KEY_PREFIX}_"] button p {{
            margin: 0;
            font-size: 0.95rem;
        }}
        """
    ]

    for sector in sectors:
        background, text = change_colours(sector.change_pct, limit)
        key = tile_key(sector.sector)
        rules.append(
            f"""
            .st-key-{key} button {{
                background-color: {background} !important;
                color: {text} !important;
            }}
            .st-key-{key} button * {{ color: {text} !important; }}
            """
        )

    return "<style>" + "".join(rules) + "</style>"


def default_tooltip(sector: SectorMarketData) -> str:
    """Constituent breadth, for the aggregated Nifty 50 board."""
    return (
        f"{sector.priced_count}/{sector.constituent_count} priced"
        f" · {sector.positive_count} advancing,"
        f" {sector.negative_count} declining"
    )


def render_sector_tiles(
    sectors: List[SectorMarketData],
    columns: int = 4,
    min_colour_scale_pct: float = MIN_SCALE_PCT,
    height_px: int = 96,
    tooltip: Optional[Callable[[SectorMarketData], str]] = None,
) -> Optional[str]:
    """Draw the clickable heatmap. Returns the sector clicked, if any.

    ``sectors`` is rendered in the order given, so the caller controls whether
    tiles are ranked by performance or held in a stable alphabetical layout.

    ``tooltip`` overrides the hover text. The index board passes its own,
    because "1/1 priced, 1 advancing" would be noise on a tile that *is* a
    single index rather than an aggregate of constituents.
    """
    if not sectors:
        return None

    st.markdown(
        build_tile_css(sectors, min_colour_scale_pct, height_px),
        unsafe_allow_html=True,
    )

    clicked: Optional[str] = None
    for start in range(0, len(sectors), columns):
        row = sectors[start : start + columns]
        cells = st.columns(columns, gap="small")
        for cell, sector in zip(cells, row):
            with cell:
                # container(key=...) is what gives us the st-key-* CSS hook.
                with st.container(key=tile_key(sector.sector)):
                    if st.button(
                        tile_label(sector),
                        key=f"{tile_key(sector.sector)}_btn",
                        width="stretch",
                        help=(tooltip or default_tooltip)(sector),
                    ):
                        clicked = sector.sector
    return clicked
