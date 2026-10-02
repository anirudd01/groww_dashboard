"""Market breadth: how many F&O stocks take part in the market's moves.

% of stocks above their 20- and 50-day averages, the advance/decline line and
new 20-day closing highs against lows, over the stored history, for the Nifty 50,
all F&O stocks, or the F&O stocks outside the Nifty 50. See market/breadth.py
and docs/FNO_INSIGHTS.md.

Data: the stored daily closes only. No API call. Visualisation only.

The "Market Breadth" page of pulse_dashboard.py; on its own:

    streamlit run apps/fno_breadth_dashboard.py --server.port 8506
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import streamlit as st

from apps.fno_common import freshness, panels, require_history, source_caption, suspected_toggle, universe_picker
from market.breadth import HIGH_LOW_DAYS, LONG_MA, SHORT_MA, breadth_table, regime
from market.price_panel import UNIVERSE_ALL, restrict
from ui.insight_charts import CONFIG, advance_decline, breadth_participation, highs_lows

RANGES = {"1M": 21, "3M": 63, "All": None}


def main() -> None:
    st.title("Market breadth")
    st.caption("How many stocks take part in the market's moves. An index can rise on a few heavyweights while "
               "most stocks fall; breadth counts the stocks instead. Descriptive, not a signal.")
    universe = require_history()

    label, symbols = universe_picker(universe, "breadth_universe", default=UNIVERSE_ALL)
    span = st.sidebar.segmented_control("Show", list(RANGES), default="3M", required=True, key="breadth_range",
                                        help="Averages and highs/lows are computed on the full history; this "
                                             "only sets how much of it the charts show.")
    hl_days = st.sidebar.segmented_control("New high/low window", [20, 50], default=HIGH_LOW_DAYS, required=True,
                                           key="breadth_hl", help="A new high = a close above every close of the "
                                                                  "previous N trading days.")
    hide = suspected_toggle("breadth_hide")

    data, _ = panels(hide)
    closes = restrict(data["close"], symbols)
    table = breadth_table(closes, SHORT_MA, LONG_MA, hl_days)
    if table.empty:
        st.info("Not enough stored history.", icon=":material/history:")
        st.stop()
    freshness(table.index[-1])

    last = table.iloc[-1]
    week_ago = table.iloc[-6] if len(table) > 5 else table.iloc[0]
    reading = regime(last["pct_above_long"])
    with st.container(horizontal=True):
        st.metric("Breadth", reading.label, border=True, help=reading.detail)
        st.metric(f"Above {LONG_MA}-day avg", f"{last['pct_above_long']:.0f}%",
                  f"{last['pct_above_long'] - week_ago['pct_above_long']:+.0f} pts in 5 days", border=True,
                  chart_data=table["pct_above_long"].dropna().iloc[-30:].round(1).tolist(), chart_type="line")
        st.metric(f"Above {SHORT_MA}-day avg", f"{last['pct_above_short']:.0f}%",
                  f"{last['pct_above_short'] - week_ago['pct_above_short']:+.0f} pts in 5 days", border=True,
                  chart_data=table["pct_above_short"].dropna().iloc[-30:].round(1).tolist(), chart_type="line")
        st.metric("Last day", f"{int(last['advances'])} up · {int(last['declines'])} down", border=True,
                  help=f"{table.index[-1]:%a %d %b %Y}, {int(last['traded'])} stocks traded both days.")
        st.metric(f"New {hl_days}-day highs / lows", f"{last['new_highs']:.0f} / {last['new_lows']:.0f}", border=True)
    st.caption(f"{label}: {len(closes.columns)} stocks, {len(table) + 1} stored days "
               f"({closes.index[0]:%d %b} to {closes.index[-1]:%d %b %Y}). {reading.detail}")

    rows = RANGES[span]
    shown = table.iloc[-rows:] if rows else table
    with st.container(border=True):
        st.subheader("Participation")
        st.plotly_chart(breadth_participation(shown, SHORT_MA, LONG_MA), width="stretch", config=CONFIG,
                        key="breadth_participation")
        st.caption("When the index rises but the share above the averages falls, fewer stocks are carrying it.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Advance / decline")
        st.plotly_chart(advance_decline(shown), width="stretch", config=CONFIG, key="breadth_ad")
    with right, st.container(border=True):
        st.subheader(f"New {hl_days}-day highs and lows")
        st.plotly_chart(highs_lows(shown, hl_days), width="stretch", config=CONFIG, key="breadth_hl_chart")
        st.caption("Closing highs and lows (the file stores closes, not intraday extremes).")

    with st.expander("Daily table", icon=":material/table:"):
        frame = shown.iloc[::-1].copy()
        frame.index = frame.index.strftime("%Y-%m-%d")
        st.dataframe(
            frame[["advances", "declines", "net", "ad_line", "pct_above_short", "pct_above_long",
                   "new_highs", "new_lows", "ew_index"]],
            column_config={
                "pct_above_short": st.column_config.NumberColumn(f"% > {SHORT_MA}d", format="%.0f%%"),
                "pct_above_long": st.column_config.NumberColumn(f"% > {LONG_MA}d", format="%.0f%%"),
                "ew_index": st.column_config.NumberColumn("EW index", format="%.1f"),
                "ad_line": st.column_config.NumberColumn("A/D line"),
            })
    source_caption()


if __name__ == "__main__":
    st.set_page_config(page_title="Market breadth", page_icon=":material/stacked_line_chart:", layout="wide")
    main()
