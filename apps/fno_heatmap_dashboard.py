"""F&O consistency heatmap: which stocks rose (or fell) steadily over the last N days.

Three stock x day heatmaps, one per tab: the Nifty 50, and the most consistent
gainers and losers among the other F&O stocks. A cell is that day's % change, so
a steady performer reads as a solid green or red row. Rows are ranked by
consistency (directional efficiency), by up days, or by net change. See
market/fno_consistency.py and docs/FNO_HEATMAP.md.

Data comes only from the stored daily closes, written by
scripts/update_fno_history.py. The page makes no API call.

Visualisation only - it places no orders and generates no signals.

This is the "F&O Heatmap" page of pulse_dashboard.py; to run it on its own:

    streamlit run apps/fno_heatmap_dashboard.py --server.port 8510
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market` and `ui` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


import pandas as pd
import streamlit as st

from market.fno_consistency import (
    METRIC_CONSISTENCY,
    METRIC_NET_CHANGE,
    METRIC_UP_DAYS,
    METRICS,
    consistency_rows,
    leaders,
    rank,
)
from market.fno_movers import (
    UPDATE_SCRIPT,
    closes_available,
    closes_stamp,
    load_closes,
    load_confirmed_moves,
    load_universe,
    suspected_corporate_actions,
)
from market.market_hours import now_ist
from market.universe import get_universe
from ui.fno_heatmap import build_heatmap, colour_limit, rows_frame

WINDOWS = [3, 5, 7, 10, 15, 20]
LIMITS = [10, 15, 20, 25, 30]

METRIC_HELP = {
    METRIC_CONSISTENCY: "Net move ÷ total distance moved, −100 to +100. +100 = closed higher every day, "
                        "whatever the size; one big day among down days scores low.",
    METRIC_UP_DAYS: "Up days minus down days; ties broken by net change.",
    METRIC_NET_CHANGE: "First close to last close, the plain biggest-move ranking.",
}


@st.cache_data(ttl="10m", show_spinner=False)
def load_history(stamp: float):
    """Stored closes + suspected splits. ``stamp`` busts the cache when the database changes."""
    rows = load_closes()
    return rows, suspected_corporate_actions(rows, load_confirmed_moves())


def heatmap_card(rows, title: str, caption: str, limit: float, key: str) -> None:
    with st.container(border=True):
        st.subheader(title)
        st.caption(caption)
        if not rows:
            st.info("No stock qualifies over this window.", icon=":material/info:")
            return
        st.plotly_chart(build_heatmap(rows, limit), width="stretch", key=key,
                        config={"displayModeBar": False})
        with st.expander("As a table", icon=":material/table:"):
            st.dataframe(rows_frame(rows), hide_index=True,
                         column_config={"Net change %": st.column_config.NumberColumn(format="%+.2f%%")})


def main() -> None:
    st.title("F&O consistency heatmap")
    st.caption(
        "Which F&O stocks moved steadily in one direction over the last few trading days. "
        "Each row is a stock and each cell one day's close-to-close % change, so a consistent "
        "performer is a solid green (or red) row, not just the stock with the biggest single move."
    )

    universe = load_universe()
    if not universe.is_usable:
        st.error(universe.error, icon=":material/error:")
        st.stop()
    if not closes_available():
        st.error(f"No close history stored. Run 'python {UPDATE_SCRIPT}'.", icon=":material/error:")
        st.stop()

    with st.sidebar:
        window = st.segmented_control("Trading days", WINDOWS, default=5, required=True, key="fno_hm_window",
                                      help="Trading days stored, so weekends and holidays are skipped.")
        metric = st.radio("Rank by", METRICS, key="fno_hm_metric",
                          captions=[METRIC_HELP[m] for m in METRICS])
        limit = st.segmented_control("Stocks per Other F&O heatmap", LIMITS, default=15, required=True,
                                     key="fno_hm_limit")
        hide_suspected = st.toggle("Hide suspected splits/bonuses", value=True, key="fno_hm_hide",
                                   help="Leave out stocks with a split-like fall inside the window.")

    rows, actions = load_history(closes_stamp())
    exclude = {(a.symbol, a.date) for a in actions} if hide_suspected else None
    all_fno = set(universe.tokens)
    nifty50 = set(get_universe("NIFTY50").symbols) & all_fno

    every, left_out = consistency_rows(rows, window, all_fno, exclude)
    if not every:
        st.info(f"Not enough stored history for {window} trading days. Run 'python {UPDATE_SCRIPT}'.",
                icon=":material/history:")
        st.stop()

    nifty_rows = rank([r for r in every if r.symbol in nifty50], metric)
    gainers, losers = leaders([r for r in every if r.symbol not in nifty50], metric, limit)
    # One colour scale for all three heatmaps, so the same shade means the same move everywhere.
    scale = colour_limit(every)

    dates = every[0].dates
    with st.container(horizontal=True):
        st.metric("Window", f"{window} trading days", border=True,
                  help=f"{pd.Timestamp(dates[0]):%a %d %b} to {pd.Timestamp(dates[-1]):%a %d %b %Y}")
        st.metric("Up every day", sum(1 for r in every if r.up_days == r.days), border=True,
                  help="F&O stocks that closed higher on every day of the window.")
        st.metric("Down every day", sum(1 for r in every if r.down_days == r.days), border=True,
                  help="F&O stocks that closed lower on every day of the window.")
        st.metric("F&O stocks ranked", f"{len(every)}/{len(all_fno)}", border=True,
                  help="Stocks missing a close on any day of the window, or with a suspected split in it, "
                       "are left out.")
    st.caption(
        f"{pd.Timestamp(dates[0]):%a %d %b} to {pd.Timestamp(dates[-1]):%a %d %b %Y}, ranked by "
        f"**{metric.lower()}**: {METRIC_HELP[metric]} Colour scale ±{scale:.1f}%. "
        f"Data source: the stored closes in data/market.db only (no live prices, no API call)."
    )
    last_day = dates[-1]
    if (pd.Timestamp(now_ist().date()) - pd.Timestamp(last_day)).days > 4:
        st.warning(f"The history ends on {last_day}. Run 'python {UPDATE_SCRIPT}' to catch up.",
                   icon=":material/history:")
    if left_out:
        st.caption(f"Left out for a missing day in the window: {', '.join(left_out)}.")

    tab_nifty, tab_up, tab_down = st.tabs([
        f"Nifty 50 ({len(nifty_rows)})",
        f"Other F&O: consistent gainers ({len(gainers)})",
        f"Other F&O: consistent losers ({len(losers)})",
    ])
    with tab_nifty:
        heatmap_card(nifty_rows, "Nifty 50",
                     "Every Nifty 50 stock, most consistent at the top and weakest at the bottom.",
                     scale, "fno_hm_nifty")
    with tab_up:
        heatmap_card(gainers, "Consistent gainers: F&O stocks outside the Nifty 50",
                     f"The top {limit} that rose over the window, strongest first.", scale, "fno_hm_up")
    with tab_down:
        heatmap_card(losers, "Consistent losers: F&O stocks outside the Nifty 50",
                     f"The top {limit} that fell over the window, weakest first.", scale, "fno_hm_down")

    with st.sidebar:
        st.divider()
        frame = rows_frame(rank(every, metric))
        frame.insert(1, "Nifty 50", frame["Symbol"].isin(nifty50))
        st.download_button("Download all ranked stocks (CSV)", frame.to_csv(index=False),
                           f"fno_consistency_{window}d.csv", mime="text/csv", icon=":material/download:")


if __name__ == "__main__":
    st.set_page_config(page_title="F&O consistency heatmap", page_icon=":material/grid_on:", layout="wide")
    main()
