import os
import re
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
from utils import (
    format_inr,
    format_inr_full,
    format_expiry_date,
    format_expiry_short,
    extract_position_sentiment,
    get_sentiment_color,
    get_position_summary,
    group_positions_by_underlying_expiry,
    EXCHANGE_NSE,
    EXCHANGE_MCX,
    SEGMENT_FNO,
    SEGMENT_COMMODITY,
)

# Quick exit helper function
def place_quick_exit_order(symbol, quantity, ltp, exchange, segment):
    """Place a quick exit order at LTP - 0.5%"""
    try:
        exit_price = ltp * 0.995  # 0.5% less than LTP
        api_client = GrowwAPIClient.get_instance()
        api_service = GrowwAPIService(api_client)

        order_response = api_service.place_order(
            trading_symbol=symbol,
            quantity=quantity,
            price=exit_price,
            validity="DAY",
            exchange=exchange,
            segment=segment,
            product="NRML",
            order_type="LIMIT",
            transaction_type="SELL",
        )
        groww_order_id = order_response.get('groww_order_id', 'Unknown')

        # Best-effort status check - order was already placed even if this fails
        order_status = "UNKNOWN"
        try:
            status_response = api_service.get_order_status(segment=segment, groww_order_id=groww_order_id)
            order_status = status_response.get('order_status') or status_response.get('status') or "UNKNOWN"
        except Exception:
            pass

        return True, groww_order_id, exit_price, order_status
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

mode_choice = st.sidebar.radio(
    "Data Source Mode:",
    ["Live FnO Trading API", "Demo / Mock Data (Test UI)"],
    index=0 if (os.getenv("GROWW_API_KEY") or os.getenv("GROWW_ACCESS_TOKEN")) else 1
)

is_mock = (mode_choice == "Demo / Mock Data (Test UI)")

with st.sidebar.expander("🔑 Broker Credentials & Connection", expanded=True):
    auth_mode = os.getenv("GROWW_AUTH_MODE", "TOTP")
    api_key = os.getenv("GROWW_API_KEY", "")
    totp_secret = os.getenv("GROWW_TOTP_SECRET", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")
    access_token = os.getenv("GROWW_ACCESS_TOKEN", "")

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
    - **Greeks:** Delta (directional), Gamma (acceleration), Theta (time decay), Vega (volatility).
    """
)

# --------------- DATA FETCHING ---------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_fno_data(mock: bool):
    """
    Fetch FnO positions using singleton client.
    Auth happens ONCE per session (singleton pattern), not per cache refresh.
    """
    try:
        # Get singleton client (authenticates only on first call)
        api_client = GrowwAPIClient.get_instance()
        if not api_client.is_connected:
            return None, api_client.auth_error or "Failed to authenticate"

        # Create service layer
        api_service = GrowwAPIService(api_client)

        # Fetch user data
        profile = api_service.get_user_profile()
        margins = api_service.get_margins()

        # Process FnO positions
        processor = PositionProcessor(api_service)
        fno_positions = processor.get_fno_positions()

        return {
            "profile": profile,
            "margins": margins,
            "fno_positions": fno_positions,
        }, None
    except Exception as e:
        return None, str(e)

with st.spinner("Fetching FnO positions..."):
    result, error_msg = fetch_fno_data(is_mock)

if error_msg:
    st.error(f"⚠️ **Error**: {error_msg}")
    st.info("Check your `.env` file credentials or switch to **'Demo / Mock Data'** mode in the sidebar.")
    st.stop()

profile = result["profile"]
margins = result["margins"]
fno_positions = result["fno_positions"]

# --------------- CALCULATE SUMMARY METRICS ---------------
total_invested = 0.0
total_fno_value = 0.0
total_fno_pnl = 0.0
total_fno_margin = 0.0
position_count = 0

for pos in fno_positions:
    entry_val = float(pos.get("entry_value", 0.0))
    total_val = float(pos.get("total_value", 0.0))
    pnl = float(pos.get("unrealized_pnl", 0.0))

    total_invested += entry_val
    total_fno_value += total_val
    total_fno_pnl += pnl
    if entry_val > 0 or total_val > 0:
        position_count += 1

# Calculate overall P&L percentage
if total_invested > 0:
    total_pnl_pct = (total_fno_pnl / total_invested) * 100.0
else:
    total_pnl_pct = 0.0

fno_margin_used = float(margins.get("fno_margin_details", {}).get("net_fno_margin_used", 0.0))
clear_cash = float(margins.get("clear_cash", 0.0))
collateral_available = float(margins.get("collateral_available", 0.0))

# --------------- TOP BAR: HEADER ---------------
col_head, col_cash = st.columns([3, 1])

with col_head:
    st.title("📈 FnO Positions & Greeks Tracker")
    if is_mock:
        st.caption("🟡 Running in **Demo Mode** with sample data. Configure `.env` to connect live account.")
    else:
        st.caption(f"🟢 Connected to Live Broker Account | Client UCC: `{profile.get('ucc', 'N/A')}`")

with col_cash:
    render_kpi_card(
        title="Account Clear Cash (Wallet)",
        value=format_inr(clear_cash),
        sub=f"Full: {format_inr_full(clear_cash)}",
        theme="green"
    )

st.markdown("---")

# --------------- FILTER POSITIONS BY ASSET TYPE ---------------
equity_positions = [p for p in fno_positions if p.get("type", "").upper() == "EQUITY"]
commodity_positions = [p for p in fno_positions if p.get("type", "").upper() == "COMMODITY"]

# Calculate metrics for each segment
def calculate_segment_metrics(positions):
    """Calculate summary metrics for a segment of positions."""
    total_invested = sum(float(p.get("entry_value", 0.0)) for p in positions)
    total_value = sum(float(p.get("total_value", 0.0)) for p in positions)
    total_pnl = sum(float(p.get("unrealized_pnl", 0.0)) for p in positions)
    pnl_pct = (total_pnl / total_invested * 100.0) if total_invested > 0 else 0.0
    count = len([p for p in positions if float(p.get("entry_value", 0.0)) > 0 or float(p.get("total_value", 0.0)) > 0])
    return {
        "total_invested": total_invested,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "pnl_pct": pnl_pct,
        "count": count
    }

equity_metrics = calculate_segment_metrics(equity_positions)
commodity_metrics = calculate_segment_metrics(commodity_positions)

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

    # Market Status Indicator
    col_market_eq, col_market_cm = st.columns(2)
    with col_market_eq:
        if equity_metrics["count"] > 0:
            st.info("📊 **Equity FnO:** Market Hours 09:15-15:30 IST (Currently **CLOSED**)")
        else:
            st.info("📊 **Equity FnO:** No active positions")

    with col_market_cm:
        if commodity_metrics["count"] > 0:
            st.success("🏆 **Commodity FnO:** 24x5 Trading (Currently **OPEN**)")
        else:
            st.info("🏆 **Commodity FnO:** No active positions")

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        render_kpi_card(
            title="Total Amount Invested",
            value=format_inr(total_invested),
            sub=f"Full: {format_inr_full(total_invested)}<br>Active Positions: {position_count}",
            theme="blue"
        )

    with k2:
        pnl_theme = "green" if total_fno_pnl >= 0 else "red"
        render_kpi_card(
            title="Total Unrealized P&L",
            value=format_inr(total_fno_pnl),
            sub=f"{total_pnl_pct:+.2f}% Overall | {format_inr_full(total_fno_pnl)}",
            theme=pnl_theme
        )

    with k3:
        render_kpi_card(
            title="Current Portfolio Value",
            value=format_inr(total_fno_value),
            sub=f"Full: {format_inr_full(total_fno_value)}",
            theme="blue"
        )

    with k4:
        render_kpi_card(
            title="Available Margin",
            value=format_inr(collateral_available + clear_cash),
            sub=f"For new positions",
            theme="green"
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Charts
    c_left, c_right = st.columns(2)

    with c_left:
        st.markdown("#### 📊 P&L Distribution by Position")
        if fno_positions:
            pnl_data = pd.DataFrame([
                {
                    "Symbol": pos.get("symbol", "UNKNOWN"),
                    "Investment": pos.get("entry_value", 0.0),
                    "P&L": pos.get("unrealized_pnl", 0.0),
                    "P&L %": pos.get("unrealized_pnl_pct", 0.0)
                }
                for pos in fno_positions
                if pos.get("entry_value", 0.0) > 0 or pos.get("total_value", 0.0) > 0
            ])

            if not pnl_data.empty:
                # Sort by P&L for better visualization
                pnl_data = pnl_data.sort_values("P&L", ascending=True)

                fig_pnl = px.bar(
                    pnl_data,
                    x="Symbol",
                    y="P&L",
                    color="P&L",
                    color_continuous_scale=['#ef4444', '#fbbf24', '#22c55e'],
                    hover_data={"Investment": ":.2f", "P&L %": ":.2f%", "P&L": ":.2f"},
                    title="Unrealized P&L by Position"
                )
                fig_pnl.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=340,
                    showlegend=False,
                    xaxis_tickangle=-45
                )
                st.plotly_chart(fig_pnl, width='content')
            else:
                st.info("No valid position data to display.")
        else:
            st.info("No FnO positions found.")

    with c_right:
        st.markdown("#### 🎯 Position Breakdown by Asset Class")
        if fno_positions:
            type_counts = pd.DataFrame([
                {"AssetType": pos.get("type", "UNKNOWN"), "Count": 1}
                for pos in fno_positions
            ]).groupby("AssetType").size().reset_index(name="Count")

            if not type_counts.empty:
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
                st.info("No position data available.")
        else:
            st.info("No FnO positions found.")

# ===== TAB 2: EQUITY FNO POSITIONS =====
with tab_equity:
    st.subheader("📈 Equity FnO Positions (NIFTY, BANKNIFTY, FINNIFTY, etc.)")
    st.markdown("Futures and options contracts on equity indices. Market hours: 09:15-15:30 IST.")

    # Equity metrics KPI
    eq_k1, eq_k2, eq_k3, eq_k4 = st.columns(4)

    with eq_k1:
        render_kpi_card(
            title="Total Invested",
            value=format_inr(equity_metrics["total_invested"]),
            sub=f"Active: {equity_metrics['count']}",
            theme="blue"
        )

    with eq_k2:
        eq_theme = "green" if equity_metrics["total_pnl"] >= 0 else "red"
        render_kpi_card(
            title="Unrealized P&L",
            value=format_inr(equity_metrics["total_pnl"]),
            sub=f"{equity_metrics['pnl_pct']:+.2f}%",
            theme=eq_theme
        )

    with eq_k3:
        render_kpi_card(
            title="Current Value",
            value=format_inr(equity_metrics["total_value"]),
            sub="Portfolio",
            theme="blue"
        )

    with eq_k4:
        status_theme = "blue" if equity_metrics["count"] == 0 else "red"
        render_kpi_card(
            title="Market Status",
            value="CLOSED",
            sub="09:15-15:30 IST",
            theme=status_theme
        )

    st.markdown("<br>", unsafe_allow_html=True)

    if equity_positions and equity_metrics["count"] > 0:
        # Create display dataframe for equity positions
        display_data = []
        for pos in equity_positions:
            entry_val = float(pos.get("entry_value", 0.0))
            if equity_metrics["total_invested"] > 0:
                pct_of_total = (entry_val / equity_metrics["total_invested"]) * 100.0
            else:
                pct_of_total = 0.0

            symbol = pos.get("symbol", "")
            expiry_display = format_expiry_short(symbol)

            display_data.append({
                "Symbol": symbol,
                "Expiry": expiry_display,
                "Qty": int(pos.get("quantity", 0)) if pos.get("quantity") else 0,
                "% of Total": pct_of_total,
                "Entry Price": pos.get("entry_price", 0.0),
                "LTP": pos.get("ltp", 0.0),
                "Investment": entry_val,
                "Current Value": pos.get("total_value", 0.0),
                "P&L": pos.get("unrealized_pnl", 0.0),
                "P&L %": pos.get("unrealized_pnl_pct", 0.0)
            })

        df_display = pd.DataFrame(display_data)

        # Sort by P&L % descending (winners first)
        df_display = df_display.sort_values("P&L %", ascending=False).reset_index(drop=True)

        # Sortable Table with Quick Exit Buttons
        st.markdown("#### Positions with Quick Exit (Sortable)")

        # Display base dataframe
        st.dataframe(
            df_display.style.format({
                "Qty": "{:,.0f}",
                "% of Total": "{:.2f}%",
                "Entry Price": "₹{:,.2f}",
                "LTP": "₹{:,.2f}",
                "Investment": "₹{:,.2f}",
                "Current Value": "₹{:,.2f}",
                "P&L": "₹{:,.2f}",
                "P&L %": "{:+.2f}%"
            }),
            width='stretch',
            height=400
        )

        # Quick Exit Buttons Below Table (winners only, highest P&L% first)
        st.markdown("**Quick Exit Buttons (profitable positions, highest P&L% first):**")

        # Prominent, persistent result banner - stays visible (and full-width) after the rerun
        # that a button click triggers, instead of a message tucked into a narrow column.
        last_exit = st.session_state.get("eq_last_exit")
        if last_exit:
            if last_exit["success"]:
                st.success(
                    f"✅ **{last_exit['symbol']}** exit order placed @ ₹{last_exit['exit_price']:.2f} | "
                    f"Order ID: `{last_exit['order_id']}` | Status: **{last_exit['order_status']}**"
                )
                st.caption("Status is read back from the API immediately after placement. Confirm the final fill in the Groww app / order book.")
            else:
                st.error(f"❌ **{last_exit['symbol']}** exit failed: {last_exit['order_id']}")
            if st.button("Dismiss", key="eq_dismiss_exit"):
                del st.session_state["eq_last_exit"]
                st.rerun()

        winning_positions = sorted(
            [p for p in display_data if p["P&L %"] > 0],
            key=lambda p: p["P&L %"],
            reverse=True
        )

        if winning_positions:
            exit_button_cols = st.columns(min(5, len(winning_positions)))
            for idx, pos_data in enumerate(winning_positions):
                with exit_button_cols[idx % len(exit_button_cols)]:
                    if st.button(
                        f"Exit {pos_data['Symbol'][:15]} (+{pos_data['P&L %']:.2f}%)",
                        key=f"eq_exit_{idx}_{pos_data['Symbol']}",
                        width='stretch'
                    ):
                        symbol = pos_data['Symbol']
                        quantity = pos_data['Qty']
                        ltp = pos_data['LTP']

                        success, result, exit_price, order_status = place_quick_exit_order(
                            symbol=symbol,
                            quantity=quantity,
                            ltp=ltp,
                            exchange=EXCHANGE_NSE,
                            segment=SEGMENT_FNO
                        )

                        st.session_state["eq_last_exit"] = {
                            "symbol": symbol,
                            "success": success,
                            "order_id": result,
                            "exit_price": exit_price,
                            "order_status": order_status,
                        }
                        st.rerun()
        else:
            st.info("No profitable positions to quick-exit right now.")

        # Summary statistics
        st.markdown("---")
        st.markdown("### Equity FnO Summary")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Positions", equity_metrics["count"])

        with col2:
            winners = len([p for p in display_data if p["P&L"] > 0])
            st.metric("Winning Positions", winners)

        with col3:
            losers = len([p for p in display_data if p["P&L"] < 0])
            st.metric("Losing Positions", losers)

        with col4:
            avg_return = df_display["P&L %"].mean() if len(df_display) > 0 else 0
            st.metric("Average Return %", f"{avg_return:+.2f}%")

    else:
        st.info("No open Equity FnO positions found in your account.")

# ===== TAB 3: COMMODITY FNO POSITIONS =====
with tab_commodity:
    st.subheader("🏆 Commodity FnO Positions (GOLD, SILVER, CRUDE, COPPER, etc.)")
    st.markdown("Futures and options contracts on commodities. Trading: 24x5 (mostly 9:00-23:30 IST with gaps).")

    # Commodity metrics KPI
    cm_k1, cm_k2, cm_k3, cm_k4 = st.columns(4)

    with cm_k1:
        render_kpi_card(
            title="Total Invested",
            value=format_inr(commodity_metrics["total_invested"]),
            sub=f"Active: {commodity_metrics['count']}",
            theme="blue"
        )

    with cm_k2:
        cm_theme = "green" if commodity_metrics["total_pnl"] >= 0 else "red"
        render_kpi_card(
            title="Unrealized P&L",
            value=format_inr(commodity_metrics["total_pnl"]),
            sub=f"{commodity_metrics['pnl_pct']:+.2f}%",
            theme=cm_theme
        )

    with cm_k3:
        render_kpi_card(
            title="Current Value",
            value=format_inr(commodity_metrics["total_value"]),
            sub="Portfolio",
            theme="blue"
        )

    with cm_k4:
        status_theme = "green" if commodity_metrics["count"] > 0 else "blue"
        render_kpi_card(
            title="Market Status",
            value="OPEN",
            sub="24x5 Trading",
            theme=status_theme
        )

    st.markdown("<br>", unsafe_allow_html=True)

    if commodity_positions and commodity_metrics["count"] > 0:
        # Create display dataframe for commodity positions
        display_data = []
        for pos in commodity_positions:
            entry_val = float(pos.get("entry_value", 0.0))
            if commodity_metrics["total_invested"] > 0:
                pct_of_total = (entry_val / commodity_metrics["total_invested"]) * 100.0
            else:
                pct_of_total = 0.0

            symbol = pos.get("symbol", "")
            expiry_display = format_expiry_short(symbol)

            display_data.append({
                "Symbol": symbol,
                "Expiry": expiry_display,
                "Qty": int(pos.get("quantity", 0)) if pos.get("quantity") else 0,
                "% of Total": pct_of_total,
                "Entry Price": pos.get("entry_price", 0.0),
                "LTP": pos.get("ltp", 0.0),
                "Investment": entry_val,
                "Current Value": pos.get("total_value", 0.0),
                "P&L": pos.get("unrealized_pnl", 0.0),
                "P&L %": pos.get("unrealized_pnl_pct", 0.0)
            })

        df_display = pd.DataFrame(display_data)

        # Sort by P&L % descending (winners first)
        df_display = df_display.sort_values("P&L %", ascending=False).reset_index(drop=True)

        # Sortable Table with Quick Exit Buttons
        st.markdown("#### Positions with Quick Exit (Sortable)")

        # Display base dataframe
        st.dataframe(
            df_display.style.format({
                "Qty": "{:,.0f}",
                "% of Total": "{:.2f}%",
                "Entry Price": "₹{:,.2f}",
                "LTP": "₹{:,.2f}",
                "Investment": "₹{:,.2f}",
                "Current Value": "₹{:,.2f}",
                "P&L": "₹{:,.2f}",
                "P&L %": "{:+.2f}%"
            }),
            width='stretch',
            height=400
        )

        # Quick Exit Buttons Below Table (winners only, highest P&L% first)
        st.markdown("**Quick Exit Buttons (profitable positions, highest P&L% first):**")

        # Prominent, persistent result banner - stays visible (and full-width) after the rerun
        # that a button click triggers, instead of a message tucked into a narrow column.
        last_exit = st.session_state.get("cm_last_exit")
        if last_exit:
            if last_exit["success"]:
                st.success(
                    f"✅ **{last_exit['symbol']}** exit order placed @ ₹{last_exit['exit_price']:.2f} | "
                    f"Order ID: `{last_exit['order_id']}` | Status: **{last_exit['order_status']}**"
                )
                st.caption("Status is read back from the API immediately after placement. Confirm the final fill in the Groww app / order book.")
            else:
                st.error(f"❌ **{last_exit['symbol']}** exit failed: {last_exit['order_id']}")
            if st.button("Dismiss", key="cm_dismiss_exit"):
                del st.session_state["cm_last_exit"]
                st.rerun()

        winning_positions = sorted(
            [p for p in display_data if p["P&L %"] > 0],
            key=lambda p: p["P&L %"],
            reverse=True
        )

        if winning_positions:
            exit_button_cols = st.columns(min(5, len(winning_positions)))
            for idx, pos_data in enumerate(winning_positions):
                with exit_button_cols[idx % len(exit_button_cols)]:
                    if st.button(
                        f"Exit {pos_data['Symbol'][:15]} (+{pos_data['P&L %']:.2f}%)",
                        key=f"cm_exit_{idx}_{pos_data['Symbol']}",
                        width='stretch'
                    ):
                        symbol = pos_data['Symbol']
                        quantity = pos_data['Qty']
                        ltp = pos_data['LTP']

                        success, result, exit_price, order_status = place_quick_exit_order(
                            symbol=symbol,
                            quantity=quantity,
                            ltp=ltp,
                            exchange=EXCHANGE_MCX,
                            segment=SEGMENT_COMMODITY
                        )

                        st.session_state["cm_last_exit"] = {
                            "symbol": symbol,
                            "success": success,
                            "order_id": result,
                            "exit_price": exit_price,
                            "order_status": order_status,
                        }
                        st.rerun()
        else:
            st.info("No profitable positions to quick-exit right now.")

        # Summary statistics
        st.markdown("---")
        st.markdown("### Commodity FnO Summary")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Positions", commodity_metrics["count"])

        with col2:
            winners = len([p for p in display_data if p["P&L"] > 0])
            st.metric("Winning Positions", winners)

        with col3:
            losers = len([p for p in display_data if p["P&L"] < 0])
            st.metric("Losing Positions", losers)

        with col4:
            avg_return = df_display["P&L %"].mean() if len(df_display) > 0 else 0
            st.metric("Average Return %", f"{avg_return:+.2f}%")

    else:
        st.info("No open Commodity FnO positions found in your account.")

# ===== TAB 4: P&L ANALYTICS & POSITION SENTIMENT =====
with tab_analytics:
    st.subheader("📊 Position Sentiment & Price Direction Analysis")
    st.markdown(
        """
        Automatically analyze each option position to understand your **directional exposure**.
        - **CALLS (🟢 Bullish):** You profit if the underlying price goes **UP**
        - **PUTS (🔴 Bearish):** You profit if the underlying price goes **DOWN**
        - **Conflicting Positions:** Same underlying with both calls & puts (hedging or straddle strategy)
        """
    )

    if fno_positions and position_count > 0:
        # Get portfolio sentiment summary
        portfolio_summary = get_position_summary(fno_positions)

        # Portfolio sentiment KPIs
        s1, s2, s3, s4 = st.columns(4)

        with s1:
            render_kpi_card(
                title="Portfolio Sentiment",
                value=portfolio_summary["net_sentiment"],
                sub=f"Overall directional bias",
                theme="blue"
            )

        with s2:
            render_kpi_card(
                title="Bullish Positions",
                value=f"{portfolio_summary['total_bullish']}",
                sub="Calls: Profit if UP ↑",
                theme="green"
            )

        with s3:
            render_kpi_card(
                title="Bearish Positions",
                value=f"{portfolio_summary['total_bearish']}",
                sub="Puts: Profit if DOWN ↓",
                theme="red"
            )

        with s4:
            render_kpi_card(
                title="Conflicting Underlyings",
                value=f"{len(portfolio_summary['conflicting'])}",
                sub="Both calls & puts held",
                theme="blue"
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # Main analytics section
        analytics_tab1, analytics_tab2, analytics_tab3 = st.tabs([
            "🎯 Position Sentiment Table",
            "📈 P&L Performance",
            "⚖️ Strategy Analysis"
        ])

        # ===== ANALYTICS TAB 1: POSITION SENTIMENT TABLE (GROUPED BY EQUITY & COMMODITY) =====
        with analytics_tab1:
            # Group positions by underlying, expiry, AND type
            grouped_positions = group_positions_by_underlying_expiry(fno_positions)

            # Separate into Equity and Commodity based on position type (from API data)
            # Build a map of (underlying, expiry, type) -> position_type for classification
            position_type_map = {}
            for pos in fno_positions:
                symbol = pos.get("symbol", "")
                sentiment_info = extract_position_sentiment(symbol)
                underlying = sentiment_info.get("underlying", "UNKNOWN")
                position_type = pos.get("type", "UNKNOWN")  # EQUITY or COMMODITY from API

                # Extract expiry for grouping key
                expiry_match = re.search(r'(\d{2})([A-Z]{3})', symbol)
                if expiry_match:
                    day, month = expiry_match.groups()
                    expiry_key = f"{day}{month}"
                else:
                    expiry_key = "UNKNOWN"

                option_type = sentiment_info.get("option_type", "UNKNOWN")
                key = (underlying, expiry_key, option_type)
                position_type_map[key] = position_type

            # Classify grouped positions using the actual type from API
            equity_groups = []
            commodity_groups = []
            for g in grouped_positions:
                # Find the position type for this group
                key = (g["underlying"], g["expiry_key"], g["option_type"])
                pos_type = position_type_map.get(key, "UNKNOWN")

                if pos_type == "EQUITY":
                    equity_groups.append(g)
                elif pos_type == "COMMODITY":
                    commodity_groups.append(g)
                else:
                    # Fallback: if unknown, try to classify by keyword
                    if any(kw in g["underlying"].upper() for kw in ["GOLD", "SILVER", "CRUDE", "COPPER", "NICKEL", "ZINC", "LEAD", "ALUMINUM"]):
                        commodity_groups.append(g)
                    else:
                        equity_groups.append(g)

            def render_positions_table(positions_group, title):
                """Helper function to render a positions table"""
                if not positions_group:
                    st.info(f"No {title.lower()} positions")
                    return

                st.markdown(f"#### {title}")

                # Build display dataframe
                display_data = []
                for group in positions_group:
                    if group["option_type"] == "CALL":
                        type_display = "CALL"
                        direction_arrow = "📈"  # Chart going UP - CALL profits if price goes UP
                    elif group["option_type"] == "PUT":
                        type_display = "PUT"
                        direction_arrow = "📉"  # Chart going DOWN - PUT profits if price goes DOWN
                    else:
                        type_display = group["option_type"]
                        direction_arrow = "➡️"

                    display_data.append({
                        "Asset": group["underlying"],
                        "Type": type_display,
                        "Expiry": group["expiry"],
                        "Qty": group["position_count"],
                        "Invested ₹": group["total_invested"],
                        "Current ₹": group["total_value"],
                        "P&L ₹": group["total_pnl"],
                        "P&L %": group["total_pnl_pct"],
                        "Performance": group["pnl_arrow"],
                        "Direction": direction_arrow,
                        "_type": type_display
                    })

                df = pd.DataFrame(display_data)

                # Create styled dataframe
                def highlight_type_column(val):
                    if val == "CALL":
                        return "background-color: #4caf50; color: white; font-weight: bold"
                    elif val == "PUT":
                        return "background-color: #f44336; color: white; font-weight: bold"
                    else:
                        return "background-color: #999999; color: white"

                styled = df[["Asset", "Type", "Expiry", "Qty", "Invested ₹", "Current ₹", "P&L ₹", "P&L %", "Performance", "Direction"]].style.format({
                    "Invested ₹": "₹{:,.0f}",
                    "Current ₹": "₹{:,.0f}",
                    "P&L ₹": "₹{:,.0f}",
                    "P&L %": "{:+.2f}%"
                }).map(
                    highlight_type_column,
                    subset=["Type"]
                ).background_gradient(
                    subset=["P&L %"],
                    cmap="RdYlGn",
                    vmin=-10,
                    vmax=10
                )

                st.dataframe(styled, width='stretch', height=400)

                # Expandable detail section
                with st.expander(f"🔍 Expand to see all symbols ({len(positions_group)} groups)"):
                    for group in positions_group:
                        type_emoji = "🟢" if group["option_type"] == "CALL" else "🔴"
                        st.markdown(
                            f"**{type_emoji} {group['underlying']} {group['option_type']} - {group['expiry']}** "
                            f"({group['position_count']} contracts | P&L: {group['pnl_arrow']} {group['total_pnl_pct']:+.2f}%)"
                        )
                        for symbol in group["symbols"]:
                            st.code(symbol, language="text")

            # Display Equity positions
            st.markdown("### 📈 Equity FnO Positions")
            render_positions_table(equity_groups, "Equity FnO")

            st.markdown("<br>", unsafe_allow_html=True)

            # Display Commodity positions
            st.markdown("### 🏆 Commodity FnO Positions")
            render_positions_table(commodity_groups, "Commodity FnO")

        # ===== ANALYTICS TAB 2: P&L PERFORMANCE =====
        with analytics_tab2:
            st.markdown("#### Winners vs Losers")

            analytics_df = pd.DataFrame([
                {
                    "Symbol": pos.get("symbol", "UNKNOWN"),
                    "Type": pos.get("type", "UNKNOWN"),
                    "Invested": pos.get("entry_value", 0.0),
                    "Current": pos.get("total_value", 0.0),
                    "P&L": pos.get("unrealized_pnl", 0.0),
                    "P&L %": pos.get("unrealized_pnl_pct", 0.0)
                }
                for pos in fno_positions
                if pos.get("entry_value", 0.0) > 0 or pos.get("total_value", 0.0) > 0
            ])

            if not analytics_df.empty:
                c1, c2 = st.columns(2)

                with c1:
                    winners = len(analytics_df[analytics_df['P&L'] > 0])
                    losers = len(analytics_df[analytics_df['P&L'] < 0])
                    neutral = len(analytics_df[analytics_df['P&L'] == 0])

                    summary_data = pd.DataFrame({
                        "Status": ["Winners", "Losers", "Neutral"],
                        "Count": [winners, losers, neutral]
                    })

                    summary_data = summary_data[summary_data['Count'] > 0]

                    if not summary_data.empty:
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
                    st.markdown("#### Investment Allocation")
                    top_positions = analytics_df.nlargest(10, "Invested")

                    fig_val = px.bar(
                        top_positions,
                        x="Symbol",
                        y=["Invested", "Current"],
                        barmode="group",
                        color_discrete_sequence=["#94a3b8", "#3b82f6"],
                        hover_data={"P&L": ":.2f", "P&L %": ":.2f%"}
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
                    best_position = analytics_df.loc[analytics_df["P&L %"].idxmax()] if len(analytics_df) > 0 else None
                    if best_position is not None:
                        st.metric(
                            "Best Performer",
                            f"{best_position['Symbol']}",
                            f"{best_position['P&L %']:+.2f}%"
                        )
                    else:
                        st.metric("Best Performer", "N/A", "0%")

                with m2:
                    worst_position = analytics_df.loc[analytics_df["P&L %"].idxmin()] if len(analytics_df) > 0 else None
                    if worst_position is not None:
                        st.metric(
                            "Worst Performer",
                            f"{worst_position['Symbol']}",
                            f"{worst_position['P&L %']:+.2f}%"
                        )
                    else:
                        st.metric("Worst Performer", "N/A", "0%")

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
                        "Sentiment": ["Bullish (Calls)", "Bearish (Puts)"],
                        "Count": [portfolio_summary["total_bullish"], portfolio_summary["total_bearish"]]
                    })
                    strategy_df = strategy_df[strategy_df["Count"] > 0]

                    fig_sentiment = px.pie(
                        strategy_df,
                        values="Count",
                        names="Sentiment",
                        color_discrete_map={"Bullish (Calls)": "#22c55e", "Bearish (Puts)": "#ef4444"},
                        title="Bullish vs Bearish Positioning"
                    )
                    fig_sentiment.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
                    st.plotly_chart(fig_sentiment, width='content')
                else:
                    st.info("No clear sentiment distribution.")

            with col_strat2:
                st.markdown("**Key Insights:**")
                if portfolio_summary["total_bullish"] > portfolio_summary["total_bearish"]:
                    st.success(
                        f"""
                        ✅ **Overall Bullish Bias**
                        - {portfolio_summary['total_bullish']} bullish positions (Calls)
                        - {portfolio_summary['total_bearish']} bearish positions (Puts)
                        - You expect upside movement in most underlyings
                        """
                    )
                elif portfolio_summary["total_bearish"] > portfolio_summary["total_bullish"]:
                    st.error(
                        f"""
                        ⚠️ **Overall Bearish Bias**
                        - {portfolio_summary['total_bearish']} bearish positions (Puts)
                        - {portfolio_summary['total_bullish']} bullish positions (Calls)
                        - You expect downside movement in most underlyings
                        """
                    )
                else:
                    st.info(
                        f"""
                        ⚪ **Neutral / Balanced**
                        - {portfolio_summary['total_bullish']} bullish positions (Calls)
                        - {portfolio_summary['total_bearish']} bearish positions (Puts)
                        - Your portfolio is balanced
                        """
                    )

            # Conflicting positions analysis
            if portfolio_summary["conflicting"]:
                st.markdown("---")
                st.markdown("##### ⚖️ Conflicting Positions (Hedging / Straddles)")
                st.markdown(
                    f"""
                    You have **both calls and puts** on these underlyings:
                    {', '.join(sorted(portfolio_summary['conflicting']))}

                    **What this means:**
                    - You might be hedging (protecting against big moves in either direction)
                    - Or running a straddle (profit from any big move, loss from no movement)
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
        """
    )

    if fno_positions:
        options_only = [pos for pos in fno_positions if pos.get("type", "").upper() == "OPTION"]

        if options_only:
            greeks_df = pd.DataFrame([
                {
                    "Symbol": pos.get("symbol", "UNKNOWN"),
                    "Delta": float(pos.get("delta", 0.0)),
                    "Gamma": float(pos.get("gamma", 0.0)),
                    "Theta": float(pos.get("theta", 0.0)),
                    "Vega": float(pos.get("vega", 0.0))
                }
                for pos in options_only
            ])

            st.markdown("#### Greeks Heatmap")
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
                    "Delta": "{:.4f}",
                    "Gamma": "{:.4f}",
                    "Theta": "{:.4f}",
                    "Vega": "{:.4f}"
                }),
                width='stretch'
            )
        else:
            st.info("No options positions found. Greeks analysis is for options only.")
    else:
        st.info("No open FnO positions for Greeks analysis.")
