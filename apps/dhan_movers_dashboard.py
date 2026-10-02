"""Dhan market movers - Streamlit entry point.

Dhan ranks stocks, futures and options on its own servers (``POST /v2/data/marketmovers``,
found in its Swagger spec but absent from its docs), so each screen is one or two calls:

    Stocks   - top gainers and losers of a universe (F&O stocks, Nifty 50, a sector index, ...),
               with each move set against the money traded behind it
    Futures  - build-up (price against open-interest change) and the most traded contracts
    Options  - open interest by strike, calls against puts, and a contract table
    History  - the stored closes: any past session's gainers and losers, breadth over time, and
               the stocks that keep topping the lists. Read from data/market.db, which
               scripts/store_dhan_movers.py fills; nothing is fetched from Dhan on this screen

The live screens rank today against the previous close, so they have no multi-day view; the
F&O pages and the History screen cover that. After the close, and on holidays, they show the
last session.

Visualisation only - it places no orders and generates no signals.

This is the "Dhan Movers" page of pulse_dashboard.py; running this file directly shows just it:

    streamlit run apps/dhan_movers_dashboard.py --server.port 8505
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market`, `ui` and `utils` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import logging

import altair as alt
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from market import dhan_movers as dm
from market import dhan_movers_store as store
from market import intraday_store
from market.market_hours import SESSION_OPEN, now_ist, session_state
from ui.shading import shade_change

logger = logging.getLogger(__name__)

#: Auto-refresh period while the market is open. The cache expires a little sooner, so a
#: refresh always reaches Dhan rather than being served the previous answer.
REFRESH_SECONDS = 30
CACHE_SECONDS = 20
CRORE = 1e7

GREEN, RED, BLUE, ORANGE = "#2e9e5b", "#d9534f", "#3b82c4", "#e08a2c"
BUILDUP_COLOURS = {dm.LONG_BUILDUP: GREEN, dm.SHORT_BUILDUP: RED,
                   dm.SHORT_COVERING: BLUE, dm.LONG_UNWINDING: ORANGE}

VIEW_STOCKS, VIEW_FUTURES, VIEW_OPTIONS, VIEW_HISTORY = "Stocks", "Futures", "Options", "History"
UNIVERSE_LABELS = {key: label for label, key in dm.UNIVERSES.items()}
UNIVERSE_ORDER = {key: i for i, key in enumerate(dm.UNIVERSES.values())}
ROW_CHOICES = [5, 10, 15, 20, 30, 50]


# -- data --------------------------------------------------------------------


@st.cache_resource(ttl="1h", show_spinner=False)
def dhan_provider():
    """A connected Dhan provider. Raises with the reason it could not be (and so is not cached)."""
    from market.providers.dhan import DhanProvider

    provider = DhanProvider()
    if not provider.is_configured():
        raise RuntimeError("Dhan is not configured - set DHAN_CLIENT_ID, DHAN_PIN and "
                           "DHAN_TOTP_SECRET in .env.")
    provider.connect()
    return provider


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def ranking(kind: str, category: str, universe: str, limit: int):
    """One Dhan ranking. Returns (movers, error, fetched_at); the error is shown, not raised."""
    try:
        movers = dm.fetch(dhan_provider(), kind, category, universe=universe, limit=limit)
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        logger.warning("Dhan ranking %s/%s failed: %s", kind, category, exc)
        return [], str(exc), None
    return movers, "", now_ist()


def load(kind: str, category: str, universe: str = "", limit: int = dm.MAX_LIMIT):
    with st.spinner("Asking Dhan...", show_time=True):
        return ranking(kind, category, universe, limit)


@st.cache_data(ttl="10m", show_spinner=False)
def last_session():
    """The trading day Dhan's prices belong to, or None if that could not be read.

    Needed because on a holiday the clock says the market is open while every price is the
    previous session's, and Dhan's rankings carry no date of their own.
    """
    try:
        return dm.session_date(dhan_provider())
    except Exception as exc:  # noqa: BLE001 - the page still works without the date
        logger.warning("Could not date Dhan's prices: %s", exc)
        return None


def count_label(movers) -> str:
    """How many rows came back; Dhan caps a ranking at 100, so a full one is "100+"."""
    return f"{dm.MAX_LIMIT}+" if len(movers) >= dm.MAX_LIMIT else str(len(movers))


# -- stored history (data/market.db, read-only) -------------------------------------


def history_stamp() -> float:
    """Changes whenever the database does, so the cached reads below refresh after a capture."""
    return intraday_store.store_stamp(store.DB_PATH)


def _dicts(rows) -> list:
    return [dict(r) for r in rows]


@st.cache_data(show_spinner=False, max_entries=16)
def history_index(stamp: float) -> list:
    """Stored session dates, newest first. ``stamp`` is only the cache key."""
    conn = store.connect_readonly()
    if conn is None:
        return []
    try:
        return store.session_dates(conn)
    finally:
        conn.close()


@st.cache_data(show_spinner=False, max_entries=64)
def history_universes(stamp: float, day: str) -> list:
    conn = store.connect_readonly()
    if conn is None:
        return []
    try:
        return store.universes_on(conn, day)
    finally:
        conn.close()


@st.cache_data(show_spinner=False, max_entries=64)
def history_session(stamp: float, day: str, universe: str) -> dict:
    """One session of one universe, with its breadth history and its repeat movers, as plain dicts."""
    conn = store.connect_readonly()
    if conn is None:
        return {"gainers": [], "losers": [], "breadth": [], "repeat_gainers": [], "repeat_losers": []}
    try:
        movers = store.movers_on(conn, day, universe)
        return {
            "gainers": _dicts(movers[store.GAINER]), "losers": _dicts(movers[store.LOSER]),
            "breadth": _dicts(store.breadth_history(conn, universe)),
            "repeat_gainers": _dicts(store.repeat_movers(conn, universe, store.GAINER)),
            "repeat_losers": _dicts(store.repeat_movers(conn, universe, store.LOSER)),
        }
    finally:
        conn.close()


# -- tables and charts ---------------------------------------------------------

PRICE_COLUMNS = {
    "LTP": st.column_config.NumberColumn(format="%.2f"),
    "Volume": st.column_config.NumberColumn(format="compact"),
    "Traded (₹ Cr)": st.column_config.NumberColumn(format="%.1f", help="Value traded so far today"),
    "OI": st.column_config.NumberColumn(
        format="compact", help="Open interest as Dhan reports it. It looks like units rather than lots."),
    "OI change %": st.column_config.NumberColumn(format="%+.2f%%", help="Against the previous session"),
    "Basis %": st.column_config.NumberColumn(
        format="%+.2f%%", help="Futures price over the underlying's price: the premium paid to hold the future"),
    "Strike": st.column_config.NumberColumn(format="%g"),
    "PCR": st.column_config.NumberColumn(format="%.2f", help="Put-call ratio as Dhan reports it; its docs do not say how it is computed"),
}


def styled(frame: pd.DataFrame, signed=("Change %",)):
    """Shade the price move green/red, and print the percentage columns with their sign."""
    if frame.empty:
        return frame
    formats = {column: "{:+.2f}%" for column in signed if column in frame}
    return frame.style.format(formats, na_rep="-").apply(shade_change, subset=["Change %"])


def stock_frame(movers) -> pd.DataFrame:
    return pd.DataFrame([{"Symbol": m.symbol, "Name": m.name, "Change %": m.change_pct, "LTP": m.ltp,
                          "Volume": m.volume,
                          "Traded (₹ Cr)": m.traded_value / CRORE} for m in movers])


def contract_frame(movers, with_side: bool = False) -> pd.DataFrame:
    rows = []
    for m in movers:
        row = {"Contract": m.symbol, "Change %": m.change_pct, "LTP": m.ltp, "OI": m.open_interest,
               "OI change %": m.oi_change_pct, "Volume": m.volume, "Traded (₹ Cr)": m.traded_value / CRORE}
        if with_side:
            row.update({"Side": m.side, "Strike": m.strike, "PCR": m.pcr})
        else:
            row["Basis %"] = m.basis_pct
        rows.append(row)
    return pd.DataFrame(rows)


def movers_table(title_markdown: str, frame: pd.DataFrame, signed=("Change %",)) -> None:
    st.markdown(title_markdown)
    if frame.empty:
        st.caption("Nothing in this ranking right now.")
        return
    st.dataframe(styled(frame, signed), hide_index=True, column_config=PRICE_COLUMNS)


# Chart fields use plain names: Vega-Lite reads "%", "(" and "₹" in a field name as syntax.


def move_vs_money_chart(movers) -> alt.Chart:
    """Each stock as a dot: how far it moved against how much money changed hands."""
    frame = pd.DataFrame([{"symbol": m.symbol, "name": m.name, "move": m.change_pct,
                           "traded": m.traded_value / CRORE,
                           "direction": "Up" if m.change_pct > 0 else "Down"}
                          for m in movers if m.traded_value > 0])
    dots = alt.Chart(frame).mark_circle(size=70, opacity=0.75).encode(
        x=alt.X("traded:Q", scale=alt.Scale(type="log"), title="Value traded today (₹ crore, log scale)"),
        y=alt.Y("move:Q", title="Change against previous close (%)"),
        color=alt.Color("direction:N", scale=alt.Scale(domain=["Up", "Down"], range=[GREEN, RED]), legend=None),
        tooltip=[alt.Tooltip("symbol:N", title="Symbol"), alt.Tooltip("name:N", title="Name"),
                 alt.Tooltip("move:Q", title="Change %", format="+.2f"),
                 alt.Tooltip("traded:Q", title="Traded (₹ Cr)", format=",.1f")],
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="gray", strokeDash=[4, 4]).encode(y="y:Q")
    return (dots + zero).properties(height=340)


def buildup_chart(frame: pd.DataFrame) -> alt.Chart:
    """Futures as dots in four quadrants: price change up/down against open interest up/down."""
    data = frame.rename(columns={"Contract": "contract", "Change %": "price", "OI change %": "oi", "Build-up": "buildup"})
    dots = alt.Chart(data).mark_circle(size=80, opacity=0.8).encode(
        x=alt.X("oi:Q", title="Open interest change (%)"),
        y=alt.Y("price:Q", title="Price change (%)"),
        color=alt.Color("buildup:N", title="Build-up",
                        scale=alt.Scale(domain=list(BUILDUP_COLOURS), range=list(BUILDUP_COLOURS.values()))),
        tooltip=[alt.Tooltip("contract:N", title="Contract"), alt.Tooltip("buildup:N", title="Build-up"),
                 alt.Tooltip("price:Q", title="Price %", format="+.2f"),
                 alt.Tooltip("oi:Q", title="OI change %", format="+.2f")],
    )
    axes = alt.Chart(pd.DataFrame({"zero": [0]}))
    rule = dict(color="gray", strokeDash=[4, 4])
    return (dots + axes.mark_rule(**rule).encode(x="zero:Q")
            + axes.mark_rule(**rule).encode(y="zero:Q")).properties(height=360)


def strike_chart(frame: pd.DataFrame) -> alt.Chart:
    """Open interest at each strike, calls beside puts."""
    data = frame.rename(columns={"Contract": "contract", "Side": "side", "Strike": "strike",
                                 "OI": "oi", "OI change %": "oi_change"})
    return alt.Chart(data).mark_bar().encode(
        x=alt.X("strike:O", title="Strike", sort="ascending"),
        xOffset="side:N",
        y=alt.Y("oi:Q", title="Open interest"),
        color=alt.Color("side:N", scale=alt.Scale(domain=["CE", "PE"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(title="Calls (CE) / puts (PE)")),
        tooltip=[alt.Tooltip("contract:N", title="Contract"), alt.Tooltip("oi:Q", title="OI", format=",.0f"),
                 alt.Tooltip("oi_change:Q", title="OI change %", format="+.2f")],
    ).properties(height=340)


# -- screens -----------------------------------------------------------------


def source_note(*fetched) -> None:
    times = [t for t in fetched if t]
    stamp = f"fetched {max(times):%H:%M:%S} IST" if times else "nothing fetched"
    st.caption(f"Source: Dhan `/v2/data/marketmovers`, {stamp}. Each move is against the previous close.")


def stocks_screen(universe_label: str, rows: int) -> None:
    universe = dm.UNIVERSES[universe_label]
    gainers, g_error, g_at = load(dm.STOCKS, dm.PRICE_GAINERS, universe)
    losers, l_error, l_at = load(dm.STOCKS, dm.PRICE_LOSERS, universe)
    for error in dict.fromkeys(e for e in (g_error, l_error) if e):
        st.error(f"{error} Press 'Refresh now' to reconnect.", icon=":material/error:")
    if not (gainers or losers):
        if not (g_error or l_error):
            st.info(f"Dhan returned nothing for {universe_label}.")
        return

    pool = gainers + losers
    with st.container(horizontal=True):
        st.metric("Advancing", count_label(gainers), border=True,
                  help="Stocks up on the day. Dhan returns at most 100 per ranking, so a full list is shown as 100+.")
        st.metric("Declining", count_label(losers), border=True)
        if gainers:
            st.metric("Top gainer", gainers[0].symbol, f"{gainers[0].change_pct:+.2f}%", border=True)
        if losers:
            st.metric("Top loser", losers[0].symbol, f"{losers[0].change_pct:+.2f}%", border=True)
        busiest = max(pool, key=lambda m: m.traded_value)
        st.metric("Most traded mover", busiest.symbol, f"₹{busiest.traded_value / CRORE:,.0f} Cr",
                  delta_color="off", border=True)

    left, right = st.columns(2)
    with left:
        movers_table(":green[**Top gainers**]", stock_frame(gainers[:rows]))
    with right:
        movers_table(":red[**Top losers**]", stock_frame(losers[:rows]))

    with st.container(border=True):
        st.subheader("Move against money traded")
        st.caption(f"The {len(pool)} biggest gainers and losers. A big move far to the right had real money "
                   "behind it; one far to the left moved on little trading.")
        st.altair_chart(move_vs_money_chart(pool))
    source_note(g_at, l_at)


def futures_screen(kind: str, show: str, rows: int) -> None:
    label = "stock" if kind == dm.STOCK_FUTURES else "index"
    if show == "Build-up":
        up, up_error, up_at = load(kind, dm.OI_GAINERS)
        down, down_error, down_at = load(kind, dm.OI_LOSERS)
        error, fetched = up_error or down_error, (up_at, down_at)
        contracts = dm.merge_by_symbol(up, down)
    else:
        contracts, error, at = load(kind, dm.TOP_VOLUME)
        fetched = (at,)
    if error:
        st.error(f"{error} Press 'Refresh now' to reconnect.", icon=":material/error:")
    if not contracts:
        if not error:
            st.info(f"Dhan returned no {label} futures.")
        return
    expiry = contracts[0].expiry or "-"

    if show == "Most traded":
        with st.container(horizontal=True):
            st.metric("Expiry", expiry, border=True)
            st.metric("Contracts", count_label(contracts), border=True)
            st.metric("Most traded", contracts[0].underlying, f"{contracts[0].change_pct:+.2f}%", border=True)
            premium = [m for m in contracts if m.basis_pct is not None]
            st.metric("Median basis", f"{sorted(m.basis_pct for m in premium)[len(premium) // 2]:+.2f}%" if premium else "-",
                      border=True, help="Futures price over the underlying's price, across the contracts shown")
        movers_table(f"**Most traded {label} futures**", contract_frame(contracts[:rows]))
        with st.container(border=True):
            st.subheader("Basis of the most traded contracts")
            st.caption("How far each future trades above (or below) the underlying. Wide premiums are the cost of holding the position.")
            top = contract_frame(contracts[:rows])
            st.bar_chart(top, x="Contract", y="Basis %", sort=False)
    else:
        frame = contract_frame(contracts)
        frame["Build-up"] = [dm.buildup(m.change_pct, m.oi_change_pct) for m in contracts]
        frame = frame.dropna(subset=["Build-up"])
        counts = frame["Build-up"].value_counts()
        with st.container(horizontal=True):
            st.metric("Expiry", expiry, border=True)
            for name in dm.BUILDUPS:
                st.metric(name, int(counts.get(name, 0)), border=True)
        st.caption(
            "Read from today's price change and open-interest change. Long build-up: price up, open interest up. "
            "Short build-up: price down, open interest up. Short covering: price up, open interest down. "
            "Long unwinding: price down, open interest down. It describes what happened; it does not predict."
        )
        with st.container(border=True):
            st.subheader("Price against open interest")
            st.altair_chart(buildup_chart(frame))
        pick = st.segmented_control("Show", ["All", *dm.BUILDUPS], default="All", required=True, key="dhan_buildup_pick")
        shown = frame if pick == "All" else frame[frame["Build-up"] == pick]
        shown = shown.reindex(shown["OI change %"].abs().sort_values(ascending=False).index).head(rows)
        movers_table("**Largest open-interest changes**" + ("" if pick == "All" else f" - {pick.lower()}"),
                     shown[["Contract", "Build-up", "Change %", "OI change %", "OI", "LTP", "Volume", "Traded (₹ Cr)", "Basis %"]],
                     signed=("Change %", "OI change %"))
    source_note(*fetched)


def options_screen(kind: str, category: str, rows: int) -> None:
    contracts, error, fetched = load(kind, category)
    if error:
        st.error(f"{error} Press 'Refresh now' to reconnect.", icon=":material/error:")
    if not contracts:
        if not error:
            st.info("Dhan returned no option contracts.")
        return

    names = pd.Series([m.underlying for m in contracts]).value_counts()
    underlying = st.selectbox("Underlying", list(names.index), index=0, key="dhan_option_underlying",
                              format_func=lambda name: f"{name} ({names[name]} contracts)")
    chosen = [m for m in contracts if m.underlying == underlying]
    calls = sum(m.open_interest or 0 for m in chosen if m.side == "CE")
    puts = sum(m.open_interest or 0 for m in chosen if m.side == "PE")
    spot = next((m.underlying_ltp for m in chosen if m.underlying_ltp), None)
    with st.container(horizontal=True):
        st.metric("Expiry", chosen[0].expiry or "-", border=True)
        st.metric(f"{underlying} price", f"{spot:,.2f}" if spot else "-", border=True)
        st.metric("Call OI", f"{calls:,}", border=True, help="Summed over the contracts in this ranking, not the whole chain")
        st.metric("Put OI", f"{puts:,}", border=True)
        st.metric("Put/call OI", f"{puts / calls:.2f}" if calls and puts else "-", border=True,
                  help="Put open interest over call open interest, for the contracts in this ranking only")

    frame = contract_frame(chosen, with_side=True)
    with st.container(border=True):
        st.subheader("Open interest by strike")
        st.caption(f"The {len(chosen)} {underlying} contracts in Dhan's '{category.replace('_', ' ').lower()}' ranking. "
                   "Strikes outside the ranking are missing, so this is not the full option chain.")
        st.altair_chart(strike_chart(frame.dropna(subset=["Strike", "OI"])))
    movers_table(f"**{underlying} contracts, in Dhan's ranked order**",
                 frame.head(rows)[["Contract", "Side", "Strike", "Change %", "LTP", "OI", "OI change %",
                                   "Volume", "Traded (₹ Cr)", "PCR"]],
                 signed=("Change %", "OI change %"))
    source_note(fetched)


def stored_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([{"Symbol": r["symbol"], "Name": r["name"], "Change %": r["change_pct"], "LTP": r["ltp"]}
                         for r in rows])


def repeat_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([{"Symbol": r["symbol"], "Name": r["name"], "Sessions": r["sessions"],
                          "Average move": r["avg_move"]} for r in rows])


REPEAT_COLUMNS = {
    "Sessions": st.column_config.NumberColumn(help="Stored sessions in which it was among the top 10"),
    "Average move": st.column_config.NumberColumn(format="%+.2f%%", help="Mean % change on those sessions"),
}


def history_screen(day: str, universe: str, rows: int) -> None:
    data = history_session(history_stamp(), day, universe)
    breadth = data["breadth"]
    today = next((b for b in breadth if b["trading_date"] == day), None)
    label = UNIVERSE_LABELS.get(universe, universe)
    if today is None:
        st.info(f"Nothing stored for {label} on {day}.")
        return

    def count(n: int, capped: int) -> str:
        return f"{n}+" if capped else str(n)

    with st.container(horizontal=True):
        st.metric("Session", f"{pd.Timestamp(day):%a %d %b %Y}", border=True)
        st.metric("Advancing", count(today["advancing"], today["advancing_capped"]), border=True,
                  help="Stocks up that day. Dhan returns at most 100 per side, so a capped count is shown with +.")
        st.metric("Declining", count(today["declining"], today["declining_capped"]), border=True)
        st.metric("Sessions stored", len(breadth), border=True)

    left, right = st.columns(2)
    with left:
        movers_table(":green[**Top gainers**]", stored_frame(data["gainers"][:rows]))
    with right:
        movers_table(":red[**Top losers**]", stored_frame(data["losers"][:rows]))

    with st.container(border=True):
        st.subheader(f"{label}: breadth over time")
        if len(breadth) < 2:
            st.caption("Needs two or more stored sessions. Run the capture script after each close to build it up.")
        else:
            st.caption("How many stocks closed up and down, session by session.")
            frame = pd.DataFrame({"Session": pd.to_datetime([b["trading_date"] for b in breadth]),
                                  "Advancing": [b["advancing"] for b in breadth],
                                  "Declining": [b["declining"] for b in breadth]})
            st.line_chart(frame, x="Session", y=["Advancing", "Declining"], color=[GREEN, RED])
            if any(b["advancing_capped"] or b["declining_capped"] for b in breadth):
                st.caption("A count that hit Dhan's 100-row limit is a floor, not the true figure.")

    with st.container(border=True):
        st.subheader("Stocks that keep topping the lists")
        st.caption(f"How often each {label} stock was among the top 10 gainers or losers, over every stored session. "
                   "More telling once several sessions are stored.")
        left, right = st.columns(2)
        with left:
            st.markdown(":green[**Most often a top gainer**]")
            st.dataframe(repeat_frame(data["repeat_gainers"]), hide_index=True, column_config=REPEAT_COLUMNS)
        with right:
            st.markdown(":red[**Most often a top loser**]")
            st.dataframe(repeat_frame(data["repeat_losers"]), hide_index=True, column_config=REPEAT_COLUMNS)
    st.caption(f"Source: stored closes in {store.DB_PATH}, written by scripts/store_dhan_movers.py. Nothing is fetched from Dhan here.")


# -- page --------------------------------------------------------------------

OPTION_RANKINGS = {"Highest open interest": dm.HIGHEST_OI, "Most traded": dm.TOP_VOLUME,
                   "OI gainers": dm.OI_GAINERS, "OI losers": dm.OI_LOSERS}


def main() -> None:
    st.title("Dhan market movers")
    view = st.segmented_control("View", [VIEW_STOCKS, VIEW_FUTURES, VIEW_OPTIONS, VIEW_HISTORY],
                                default=VIEW_STOCKS, required=True, key="dhan_view", bind="query-params",
                                label_visibility="collapsed")
    live = False
    with st.container(horizontal=True, vertical_alignment="center"):
        if view == VIEW_HISTORY:
            st.caption("Stored closes: any past session's gainers and losers, and how they add up over time. "
                       "Read from the database; nothing is fetched from Dhan on this screen.")
        else:
            day = last_session()
            live = session_state() == SESSION_OPEN and (day is None or day == now_ist().date())
            if live:
                st.badge("Live", icon=":material/sensors:", color="green")
            else:
                st.badge(f"Last session{f': {day:%a %d %b %Y}' if day else ''}", icon=":material/history:", color="gray")
            st.caption({
                VIEW_STOCKS: "Top gainers and losers of a universe, ranked by Dhan.",
                VIEW_FUTURES: "Futures ranked by open-interest change and by trading volume.",
                VIEW_OPTIONS: "Option contracts ranked by open interest, volume and open-interest change.",
            }[view] + " Each move is against the previous close; outside market hours (and on holidays) it is the last session's.")

    auto = False
    with st.sidebar:
        if view == VIEW_STOCKS:
            universe = st.selectbox("Universe", list(dm.UNIVERSES), key="dhan_universe", bind="query-params",
                                    help="Dhan lists 58 universes, 31 of them NSE; these are the broad lists and the NSE sector indices.")
            screen, args = stocks_screen, (universe,)
        elif view == VIEW_FUTURES:
            contracts = st.segmented_control("Contracts", ["Stock futures", "Index futures"], default="Stock futures",
                                             required=True, key="dhan_futures_kind", bind="query-params")
            show = st.segmented_control("Show", ["Build-up", "Most traded"], default="Build-up",
                                        required=True, key="dhan_futures_show", bind="query-params")
            kind = dm.STOCK_FUTURES if contracts == "Stock futures" else dm.INDEX_FUTURES
            screen, args = futures_screen, (kind, show)
        elif view == VIEW_OPTIONS:
            contracts = st.segmented_control("Contracts", ["Index options", "Stock options"], default="Index options",
                                             required=True, key="dhan_options_kind", bind="query-params")
            chosen = st.selectbox("Ranking", list(OPTION_RANKINGS), key="dhan_options_ranking", bind="query-params")
            kind = dm.INDEX_OPTIONS if contracts == "Index options" else dm.STOCK_OPTIONS
            screen, args = options_screen, (kind, OPTION_RANKINGS[chosen])
        else:
            stamp = history_stamp()
            dates = history_index(stamp)
            if not dates:
                screen, args = None, ()
            else:
                session = st.selectbox("Session", dates, key="dhan_history_day", bind="query-params",
                                       format_func=lambda d: f"{pd.Timestamp(d):%a %d %b %Y}")
                keys = sorted(history_universes(stamp, session), key=lambda k: UNIVERSE_ORDER.get(k, len(UNIVERSE_ORDER)))
                universe = st.selectbox("Universe", keys, key="dhan_history_universe", bind="query-params",
                                        format_func=lambda k: UNIVERSE_LABELS.get(k, k))
                screen, args = history_screen, (session, universe)
        rows = st.segmented_control("Rows per table", ROW_CHOICES, default=10, required=True, key="dhan_rows")
        if view != VIEW_HISTORY:
            auto = st.toggle("Auto-refresh", value=True, key="dhan_auto",
                             help=f"Every {REFRESH_SECONDS} s while the market is open.")
            if st.button("Refresh now", icon=":material/refresh:", key="dhan_refresh"):
                ranking.clear()
                last_session.clear()
                dhan_provider.clear()

    if screen is None:
        st.info("No history stored yet. Run `python scripts/store_dhan_movers.py` after 16:00 IST, or any time later: "
                "it stores the latest finished session's close.", icon=":material/database:")
        return
    run_every = REFRESH_SECONDS if auto and live else None
    st.fragment(screen, run_every=run_every)(*args, rows)


def page_dhan_movers() -> None:
    main()


if __name__ == "__main__":
    st.set_page_config(page_title="Dhan market movers", page_icon=":material/leaderboard:", layout="wide")
    main()
