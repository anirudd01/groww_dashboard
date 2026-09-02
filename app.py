import os
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

from groww_client import GrowwClient, format_inr, format_inr_full

# ----------------- STREAMLIT CONFIGURATION -----------------
st.set_page_config(
    page_title="Pulse Tester: Portfolio & MTF Decoupler",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CUSTOM CSS FOR RESPONSIVE FULL-WIDTH UI & BOXES -----------------
st.markdown("""
<style>
    /* Full width layout - remove narrow center wrapping and excessive padding */
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 98% !important;
    }

    /* Metric card container */
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

    /* Green Box: Incoming / Asset / Cash Holdings / Wallet (Positive) */
    .box-green {
        background-color: #f0fdf4;
        border: 1.5px solid #86efac;
        color: #14532d;
    }
    .box-green .kpi-title { color: #166534; }
    .box-green .kpi-value { color: #14532d; }
    .box-green .kpi-sub { color: #15803d; }

    /* Red Box: Outgoing / Broker Debt / Interest Costs (Liabilities) */
    .box-red {
        background-color: #fef2f2;
        border: 1.5px solid #fca5a5;
        color: #7f1d1d;
    }
    .box-red .kpi-title { color: #991b1b; }
    .box-red .kpi-value { color: #7f1d1d; }
    .box-red .kpi-sub { color: #b91c1c; }

    /* Blue / Slate Box: Neutral / Total Value / Portfolio Gross */
    .box-blue {
        background-color: #f8fafc;
        border: 1.5px solid #cbd5e1;
        color: #0f172a;
    }
    .box-blue .kpi-title { color: #334155; }
    .box-blue .kpi-value { color: #0f172a; }
    .box-blue .kpi-sub { color: #475569; }

    /* Dark theme support */
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

    /* Tabs styling */
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
    """Renders a custom styled KPI box with no truncation."""
    theme_class = f"box-{theme}"
    html = f"""
    <div class="kpi-card {theme_class}">
        <div class="kpi-title">{title}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ----------------- SIDEBAR -----------------
st.sidebar.title("📊 Pulse Tester: MTF Decoupler")
st.sidebar.caption("Separate **Actual Delivery Holdings** from **MTF Leveraged Positions**.")

mode_choice = st.sidebar.radio(
    "Data Source Mode:",
    ["Live Groww Trading API", "Demo / Mock Data (Test UI)"],
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
    
    if st.button("🔄 Refresh / Re-authenticate", width='stretch'):
        st.cache_data.clear()
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    **📌 Understanding Your Capital vs Margins:**
    - **📦 Actual Delivery Holdings:** 100% owned cash shares. Pledging them provides **Collateral Margin** to trade, but you still own the shares.
    - **⚡ MTF Positions:** Leveraged positions financed via **Groww Loan** (~16.5% p.a. interest).
    """
)

# ----------------- DATA FETCHING -----------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_portfolio_data(mock: bool):
    client = GrowwClient(mock_mode=mock)
    if not client.is_connected and not mock:
        return None, client.auth_error
    try:
        data = client.get_processed_portfolio()
        profile = client.get_user_profile()
        return {"data": data, "profile": profile, "client": client}, None
    except Exception as e:
        return None, str(e)

with st.spinner("Fetching and processing portfolio data..."):
    result, error_msg = fetch_portfolio_data(is_mock)

if error_msg:
    st.error(f"⚠️ **Authentication / API Error**: {error_msg}")
    st.info("Check your `.env` file credentials or switch to **'Demo / Mock Data'** mode in the sidebar.")
    st.stop()

processed = result["data"]
summary = processed["summary"]
profile = result["profile"]
delivery_holdings = processed["delivery_holdings"]
mtf_positions = processed["mtf_positions"]

# ----------------- TOP BAR: HEADER & WALLET CASH -----------------
col_head, col_cash = st.columns([3, 1])

with col_head:
    st.title("Pulse Tester: Portfolio & Margin Decoupler")
    if is_mock:
        st.caption("🟡 Running in **Demo Mode** with sample data. Configure `.env` to connect live account.")
    else:
        st.caption(f"🟢 Connected to Live Broker Account | Client UCC: `{profile.get('ucc', 'N/A')}`")

with col_cash:
    render_kpi_card(
        title="Account Clear Cash (Wallet)",
        value=format_inr(summary.get("clear_cash", 0.0)),
        sub=f"Full: {format_inr_full(summary.get('clear_cash', 0.0))}",
        theme="green"
    )

st.markdown("---")

# ----------------- DASHBOARD TABS -----------------
tab_overview, tab_delivery, tab_mtf, tab_simulator, tab_api = st.tabs([
    "📊 Executive Overview",
    "📦 Actual Delivery Holdings (100% Cash Owned)",
    "⚡ MTF (Pay Later) Leveraged Positions",
    "🛡️ Margin Health & MTF Conversion",
    "🔍 API Diagnostics & Raw Responses"
])

# =====================================================================
# TAB 1: EXECUTIVE OVERVIEW
# =====================================================================
with tab_overview:
    st.markdown("### 💼 Portfolio Capital & Liability Breakdown")
    st.caption(
        "Total Actual Cash Deployed = Total Pledged Stock Value + Clear Cash (your wallet cash still free to deploy)."
    )
    
    # 6 KPI Cards: Green for your own cash/assets, Red for Groww's loan/interest, Blue for totals
    k0, k1, k2, k3, k5, k6 = st.columns(6)

    with k0:
        render_kpi_card(
            title="Total Pledged Stock Value",
            value=format_inr(summary["pledged_value_gross"]),
            sub=f"Haircut: -{format_inr(summary['pledged_haircut_value'])} ({summary['pledged_haircut_pct']:.1f}%)<br>Usable: {format_inr(summary['collateral_margin_total'])}",
            theme="blue"
        )

    with k1:
        render_kpi_card(
            title="Total Actual Cash Deployed",
            value=format_inr(summary["total_actual_cash_deployed"]),
            sub=f"Full: {format_inr_full(summary['total_actual_cash_deployed'])}",
            theme="green"
        )
    
    with k2:
        render_kpi_card(
            title="Total Portfolio Value",
            value=format_inr(summary["total_portfolio_value"]),
            sub=f"Net P&L: {format_inr(summary['total_pnl'])} ({summary['total_pnl_pct']:+.2f}%)",
            theme="blue"
        )
    
    with k3:
        render_kpi_card(
            title="Total (Holding+Position)",
            value=format_inr(summary["delivery_current"]),
            sub=f"Invested: {format_inr(summary['delivery_invested'])}",
            theme="green"
        )
    
    with k5:
        render_kpi_card(
            title="Broker MTF Loan (Debt)",
            value=format_inr(summary["mtf_broker_loan"]),
            sub=f"Daily Cost: -{format_inr(summary['mtf_daily_interest'])}/day<br>Available for Margin: {format_inr(summary['collateral_available'])}",
            theme="red"
        )
    
    with k6:
        render_kpi_card(
            title="Annual Interest Drag",
            value=format_inr(summary["mtf_annual_interest"]),
            sub=f"-{format_inr(summary['mtf_monthly_interest'])} / month (@ 16.5% p.a.)",
            theme="red"
        )

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Charts Section
    c_left, c_right = st.columns(2)
    
    with c_left:
        st.markdown("#### 🥧 Capital Ownership & Margin Structure")
        
        pie_labels = [
            "Free Delivery/CNC Holdings",
            "Collateral Pledged Delivery/CNC Holdings",
            "Your Cash Used for MTF",
            "Groww Borrowed Loan (MTF Debt)"
        ]
        pie_values = [
            summary["delivery_free_value"],
            summary["delivery_pledged_value"],
            summary["mtf_your_cash_used"],
            summary["mtf_broker_loan"]
        ]
        
        if sum(pie_values) > 0:
            fig_pie = go.Figure(data=[go.Pie(
                labels=pie_labels,
                values=pie_values,
                hole=0.45,
                marker=dict(colors=["#22c55e", "#eab308", "#3b82f6", "#ef4444"]),
                textinfo="label+percent",
                insidetextorientation="radial"
            )])
            fig_pie.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                height=340,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5)
            )
            st.plotly_chart(fig_pie, width='stretch')
        else:
            st.info("No active holdings found.")

    with c_right:
        st.markdown("#### ⚖️ Return & Value Distribution")
        chart_df = pd.DataFrame([
            {
                "Category": "Delivery / CNC Holdings",
                "Invested (Own Money)": summary["delivery_invested"],
                "Current Market Value": summary["delivery_current"]
            },
            {
                "Category": "MTF Leveraged Exposure",
                "Invested (Own Money)": summary["mtf_your_cash_used"],
                "Current Market Value": summary["mtf_gross_value"]
            }
        ])
        fig_bar = px.bar(
            chart_df,
            x="Category",
            y=["Invested (Own Money)", "Current Market Value"],
            barmode="group",
            color_discrete_sequence=["#94a3b8", "#3b82f6"]
        )
        fig_bar.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            height=340,
            yaxis_title="Amount (₹)",
            legend_title=""
        )
        st.plotly_chart(fig_bar, width='stretch')

# =====================================================================
# TAB 2: ACTUAL DELIVERY HOLDINGS (100% OWNED)
# =====================================================================
with tab_delivery:
    st.subheader("📦 Actual Delivery Holdings (100% User Owned)")
    st.markdown(
        """
        These are your **actual equity shares** bought with your own cash capital. 
        - **Free Qty:** Unpledged shares freely available in your Demat account.
        - **Pledged Qty:** Your own delivery shares pledged to acquire **Collateral Margin** for MTF / F&O trading. *(You still own 100% of these shares, with zero borrowing interest on them).*
        """
    )

    del_c1, del_c2, del_c3 = st.columns(3)
    with del_c1:
        render_kpi_card(
            title="Delivery Invested Capital",
            value=format_inr(summary["delivery_invested"]),
            sub=f"Full: {format_inr_full(summary['delivery_invested'])}",
            theme="green"
        )
    with del_c2:
        render_kpi_card(
            title="Delivery Current Value",
            value=format_inr(summary["delivery_current"]),
            sub=f"Free: {format_inr(summary['delivery_free_value'])} | Pledged: {format_inr(summary['delivery_pledged_value'])}",
            theme="green"
        )
    with del_c3:
        pnl_theme = "green" if summary["delivery_pnl"] >= 0 else "red"
        render_kpi_card(
            title="Unrealized Delivery P&L",
            value=format_inr(summary["delivery_pnl"]),
            sub=f"{summary['delivery_pnl_pct']:+.2f}% Overall Return",
            theme=pnl_theme
        )

    st.markdown("### Delivery Holdings Breakdown")
    if delivery_holdings:
        df_del = pd.DataFrame(delivery_holdings)
        
        display_del_df = df_del[[
            "symbol", "total_quantity", "free_quantity", "pledged_quantity", 
            "avg_price", "ltp", "invested_value", "current_value", "unrealized_pnl", "unrealized_pnl_pct", "pledge_status"
        ]].copy()
        
        display_del_df.columns = [
            "Symbol", "Total Qty", "Free Qty", "Pledged Qty", 
            "Avg Buy (₹)", "LTP (₹)", "Invested (₹)", "Current Value (₹)", "P&L (₹)", "Return (%)", "Collateral Status"
        ]

        st.dataframe(
            display_del_df.style.format({
                "Total Qty": "{:,.0f}",
                "Free Qty": "{:,.0f}",
                "Pledged Qty": "{:,.0f}",
                "Avg Buy (₹)": "₹{:,.2f}",
                "LTP (₹)": "₹{:,.2f}",
                "Invested (₹)": "₹{:,.2f}",
                "Current Value (₹)": "₹{:,.2f}",
                "P&L (₹)": "₹{:,.2f}",
                "Return (%)": "{:+.2f}%"
            }),
            width='stretch'
        )
    else:
        st.info("No delivery holdings found in your account.")

# =====================================================================
# TAB 3: MTF (PAY LATER) LEVERAGED POSITIONS
# =====================================================================
with tab_mtf:
    st.subheader("⚡ MTF (Pay Later) Leveraged Positions")
    st.markdown(
        """
        These are your **leveraged margin positions** financed through the broker's Margin Trading Facility (Pay Later).
        The gross value / cost basis come directly from your positions; the "cash used" figure below is the broker's
        **actual reported equity margin usage**, not an assumed percentage.
        """
    )

    mtf_c1, mtf_c2, mtf_c3, mtf_c4 = st.columns(4)
    with mtf_c1:
        render_kpi_card(
            title="MTF Gross Value",
            value=format_inr(summary["mtf_gross_value"]),
            sub=f"Cost: {format_inr(summary['mtf_cost_basis'])}",
            theme="blue"
        )
    with mtf_c2:
        render_kpi_card(
            title="Your Cash Used for MTF",
            value=format_inr(summary["mtf_your_cash_used"]),
            sub="From Groww's Margin API (real, not assumed)",
            theme="green"
        )
    with mtf_c3:
        render_kpi_card(
            title="Broker MTF Loan (Debt)",
            value=format_inr(summary["mtf_broker_loan"]),
            sub=f"Full: {format_inr_full(summary['mtf_broker_loan'])}",
            theme="red"
        )
    with mtf_c4:
        render_kpi_card(
            title="Daily Interest Drag",
            value=f"{format_inr(summary['mtf_daily_interest'])}/day",
            sub=f"Annual: {format_inr(summary['mtf_annual_interest'])}/yr",
            theme="red"
        )

    st.markdown("### MTF Positions & Loan Table")
    st.caption("Per-stock 'Your Cash' / 'Broker Loan' columns are an estimated proportional split of the real account-level margin used, since the broker does not expose a per-stock MTF margin breakdown.")
    if mtf_positions:
        df_mtf = pd.DataFrame(mtf_positions)
        display_mtf = df_mtf[[
            "symbol", "mtf_quantity", "buy_price", "ltp", "total_position_value", 
            "est_your_cash_used", "est_broker_funded_loan", 
            "unrealized_pnl", "unrealized_pnl_pct", "est_daily_interest_drag", "est_annual_interest_drag"
        ]].copy()

        display_mtf.columns = [
            "Symbol", "MTF Qty", "Buy Price (₹)", "LTP (₹)", "Gross Value (₹)",
            "Est. Your Cash (₹)", "Est. Broker Loan (₹)",
            "P&L (₹)", "P&L (%)", "Est. Interest (₹/day)", "Est. Interest (₹/yr)"
        ]

        st.dataframe(
            display_mtf.style.format({
                "MTF Qty": "{:,.0f}",
                "Buy Price (₹)": "₹{:,.2f}",
                "LTP (₹)": "₹{:,.2f}",
                "Gross Value (₹)": "₹{:,.2f}",
                "Est. Your Cash (₹)": "₹{:,.2f}",
                "Est. Groww Loan (₹)": "₹{:,.2f}",
                "P&L (₹)": "₹{:,.2f}",
                "P&L (%)": "{:+.2f}%",
                "Est. Interest (₹/day)": "₹{:,.2f}",
                "Est. Interest (₹/yr)": "₹{:,.2f}"
            }),
            width='stretch'
        )
    else:
        st.info("No active MTF (Pay Later) positions detected in your account.")

# =====================================================================
# TAB 4: MARGIN HEALTH & CONVERSION SIMULATOR
# =====================================================================
with tab_simulator:
    st.subheader("🛡️ Margin Health & MTF Conversion Planner")
    st.markdown("Plan how to convert borrowed MTF positions into pure delivery and stress-test your margin buffer.")

    sim_col1, sim_col2 = st.columns(2)

    with sim_col1:
        st.markdown("#### 🔄 Convert MTF Position to Cash Delivery (CNC)")
        st.write("Pay off the broker loan on an MTF position to eliminate interest and transfer shares to pure Demat delivery.")

        if mtf_positions:
            mtf_symbols = [item["symbol"] for item in mtf_positions]
            selected_sym = st.selectbox("Select MTF Position to Convert:", mtf_symbols)
            matched_mtf = next(item for item in mtf_positions if item["symbol"] == selected_sym)

            st.markdown(f"""
            - **Stock Symbol:** `{matched_mtf['symbol']}`
            - **MTF Quantity:** `{matched_mtf['mtf_quantity']:,.0f}` shares
            - **Current Position Value:** `{format_inr(matched_mtf['total_position_value'])}`
            - **Est. Broker Loan to Repay:** **`{format_inr(matched_mtf['est_broker_funded_loan'])}`** (`{format_inr_full(matched_mtf['est_broker_funded_loan'])}`)
            - **Est. Daily Interest Saved:** `₹{matched_mtf['est_daily_interest_drag']:,.2f}/day` (`₹{matched_mtf['est_annual_interest_drag']:,.2f}/year`)
            """)

            wallet_cash = summary.get("clear_cash", 0.0)
            required_cash = matched_mtf["est_broker_funded_loan"]

            if wallet_cash >= required_cash:
                st.success(f"✅ Your wallet clear cash ({format_inr(wallet_cash)}) is sufficient to convert this position!")
            else:
                deficit = required_cash - wallet_cash
                st.warning(f"⚠️ You need an additional **{format_inr(deficit)}** ({format_inr_full(deficit)}) in your wallet to convert this MTF position.")
        else:
            st.info("No active MTF positions found to convert.")

    with sim_col2:
        st.markdown("#### 📉 Market Stress Test (Margin Safety)")
        st.write("Simulate the effect of a market correction on your MTF positions and total equity.")

        market_drop = st.slider("Simulate Market Drop (%)", min_value=-30, max_value=0, value=-10, step=1)
        factor = (100.0 + market_drop) / 100.0

        sim_mtf_val = summary["mtf_gross_value"] * factor
        sim_mtf_loss = sim_mtf_val - summary["mtf_gross_value"]
        sim_user_net_worth = summary["delivery_current"] * factor + (sim_mtf_val - summary["mtf_broker_loan"])

        st.markdown(f"""
        - **Simulated Market Drop:** `{market_drop}%`
        - **Simulated MTF Gross Value:** `{format_inr(sim_mtf_val)}`
        - **Unrealized MTF Drop:** `<span style='color: #ef4444;'>{format_inr(sim_mtf_loss)}</span>`
        - **Broker Loan Obligation (Fixed):** `{format_inr(summary['mtf_broker_loan'])}`
        - **Simulated Net Portfolio Value:** `{format_inr(sim_user_net_worth)}`
        """, unsafe_allow_html=True)

# =====================================================================
# TAB 5: API DIAGNOSTICS & RAW RESPONSES
# =====================================================================
with tab_api:
    st.subheader("🔍 API Diagnostics & Raw Response Inspector")
    st.markdown("Inspect the exact JSON response returned by every Trading API this dashboard uses.")

    client_diag = GrowwClient(mock_mode=is_mock)

    # Every API endpoint the dashboard calls, mapped to its underlying growwapi SDK method
    API_ENDPOINTS = [
        ("get_user_profile()", "groww.get_user_profile()", client_diag.get_user_profile, ()),
        ("get_available_margin_details()", "groww.get_available_margin_details()", client_diag.get_margins, ()),
        ("get_holdings_for_user()", "groww.get_holdings_for_user()", client_diag.get_holdings, ()),
        ("get_positions_for_user()", "groww.get_positions_for_user(segment=SEGMENT_CASH)", client_diag.get_positions, ()),
        ("get_ltp() (Sample Quotes)", "groww.get_ltp(segment=SEGMENT_CASH, exchange_trading_symbols=...)", client_diag.get_ltp, (["RELIANCE", "INFY", "TCS", "HDFCBANK", "SBIN"],)),
    ]

    st.markdown("### 📡 Fetch All APIs Used by This Dashboard")
    if st.button("🚀 Fetch All API Responses", type="primary", width='stretch'):
        results = {}
        for label, sdk_call, fn, args in API_ENDPOINTS:
            try:
                results[label] = {"status": "success", "data": fn(*args), "sdk_call": sdk_call}
            except Exception as e:
                results[label] = {"status": "error", "data": str(e), "sdk_call": sdk_call}
        st.session_state["all_api_results"] = results

    if "all_api_results" in st.session_state:
        for label, result in st.session_state["all_api_results"].items():
            icon = "✅" if result["status"] == "success" else "❌"
            with st.expander(f"{icon} {label}  —  `{result['sdk_call']}`", expanded=False):
                if result["status"] == "success":
                    st.json(result["data"])
                else:
                    st.error(result["data"])

    st.markdown("---")
    st.markdown("### 🎯 Test a Single Endpoint")
    diag_c1, diag_c2 = st.columns([1, 2])
    with diag_c1:
        call_choice = st.selectbox(
            "Select Groww Endpoint:",
            [label for label, _, _, _ in API_ENDPOINTS]
        )
        if st.button("🚀 Fetch Raw Response", width='stretch'):
            try:
                _, sdk_call, fn, args = next(e for e in API_ENDPOINTS if e[0] == call_choice)
                raw_data = fn(*args)
                st.session_state["raw_api_view"] = raw_data
            except Exception as e:
                st.session_state["raw_api_view"] = {"error": str(e)}

    with diag_c2:
        if "raw_api_view" in st.session_state:
            st.json(st.session_state["raw_api_view"])
        else:
            st.info("Click 'Fetch Raw Response' to view endpoint payload.")

