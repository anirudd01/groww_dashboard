"""F&O top gainers and losers, day by day - Streamlit entry point.

Two views: the Nifty 50 (all of which trade in F&O) and every NSE F&O stock.
Past days come from the stored daily closes, written by
scripts/update_fno_history.py. Today, while the market is open, comes from one
bulk Kite quote for all ~210 stocks.

Visualisation only - it places no orders and generates no signals.

These are the "F&O Nifty 50" and "F&O All Stocks" pages of pulse_dashboard.py;
running this file directly shows just those two:

    streamlit run apps/fno_movers_dashboard.py --server.port 8503
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market`, `ui` and `utils` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import io
import logging

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from market.fno_movers import (
    CLOSE_COLUMNS,
    UPDATE_SCRIPT,
    closes_available,
    closes_stamp,
    daily_changes,
    drop_suspected_moves,
    drop_suspected_periods,
    live_moves,
    load_closes,
    load_confirmed_moves,
    load_universe,
    period_changes,
    suspected_corporate_actions,
    top_movers,
    top_period_movers,
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
from ui.shading import shade_change

logger = logging.getLogger(__name__)

LIVE_TTL_SECONDS = 30


# -- data --------------------------------------------------------------------


@st.cache_data(ttl="10m", show_spinner=False)
def load_history(stamp: float):
    """Stored closes + per-day moves. ``stamp`` busts the cache when the database changes."""
    rows = load_closes()
    return rows, daily_changes(rows), suspected_corporate_actions(rows, load_confirmed_moves())


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
    "Close": st.column_config.NumberColumn(format="%.2f"),
    "Prev close": st.column_config.NumberColumn(format="%.2f"),
}


def styled_movers(moves):
    frame = movers_frame(moves)
    if frame.empty:
        return frame
    return frame.style.apply(shade_change, subset=["Change %"]).format({"Change %": "{:+.2f}%"})


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
            st.dataframe(styled_movers(gainers), hide_index=True, column_config=COLUMNS)
        with right:
            st.markdown(":red[**Top losers**]")
            st.dataframe(styled_movers(losers), hide_index=True, column_config=COLUMNS)


PERIODS = {"3D": 3, "5D": 5, "10D": 10, "20D": 20, "30D": 30, "50D": 50, "100D": 100}

PERIOD_COLUMNS = {
    "Change %": st.column_config.NumberColumn(format="%+.2f%%"),
    "From close": st.column_config.NumberColumn(format="%.2f"),
    "To close": st.column_config.NumberColumn(format="%.2f"),
    "Trend": st.column_config.LineChartColumn(help="Daily closes over the period"),
}


def period_frame(moves) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Symbol": m.symbol, "Change %": m.change_pct, "Up days": f"{m.up_days}/{m.days}",
          "Trend": m.history, "From close": m.start_close, "To close": m.end_close} for m in moves]
    )


def styled_periods(moves):
    frame = period_frame(moves)
    if frame.empty:
        return frame
    return frame.style.apply(shade_change, subset=["Change %"]).format({"Change %": "{:+.2f}%"})


def period_view(rows, today_moves, symbols: set, window: int, limit: int, actions, hide_suspected: bool) -> None:
    moves = period_changes(rows, window, today_moves)
    if not moves:
        st.info(f"Not enough stored history for a {window}-day change. Run 'python {UPDATE_SCRIPT}'.")
        return
    if hide_suspected:
        moves = drop_suspected_periods(moves, actions)
    pool = [m for m in moves if m.symbol in symbols]
    gainers, losers = top_period_movers(pool, limit)
    ranked = sorted(m.change_pct for m in pool)
    median = ranked[len(ranked) // 2] if ranked else 0.0
    up = sum(1 for m in pool if m.change_pct > 0)
    down = sum(1 for m in pool if m.change_pct < 0)
    start, end = moves[0].start_date, moves[0].end_date
    live_end = bool(today_moves) and end == today_moves[0].date

    with st.container(horizontal=True):
        st.metric("Window", f"{window} trading days", border=True)
        st.metric("Advancing", f"{up}/{len(pool)}", border=True)
        st.metric("Declining", f"{down}/{len(pool)}", border=True)
        st.metric("Median move", f"{median:+.2f}%", border=True)
    st.caption(
        f"{pd.Timestamp(start):%a %d %b} close to {pd.Timestamp(end):%a %d %b}"
        f"{' (live price)' if live_end else ' close'}. "
        "Up days = days in the window that closed above the day before."
    )
    left, right = st.columns(2)
    with left:
        st.markdown(":green[**Top gainers**]")
        st.dataframe(styled_periods(gainers), hide_index=True, column_config=PERIOD_COLUMNS)
    with right:
        st.markdown(":red[**Top losers**]")
        st.dataframe(styled_periods(losers), hide_index=True, column_config=PERIOD_COLUMNS)


def corporate_actions_panel(actions, symbols: set, hidden: bool) -> None:
    """Suspected splits/bonuses among this page's stocks, and how to settle them."""
    shown = [a for a in actions if a.symbol in symbols]
    if not shown:
        return
    with st.expander(f"Suspected splits / bonuses ({len(shown)})", icon=":material/call_split:"):
        st.caption(
            "A fall this size that matches a split or bonus ratio is probably a corporate action, not a "
            "market move. "
            + ("These stocks are left out of the rankings." if hidden
               else "They are included in the rankings; turn on the sidebar switch to hide them.")
            + f" Run `python {UPDATE_SCRIPT} --fix-splits` to re-fetch them: if Kite's adjusted candles "
              "remove the jump it was a corporate action, otherwise it stays as a real move."
        )
        st.dataframe(
            pd.DataFrame([{"Symbol": a.symbol, "Date": a.date, "Prior close": a.previous_close,
                           "Close": a.close, "Move %": a.change_pct, "Looks like": a.label} for a in shown]),
            hide_index=True,
            column_config={"Prior close": st.column_config.NumberColumn(format="%.2f"),
                           "Close": st.column_config.NumberColumn(format="%.2f"),
                           "Move %": st.column_config.NumberColumn(format="%+.2f%%")},
        )


# -- page --------------------------------------------------------------------


VIEW_NIFTY50 = "nifty50"
VIEW_ALL = "all"


def main(view: str = VIEW_ALL) -> None:
    """One F&O movers page: the Nifty 50 or every F&O stock."""
    st.title("F&O movers: " + ("Nifty 50" if view == VIEW_NIFTY50 else "All F&O stocks"))
    mode = st.segmented_control("View", ["By day", "Over a period"], default="By day", required=True,
                                key="fno_view_mode", label_visibility="collapsed")
    if mode == "By day":
        st.caption("Top gainers and losers by day. Each move is that day's close against the previous trading day's close.")
    else:
        st.caption("Top gainers and losers over the last few trading days: the latest close against the close "
                   "that many trading days earlier.")

    universe = load_universe()
    if not universe.is_usable:
        st.error(universe.error, icon=":material/error:")
        st.stop()
    if not closes_available():
        st.error(f"No close history stored. Run 'python {UPDATE_SCRIPT}'.", icon=":material/error:")
        st.stop()

    with st.sidebar:
        if mode == "By day":
            days_to_show = st.segmented_control("Days", [1, 3, 5, 7], default=3, required=True)
        else:
            period = st.segmented_control("Period", list(PERIODS), default="5D", required=True,
                                          help="Trading days stored, so weekends and holidays are skipped.")
        limit = st.segmented_control("Rows per table", [5, 10, 15, 20], default=10, required=True)
        hide_suspected = st.toggle("Hide suspected splits/bonuses", value=True,
                                   help="Leave stocks whose close fell by a split-like ratio out of the rankings.")
        show_live = st.toggle("Include today (live)", value=True,
                              help="One bulk Kite quote for all F&O stocks, refreshed at most every 30 s.")
        if st.button("Refresh live prices", icon=":material/refresh:"):
            live_quotes.clear()

    rows, stored_moves, actions = load_history(closes_stamp())
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

    days = sorted(moves_by_day, reverse=True)[:days_to_show] if mode == "By day" else []
    stored_days = sorted({d for d, _ in rows})

    with st.container(horizontal=True):
        st.metric("F&O stocks", len(universe.tokens), border=True)
        st.metric("Stored days", len(stored_days), border=True,
                  help=f"{stored_days[0]} to {stored_days[-1]}" if stored_days else None)
        st.metric("Last stored day", stored_days[-1] if stored_days else "-", border=True)
    st.caption(
        "Data source: Kite. Past days come from the stored closes "
        f"(data/market.db, written by {UPDATE_SCRIPT} from Kite's daily candles); "
        "today comes from one Kite quote. This page does not use the sidebar "
        "data-provider setting of the heatmap pages."
    )
    if live_note:
        st.caption(live_note)
    if stored_days and (pd.Timestamp(today) - pd.Timestamp(stored_days[-1])).days > 4:
        st.warning(f"The history ends on {stored_days[-1]}. Run 'python {UPDATE_SCRIPT}' to catch up.",
                   icon=":material/history:")

    nifty50 = set(get_universe("NIFTY50").symbols) & set(universe.tokens)
    all_fno = set(universe.tokens)

    symbols = nifty50 if view == VIEW_NIFTY50 else all_fno
    st.caption(f"{len(symbols)} stocks")
    corporate_actions_panel(actions, symbols, hide_suspected)
    if mode == "By day":
        for day in days:
            moves = moves_by_day[day]
            if hide_suspected:
                moves = drop_suspected_moves(moves, actions)
            day_card(day, moves, symbols, limit, live=(day == today and day not in stored_moves))
    else:
        period_view(rows, moves_by_day.get(today) if today not in stored_moves else None,
                    symbols, PERIODS[period], limit, actions, hide_suspected)

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
        history = io.StringIO()
        pd.DataFrame(list(rows.values()), columns=list(CLOSE_COLUMNS)).sort_values(["date", "symbol"]).to_csv(
            history, index=False)
        st.download_button("Download full close history", history.getvalue(), "fno_daily_closes.csv",
                           mime="text/csv", icon=":material/table:")


def page_nifty50() -> None:
    main(VIEW_NIFTY50)


def page_all() -> None:
    main(VIEW_ALL)


if __name__ == "__main__":
    st.set_page_config(page_title="F&O movers", page_icon=":material/trending_up:", layout="wide")
    st.navigation([
        st.Page(page_nifty50, title="Nifty 50", url_path="nifty50", default=True),
        st.Page(page_all, title="All F&O stocks", url_path="all"),
    ], position="top").run()
