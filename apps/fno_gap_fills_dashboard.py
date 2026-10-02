"""Gap fills: after an F&O stock opens away from yesterday's close, does it trade back the same day?

Fill rate by gap size and direction, how fast gaps fill through the day, and
which stocks fill reliably or tend to "gap and go". See market/gap_fills.py and
docs/FNO_INSIGHTS.md.

Data: data/market.db (1-minute bars + daily_gaps), written by
scripts/backfill_intraday.py. Not checked in; the page says so if it is missing.
No API call. Visualisation only.

The "Gap Fills" page of pulse_dashboard.py; on its own:

    streamlit run apps/fno_gap_fills_dashboard.py --server.port 8509
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os

import pandas as pd
import streamlit as st

from apps.fno_common import freshness, require_history, universe_picker
from market.gap_fills import (
    OUTCOME_FILLED,
    OUTCOME_GO,
    OUTCOME_HELD,
    fill_curve,
    fill_rates,
    filter_gaps,
    load_gaps,
    per_stock,
)
from market.intraday_store import BACKFILL_SCRIPT, DB_PATH
from market.price_panel import UNIVERSE_ALL
from ui.insight_charts import CONFIG, fill_curve_chart, fill_rate_bars

THRESHOLDS = [0.25, 0.5, 1.0, 2.0]
DIRECTIONS = {"Both": None, "Gap up": "Gap up", "Gap down": "Gap down"}

STOCK_COLUMNS = {
    "gaps": st.column_config.NumberColumn("Gaps"),
    "filled_pct": st.column_config.ProgressColumn("Filled", format="%.0f%%", min_value=0, max_value=100),
    "up_filled_pct": st.column_config.NumberColumn("Gap-ups filled", format="%.0f%%"),
    "down_filled_pct": st.column_config.NumberColumn("Gap-downs filled", format="%.0f%%"),
    "median_fill_minutes": st.column_config.NumberColumn("Median minutes to fill", format="%.0f",
                                                         help="From 09:15. 0 = within the first minute."),
    "gap_and_go_pct": st.column_config.NumberColumn("Gap and go", format="%.0f%%",
                                                    help="Never filled, and closed beyond the open in the gap's "
                                                         "direction."),
    "avg_abs_gap": st.column_config.NumberColumn("Avg gap", format="%.2f%%"),
}


@st.cache_data(ttl="30m", show_spinner="Reading gaps and minute bars ...")
def gaps_table(path: str, mtime: float) -> pd.DataFrame:
    return load_gaps(path)


def main() -> None:
    st.title("Gap fills")
    st.caption("When a stock opens away from yesterday's close, does it trade back to that close the same day? "
               "A gap-up is filled when the price falls back to the previous close, and a gap-down when it rises "
               "back to it.")
    universe = require_history()
    if not os.path.exists(DB_PATH):
        st.error(f"No intraday store at {DB_PATH}. It is not checked in: build it with "
                 f"'python {BACKFILL_SCRIPT}' (needs today's Kite login, about 5 minutes).", icon=":material/error:")
        st.stop()

    label, symbols = universe_picker(universe, "gaps_universe", default=UNIVERSE_ALL)
    with st.sidebar:
        threshold = st.segmented_control("Smallest gap", THRESHOLDS, default=0.5, required=True, key="gaps_min",
                                         format_func=lambda v: f"{v:g}%")
        direction = st.segmented_control("Direction", list(DIRECTIONS), default="Both", required=True,
                                         key="gaps_dir")
        min_gaps = st.slider("Stock table: at least N gaps", 1, 15, 5, key="gaps_min_count")

    everything = gaps_table(DB_PATH, os.path.getmtime(DB_PATH))
    gaps = filter_gaps(everything, threshold, symbols, DIRECTIONS[direction])
    if gaps.empty:
        st.info("No gaps match these settings.", icon=":material/info:")
        st.stop()
    freshness(gaps["date"].max(), BACKFILL_SCRIPT)

    filled = gaps["filled"].mean() * 100
    up, down = gaps[gaps["gap_pct"] > 0], gaps[gaps["gap_pct"] < 0]
    with st.container(horizontal=True):
        st.metric("Gaps", f"{len(gaps):,}", border=True,
                  help=f"{gaps['date'].nunique()} trading days, {gaps['symbol'].nunique()} stocks.")
        st.metric("Filled the same day", f"{filled:.0f}%", border=True)
        if len(up):
            st.metric("Gap-ups filled", f"{up['filled'].mean() * 100:.0f}%", border=True,
                      help=f"{len(up):,} gap-ups")
        if len(down):
            st.metric("Gap-downs filled", f"{down['filled'].mean() * 100:.0f}%", border=True,
                      help=f"{len(down):,} gap-downs")
        st.metric("Median minutes to fill", f"{gaps['fill_minutes'].median():.0f}", border=True,
                  help="Of the gaps that filled, counted from 09:15.")
        st.metric("Gap and go", f"{(gaps['outcome'] == OUTCOME_GO).mean() * 100:.0f}%", border=True,
                  help="Never filled, and closed beyond the open in the gap's direction.")
    st.caption(f"{label}, gaps of {threshold:g}% or more, {gaps['date'].min()} to {gaps['date'].max()}. "
               "Gap = official open against the previous official close (daily candles). Fill = a minute bar "
               "reaching the previous close, or the official close getting back through it in the closing auction "
               "(counted at 15:15).")

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Fill rate by gap size")
        st.plotly_chart(fill_rate_bars(fill_rates(gaps)), width="stretch", config=CONFIG, key="gaps_rates")
        st.caption("Bigger gaps fill less often. n = how many gaps in each bar.")
    with right, st.container(border=True):
        st.subheader("How fast gaps fill")
        st.plotly_chart(fill_curve_chart(fill_curve(gaps)), width="stretch", config=CONFIG, key="gaps_curve")
        st.caption("Share of all gaps (filled or not) that had filled by each time of day.")

    outcomes = gaps["outcome"].value_counts()
    with st.container(horizontal=True):
        for outcome, meaning in ((OUTCOME_FILLED, "Traded back to the previous close."),
                                 (OUTCOME_HELD, "Never filled, but closed back inside the gap (between the "
                                                "previous close and the open)."),
                                 (OUTCOME_GO, "Never filled, and closed beyond the open.")):
            st.metric(outcome, f"{outcomes.get(outcome, 0) / len(gaps) * 100:.0f}%", border=True, help=meaning)

    stocks = per_stock(gaps, min_gaps)
    tab_fill, tab_go, tab_all = st.tabs(["Fill most often", "Gap and go most often", "Every gap"])
    with tab_fill:
        st.dataframe(stocks.head(25), column_config=STOCK_COLUMNS)
    with tab_go:
        st.dataframe(stocks.sort_values(["gap_and_go_pct", "gaps"], ascending=False).head(25),
                     column_config=STOCK_COLUMNS)
    with tab_all:
        st.dataframe(
            gaps.sort_values(["date", "abs_gap"], ascending=[False, False])[
                ["date", "symbol", "gap_pct", "prev_close", "open", "close", "outcome", "fill_minutes"]],
            hide_index=True,
            column_config={"gap_pct": st.column_config.NumberColumn("Gap", format="%+.2f%%"),
                           "fill_minutes": st.column_config.NumberColumn("Minutes to fill", format="%.0f")})
    st.caption(f"Data: {DB_PATH} (Kite 1-minute and daily candles, written by {BACKFILL_SCRIPT}; not checked in). "
               "No live prices and no API call on this page.")


if __name__ == "__main__":
    st.set_page_config(page_title="Gap fills", page_icon=":material/vertical_align_center:", layout="wide")
    main()
