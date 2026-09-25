"""F&O top gainers and losers, day by day - Streamlit entry point.

Two views: the Nifty 50 (all of which trade in F&O) and every NSE F&O stock.
Past days come from data/fno_daily_closes.csv, written by
scripts/update_fno_history.py. Today, while the market is open, comes from one
bulk Kite quote for all ~210 stocks.

Visualisation only - it places no orders and generates no signals.

    streamlit run fno_movers_dashboard.py --server.port 8503
"""

import io
import logging
import os

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from market.fno_movers import (
    CLOSES_PATH,
    UPDATE_SCRIPT,
    daily_changes,
    live_moves,
    load_closes,
    load_universe,
    top_movers,
)
from market.market_hours import (
    SESSION_OPEN,
    SESSION_PRE_MARKET,
    SESSION_WEEKEND,
    now_ist,
    session_state,
)
from market.providers.base import InstrumentRef
from market.universe import get_universe

logger = logging.getLogger(__name__)

LIVE_TTL_SECONDS = 30

st.set_page_config(page_title="F&O movers", page_icon=":material/trending_up:", layout="wide")


# -- data --------------------------------------------------------------------


@st.cache_data(ttl="10m", show_spinner=False)
def load_history(path: str, mtime: float):
    """Stored closes + per-day moves. ``mtime`` busts the cache when the file changes."""
    rows = load_closes(path)
    return rows, daily_changes(rows)


@st.cache_resource(ttl="1h", show_spinner=False)
def kite_provider():
    """A connected Kite provider, or the reason there is none."""
    from market.providers.kite import KiteProvider

    provider = KiteProvider()
    if not provider.is_configured():
        return None, "No Kite session for today - run 'python scripts/kite_login.py'."
    try:
        provider.connect()
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        return None, str(exc)
    return provider, ""


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def live_quotes(tokens: tuple):
    """One ``/quote/ohlc`` call for every F&O stock. Returns (quotes, error, fetched_at)."""
    provider, error = kite_provider()
    if provider is None:
        return {}, error, None
    refs = [InstrumentRef(symbol=s, provider_id=t) for s, t in tokens]
    try:
        quotes = provider.get_ohlc_quotes(refs)
    except Exception as exc:  # noqa: BLE001
        return {}, f"Kite quote failed: {exc}", None
    return quotes, "", now_ist()


def movers_frame(moves) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Symbol": m.symbol, "Change %": m.change_pct, "Close": m.close,
          "Prev close": m.previous_close} for m in moves]
    )


COLUMNS = {
    "Change %": st.column_config.NumberColumn(format="%+.2f%%"),
    "Close": st.column_config.NumberColumn(format="%.2f"),
    "Prev close": st.column_config.NumberColumn(format="%.2f"),
}


def day_card(day: str, moves, symbols: set, limit: int, live: bool) -> None:
    pool = [m for m in moves if m.symbol in symbols]
    gainers, losers = top_movers(pool, limit)
    up = sum(1 for m in pool if m.change_pct > 0)
    down = sum(1 for m in pool if m.change_pct < 0)
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader(pd.Timestamp(day).strftime("%a %d %b %Y"))
            if live:
                st.badge("Live", icon=":material/sensors:", color="green")
            st.caption(f"{len(pool)} stocks · {up} up · {down} down")
        left, right = st.columns(2)
        with left:
            st.markdown(":green[**Top gainers**]")
            st.dataframe(movers_frame(gainers), hide_index=True, column_config=COLUMNS)
        with right:
            st.markdown(":red[**Top losers**]")
            st.dataframe(movers_frame(losers), hide_index=True, column_config=COLUMNS)


# -- page --------------------------------------------------------------------

st.title("F&O movers")
st.caption("Top gainers and losers by day. Each move is that day's close against the previous trading day's close.")

universe = load_universe()
if not universe.is_usable:
    st.error(universe.error, icon=":material/error:")
    st.stop()
if not os.path.exists(CLOSES_PATH):
    st.error(f"No close history at {CLOSES_PATH}. Run 'python {UPDATE_SCRIPT}'.", icon=":material/error:")
    st.stop()

with st.sidebar:
    days_to_show = st.segmented_control("Days", [1, 3, 5, 7], default=3, required=True)
    limit = st.segmented_control("Rows per table", [5, 10, 15, 20], default=10, required=True)
    show_live = st.toggle("Include today (live)", value=True,
                          help="One bulk Kite quote for all F&O stocks, refreshed at most every 30 s.")
    if st.button("Refresh live prices", icon=":material/refresh:"):
        live_quotes.clear()

rows, stored_moves = load_history(CLOSES_PATH, os.path.getmtime(CLOSES_PATH))
moves_by_day = dict(stored_moves)
today = now_ist().date().isoformat()
state = session_state()

live_note = ""
if show_live and today not in moves_by_day and state != SESSION_WEEKEND:
    quotes, error, fetched_at = live_quotes(tuple(sorted(universe.tokens.items())))
    if error:
        live_note = f"Today not shown: {error}"
    elif quotes:
        in_session = state in (SESSION_OPEN, SESSION_PRE_MARKET)
        todays = live_moves(quotes, today, rows, in_session)
        if todays:
            moves_by_day[today] = todays
            live_note = f"Today: {len(todays)} stocks, Kite quote at {fetched_at:%H:%M:%S} IST ({state.lower()})"

days = sorted(moves_by_day, reverse=True)[:days_to_show]
stored_days = sorted({d for d, _ in rows})

with st.container(horizontal=True):
    st.metric("F&O stocks", len(universe.tokens), border=True)
    st.metric("Stored days", len(stored_days), border=True,
              help=f"{stored_days[0]} to {stored_days[-1]}" if stored_days else None)
    st.metric("Last stored day", stored_days[-1] if stored_days else "-", border=True)
if live_note:
    st.caption(live_note)
if stored_days and (pd.Timestamp(today) - pd.Timestamp(stored_days[-1])).days > 4:
    st.warning(f"The history ends on {stored_days[-1]}. Run 'python {UPDATE_SCRIPT}' to catch up.",
               icon=":material/history:")

nifty50 = set(get_universe("NIFTY50").symbols) & set(universe.tokens)
all_fno = set(universe.tokens)

tab_nifty, tab_all = st.tabs([f"Nifty 50 ({len(nifty50)})", f"All F&O stocks ({len(all_fno)})"])
for tab, symbols in ((tab_nifty, nifty50), (tab_all, all_fno)):
    with tab:
        for day in days:
            day_card(day, moves_by_day[day], symbols, limit, live=(day == today and day not in stored_moves))

with st.sidebar:
    st.divider()
    export = io.StringIO()
    pd.DataFrame(
        [{"date": m.date, "symbol": m.symbol, "change_pct": round(m.change_pct, 4),
          "close": m.close, "prev_close": m.previous_close,
          "nifty50": m.symbol in nifty50}
         for day in days for m in moves_by_day[day]]
    ).to_csv(export, index=False)
    st.download_button("Download shown days (CSV)", export.getvalue(), "fno_movers.csv",
                       mime="text/csv", icon=":material/download:")
    with open(CLOSES_PATH, "rb") as handle:
        st.download_button("Download full close history", handle.read(), "fno_daily_closes.csv",
                           mime="text/csv", icon=":material/table:")
