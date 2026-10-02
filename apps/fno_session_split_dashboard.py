"""Overnight vs intraday: is a stock's move made in the gaps or during the session?

Every close-to-close move is split into overnight (previous close to open) and
intraday (open to close). Over a window this shows gap-driven stocks, session-driven
stocks, and stocks where the two fight (gap up, sold all day). See
market/session_split.py and docs/FNO_INSIGHTS.md.

Data: the stored daily closes only. No API call. Visualisation only.

The "Overnight vs Intraday" page of pulse_dashboard.py; on its own:

    streamlit run apps/fno_session_split_dashboard.py --server.port 8507
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import streamlit as st

from apps.fno_common import freshness, panels, require_history, source_caption, suspected_toggle, universe_picker
from market.price_panel import UNIVERSE_ALL, restrict
from market.session_split import split_returns, split_summary, universe_split
from ui.insight_charts import CONFIG, split_scatter
from ui.insight_charts import universe_split as universe_split_chart

WINDOWS = {"20D": 20, "60D": 60, "All": None}
COLUMNS = {
    "overnight_pct": st.column_config.NumberColumn("Overnight", format="%+.2f%%"),
    "intraday_pct": st.column_config.NumberColumn("Intraday", format="%+.2f%%"),
    "total_pct": st.column_config.NumberColumn("Total", format="%+.2f%%"),
    "overnight_share": st.column_config.ProgressColumn("Share from gaps", format="percent", min_value=0,
                                                       max_value=1),
    "gap_up_days": st.column_config.NumberColumn("Gap-up days"),
    "days": st.column_config.NumberColumn("Days"),
    "pattern": st.column_config.TextColumn("Pattern"),
}
ORDER = ["total_pct", "overnight_pct", "intraday_pct", "overnight_share", "pattern", "gap_up_days", "days"]


def ranked(summary, column: str, ascending: bool, limit: int):
    return summary.sort_values(column, ascending=ascending).head(limit)[ORDER]


def main() -> None:
    st.title("Overnight vs intraday")
    st.caption("Every daily move has two parts: the overnight gap (previous close to open) and the session "
               "(open to close). This shows which part each stock's move came from.")
    universe = require_history()

    label, symbols = universe_picker(universe, "split_universe", default=UNIVERSE_ALL)
    window_label = st.sidebar.segmented_control("Window", list(WINDOWS), default="60D", required=True,
                                                key="split_window", help="Trading days, counted back from the "
                                                                         "last stored day.")
    limit = st.sidebar.segmented_control("Rows per table", [10, 15, 20], default=10, required=True, key="split_rows")
    hide = suspected_toggle("split_hide")

    data, _ = panels(hide)
    opens, closes = restrict(data["open"], symbols), restrict(data["close"], symbols)
    overnight, intraday = split_returns(opens, closes)
    window = WINDOWS[window_label]
    summary = split_summary(overnight, intraday, window)
    if summary.empty:
        st.info("Not enough stored history.", icon=":material/history:")
        st.stop()
    freshness(closes.index[-1])
    average = universe_split(overnight, intraday, window)
    first_day = average.index[0]

    last = average.iloc[-1]
    with st.container(horizontal=True):
        st.metric("Average stock, total", f"{last['Total']:+.2f}%", border=True)
        st.metric("…from overnight gaps", f"{last['Overnight']:+.2f}%", border=True)
        st.metric("…from the session", f"{last['Intraday']:+.2f}%", border=True)
        st.metric("Gap-driven stocks", int(summary["pattern"].str.startswith("Gap-driven").sum()), border=True,
                  help="At least 65% of the movement came from overnight gaps.")
        st.metric("Gaps fought by the session", int(summary["pattern"].str.contains("in session").sum()),
                  border=True, help="Overnight and intraday moved in opposite directions over the window.")
    st.caption(f"{label}: {len(summary)} stocks, {first_day:%a %d %b} to {average.index[-1]:%a %d %b %Y}. "
               "Parts are compounded log returns, so overnight and intraday together give the total exactly.")

    with st.container(border=True):
        st.subheader("Where the average stock made its move")
        st.plotly_chart(universe_split_chart(average), width="stretch", config=CONFIG, key="split_universe_chart")
        st.caption("Cumulative, equal-weight across the stocks shown. A rising Overnight line with a falling "
                   "Intraday line means gaps up that get sold during the day.")

    with st.container(border=True):
        st.subheader("Each stock: overnight against intraday")
        st.plotly_chart(split_scatter(summary), width="stretch", config=CONFIG, key="split_scatter")
        st.caption("Right = gained in the gaps, up = gained in the session. Top-right: up both ways. Bottom-right: "
                   "gaps up, sold in session. Stocks on the dotted diagonal went nowhere overall. Colour = total.")

    tab_gap, tab_session, tab_fight, tab_all = st.tabs(
        ["Gap-driven", "Session-driven", "Gaps fought by the session", "All stocks"])
    with tab_gap:
        left, right = st.columns(2)
        with left:
            st.markdown(":green[**Biggest overnight gains**]")
            st.dataframe(ranked(summary, "overnight_pct", False, limit), column_config=COLUMNS)
        with right:
            st.markdown(":red[**Biggest overnight losses**]")
            st.dataframe(ranked(summary, "overnight_pct", True, limit), column_config=COLUMNS)
    with tab_session:
        left, right = st.columns(2)
        with left:
            st.markdown(":green[**Biggest intraday gains**]")
            st.dataframe(ranked(summary, "intraday_pct", False, limit), column_config=COLUMNS)
        with right:
            st.markdown(":red[**Biggest intraday losses**]")
            st.dataframe(ranked(summary, "intraday_pct", True, limit), column_config=COLUMNS)
    with tab_fight:
        fight = summary[summary["pattern"].str.contains("in session")]
        fight = fight.assign(conflict=(fight["overnight_pct"].abs() + fight["intraday_pct"].abs()))
        st.caption("Overnight and intraday pulled in opposite directions. Sorted by how hard they pulled.")
        st.dataframe(fight.sort_values("conflict", ascending=False).head(limit * 2)[ORDER], column_config=COLUMNS)
    with tab_all:
        st.dataframe(summary.sort_values("total_pct", ascending=False)[ORDER], column_config=COLUMNS)
    source_caption()


if __name__ == "__main__":
    st.set_page_config(page_title="Overnight vs intraday", page_icon=":material/contrast:", layout="wide")
    main()
