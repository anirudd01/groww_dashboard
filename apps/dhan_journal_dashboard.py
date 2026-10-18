"""Dhan trade journal - Streamlit entry point.

Your Dhan fills and ledger, turned into round trips (flat to flat, per contract and product) and
measured after costs: win rate, average win against average loss, expectancy per trade, profit
factor, drawdown, the worst losing streak, and the days that broke the daily loss limit, then
split by contract, side and product, underlying, holding time, weekday and entry hour.

The page reads data/market.db, which ``python scripts/dhan.py --journal`` fills; "Sync now" runs
the same sync. Daily P&L for MCX and NSE F&O is Dhan's own daily settlement from the ledger
(carried positions marked to market), so it matches the account. See docs/DHAN_JOURNAL.md.

Reads account statements only - it places no orders.

    streamlit run apps/dhan_journal_dashboard.py --server.port 8506
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market`, `ui` and `utils` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import logging
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from market import dhan_journal as j
from market.market_hours import now_ist
from ui.shading import shade_change
from utils.formatting import format_inr

logger = logging.getLogger(__name__)

GREEN, RED, GREY = "#2e9e5b", "#d9534f", "#8a8f98"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BREAKDOWNS = {
    "Underlying": lambda t: t.underlying,
    "Side": lambda t: t.side.title(),
    "Holding time": j.holding_bucket,
    "Product": lambda t: t.product or "-",
    "Entry weekday": lambda t: WEEKDAYS[datetime.fromisoformat(t.opened_at).weekday()],
    "Entry hour": lambda t: f"{t.opened_at[11:13]}:00",
    "Segment": lambda t: j.SEGMENT_LABELS.get(t.segment, t.segment),
}
VIEWS = ["Daily P&L", "Trades", "Breakdown", "Costs", "Checks"]
CUSTOM = "Dates"
PERIODS = list(j.PERIOD_KINDS) + [CUSTOM]
COUNT_LABELS = {"Financial year": "Financial years", "Month": "Months", "Week": "Weeks"}


def inr(value) -> str:
    return "—" if value is None else format_inr(value)


def pct(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def ratio(value) -> str:
    return "—" if value is None else f"{value:.2f}"


def duration(seconds) -> str:
    if seconds is None:
        return "—"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} min"
    if minutes < 24 * 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / 1440:.1f} d"


def load():
    """(fills, ledger) from the store, or None when nothing has been synced yet."""
    conn = j.connect_readonly()
    if conn is None:
        return None
    try:
        return j.load_fills(conn), j.load_ledger(conn)
    finally:
        conn.close()


def run_sync() -> None:
    with st.spinner("Fetching your fills and ledger from Dhan..."):
        try:
            result = j.sync(j.DhanAccount(), now_ist().date())
        except Exception as exc:  # noqa: BLE001 - shown on the page
            st.session_state["journal_sync_message"] = ("error", f"Sync failed: {exc}")
            return
    kind = "warning" if result.price_error else "success"
    st.session_state["journal_sync_message"] = (kind, f"Stored {result.summary()}.")


def header() -> None:
    st.title("Trade journal")
    synced = j.last_sync() or {}
    with st.container(horizontal=True, vertical_alignment="center"):
        when = synced.get("synced_at")
        st.caption(f"Dhan fills and ledger, last synced {when[:16].replace('T', ' ')} IST" if when
                   else "Dhan fills and ledger, not synced yet")
        st.button("Sync now", icon=":material/sync:", on_click=run_sync, key="journal_sync")
    message = st.session_state.pop("journal_sync_message", None)
    if message:
        getattr(st, message[0])(message[1])


def in_range(trip: j.Trip, start: date, end: date) -> bool:
    day = date.fromisoformat((trip.closed_at or trip.opened_at)[:10])
    return start <= day <= end


def kpis(stats: dict, days: pd.DataFrame, limit: float) -> None:
    breaches = int((days["total"] < -limit).sum()) if not days.empty else 0
    with st.container(horizontal=True):
        st.metric("Net P&L", inr(stats["net"]), border=True,
                  help="Closed round trips, after every charge on the fills. Open positions are not in it.")
        st.metric("Charges", inr(stats["charges"]), border=True,
                  help="Brokerage, STT, exchange, SEBI, stamp duty and GST on the fills of these trips.")
        st.metric("Round trips", stats["trips"], border=True)
        st.metric("Win rate", pct(stats["win_rate"]), border=True, help="Share of round trips with a positive net.")
        st.metric("Expectancy", inr(stats["expectancy"]), border=True, help="Average net per round trip.")
        st.metric("Profit factor", ratio(stats["profit_factor"]), border=True,
                  help="Money won divided by money lost. Below 1 loses money.")
    with st.container(horizontal=True):
        st.metric("Average win", inr(stats["avg_win"]), border=True)
        st.metric("Average loss", inr(stats["avg_loss"]), border=True)
        st.metric("Win / loss size", ratio(stats["payoff"]), border=True,
                  help="Average win divided by the average loss.")
        st.metric("Max drawdown", inr(stats["max_drawdown"]), border=True,
                  help="Largest fall of cumulative net P&L from a peak, trip by trip.")
        st.metric("Worst losing streak", stats["worst_losing_streak"], border=True)
        st.metric(f"Days below -{format_inr(limit, 0)}", breaches, border=True,
                  help="Days whose P&L (Daily P&L view) was below the daily loss limit.")


def daily_view(days: pd.DataFrame, limit: float) -> None:
    if days.empty:
        st.info("No P&L days in this period.")
        return
    frame = days.assign(date=pd.to_datetime(days["date"]), cumulative=days["total"].cumsum())
    green, red = int((frame["total"] > 0).sum()), int((frame["total"] < 0).sum())
    with st.container(horizontal=True):
        st.metric("Days traded", len(frame), border=True)
        st.metric("Green days", green, border=True)
        st.metric("Red days", red, border=True)
        st.metric("Best day", inr(frame["total"].max()), border=True)
        st.metric("Worst day", inr(frame["total"].min()), border=True)

    bars = alt.Chart(frame).mark_bar().encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("total:Q", title="P&L (₹)"),
        color=alt.condition("datum.total >= 0", alt.value(GREEN), alt.value(RED)),
        tooltip=[alt.Tooltip("date:T", title="Day"), alt.Tooltip("total:Q", title="P&L", format=",.0f")],
    )
    rule = alt.Chart(pd.DataFrame({"limit": [-limit]})).mark_rule(strokeDash=[6, 4], color=GREY).encode(y="limit:Q")
    st.altair_chart((bars + rule).properties(height=280), alt=f"Daily P&L with the -{limit:,.0f} loss limit")
    st.altair_chart(
        alt.Chart(frame).mark_line(point=True).encode(
            x=alt.X("date:T", title=None), y=alt.Y("cumulative:Q", title="Cumulative P&L (₹)"),
            tooltip=[alt.Tooltip("date:T", title="Day"), alt.Tooltip("cumulative:Q", title="Cumulative", format=",.0f")],
        ).properties(height=220),
        alt="Cumulative daily P&L")

    breaches = frame[frame["total"] < -limit]
    if not breaches.empty:
        st.subheader(f"{len(breaches)} days below the -{format_inr(limit, 0)} limit")
        st.dataframe(breaches.drop(columns=["cumulative"]).assign(date=breaches["date"].dt.strftime("%a %d %b %Y")),
                     hide_index=True, column_config=money_columns(breaches.columns), alt="Days over the loss limit")
    st.caption("MCX and NSE F&O: Dhan's daily settlement from the ledger, net of charges, with positions carried "
               "overnight marked to market. NSE cash: closed round trips on the day they closed.")


def money_columns(columns) -> dict:
    return {c: st.column_config.NumberColumn(c, format="₹ %.0f") for c in columns
            if c not in ("date", "trips", "group", "win_rate", "profit_factor")}


def trades_view(trips, prices: dict) -> None:
    open_trips = [t for t in trips if t.is_open]
    if open_trips:
        st.subheader("Open positions")
        st.dataframe(pd.DataFrame([{
            "Opened": t.opened_at.replace("T", " ")[:16], "Contract": t.symbol, "Side": t.side.title(),
            "Product": t.product, "Quantity": abs(t.open_quantity), "Average price": round(t.avg_entry, 2),
            "Last price": prices.get(t.security_id), "Unrealised": t.unrealised(prices.get(t.security_id)),
            "Booked so far": t.booked - t.charges if t.exit_quantity else None,
        } for t in open_trips]), hide_index=True, alt="Open positions",
            column_config={"Unrealised": st.column_config.NumberColumn(format="₹ %.0f"),
                           "Booked so far": st.column_config.NumberColumn(format="₹ %.0f")})
        st.caption("Last price as of the last sync. Booked so far: closed part of the position, after charges.")

    st.subheader("Round trips by contract, side and product")
    groups = {}
    for t in j.scored(trips):
        groups.setdefault((t.symbol, t.side.title(), t.product or "-"), []).append(t)
    if not groups:
        st.info("No closed round trips in this period.")
        return
    rows = []
    for (contract, side, product), members in groups.items():
        stats = j.trip_stats(members)
        held = sorted(t.holding_seconds for t in members)
        rows.append({
            "Contract": contract, "Side": side, "Product": product, "Trips": stats["trips"],
            "Win rate": stats["win_rate"],
            "Size": round(sum(t.max_quantity for t in members) / len(members)),
            "Points": round(sum((t.avg_exit - t.avg_entry) * t.sign for t in members) / len(members), 1),
            "Held": duration(held[len(held) // 2]),
            "Gross": stats["gross"], "Charges": stats["charges"], "Net": stats["net"], "Per trip": stats["expectancy"],
        })
    frame = pd.DataFrame(rows).sort_values("Net", ascending=False)
    st.dataframe(frame.style.apply(shade_change, subset=["Net"]), hide_index=True,
                 alt="Round trips grouped by contract, side and product",
                 column_config={
                     "Win rate": st.column_config.NumberColumn(format="percent"),
                     "Size": st.column_config.NumberColumn(help="Average largest position held during a trip"),
                     "Points": st.column_config.NumberColumn(help="Average move captured per trip, in price points"),
                     "Held": st.column_config.TextColumn(help="Median time from first to last fill"),
                     **{c: st.column_config.NumberColumn(format="₹ %.0f") for c in ("Gross", "Charges", "Net", "Per trip")}})
    left_out = [t for t in trips if not t.is_open and t not in j.scored(trips)]
    if left_out:
        st.caption(f"{len(left_out)} closed round trips left out: today's, without charges yet, or shares bought "
                   "before the stored history (see Checks).")


def breakdown_view(trips) -> None:
    if not j.scored(trips):
        st.info("No closed round trips in this period.")
        return
    for choice, key in BREAKDOWNS.items():
        st.subheader(f"By {choice.lower()}")
        frame = pd.DataFrame(j.breakdown(trips, key)).rename(columns={
            "group": choice, "trips": "Trips", "win_rate": "Win rate", "net": "Net", "expectancy": "Per trip",
            "gross": "Gross", "charges": "Charges", "avg_win": "Average win", "avg_loss": "Average loss",
            "profit_factor": "Profit factor"})
        st.altair_chart(
            alt.Chart(frame).mark_bar().encode(
                x=alt.X("Net:Q", title="Net P&L (₹)"), y=alt.Y(f"{choice}:N", sort="-x", title=None),
                color=alt.condition("datum.Net >= 0", alt.value(GREEN), alt.value(RED)),
                tooltip=[choice, "Trips", alt.Tooltip("Net:Q", format=",.0f"), alt.Tooltip("Win rate:Q", format=".0%")],
            ).properties(height=max(120, 28 * len(frame))),
            alt=f"Net P&L by {choice.lower()}")
        st.dataframe(frame.style.apply(shade_change, subset=["Net"]), hide_index=True,
                     alt=f"Statistics by {choice.lower()}",
                     column_config={
                         "Win rate": st.column_config.NumberColumn(format="percent"),
                         "Profit factor": st.column_config.NumberColumn(format="%.2f"),
                         **{c: st.column_config.NumberColumn(format="₹ %.0f")
                            for c in ("Net", "Per trip", "Gross", "Charges", "Average win", "Average loss")}})


def costs_view(fills: list, trips, ledger: list, stats: dict) -> None:
    by_kind = j.charges_by_kind(fills)
    frame = pd.DataFrame([{"Charge": k, "Amount": v} for k, v in by_kind.items()]).sort_values(
        "Amount", ascending=False)
    with st.container(horizontal=True):
        st.metric("Charges on fills", inr(sum(by_kind.values())), border=True)
        st.metric("Gross P&L of closed trips", inr(stats["gross"]), border=True)
        st.metric("Charges / gross P&L", pct(stats["charges_share"]), border=True,
                  help="How much of the gross profit went on charges. Over 100% means charges turned a profit into a loss.")
    st.altair_chart(alt.Chart(frame).mark_bar(color=RED).encode(
        x=alt.X("Amount:Q", title="₹"), y=alt.Y("Charge:N", sort="-x", title=None),
        tooltip=["Charge", alt.Tooltip("Amount:Q", format=",.0f")]).properties(height=200),
        alt="Charges by kind")
    st.caption("Dhan reports STT and CTT in one field; fills on MCX pay CTT, the rest STT.")

    by_segment = j.breakdown(trips, lambda t: j.SEGMENT_LABELS.get(t.segment, t.segment))
    if by_segment:
        st.dataframe(pd.DataFrame([{"Segment": r["group"], "Trips": r["trips"], "Gross": r["gross"],
                                    "Charges": r["charges"], "Net": r["net"],
                                    "Charges per trip": r["charges"] / r["trips"]} for r in by_segment]),
                     hide_index=True, alt="Charges by segment",
                     column_config={c: st.column_config.NumberColumn(format="₹ %.0f")
                                    for c in ("Gross", "Charges", "Net", "Charges per trip")})

    others = j.other_costs(ledger)
    if others:
        st.subheader("Other costs in the ledger")
        st.dataframe(pd.DataFrame(others).rename(columns={"kind": "Kind", "amount": "Amount"}), hide_index=True,
                     alt="Other ledger costs", column_config={"Amount": st.column_config.NumberColumn(format="₹ %.2f")})
        st.caption("Interest, account and data fees: not part of any trade's P&L above.")


def checks_view(ledger: list, trips, prices: dict) -> None:
    st.markdown("Dhan's ledger books each day's MCX and NSE F&O result separately from the fills. The journal's "
                "total should match it: closed round trips after charges, plus open positions at the last price.")
    rows = j.reconcile(ledger, trips, prices)
    st.dataframe(pd.DataFrame(rows).rename(columns={
        "segment": "Segment", "ledger": "Ledger", "journal": "Journal", "difference": "Difference",
        "unpriced_open": "Open, no price"}), hide_index=True, alt="Journal against the ledger",
        column_config={c: st.column_config.NumberColumn(format="₹ %.2f") for c in ("Ledger", "Journal", "Difference")})
    st.caption("A small difference is normal while a position is open: the ledger values it at the last settlement "
               "price, the journal at the last traded price. Whole history, not the period filter.")
    incomplete = [t for t in trips if t.incomplete]
    pending = [t for t in trips if not t.charges_known]
    if incomplete:
        st.warning(f"{len(incomplete)} sales of shares bought before the stored history are left out of the "
                   "statistics. Sync from an earlier date (`python scripts/dhan.py --journal --since YYYY-MM-DD`).")
    if pending:
        st.info(f"{len(pending)} round trips include today's fills, which Dhan gives without charges. "
                "They join the statistics after tomorrow's sync.")


def main() -> None:
    header()
    data = load()
    if not data or not data[0]:
        st.info("Nothing synced yet. Press **Sync now**, or run `python scripts/dhan.py --journal`.")
        return
    fills, ledger = data
    synced = j.last_sync() or {}
    prices = synced.get("prices") or {}
    all_trips = j.round_trips(fills)

    first = date.fromisoformat(fills[0]["trade_date"])
    today = now_ist().date()
    segments = sorted({j.SEGMENT_LABELS.get(f["segment"], f["segment"]) for f in fills})
    with st.container(horizontal=True, vertical_alignment="bottom"):
        kind = st.segmented_control("Period", PERIODS, default=PERIODS[0], key="journal_span") or PERIODS[0]
        if kind == CUSTOM:
            period = st.date_input("From - to", (max(first, j.financial_year_start(today)), today), min_value=first,
                                   max_value=today, key="journal_period")
            start, end = period if isinstance(period, (tuple, list)) and len(period) == 2 else (first, today)
        else:
            count = st.number_input(COUNT_LABELS[kind], min_value=1, max_value=60, value=1, step=1,
                                    key=f"journal_count_{kind}", help="1 = the current one, 2 = this and the one before")
            start, end = j.period_start(kind, count, today), today
        chosen = st.pills("Segments", segments, selection_mode="multi", default=segments, key="journal_segments")
        limit = st.number_input("Daily loss limit (₹)", min_value=0.0, value=j.DAILY_LOSS_LIMIT, step=5000.0,
                                key="journal_limit")
    st.caption(f"{start:%a %d %b %Y} to {end:%a %d %b %Y}")
    chosen = set(chosen or segments)

    trips = [t for t in all_trips if in_range(t, start, end) and j.SEGMENT_LABELS.get(t.segment, t.segment) in chosen]
    stats = j.trip_stats(trips)
    days = pd.DataFrame(j.daily_pnl(ledger, all_trips))
    if not days.empty:
        days = days[(days["date"] >= start.isoformat()) & (days["date"] <= end.isoformat())]
        keep = [c for c in days.columns if c in ("date", "total") or c in chosen]
        days = days[keep].fillna(0.0)
        days = days.assign(total=days.drop(columns=["date", "total"]).sum(axis=1))
        days = days[days.drop(columns=["date"]).abs().sum(axis=1) > 0]

    kpis(stats, days, limit)
    view = st.segmented_control("View", VIEWS, default=VIEWS[0], key="journal_view", label_visibility="collapsed")
    view = view or VIEWS[0]
    if view == "Daily P&L":
        daily_view(days, limit)
    elif view == "Trades":
        trades_view(trips, prices)
    elif view == "Breakdown":
        breakdown_view(trips)
    elif view == "Costs":
        trip_ids = {t.trip_id for t in j.scored(trips)}
        period_fills = [f for f in fills if start.isoformat() <= f["trade_date"] <= end.isoformat()
                        and j.SEGMENT_LABELS.get(f["segment"], f["segment"]) in chosen]
        ledger_in = [r for r in ledger if start.isoformat() <= r["entry_date"] <= end.isoformat()]
        costs_view(period_fills, trips, ledger_in, stats) if trip_ids or period_fills else st.info("No fills in this period.")
    else:
        checks_view(ledger, all_trips, prices)


def page_dhan_journal() -> None:
    main()


if __name__ == "__main__":
    st.set_page_config(page_title="Trade journal", page_icon=":material/menu_book:", layout="wide")
    main()
