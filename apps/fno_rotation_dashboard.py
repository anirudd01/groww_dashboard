"""Relative rotation (RRG-style): which sectors and stocks lead the market, and which are turning.

Each name is plotted by RS-Ratio (beating the benchmark?) and RS-Momentum (is
that edge growing?), with a trail of recent days, against an equal-weight Nifty 50
built from its members. See market/rotation.py and docs/FNO_INSIGHTS.md.

Data: the stored daily closes only. No API call. Visualisation only.

The "Relative Rotation" page of pulse_dashboard.py; on its own:

    streamlit run apps/fno_rotation_dashboard.py --server.port 8508
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import streamlit as st

from apps.fno_common import freshness, panels, require_history, source_caption, suspected_toggle, universe_options
from market.price_panel import UNIVERSE_EX_NIFTY, UNIVERSE_NIFTY50, equal_weight_index, restrict
from market.rotation import (
    IMPROVING,
    LAGGING,
    LEADING,
    LOOKBACK,
    MOMENTUM,
    QUADRANTS,
    WEAKENING,
    latest,
    rotation,
    sector_indices,
    trails,
)
from market.sector_mapping import NIFTY_50_SECTORS
from ui.insight_charts import CONFIG, rotation_chart

VIEW_SECTORS = "Nifty 50 sectors"
VIEW_NIFTY = "Nifty 50 stocks"
VIEW_OTHER = "Other F&O stocks"
VIEWS = (VIEW_SECTORS, VIEW_NIFTY, VIEW_OTHER)
#: Above this many names the chart drops its text labels and trails unless names are picked.
MAX_LABELLED = 20

QUADRANT_HELP = {
    LEADING: "Beating the benchmark, and the edge is growing.",
    WEAKENING: "Still beating it, but the edge is shrinking.",
    LAGGING: "Behind the benchmark, and falling further behind.",
    IMPROVING: "Behind the benchmark, but catching up.",
}


def main() -> None:
    st.title("Relative rotation")
    st.caption("Who is leading the market and who is turning. Right = beating an equal-weight Nifty 50; "
               "up = that edge is growing. Names tend to rotate clockwise: Improving → Leading → Weakening → "
               "Lagging.")
    universe = require_history()

    with st.sidebar:
        view = st.segmented_control("Plot", list(VIEWS), default=VIEW_SECTORS, required=True, key="rrg_view")
        trail = st.slider("Trail (trading days)", 2, 20, 8, key="rrg_trail")
        lookback = st.segmented_control("RS-Ratio lookback", [10, 20, 40], default=LOOKBACK, required=True,
                                        key="rrg_lookback", help="Days of relative strength the ratio compares "
                                                                 "against. Shorter = more responsive, noisier.")
        momentum = st.segmented_control("RS-Momentum over", [3, 5, 10], default=MOMENTUM, required=True,
                                        key="rrg_momentum", help="Days back the momentum compares the ratio with.")
    hide = suspected_toggle("rrg_hide")

    data, _ = panels(hide)
    options = universe_options(universe)
    closes = data["close"]
    benchmark = equal_weight_index(restrict(closes, options[UNIVERSE_NIFTY50]))
    if view == VIEW_SECTORS:
        series = sector_indices(closes, {s: sec for s, sec in NIFTY_50_SECTORS.items()
                                         if s in options[UNIVERSE_NIFTY50]})
    else:
        series = restrict(closes, options[UNIVERSE_NIFTY50 if view == VIEW_NIFTY else UNIVERSE_EX_NIFTY])
    ratio, mom = rotation(series, benchmark, lookback, momentum)
    points = latest(ratio, mom)
    if points.empty:
        st.info(f"Not enough stored history for a {lookback}-day ratio and {momentum}-day momentum.",
                icon=":material/history:")
        st.stop()
    freshness(closes.index[-1])

    many = len(points) > MAX_LABELLED
    picked = st.multiselect(
        "Highlight" if many else "Show only", sorted(points.index), key="rrg_pick",
        placeholder=("Pick names to draw their trails and labels" if many else "All shown"),
        help="With many names the chart shows dots only; pick some to see where they came from.")
    shown = points.loc[picked] if picked else points
    trail_names = picked if (picked or not many) else []
    if not trail_names and not many:
        trail_names = list(shown.index)

    with st.container(horizontal=True):
        for quadrant in QUADRANTS:
            st.metric(quadrant, int((points["quadrant"] == quadrant).sum()), border=True,
                      help=QUADRANT_HELP[quadrant])
        moved = points[(points["was"] != "") & (points["was"] != points["quadrant"])]
        st.metric("Changed quadrant (5 days)", len(moved), border=True)
    st.caption(f"{view}: {len(points)} plotted, as of {ratio.index[-1]:%a %d %b %Y}. Benchmark: equal-weight Nifty 50 "
               f"built from its members' closes. RS-Ratio = relative strength vs its {lookback}-day average; "
               f"RS-Momentum = RS-Ratio vs {momentum} days earlier. An open approximation of RRG, so values differ "
               "from commercial RRG charts.")

    with st.container(border=True):
        st.plotly_chart(rotation_chart(shown, trails(ratio, mom, trail_names, trail),
                                       label_all=bool(picked) or not many),
                        width="stretch", config=CONFIG, key="rrg_chart")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Where each name sits")
        order = points["quadrant"].map({q: i for i, q in enumerate(QUADRANTS)})
        table = points.assign(_order=order).sort_values(["_order", "rs_ratio"], ascending=[True, False]).drop(
            columns="_order").rename(
            columns={"rs_ratio": "RS-Ratio", "rs_momentum": "RS-Momentum", "quadrant": "Quadrant",
                     "was": "5 days ago"})
        st.dataframe(table, column_config={"RS-Ratio": st.column_config.NumberColumn(format="%.2f"),
                                           "RS-Momentum": st.column_config.NumberColumn(format="%.2f")})
    with right:
        st.subheader("Changed quadrant in 5 days")
        if moved.empty:
            st.caption("None.")
        else:
            st.dataframe(moved.assign(move=moved["was"] + " → " + moved["quadrant"])[["move"]]
                         .rename(columns={"move": "Move"}).sort_values("Move"))
    source_caption()


if __name__ == "__main__":
    st.set_page_config(page_title="Relative rotation", page_icon=":material/360:", layout="wide")
    main()
