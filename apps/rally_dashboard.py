"""Rise from low: how far each stock trades above its low over a window, as a treemap.

The mirror of the Drop from High page. Each tile is a stock, sized by free-float market cap and
coloured by its rise from the lowest intraday low in the window (52 weeks, year to date, 2 or 5
years, or since a date). Tiles can be boxed by sector; the outer box is the whole universe. A range
filter keeps only the stocks within a band of rises (still near the low, up 20% or more, ...), and
a second filter keeps the stocks whose low came after their high (falling, then bouncing) or
before it. See market/rally.py and docs/RISE_FROM_LOW.md.

Data comes only from the stored daily bars in data/market.db, written by
scripts/kite.py history. Every figure is computed in SQLite; the page makes no API call.

Visualisation only - it places no orders and generates no signals.

This is the "Rise from Low" page of pulse_dashboard.py; to run it on its own:

    streamlit run apps/rally_dashboard.py --server.port 8513
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market` and `ui` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


from datetime import date, timedelta

import pandas as pd
import streamlit as st

from apps.drawdown_dashboard import (
    SIZE_CAP,
    SIZE_EQUAL,
    STALE_AFTER_DAYS,
    UNIVERSE_NIFTY50,
    UNIVERSE_OPTIONS,
    reference,
    universe_symbols,
)
from market import drawdown as dd
from market import rally
from market.fno_movers import CONFIRM_SCRIPT, UPDATE_SCRIPT, closes_stamp
from market.market_hours import now_ist
from ui.rally_treemap import build_rally_treemap, sectors_frame, stocks_frame

#: The rise slider's top. Its top value means "this much or more", so a 5-year tenbagger still shows.
BAND_TOP_PCT = 100

ORDER_ANY = "Any"
ORDER_AFTER = "Low after high"
ORDER_BEFORE = "Low before high"
ORDER_OPTIONS = (ORDER_ANY, ORDER_AFTER, ORDER_BEFORE)


@st.cache_data(ttl="10m", show_spinner=False)
def compute(stamp: float, symbols: tuple, start: str, as_of: str, reset: bool):
    """``(rallies, suspected actions)``. ``stamp`` busts the cache when the database changes."""
    actions = dd.suspected_actions(symbols, start, as_of)
    rows = rally.rallies(symbols, start, as_of, resets=dd.resets_for(actions) if reset else None)
    return rows, actions


def in_band(row: rally.Rally, band) -> bool:
    top = float("inf") if band[1] >= BAND_TOP_PCT else band[1]
    return band[0] <= row.rise_pct <= top


def in_order(row: rally.Rally, order: str) -> bool:
    if order == ORDER_AFTER:
        return row.low_after_high
    if order == ORDER_BEFORE:
        return not row.low_after_high
    return True


def main() -> None:
    st.title("Rise from low")
    st.caption(
        "How far each stock trades above its lowest price over a window. A tile is a stock, sized by "
        "free-float market cap; red is still at the low, darker green is further above it. The low is the "
        "lowest intraday low in the window, the same definition NSE uses for the 52-week low."
    )

    first, last = dd.stored_range()
    if not last:
        st.error(f"No daily history stored. Run 'python {UPDATE_SCRIPT} --full --history-days 1830'.",
                 icon=":material/error:")
        st.stop()
    first_day, last_day = date.fromisoformat(first), date.fromisoformat(last)

    with st.sidebar:
        label = st.segmented_control("Stocks", UNIVERSE_OPTIONS, default=UNIVERSE_NIFTY50, required=True,
                                     key="rl_universe")
        window = st.segmented_control("Low over", dd.WINDOWS, default=dd.WINDOW_52W, required=True,
                                      key="rl_window")
        as_of = st.date_input("As of", value=last_day, min_value=first_day, max_value=last_day, key="rl_as_of",
                              help="The close compared with the low. Pick an earlier day to see the board "
                                   "as it stood then.")
        custom = None
        if window == dd.WINDOW_CUSTOM:
            custom = st.date_input("Low since", value=max(first_day, as_of - timedelta(days=90)),
                                   min_value=first_day, max_value=as_of, key="rl_since",
                                   help="For example the day a sell-off started.").isoformat()
        band = st.slider("Show stocks whose rise is between", 0, BAND_TOP_PCT, (0, BAND_TOP_PCT), step=1,
                         format="%d%%", key="rl_band",
                         help=f"0 to 5 keeps the stocks still within 5% of their low; 20 to {BAND_TOP_PCT} "
                              f"keeps the ones up 20% or more. {BAND_TOP_PCT}% at the top means "
                              f"{BAND_TOP_PCT}% or more.")
        order = st.segmented_control("Low came", ORDER_OPTIONS, default=ORDER_ANY, required=True, key="rl_order",
                                     help="Low after high: the stock fell and is bouncing off the bottom. "
                                          "Low before high: it set the low early and has climbed since.")
        grouped = st.toggle("Group by sector", value=True, key="rl_grouped")
        size = st.segmented_control("Tile size", [SIZE_CAP, SIZE_EQUAL], default=SIZE_CAP, required=True,
                                    key="rl_size")
        reset = st.toggle("Measure from after a suspected split/demerger", value=True, key="rl_reset",
                          help="Kite's history is adjusted for splits and bonuses but not demergers, so a "
                               "demerged stock's lower post-demerger prices would set a fake low. With this "
                               "on, a stock with a split-like fall in the window is measured from that day.")

    as_of_text = as_of.isoformat()
    start = dd.window_start(window, as_of_text, custom)
    symbols = universe_symbols(label)
    if not symbols:
        st.error(f"No {label} list stored. Run 'python scripts/kite.py --master'.", icon=":material/error:")
        st.stop()
    stamp = closes_stamp()
    every, actions = compute(stamp, tuple(symbols), start, as_of_text, reset)
    sectors, caps = reference(stamp)
    weights = caps if size == SIZE_CAP else None
    shown = [r for r in every if in_band(r, band) and in_order(r, order)]

    whole = rally.summarise(label, every, caps)
    after = sum(1 for r in every if r.low_after_high)
    with st.container(horizontal=True):
        st.metric("Stocks", f"{len(shown)}/{len(every)}", border=True,
                  help="Shown after the filters / in the universe with history in the window.")
        st.metric("Median from low", f"{whole.median_rise_pct:+.1f}%", border=True,
                  help=f"Median over all {whole.count} {label} stocks, whatever the filters.")
        st.metric("Cap-weighted from low", f"{whole.weighted_rise_pct:+.1f}%", border=True,
                  help="Rises averaged by free-float market cap: roughly the index-level view, but a "
                       "stock's own low, not the index's.")
        st.metric(f"Within {rally.NEAR_LOW_PCT:.0f}% of low", whole.near_low, border=True)
        st.metric(f"Up {rally.STRONG_RISE_PCT:.0f}%+", whole.strong_rise, border=True)
        st.metric("Low after high", f"{after}/{len(every)}", border=True,
                  help="Stocks that set their high first and their low later in the window.")

    st.caption(
        f"**{window}**: lows from {pd.Timestamp(start):%d %b %Y} to {pd.Timestamp(as_of_text):%d %b %Y}, "
        f"against the close of {pd.Timestamp(as_of_text):%a %d %b %Y}. Data source: the stored daily bars in "
        f"data/market.db (Kite, adjusted for splits and bonuses), no live prices and no API call. "
        f"Tiles marked * are measured over less than the window (see the table's Note)."
    )
    if start < first:
        st.warning(f"The stored history starts on {first}, after the window does: stocks are measured "
                   f"from {first}.", icon=":material/history:")
    if (now_ist().date() - last_day).days > STALE_AFTER_DAYS:
        st.warning(f"The history ends on {last}. Run 'python {UPDATE_SCRIPT}' to catch up.",
                   icon=":material/history:")
    missing = sorted(set(symbols) - {r.symbol for r in every})
    if missing:
        st.caption(f"No bars in the window: {', '.join(missing)}.")
    if actions:
        listed = "; ".join(f"{a.symbol} {a.date} ({a.change_pct:+.1f}%)" for a in actions)
        how = "measured from that day" if reset else "measured over the whole window (the toggle is off)"
        st.info(f"Suspected split or demerger in the window, {how}: {listed}. If a fall was real, record it "
                f"with 'python {CONFIRM_SCRIPT} add SYMBOL DATE \"why\"' and it is measured normally.",
                icon=":material/call_split:")

    with st.container(border=True):
        if not shown:
            st.info("No stock is inside the filters.", icon=":material/filter_alt_off:")
        else:
            root = label if len(shown) == len(every) else f"{label}: {len(shown)} of {len(every)}"
            st.plotly_chart(build_rally_treemap(shown, root, sectors if grouped else None, weights),
                            width="stretch", key="rl_treemap", config={"displayModeBar": False})

    stock_tab, sector_tab = st.tabs([f"Stocks ({len(shown)})", "Sectors"])
    table = stocks_frame(shown, sectors)
    with stock_tab:
        st.dataframe(table, hide_index=True, column_config={
            "From low %": st.column_config.NumberColumn(format="%+.2f%%"),
            "From high %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Fall won back %": st.column_config.NumberColumn(
                format="%.1f%%", help="Low after high only: the share of the fall from the high to the low "
                                      "that the close has won back."),
            "Close": st.column_config.NumberColumn(format="%.2f"),
            "Low": st.column_config.NumberColumn(format="%.2f"),
            "High": st.column_config.NumberColumn(format="%.2f"),
        })
    with sector_tab:
        st.caption("Over the stocks the filters show. Weighted = averaged by free-float market cap.")
        st.dataframe(sectors_frame(rally.by_sector(shown, sectors, caps)), hide_index=True, column_config={
            "Weighted from low %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Median from low %": st.column_config.NumberColumn(format="%+.2f%%"),
        })

    with st.sidebar:
        st.divider()
        st.download_button("Download the table (CSV)", table.to_csv(index=False),
                           f"rise_from_low_{label.replace(' ', '_').replace('&', '')}_{as_of_text}.csv",
                           mime="text/csv", icon=":material/download:")


if __name__ == "__main__":
    st.set_page_config(page_title="Rise from low", page_icon=":material/trending_up:", layout="wide")
    main()
