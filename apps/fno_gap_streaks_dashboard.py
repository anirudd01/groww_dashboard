"""Gap streaks: which F&O stocks gapped up (or down) consistently over the last N trading days.

Stock x day heatmaps of each day's gap (open against the previous close), laid
out like the F&O Heatmap page: the Nifty 50, then the most consistent gap-ups and
gap-downs among the other F&O stocks, plus a table of current streaks and whether
the gaps held through the session. See market/gap_streaks.py and docs/FNO_INSIGHTS.md.

Data: the stored daily closes only (open and close). No API call. Visualisation only.

The "Gap Streaks" page of pulse_dashboard.py; on its own:

    streamlit run apps/fno_gap_streaks_dashboard.py --server.port 8511
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from apps.fno_common import freshness, panels, require_history, source_caption, suspected_toggle, universe_options
from market.fno_consistency import METRIC_CONSISTENCY, METRIC_NET_CHANGE, METRIC_UP_DAYS, METRICS, leaders, rank
from market.gap_streaks import DEFAULT_FLAT_BELOW, gap_rows, session_after, streak_table
from market.price_panel import UNIVERSE_ALL, UNIVERSE_NIFTY50
from market.session_split import split_returns
from ui.fno_heatmap import build_heatmap, colour_limit, rows_frame
from ui.insight_charts import CONFIG

WINDOWS = [5, 10, 15, 20, 30]
LIMITS = [10, 15, 20, 25, 30]
FLAT = [0.0, 0.1, 0.25, 0.5]
#: Gaps are smaller than daily moves, so the colour scale saturates sooner than on the F&O Heatmap.
MIN_LIMIT_PCT = 0.5

RANK_LABELS = {METRIC_CONSISTENCY: "Consistency", METRIC_UP_DAYS: "Gap-up days", METRIC_NET_CHANGE: "Net gap"}
RANK_HELP = {
    METRIC_CONSISTENCY: "Net gap ÷ total gap distance, −100 to +100. +100 = opened above the previous close "
                        "every day.",
    METRIC_UP_DAYS: "Gap-up days minus gap-down days; ties broken by net gap.",
    METRIC_NET_CHANGE: "All the window's gaps compounded: the biggest overnight movers.",
}
STREAK_COLUMNS = {
    "streak": st.column_config.NumberColumn("Current streak", format="%+d",
                                            help="Consecutive gap-ups (+) or gap-downs (−) up to the last day."),
    "gap_up_days": st.column_config.NumberColumn("Gap-up days"),
    "gap_down_days": st.column_config.NumberColumn("Gap-down days"),
    "net_gap_pct": st.column_config.NumberColumn("Net gap", format="%+.2f%%"),
    "avg_gap_pct": st.column_config.NumberColumn("Avg gap", format="%+.2f%%"),
    "consistency": st.column_config.NumberColumn("Consistency", format="%+.0f"),
    "session_after_pct": st.column_config.NumberColumn(
        "Session, same days", format="%+.2f%%",
        help="Open-to-close moves over the same days, compounded. Opposite sign to the net gap = the gaps "
             "were sold (or bought) back during the day."),
}


def heatmap_card(rows, title: str, caption: str, limit: float, key: str) -> None:
    with st.container(border=True):
        st.subheader(title)
        st.caption(caption)
        if not rows:
            st.info("No stock qualifies over this window.", icon=":material/info:")
            return
        st.plotly_chart(build_heatmap(rows, limit, scale_title="Gap %"), width="stretch", key=key, config=CONFIG)
        with st.expander("As a table", icon=":material/table:"):
            st.dataframe(rows_frame(rows, "Gap-up days", "Gap-down days").rename(columns={"Net change %": "Net gap %"}),
                         hide_index=True,
                         column_config={"Net gap %": st.column_config.NumberColumn(format="%+.2f%%")})


def main() -> None:
    st.title("Gap streaks")
    st.caption("Which F&O stocks opened above (or below) the previous close day after day. Each cell is one day's "
               "gap: the open against the previous trading day's close. A solid green row = gapped up every day.")
    universe = require_history()

    with st.sidebar:
        window = st.segmented_control("Trading days", WINDOWS, default=10, required=True, key="gs_window")
        metric = st.radio("Rank by", METRICS, key="gs_metric", format_func=RANK_LABELS.get,
                          captions=[RANK_HELP[m] for m in METRICS])
        flat = st.segmented_control("Ignore gaps smaller than", FLAT, default=DEFAULT_FLAT_BELOW, required=True,
                                    key="gs_flat", format_func=lambda v: f"{v:g}%",
                                    help="Such a day counts as neither a gap-up nor a gap-down (for the day "
                                         "counts and streaks; the heatmap still shows it).")
        limit = st.segmented_control("Stocks per Other F&O heatmap", LIMITS, default=15, required=True,
                                     key="gs_limit")
    hide = suspected_toggle("gs_hide")

    data, _ = panels(hide)
    overnight, intraday = split_returns(data["open"], data["close"])
    options = universe_options(universe)
    nifty50 = options[UNIVERSE_NIFTY50]
    every, left_out = gap_rows(overnight, window, options[UNIVERSE_ALL], flat)
    if not every:
        st.info(f"Not enough stored history for {window} trading days.", icon=":material/history:")
        st.stop()
    freshness(every[0].dates[-1])

    nifty_rows = rank([r for r in every if r.symbol in nifty50], metric)
    gappers_up, gappers_down = leaders([r for r in every if r.symbol not in nifty50], metric, limit)
    scale = colour_limit(every, MIN_LIMIT_PCT)
    table = streak_table(every, session_after(intraday, window))
    dates = every[0].dates

    with st.container(horizontal=True):
        st.metric("Gapped up every day", int((table["gap_up_days"] == window).sum()), border=True,
                  help=f"Gap of more than {flat:g}% on all {window} days.")
        st.metric("Gapped down every day", int((table["gap_down_days"] == window).sum()), border=True)
        longest_up = table["streak"].max()
        longest_down = table["streak"].min()
        st.metric("Longest gap-up streak now", f"{max(longest_up, 0)} days", border=True,
                  help=", ".join(table.index[table["streak"] == longest_up][:5]) if longest_up > 0 else None)
        st.metric("Longest gap-down streak now", f"{max(-longest_down, 0)} days", border=True,
                  help=", ".join(table.index[table["streak"] == longest_down][:5]) if longest_down < 0 else None)
        st.metric("Gaps held by the session", f"{held_share(table):.0f}%", border=True,
                  help="Of stocks with a net gap, the share whose same-day sessions moved the same way.")
    st.caption(
        f"{pd.Timestamp(dates[0]):%a %d %b} to {pd.Timestamp(dates[-1]):%a %d %b %Y}, ranked by "
        f"**{RANK_LABELS[metric].lower()}**: {RANK_HELP[metric]} Colour scale ±{scale:.2f}%."
    )
    if left_out:
        st.caption(f"Left out for a missing day in the window: {', '.join(left_out)}.")

    tab_nifty, tab_up, tab_down, tab_streaks = st.tabs([
        f"Nifty 50 ({len(nifty_rows)})",
        f"Other F&O: consistent gap-ups ({len(gappers_up)})",
        f"Other F&O: consistent gap-downs ({len(gappers_down)})",
        "Streaks and follow-through",
    ])
    with tab_nifty:
        heatmap_card(nifty_rows, "Nifty 50", "Every Nifty 50 stock, most consistent gap-ups at the top, gap-downs "
                     "at the bottom.", scale, "gs_nifty")
    with tab_up:
        heatmap_card(gappers_up, "Consistent gap-ups: F&O stocks outside the Nifty 50",
                     f"The top {limit} with a net gap up over the window, strongest first.", scale, "gs_up")
    with tab_down:
        heatmap_card(gappers_down, "Consistent gap-downs: F&O stocks outside the Nifty 50",
                     f"The top {limit} with a net gap down over the window, weakest first.", scale, "gs_down")
    with tab_streaks:
        st.caption("Every F&O stock. Sort any column. A long streak with the session moving the other way means "
                   "the gaps keep getting faded.")
        shown = table.assign(nifty50=table.index.isin(nifty50)).sort_values(["streak", "net_gap_pct"],
                                                                           ascending=False)
        st.dataframe(shown, column_config={**STREAK_COLUMNS, "nifty50": st.column_config.CheckboxColumn("Nifty 50")})
    source_caption()


def held_share(table: pd.DataFrame) -> float:
    moved = table[(table["net_gap_pct"] != 0) & table["session_after_pct"].notna()]
    if moved.empty:
        return 0.0
    same = (moved["net_gap_pct"] > 0) == (moved["session_after_pct"] > 0)
    return same.mean() * 100


if __name__ == "__main__":
    st.set_page_config(page_title="Gap streaks", page_icon=":material/keyboard_double_arrow_up:", layout="wide")
    main()
