"""F&O and MCX positions from a Groww account: P&L, direction, Greeks and one-click exits.

Positions come from Groww's positions API, contract facts (expiry, lot, tick) from its instrument
list, prices from its quote calls and Greeks from ``get_greeks``. Prices and Greeks need Groww's
paid data plan; without it the page lists the positions with no price or P&L and says why
(groww_api/position_processor.py). Exits are marketable limit orders built by groww_api/orders.py.
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market`, `ui` and `utils` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

from groww_api import GrowwAPIClient, GrowwAPIService, PositionProcessor
from groww_api.orders import build_exit_order
from market.market_hours import IST, is_market_open
from market.mcx_futures import in_session as mcx_in_session
from utils import (
    format_inr,
    format_inr_full,
    format_expiry_short,
    position_sentiment,
    get_position_summary,
    group_positions_by_underlying_expiry,
)


def place_quick_exit_order(pos):
    """Flatten one position with a marketable limit order. (success, order id or reason, price, status)."""
    try:
        order = build_exit_order(pos)
    except ValueError as e:
        return False, str(e), None, None
    try:
        api_service = GrowwAPIService(GrowwAPIClient.get_instance())
        try:
            order_response = api_service.place_order(**order, timeout=15)
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
                return False, (f"no answer from Groww within 15 s ({e}). The order may still have been placed: "
                               "check the Groww order book before trying again."), None, None
            raise
        groww_order_id = order_response.get('groww_order_id', 'Unknown')

        # Best-effort status check - order was already placed even if this fails
        order_status = "UNKNOWN"
        try:
            status_response = api_service.get_order_status(segment=order["segment"], groww_order_id=groww_order_id)
            order_status = status_response.get('order_status') or status_response.get('status') or "UNKNOWN"
        except Exception:
            pass

        return True, groww_order_id, order["price"], order_status
    except Exception as e:
        return False, str(e), None, None

# --------------- STREAMLIT CONFIGURATION ---------------
st.set_page_config(
    page_title="Pulse Tester: FnO Positions Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --------------- CUSTOM CSS FOR RESPONSIVE FULL-WIDTH UI ---------------
st.markdown("""
<style>
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 98% !important;
    }

    .kpi-card {
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 12px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.06);
        transition: transform 0.15s ease-in-out;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
    }
    .kpi-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 1.85rem;
        font-weight: 700;
        line-height: 1.2;
        white-space: nowrap;
    }
    .kpi-sub {
        font-size: 0.82rem;
        margin-top: 5px;
        white-space: nowrap;
    }

    .box-green {
        background-color: #f0fdf4;
        border: 1.5px solid #86efac;
        color: #14532d;
    }
    .box-green .kpi-title { color: #166534; }
    .box-green .kpi-value { color: #14532d; }
    .box-green .kpi-sub { color: #15803d; }

    .box-red {
        background-color: #fef2f2;
        border: 1.5px solid #fca5a5;
        color: #7f1d1d;
    }
    .box-red .kpi-title { color: #991b1b; }
    .box-red .kpi-value { color: #7f1d1d; }
    .box-red .kpi-sub { color: #b91c1c; }

    .box-blue {
        background-color: #f8fafc;
        border: 1.5px solid #cbd5e1;
        color: #0f172a;
    }
    .box-blue .kpi-title { color: #334155; }
    .box-blue .kpi-value { color: #0f172a; }
    .box-blue .kpi-sub { color: #475569; }

    @media (prefers-color-scheme: dark) {
        .box-green {
            background-color: #072714;
            border-color: #15803d;
            color: #bbf7d0;
        }
        .box-green .kpi-title { color: #86efac; }
        .box-green .kpi-value { color: #dcfce7; }
        .box-green .kpi-sub { color: #4ade80; }

        .box-red {
            background-color: #2b0b0b;
            border-color: #991b1b;
            color: #fecaca;
        }
        .box-red .kpi-title { color: #fca5a5; }
        .box-red .kpi-value { color: #fee2e2; }
        .box-red .kpi-sub { color: #f87171; }

        .box-blue {
            background-color: #0f172a;
            border-color: #334155;
            color: #f1f5f9;
        }
        .box-blue .kpi-title { color: #94a3b8; }
        .box-blue .kpi-value { color: #f8fafc; }
        .box-blue .kpi-sub { color: #cbd5e1; }
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 2px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem;
        font-weight: 600;
        padding: 8px 16px;
    }
</style>
""", unsafe_allow_html=True)

def render_kpi_card(title: str, value: str, sub: str, theme: str = "blue"):
    """Renders a custom styled KPI box."""
    theme_class = f"box-{theme}"
    html = f"""
    <div class="kpi-card {theme_class}">
        <div class="kpi-title">{title}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# --------------- SIDEBAR ---------------
st.sidebar.title("📈 Pulse Tester: FnO Tracker")
st.sidebar.caption("Monitor and manage all open **Futures & Options** positions.")

with st.sidebar.expander("🔑 Broker Credentials & Connection", expanded=True):
    auth_mode = os.getenv("GROWW_AUTH_MODE", "TOTP")
    api_key = os.getenv("GROWW_API_KEY", "")
    totp_secret = os.getenv("GROWW_TOTP_SECRET", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")

    st.write(f"**Auth Mode:** `{auth_mode}`")
    st.write(f"**TOTP Token / API Key:** {'✅ Configured' if api_key else '❌ Missing in .env'}")
    if auth_mode == "TOTP":
        st.write(f"**TOTP Secret:** {'✅ Configured' if totp_secret else '❌ Missing in .env'}")
    else:
        st.write(f"**API Secret:** {'✅ Configured' if api_secret else '❌ Missing in .env'}")

    if st.button("🔄 Refresh Data", width='stretch'):
        st.cache_data.clear()
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    **📌 Understanding FnO Positions:**
    - **Futures:** Leveraged directional bets on index or stock price movements.
    - **Options:** Limited-risk exposure with defined premium paid/received.
    - **Shorts** show a negative quantity; their P&L rises as the price falls.
    - **Greeks:** Delta (directional), Gamma (acceleration), Theta (time decay), Vega (volatility).
    """
)

# --------------- DATA FETCHING ---------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_fno_data():
    """
    Fetch FnO positions using singleton client.
    Auth happens ONCE per session (singleton pattern), not per cache refresh.
    """
    try:
        api_client = GrowwAPIClient.get_instance()
        if not api_client.is_connected:
            return None, api_client.auth_error or "Failed to authenticate"

        api_service = GrowwAPIService(api_client)
        processor = PositionProcessor(api_service)
        fno_positions = processor.get_fno_positions()
        greeks, greeks_error = processor.get_option_greeks(fno_positions)

        return {
            "profile": api_service.get_user_profile(),
            "margins": api_service.get_margins(),
            "fno_positions": fno_positions,
            "greeks": greeks,
            "greeks_error": greeks_error,
        }, None
    except Exception as e:
        return None, str(e)

with st.spinner("Fetching FnO positions..."):
    result, error_msg = fetch_fno_data()

if error_msg:
    st.error(f"⚠️ **Error**: {error_msg}")
    st.info("Check the `GROWW_*` credentials in your `.env` file.")
    st.stop()

profile = result["profile"]
margins = result["margins"]
fno_positions = result["fno_positions"]

# --------------- CALCULATE SUMMARY METRICS ---------------
def calculate_segment_metrics(positions):
    """Totals for a group of positions. Value and P&L cover only the positions that have a price."""
    open_positions = [p for p in positions if p["quantity"]]
    priced = [p for p in open_positions if p["priced"]]
    priced_invested = sum(p["entry_value"] for p in priced)
    total_pnl = sum(p["unrealized_pnl"] for p in priced)
    return {
        "total_invested": sum(p["entry_value"] for p in open_positions),
        "total_value": sum(p["total_value"] for p in priced),
        "total_pnl": total_pnl,
        "pnl_pct": (total_pnl / priced_invested * 100.0) if priced_invested > 0 else 0.0,
        "realised": sum(p["realised_pnl"] for p in positions),
        "count": len(open_positions),
        "priced": len(priced),
    }


def market_status(asset_type):
    """("OPEN"/"CLOSED", hours) from the clock. Exchange holidays are not known."""
    now = datetime.now(IST)
    if asset_type == "COMMODITY":
        return ("OPEN" if mcx_in_session(now) else "CLOSED"), "MCX 09:00-23:55 IST, Mon-Fri"
    return ("OPEN" if is_market_open(now) else "CLOSED"), "NSE F&O 09:15-15:30 IST, Mon-Fri"


all_metrics = calculate_segment_metrics(fno_positions)
open_positions = [p for p in fno_positions if p["quantity"]]
unpriced = [p for p in open_positions if not p["priced"]]

fno_details = margins.get("fno_margin_details", {}) or {}
# Groww reports margin "used" as a negative number; its F&O figures already include MCX.
fno_margin_used = abs(float(fno_details.get("net_fno_margin_used", 0.0) or 0.0))
fno_balance_available = float(fno_details.get("future_balance_available", 0.0) or 0.0)
clear_cash = float(margins.get("clear_cash", 0.0))

# --------------- TOP BAR: HEADER ---------------
col_head, col_cash = st.columns([3, 1])

with col_head:
    st.title("📈 FnO Positions & Greeks Tracker")
    st.caption(f"🟢 Connected to Live Broker Account | Client UCC: `{profile.get('ucc', 'N/A')}`")

with col_cash:
    render_kpi_card(
        title="Account Clear Cash (Wallet)",
        value=format_inr(clear_cash),
        sub=f"Full: {format_inr_full(clear_cash)}",
        theme="green"
    )

if unpriced:
    st.warning(
        f"⚠️ **No live price for {len(unpriced)} of {len(open_positions)} open position(s)** "
        f"({', '.join(p['symbol'] for p in unpriced[:6])}{', ...' if len(unpriced) > 6 else ''}). "
        "Their price and P&L are left blank and they are left out of the P&L totals and the quick-exit "
        "buttons. Groww refuses price calls without its paid data plan."
    )

st.markdown("---")

# --------------- FILTER POSITIONS BY ASSET TYPE ---------------
equity_positions = [p for p in fno_positions if p.get("type") == "EQUITY"]
commodity_positions = [p for p in fno_positions if p.get("type") == "COMMODITY"]

equity_metrics = calculate_segment_metrics(equity_positions)
commodity_metrics = calculate_segment_metrics(commodity_positions)


def render_segment_kpis(metrics, asset_type):
    status, hours = market_status(asset_type)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_kpi_card(
            title="Notional at Entry",
            value=format_inr(metrics["total_invested"]),
            sub=f"Open: {metrics['count']}",
            theme="blue"
        )
    with k2:
        render_kpi_card(
            title="Unrealized P&L",
            value=format_inr(metrics["total_pnl"]),
            sub=f"{metrics['pnl_pct']:+.2f}% | priced {metrics['priced']} of {metrics['count']}",
            theme="green" if metrics["total_pnl"] >= 0 else "red"
        )
    with k3:
        render_kpi_card(
            title="Realised P&L",
            value=format_inr(metrics["realised"]),
            sub="From Groww's positions",
            theme="green" if metrics["realised"] >= 0 else "red"
        )
    with k4:
        render_kpi_card(
            title="Market Status",
            value=status,
            sub=hours,
            theme="green" if status == "OPEN" else "blue"
        )


def render_positions_section(positions, key_prefix, label):
    """Positions table, quick-exit buttons and a summary for one asset type."""
    open_rows = [p for p in positions if p["quantity"]]
    closed_rows = [p for p in positions if not p["quantity"]]

    if not open_rows:
        st.info(f"No open {label} positions found in your account.")
    else:
        display_data = [
            {
                "Symbol": pos["symbol"],
                "Side": pos["side"],
                "Expiry": format_expiry_short(pos.get("expiry_date")),
                "Qty": pos["quantity"],
                "Lots": (abs(pos["quantity"]) / pos["lot_size"]) if pos.get("lot_size") else None,
                "Entry Price": pos["entry_price"],
                "LTP": pos["ltp"],
                "Notional": pos["entry_value"],
                "P&L": pos["unrealized_pnl"],
                "P&L %": pos["unrealized_pnl_pct"],
                "_pos": pos,
            }
            for pos in open_rows
        ]
        df_display = pd.DataFrame(display_data).drop(columns="_pos")
        df_display = df_display.sort_values("P&L %", ascending=False, na_position="last").reset_index(drop=True)

        st.markdown("#### Open Positions (Sortable)")
        st.dataframe(
            df_display.style.format({
                "Qty": "{:,.0f}",
                "Lots": "{:,.4g}",
                "Entry Price": "₹{:,.2f}",
                "LTP": "₹{:,.2f}",
                "Notional": "₹{:,.2f}",
                "P&L": "₹{:,.2f}",
                "P&L %": "{:+.2f}%"
            }, na_rep="—"),
            width='stretch',
            height=min(400, 40 + 35 * len(df_display))
        )

        # Quick Exit Buttons Below Table (priced winners only, highest P&L% first)
        st.markdown("**Quick Exit Buttons (profitable positions, highest P&L% first):**")
        st.caption("A limit order 0.5% through the last price, on the tick grid, in the position's own product. "
                   "Longs are sold, shorts bought back.")

        # Prominent, persistent result banner - stays visible (and full-width) after the rerun
        # that a button click triggers, instead of a message tucked into a narrow column.
        last_exit = st.session_state.get(f"{key_prefix}_last_exit")
        if last_exit:
            if last_exit["success"]:
                st.success(
                    f"✅ **{last_exit['symbol']}** exit order placed @ ₹{last_exit['exit_price']:,.2f} | "
                    f"Order ID: `{last_exit['order_id']}` | Status: **{last_exit['order_status']}**"
                )
                st.caption("Status is read back from the API immediately after placement. Confirm the final fill in the Groww app / order book.")
            else:
                st.error(f"❌ **{last_exit['symbol']}** exit failed: {last_exit['order_id']}")
            if st.button("Dismiss", key=f"{key_prefix}_dismiss_exit"):
                del st.session_state[f"{key_prefix}_last_exit"]
                st.rerun()

        # Only positions an exit order can be built for: priced, profitable, tick size known.
        winning_positions = sorted(
            [p for p in display_data if (p["P&L %"] or 0) > 0 and p["_pos"].get("tick")],
            key=lambda p: p["P&L %"],
            reverse=True
        )

        if winning_positions:
            exit_button_cols = st.columns(min(5, len(winning_positions)))
            for idx, pos_data in enumerate(winning_positions):
                pos = pos_data["_pos"]
                with exit_button_cols[idx % len(exit_button_cols)]:
                    # Keyed by the position itself, never by list order: the click reruns the page,
                    # the list may re-sort after a refresh, and one contract can be held as both
                    # MIS and NRML.
                    if st.button(
                        f"Exit {pos_data['Symbol'][:15]} {pos['product']} (+{pos_data['P&L %']:.2f}%)",
                        key=f"{key_prefix}_exit_{pos['exchange']}_{pos['symbol']}_{pos['product']}",
                        width='stretch'
                    ):
                        success, result_text, exit_price, order_status = place_quick_exit_order(pos_data["_pos"])
                        st.session_state[f"{key_prefix}_last_exit"] = {
                            "symbol": pos_data["Symbol"],
                            "success": success,
                            "order_id": result_text,
                            "exit_price": exit_price,
                            "order_status": order_status,
                        }
                        st.rerun()
        else:
            st.info("No priced, profitable positions to quick-exit right now.")

        st.markdown("---")
        st.markdown(f"### {label} Summary")
        priced_rows = [p for p in display_data if p["P&L"] is not None]
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Open Positions", len(open_rows))
        with col2:
            st.metric("Winning Positions", len([p for p in priced_rows if p["P&L"] > 0]))
        with col3:
            st.metric("Losing Positions", len([p for p in priced_rows if p["P&L"] < 0]))
        with col4:
            avg_return = sum(p["P&L %"] for p in priced_rows) / len(priced_rows) if priced_rows else None
            st.metric("Average Return %", f"{avg_return:+.2f}%" if avg_return is not None else "—")

    if closed_rows:
        st.markdown("#### Closed (quantity 0, realised P&L only)")
        st.dataframe(
            pd.DataFrame([
                {"Symbol": p["symbol"], "Expiry": format_expiry_short(p.get("expiry_date")),
                 "Realised P&L": p["realised_pnl"]}
                for p in closed_rows
            ]).style.format({"Realised P&L": "₹{:,.2f}"}),
            width='stretch'
        )


# --------------- DASHBOARD TABS ---------------
tab_overview, tab_equity, tab_commodity, tab_analytics, tab_greeks = st.tabs([
    "📊 FnO Overview (All)",
    "📈 Equity FnO (NIFTY, BANKNIFTY)",
    "🏆 Commodity FnO (GOLD, SILVER, CRUDE)",
    "📈 P&L Analytics",
    "⚙️ Greeks Analysis"
])

# ===== TAB 1: FNO OVERVIEW (ALL POSITIONS) =====
with tab_overview:
    st.markdown("### 💼 FnO Portfolio Summary (All Positions)")

    col_market_eq, col_market_cm = st.columns(2)
    for column, metrics, asset_type, name in (
        (col_market_eq, equity_metrics, "EQUITY", "Equity FnO"),
        (col_market_cm, commodity_metrics, "COMMODITY", "Commodity FnO"),
    ):
        with column:
            status, hours = market_status(asset_type)
            if metrics["count"] > 0:
                st.info(f"**{name}:** {hours} (currently **{status}**, by the clock; holidays not known)")
            else:
                st.info(f"**{name}:** No open positions")

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        render_kpi_card(
            title="Notional at Entry",
            value=format_inr(all_metrics["total_invested"]),
            sub=f"Full: {format_inr_full(all_metrics['total_invested'])}<br>Open Positions: {all_metrics['count']}",
            theme="blue"
        )

    with k2:
        render_kpi_card(
            title="Total Unrealized P&L",
            value=format_inr(all_metrics["total_pnl"]),
            sub=f"{all_metrics['pnl_pct']:+.2f}% | priced {all_metrics['priced']} of {all_metrics['count']}",
            theme="green" if all_metrics["total_pnl"] >= 0 else "red"
        )

    with k3:
        render_kpi_card(
            title="Realised P&L",
            value=format_inr(all_metrics["realised"]),
            sub=f"Full: {format_inr_full(all_metrics['realised'])}",
            theme="green" if all_metrics["realised"] >= 0 else "red"
        )

    with k4:
        render_kpi_card(
            title="F&O Balance Available",
            value=format_inr(fno_balance_available),
            sub=f"Margin used (F&O + MCX): {format_inr(fno_margin_used)}",
            theme="green"
        )

    st.markdown("<br>", unsafe_allow_html=True)

    c_left, c_right = st.columns(2)

    with c_left:
        st.markdown("#### 📊 P&L Distribution by Position")
        pnl_data = pd.DataFrame([
            {
                "Symbol": pos["symbol"],
                "Notional": pos["entry_value"],
                "P&L": pos["unrealized_pnl"],
                "P&L %": pos["unrealized_pnl_pct"]
            }
            for pos in open_positions if pos["priced"]
        ])
        if not pnl_data.empty:
            pnl_data = pnl_data.sort_values("P&L", ascending=True)
            fig_pnl = px.bar(
                pnl_data,
                x="Symbol",
                y="P&L",
                color="P&L",
                color_continuous_scale=['#ef4444', '#fbbf24', '#22c55e'],
                hover_data={"Notional": ":.2f", "P&L %": ":.2f", "P&L": ":.2f"},
                title="Unrealized P&L by Position"
            )
            fig_pnl.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                height=340,
                showlegend=False,
                xaxis_tickangle=-45
            )
            st.plotly_chart(fig_pnl, width='content')
        elif open_positions:
            st.info("No open position has a live price, so there is no P&L to chart.")
        else:
            st.info("No open FnO positions found.")

    with c_right:
        st.markdown("#### 🎯 Position Breakdown by Asset Class")
        if open_positions:
            type_counts = pd.DataFrame([
                {"AssetType": pos.get("type", "UNKNOWN"), "Count": 1}
                for pos in open_positions
            ]).groupby("AssetType").size().reset_index(name="Count")

            fig_type = px.pie(
                type_counts,
                values="Count",
                names="AssetType",
                hole=0.45,
                title="Position Distribution (Equity vs Commodity)",
                color_discrete_map={"EQUITY": "#3b82f6", "COMMODITY": "#f59e0b"}
            )
            fig_type.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
            st.plotly_chart(fig_type, width='content')
        else:
            st.info("No open FnO positions found.")

# ===== TAB 2: EQUITY FNO POSITIONS =====
with tab_equity:
    st.subheader("📈 Equity FnO Positions (NIFTY, BANKNIFTY, FINNIFTY, etc.)")
    st.markdown("Futures and options contracts on equity indices and stocks.")
    render_segment_kpis(equity_metrics, "EQUITY")
    st.markdown("<br>", unsafe_allow_html=True)
    render_positions_section(equity_positions, "eq", "Equity FnO")

# ===== TAB 3: COMMODITY FNO POSITIONS =====
with tab_commodity:
    st.subheader("🏆 Commodity FnO Positions (GOLD, SILVER, CRUDE, COPPER, etc.)")
    st.markdown("Futures and options contracts on MCX commodities.")
    render_segment_kpis(commodity_metrics, "COMMODITY")
    st.markdown("<br>", unsafe_allow_html=True)
    render_positions_section(commodity_positions, "cm", "Commodity FnO")

# ===== TAB 4: P&L ANALYTICS & POSITION SENTIMENT =====
with tab_analytics:
    st.subheader("📊 Position Sentiment & Price Direction Analysis")
    st.markdown(
        """
        Which way each open position profits, from its contract type **and** whether you bought or sold it.
        - **Bullish 🟢:** bought calls, sold puts and long futures profit if the underlying goes **UP**
        - **Bearish 🔴:** bought puts, sold calls and short futures profit if it goes **DOWN**
        - **Conflicting:** exposure on both sides of the same underlying (hedges, straddles, spreads)
        """
    )

    if open_positions:
        portfolio_summary = get_position_summary(fno_positions)

        s1, s2, s3, s4 = st.columns(4)

        with s1:
            render_kpi_card(
                title="Portfolio Sentiment",
                value=portfolio_summary["net_sentiment"],
                sub="Overall directional bias",
                theme="blue"
            )

        with s2:
            render_kpi_card(
                title="Bullish Positions",
                value=f"{portfolio_summary['total_bullish']}",
                sub="Profit if UP ↑",
                theme="green"
            )

        with s3:
            render_kpi_card(
                title="Bearish Positions",
                value=f"{portfolio_summary['total_bearish']}",
                sub="Profit if DOWN ↓",
                theme="red"
            )

        with s4:
            render_kpi_card(
                title="Conflicting Underlyings",
                value=f"{len(portfolio_summary['conflicting'])}",
                sub="Exposure on both sides",
                theme="blue"
            )

        st.markdown("<br>", unsafe_allow_html=True)

        analytics_tab1, analytics_tab2, analytics_tab3 = st.tabs([
            "🎯 Position Sentiment Table",
            "📈 P&L Performance",
            "⚖️ Strategy Analysis"
        ])

        # ===== ANALYTICS TAB 1: POSITION SENTIMENT TABLE (GROUPED BY EQUITY & COMMODITY) =====
        with analytics_tab1:
            grouped_positions = group_positions_by_underlying_expiry(fno_positions)

            def render_positions_table(positions_group, title):
                """Helper function to render a grouped positions table"""
                if not positions_group:
                    st.info(f"No {title.lower()} positions")
                    return

                st.markdown(f"#### {title}")

                display_data = []
                for group in positions_group:
                    sentiment = position_sentiment(
                        {"kind": group["option_type"], "underlying": group["underlying"],
                         "quantity": 1 if group["side"] == "LONG" else -1}
                    )["sentiment"]
                    display_data.append({
                        "Asset": group["underlying"],
                        "Type": group["option_type"],
                        "Side": group["side"],
                        "Expiry": group["expiry"],
                        "Contracts": group["position_count"],
                        "Notional ₹": group["total_invested"],
                        "P&L ₹": group["total_pnl"] if group["unpriced"] < group["position_count"] else None,
                        "P&L %": group["total_pnl_pct"] if group["unpriced"] < group["position_count"] else None,
                        "Performance": group["pnl_arrow"],
                        "Direction": {"BULLISH": "📈", "BEARISH": "📉"}.get(sentiment, "➡️"),
                    })

                df = pd.DataFrame(display_data)

                def highlight_type_column(val):
                    if val == "CALL":
                        return "background-color: #4caf50; color: white; font-weight: bold"
                    elif val == "PUT":
                        return "background-color: #f44336; color: white; font-weight: bold"
                    else:
                        return "background-color: #999999; color: white"

                def shade_pnl(val):
                    # Green or red, stronger up to +/-10%. Done by hand: pandas' background_gradient
                    # needs matplotlib, which this project does not install.
                    if val is None or pd.isna(val) or val == 0:
                        return ""
                    alpha = 0.15 + 0.6 * min(abs(val), 10) / 10
                    rgb = "34, 197, 94" if val > 0 else "239, 68, 68"
                    return f"background-color: rgba({rgb}, {alpha:.2f})"

                styled = df.style.format({
                    "Notional ₹": "₹{:,.0f}",
                    "P&L ₹": "₹{:,.0f}",
                    "P&L %": "{:+.2f}%"
                }, na_rep="—").map(
                    highlight_type_column,
                    subset=["Type"]
                ).map(
                    shade_pnl,
                    subset=["P&L %"]
                )

                st.dataframe(styled, width='stretch', height=min(400, 40 + 35 * len(df)))

                with st.expander(f"🔍 Expand to see all symbols ({len(positions_group)} groups)"):
                    for group in positions_group:
                        st.markdown(
                            f"**{group['underlying']} {group['option_type']} {group['side']} - {group['expiry']}** "
                            f"({group['position_count']} contracts | P&L: {group['pnl_arrow']} {group['total_pnl_pct']:+.2f}%"
                            f"{', ' + str(group['unpriced']) + ' unpriced' if group['unpriced'] else ''})"
                        )
                        for symbol in group["symbols"]:
                            st.code(symbol, language="text")

            st.markdown("### 📈 Equity FnO Positions")
            render_positions_table([g for g in grouped_positions if g["asset_type"] == "EQUITY"], "Equity FnO")

            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown("### 🏆 Commodity FnO Positions")
            render_positions_table([g for g in grouped_positions if g["asset_type"] == "COMMODITY"], "Commodity FnO")

        # ===== ANALYTICS TAB 2: P&L PERFORMANCE =====
        with analytics_tab2:
            st.markdown("#### Winners vs Losers")

            analytics_df = pd.DataFrame([
                {
                    "Symbol": pos["symbol"],
                    "Type": pos["type"],
                    "Notional": pos["entry_value"],
                    "Current": pos["total_value"],
                    "P&L": pos["unrealized_pnl"],
                    "P&L %": pos["unrealized_pnl_pct"]
                }
                for pos in open_positions if pos["priced"]
            ])

            if analytics_df.empty:
                st.info("No open position has a live price, so there is no P&L to analyse.")
            else:
                c1, c2 = st.columns(2)

                with c1:
                    summary_data = pd.DataFrame({
                        "Status": ["Winners", "Losers", "Neutral"],
                        "Count": [
                            len(analytics_df[analytics_df['P&L'] > 0]),
                            len(analytics_df[analytics_df['P&L'] < 0]),
                            len(analytics_df[analytics_df['P&L'] == 0]),
                        ]
                    })
                    summary_data = summary_data[summary_data['Count'] > 0]

                    fig_summary = px.pie(
                        summary_data,
                        values="Count",
                        names="Status",
                        color_discrete_map={"Winners": "#22c55e", "Losers": "#ef4444", "Neutral": "#94a3b8"},
                        hole=0.45,
                        title="Position Performance"
                    )
                    fig_summary.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
                    st.plotly_chart(fig_summary, width='content')

                with c2:
                    st.markdown("#### Notional: Entry vs Now")
                    top_positions = analytics_df.nlargest(10, "Notional")

                    fig_val = px.bar(
                        top_positions,
                        x="Symbol",
                        y=["Notional", "Current"],
                        barmode="group",
                        color_discrete_sequence=["#94a3b8", "#3b82f6"],
                        hover_data={"P&L": ":.2f", "P&L %": ":.2f"}
                    )
                    fig_val.update_layout(
                        margin=dict(t=10, b=10, l=10, r=10),
                        height=340,
                        yaxis_title="Amount (₹)",
                        legend_title="",
                        xaxis_tickangle=-45
                    )
                    st.plotly_chart(fig_val, width='content')

                st.markdown("---")
                st.markdown("### Performance Metrics")
                m1, m2, m3, m4 = st.columns(4)

                with m1:
                    best_position = analytics_df.loc[analytics_df["P&L %"].idxmax()]
                    st.metric("Best Performer", f"{best_position['Symbol']}", f"{best_position['P&L %']:+.2f}%")

                with m2:
                    worst_position = analytics_df.loc[analytics_df["P&L %"].idxmin()]
                    st.metric("Worst Performer", f"{worst_position['Symbol']}", f"{worst_position['P&L %']:+.2f}%")

                with m3:
                    total_gain = analytics_df[analytics_df['P&L'] > 0]['P&L'].sum()
                    st.metric("Total Gains", format_inr(total_gain), "")

                with m4:
                    total_loss = analytics_df[analytics_df['P&L'] < 0]['P&L'].sum()
                    st.metric("Total Losses", format_inr(total_loss), "")

        # ===== ANALYTICS TAB 3: STRATEGY ANALYSIS =====
        with analytics_tab3:
            st.markdown("#### Portfolio Strategy Analysis")

            st.markdown("##### 🎯 Sentiment Distribution")
            col_strat1, col_strat2 = st.columns(2)

            with col_strat1:
                if portfolio_summary["total_bullish"] > 0 or portfolio_summary["total_bearish"] > 0:
                    strategy_df = pd.DataFrame({
                        "Sentiment": ["Bullish", "Bearish"],
                        "Count": [portfolio_summary["total_bullish"], portfolio_summary["total_bearish"]]
                    })
                    strategy_df = strategy_df[strategy_df["Count"] > 0]

                    fig_sentiment = px.pie(
                        strategy_df,
                        values="Count",
                        names="Sentiment",
                        color_discrete_map={"Bullish": "#22c55e", "Bearish": "#ef4444"},
                        title="Bullish vs Bearish Positioning"
                    )
                    fig_sentiment.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
                    st.plotly_chart(fig_sentiment, width='content')
                else:
                    st.info("No clear sentiment distribution.")

            with col_strat2:
                st.markdown("**Key Insights:**")
                bullish, bearish = portfolio_summary["total_bullish"], portfolio_summary["total_bearish"]
                if bullish > bearish:
                    st.success(f"✅ **Overall Bullish Bias**\n- {bullish} position(s) profit if prices rise\n- {bearish} profit if they fall")
                elif bearish > bullish:
                    st.error(f"⚠️ **Overall Bearish Bias**\n- {bearish} position(s) profit if prices fall\n- {bullish} profit if they rise")
                else:
                    st.info(f"⚪ **Neutral / Balanced**\n- {bullish} bullish and {bearish} bearish position(s)")

            if portfolio_summary["conflicting"]:
                st.markdown("---")
                st.markdown("##### ⚖️ Conflicting Positions (Hedges / Straddles / Spreads)")
                st.markdown(
                    f"""
                    You have exposure on **both sides** of these underlyings:
                    {', '.join(sorted(portfolio_summary['conflicting']))}

                    **What this means:**
                    - You might be hedging (protecting against big moves in either direction)
                    - Or running a straddle or spread (profit from a range or a big move)
                    """
                )
            else:
                st.markdown("---")
                st.info("✅ No conflicting positions. Your directional bias is clear.")
    else:
        st.info("No open FnO positions for analytics.")

# ===== TAB 5: GREEKS ANALYSIS =====
with tab_greeks:
    st.subheader("⚙️ Greeks: Options Risk & Sensitivity Analysis")
    st.markdown(
        """
        - **Delta (Δ):** Rate of price change relative to underlying (0 to 1 for calls, -1 to 0 for puts).
        - **Gamma (Γ):** Rate of delta change; higher gamma = more reactive to price moves.
        - **Theta (Θ):** Time decay (daily P&L from passage of time alone). Negative for buyers, positive for sellers.
        - **Vega (ν):** Sensitivity to implied volatility changes.
        - **Position Δ:** contract delta × your signed quantity, so a sold call shows negative delta.
        """
    )

    options_only = [p for p in open_positions if p.get("kind") in ("CALL", "PUT")]
    greeks = result.get("greeks") or {}

    if not options_only:
        st.info("No open options positions. Greeks analysis is for options only.")
    elif not greeks:
        st.warning(
            "No Greeks available. Groww positions carry none; they come from Groww's `get_greeks` call, "
            "which needs its paid data plan and covers NSE options only."
            + (f" Reason: `{result['greeks_error']}`" if result.get("greeks_error") else "")
        )
    else:
        greeks_df = pd.DataFrame([
            {
                "Symbol": pos["symbol"],
                "Qty": pos["quantity"],
                "Delta": greeks[pos["symbol"]].get("delta"),
                "Gamma": greeks[pos["symbol"]].get("gamma"),
                "Theta": greeks[pos["symbol"]].get("theta"),
                "Vega": greeks[pos["symbol"]].get("vega"),
                "IV": greeks[pos["symbol"]].get("iv"),
                "Position Δ": (greeks[pos["symbol"]].get("delta") or 0.0) * pos["quantity"],
            }
            for pos in options_only if pos["symbol"] in greeks
        ])
        missing = [p["symbol"] for p in options_only if p["symbol"] not in greeks]
        if missing:
            st.warning(f"No Greeks for {', '.join(missing)}"
                       + (f": `{result['greeks_error']}`" if result.get("greeks_error") else "."))

        st.markdown("#### Greeks Heatmap (per contract)")
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=[greeks_df['Delta'], greeks_df['Gamma'], greeks_df['Theta'], greeks_df['Vega']],
            x=greeks_df['Symbol'],
            y=['Delta', 'Gamma', 'Theta', 'Vega'],
            colorscale='RdYlGn',
            zmid=0
        ))
        fig_heatmap.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_heatmap, width='content')

        st.markdown("#### Greeks Summary Table")
        st.dataframe(
            greeks_df.style.format({
                "Qty": "{:,.0f}",
                "Delta": "{:.4f}",
                "Gamma": "{:.4f}",
                "Theta": "{:.4f}",
                "Vega": "{:.4f}",
                "IV": "{:.2f}",
                "Position Δ": "{:,.2f}",
            }, na_rep="—"),
            width='stretch'
        )
