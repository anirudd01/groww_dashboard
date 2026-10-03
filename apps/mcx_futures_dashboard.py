"""MCX commodity futures - Streamlit entry point.

One row per commodity (gold, silver, crude, natural gas, base metals, agri): last price, change
against the previous close, the day's range, volume and open interest. Click a row to chart it as
5-minute, 15-minute, hourly or daily candles with open interest underneath.

Data from Dhan, falling back to Kite when Dhan fails (market/mcx_futures.py says why that order):
one quote call for every live contract, then one candle call for the charted one. The contract
list is read from data/market.db, which ``python scripts/fetch_mcx_futures.py`` fills; run it
about monthly.

Visualisation only - it places no orders and generates no signals.

This is the "MCX Futures" page of pulse_dashboard.py; running this file directly shows just it:

    streamlit run apps/mcx_futures_dashboard.py --server.port 8506
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market` and `ui` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import logging
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from market import mcx_futures as mf
from market.market_hours import now_ist
from ui.shading import shade_change

logger = logging.getLogger(__name__)

#: Auto-refresh period while MCX is trading. The quote cache expires a little sooner, so a
#: refresh always reaches the broker.
REFRESH_SECONDS = 30
CACHE_SECONDS = 20
GREEN, RED, GREY = "#2e9e5b", "#d9534f", "#8a8f98"
#: Warn when the stored contract list runs out within this many days.
EXPIRY_WARNING_DAYS = 45

COLUMNS = {
    "Contract": st.column_config.TextColumn(pinned=True),
    "Expiry": st.column_config.DateColumn(format="DD MMM YYYY"),
    "LTP": st.column_config.NumberColumn(format="%.2f"),
    "Change": st.column_config.NumberColumn(format="%+.2f"),
    "Change %": st.column_config.NumberColumn(format="%+.2f%%", help="Against the previous session's close"),
    "Open": st.column_config.NumberColumn(format="%.2f"),
    "High": st.column_config.NumberColumn(format="%.2f"),
    "Low": st.column_config.NumberColumn(format="%.2f"),
    "Prev close": st.column_config.NumberColumn(format="%.2f"),
    "Volume": st.column_config.NumberColumn(format="compact", help="Lots traded in the session"),
    "OI": st.column_config.NumberColumn(format="compact", help="Open interest as the broker reports it"),
    "Last trade": st.column_config.DatetimeColumn(format="ddd DD MMM, HH:mm:ss", help="IST"),
}


# -- data --------------------------------------------------------------------


LABELS = {"dhan": "Dhan", "kite": "Kite"}
NOT_CONFIGURED = {
    "dhan": "Dhan is not configured - set DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in .env.",
    "kite": "No Kite session for today - run 'python scripts/kite_login.py'.",
}


@st.cache_resource(ttl="1h", show_spinner=False)
def provider(name: str):
    """A connected Dhan or Kite provider. Raises with the reason it could not be (and so is not cached)."""
    if name == "kite":
        from market.providers.kite import KiteProvider as Provider
    else:
        from market.providers.dhan import DhanProvider as Provider

    connected = Provider()
    if not connected.is_configured():
        raise RuntimeError(NOT_CONFIGURED[name])
    connected.connect()
    return connected


@st.cache_data(ttl="1h", show_spinner=False)
def stored_contracts():
    return mf.load_contracts()


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def live_quotes(day: str):
    """Quotes for every unexpired contract, from the first broker that answers.

    Returns (quotes, source, failures, fetched_at). Failures are shown, not raised.
    """
    contracts, _, error = stored_contracts()
    if error:
        return [], "", {}, None
    quotes, source, failures = mf.quotes_with_fallback(
        provider, mf.live_contracts(contracts, pd.Timestamp(day).date()))
    for name, reason in failures.items():
        logger.warning("MCX quotes from %s failed: %s", name, reason)
    return quotes, source, failures, now_ist() if source else None


@st.cache_data(ttl=60, show_spinner=False)
def candles(security_id: str, interval: str, source: str):
    """Candles from the broker serving the quotes first, then the other one. (rows, source, failures)."""
    contract = next(c for c in stored_contracts()[0] if c.security_id == security_id)
    order = (source,) + tuple(name for name in mf.PROVIDERS if name != source)
    return mf.candles_with_fallback(provider, contract, interval, now_ist(), order)


def failure_text(failures) -> str:
    return " ".join(f"{LABELS[name]}: {reason}" for name, reason in failures.items())


# -- views -------------------------------------------------------------------


def quote_frame(quotes) -> pd.DataFrame:
    return pd.DataFrame([{
        "Group": q.contract.group, "Contract": q.contract.name, "Expiry": q.contract.expiry,
        "LTP": q.ltp, "Change": q.change, "Change %": q.change_pct, "Open": q.open, "High": q.high,
        "Low": q.low, "Prev close": q.prev_close, "Volume": q.volume, "OI": q.oi,
        "Last trade": q.last_trade.replace(tzinfo=None) if q.last_trade else None,
    } for q in quotes])


def headline_metrics(quotes) -> None:
    by_commodity = {q.contract.commodity: q for q in quotes}
    with st.container(horizontal=True):
        for commodity in mf.HEADLINE:
            quote = by_commodity.get(commodity)
            if quote is None or quote.ltp is None:
                continue
            delta = f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else None
            st.metric(quote.contract.name.title(), f"{quote.ltp:,.2f}", delta, border=True,
                      help=f"Expires {quote.contract.expiry:%d %b %Y}. Change against the previous close.")


def candle_charts(rows, daily: bool):
    """Candles (wick + body, green up / red down), and open interest as a second chart.

    Two charts rather than an Altair ``vconcat``, which does not stretch to the page width.
    """
    frame = pd.DataFrame(rows)
    frame["direction"] = (frame["close"] >= frame["open"]).map({True: "Up", False: "Down"})
    colour = alt.Color("direction:N", scale=alt.Scale(domain=["Up", "Down"], range=[GREEN, RED]), legend=None)
    time_format = "%d %b" if daily else "%d %b %H:%M"
    x = alt.X("time:T", title=None, axis=alt.Axis(format=time_format, labelOverlap=True))
    tooltip = [alt.Tooltip("time:T", title="Time", format="%a %d %b %Y" if daily else time_format),
               alt.Tooltip("open:Q", title="Open", format=",.2f"), alt.Tooltip("high:Q", title="High", format=",.2f"),
               alt.Tooltip("low:Q", title="Low", format=",.2f"), alt.Tooltip("close:Q", title="Close", format=",.2f"),
               alt.Tooltip("volume:Q", title="Volume", format=",.0f"),
               alt.Tooltip("open_interest:Q", title="OI", format=",.0f")]
    base = alt.Chart(frame).encode(x=x, color=colour, tooltip=tooltip)
    body_width = max(1.0, min(8.0, 900 / max(len(frame), 1)))
    price = (base.mark_rule().encode(y=alt.Y("low:Q", title="Price", scale=alt.Scale(zero=False)), y2="high:Q")
             + base.mark_rule(strokeWidth=body_width).encode(y="open:Q", y2="close:Q")).properties(height=340)
    oi = alt.Chart(frame).mark_line(color=GREY, interpolate="step-after").encode(
        x=x, y=alt.Y("open_interest:Q", title="Open interest", scale=alt.Scale(zero=False)),
        tooltip=tooltip).properties(height=120)
    return price, oi


def chart_card(quote, source: str) -> None:
    contract = quote.contract
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader(contract.name.title(), anchor=False)
            interval = st.segmented_control("Interval", list(mf.INTERVALS), default="15 min", required=True,
                                            key="mcx_interval", bind="query-params", label_visibility="collapsed")
        rows, served_by, failures = candles(contract.security_id, interval, source)
        if not rows:
            st.info(f"No {interval} candles for {contract.name}. {failure_text(failures)}",
                    icon=":material/info:")
            return
        price, oi = candle_charts(rows, daily=mf.INTERVALS[interval][0] is None)
        st.altair_chart(price)
        st.altair_chart(oi)
        st.caption(f"{len(rows)} candles from {LABELS[served_by]}, IST. Daily candles are a continuous "
                   "series that reaches back before this contract was the active one (open interest drops "
                   "at each monthly roll), and their close is MCX's daily close, which can differ from "
                   "the last trade.")


def board(pick: str, groups, show_minis: bool) -> None:
    quotes, source, failures, fetched_at = live_quotes(now_ist().date().isoformat())
    if not source:
        st.error(f"No broker returned MCX prices. {failure_text(failures)} Press 'Refresh now' to retry.",
                 icon=":material/error:")
        return
    if failures:
        st.warning(f"Showing {LABELS[source]} because {failure_text(failures)}", icon=":material/swap_horiz:")
    chosen = mf.choose(quotes, pick)
    headline_metrics(mf.choose(quotes, mf.MOST_ACTIVE) if pick != mf.MOST_ACTIVE else chosen)

    shown = [q for q in chosen if q.contract.group in groups and (show_minis or not q.contract.is_mini)]
    if not shown:
        st.info("No contracts match the filters.")
        return
    frame = quote_frame(shown)
    styled = frame.style.apply(shade_change, subset=["Change %"])
    event = st.dataframe(styled, hide_index=True, column_config=COLUMNS, on_select="rerun",
                         selection_mode="single-row", key="mcx_table")
    selected = event.selection.rows
    focus = shown[selected[0]] if selected else next(
        (q for q in shown if q.contract.commodity == "GOLD"), shown[0])
    note = " Kite reports volume as 0 after the session, so it is blank then." if source == "kite" else ""
    st.caption(f"Click a row to chart it. Source: {LABELS[source]}, fetched {fetched_at:%H:%M:%S} IST.{note}")
    chart_card(focus, source)


def main() -> None:
    st.title("MCX commodity futures")
    contracts, generated_at, load_error = stored_contracts()
    if load_error:
        st.info(load_error, icon=":material/database:")
        return

    today = now_ist().date()
    quotes, _, _, _ = live_quotes(today.isoformat())
    latest = mf.latest_trade(quotes)
    live = mf.is_live(quotes, now_ist())
    with st.container(horizontal=True, vertical_alignment="center"):
        if live:
            st.badge("Live", icon=":material/sensors:", color="green")
        elif latest:
            st.badge(f"Last trade: {latest:%a %d %b, %H:%M}", icon=":material/history:", color="gray")
        st.caption("One contract per commodity. Change is against the previous session's close. "
                   "MCX trades 09:00 to 23:30 IST (23:55 while the US is on summer time).")

    last = mf.last_expiry(contracts)
    if last is None or last - today < timedelta(days=EXPIRY_WARNING_DAYS):
        st.warning(f"The stored contract list runs out on {last}. Run `python {mf.SCRIPT}` to refresh it.",
                   icon=":material/update:")

    with st.sidebar:
        pick = st.segmented_control("Contract", list(mf.PICKS), default=mf.MOST_ACTIVE, required=True,
                                    key="mcx_pick", bind="query-params",
                                    help="Most active = highest open interest. MCX liquidity often sits in "
                                         "a later month than the nearest expiry.")
        groups = st.pills("Groups", mf.GROUP_ORDER, default=mf.GROUP_ORDER, selection_mode="multi",
                          key="mcx_groups")
        show_minis = st.toggle("Show mini contracts", value=False, key="mcx_minis",
                               help="GOLDM, SILVERM, CRUDEOILM and the other small-lot copies.")
        auto = st.toggle("Auto-refresh", value=True, key="mcx_auto",
                         help=f"Every {REFRESH_SECONDS} s while MCX is trading.")
        if st.button("Refresh now", icon=":material/refresh:", key="mcx_refresh"):
            live_quotes.clear()
            candles.clear()
            stored_contracts.clear()
            provider.clear()
        if generated_at:
            st.caption(f"{len(contracts)} contracts stored {generated_at.astimezone():%d %b %Y}.")

    run_every = REFRESH_SECONDS if auto and live else None
    st.fragment(board, run_every=run_every)(pick, groups, show_minis)


def page_mcx_futures() -> None:
    main()


if __name__ == "__main__":
    st.set_page_config(page_title="MCX commodity futures", page_icon=":material/oil_barrel:", layout="wide")
    main()
