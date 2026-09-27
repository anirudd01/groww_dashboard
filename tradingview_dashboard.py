"""Market pulse - TradingView widgets for crude, natural gas, INR and Indian markets.

Two views:

* **Ticker tags** - one compact pill per instrument, grouped by category;
  hover a pill for its intraday chart.
* **Charts & news** - a Mini Chart per instrument, with TradingView's Top
  Stories feed alongside.

The app makes no network calls and needs no credentials: every widget is
TradingView's own script, loaded by the browser, fetching its data from
TradingView. What each widget can and cannot show - notably that NSE, MCX and
GIFT Nifty are not licensed for widgets - is in docs/TRADINGVIEW_WIDGETS.md.

Visualisation only - it places no orders and generates no signals.

    streamlit run tradingview_dashboard.py --server.port 8504
"""

import streamlit as st

from market.tradingview_symbols import CATEGORIES, TIME_FRAMES, symbol_page_url
from ui.tradingview import (
    CHART_TYPES,
    NEWS_MARKETS,
    TICKER_TAG_SIZES,
    chart_grid_height,
    mini_charts_page,
    ticker_sections_height,
    ticker_sections_page,
    top_stories_page,
)

CHART_COLUMNS = 3
NEWS_HEIGHT = 1150

VIEW_TAGS = "Ticker tags"
VIEW_CHARTS = "Charts & news"

st.set_page_config(page_title="Market pulse", page_icon=":material/monitoring:", layout="wide")

# -- controls ------------------------------------------------------------------

with st.sidebar:
    st.header("Settings")
    tag_size = st.segmented_control(
        "Ticker tag size", TICKER_TAG_SIZES, default="large", required=True, key="tag_size",
        format_func=str.capitalize,
    )
    time_frame = st.selectbox(
        "Chart range", list(TIME_FRAMES), index=0, format_func=TIME_FRAMES.get, key="time_frame",
        help="BSE data is end of day, so the Indian-market charts never go below 3 months.",
    )
    chart_type = st.segmented_control(
        "Chart type", CHART_TYPES, default="Area", required=True, key="chart_type",
    )
    show_time_scale = st.toggle("Show time axis", value=True, key="show_time_scale")
    st.caption(
        "Data streams from TradingView straight to your browser: forex and CFDs in real "
        "time, BSE end of day. The app itself makes no market-data calls."
    )

# Only a fallback: each widget page reads the real theme in the browser, because
# st.context.theme can be wrong on first load (see ui/tradingview.py).
theme = st.context.theme.type or "light"

st.title("Market pulse")
view = st.segmented_control(
    "View", [VIEW_TAGS, VIEW_CHARTS], default=VIEW_TAGS, required=True,
    key="view", bind="query-params", label_visibility="collapsed",
)

# -- views ---------------------------------------------------------------------

if view == VIEW_TAGS:
    st.iframe(
        ticker_sections_page(CATEGORIES, fallback_theme=theme, size=tag_size),
        height=ticker_sections_height(CATEGORIES, size=tag_size),
    )
else:
    row_height = 200 if show_time_scale else 170
    charts_col, news_col = st.columns([3, 1.25], gap="medium")

    with charts_col:
        for category in CATEGORIES:
            st.subheader(f"{category.icon} {category.title}")
            if category.caption:
                st.caption(category.caption)
            st.iframe(
                mini_charts_page(
                    category.instruments,
                    fallback_theme=theme,
                    time_frame=time_frame,
                    chart_type=chart_type,
                    show_time_scale=show_time_scale,
                    columns=CHART_COLUMNS,
                    row_height=row_height,
                ),
                height=chart_grid_height(
                    len(category.instruments), columns=CHART_COLUMNS, row_height=row_height
                ),
            )
            if category.unavailable:
                links = " · ".join(
                    f"[{u.label} :material/open_in_new:]({symbol_page_url(u.symbol)})"
                    for u in category.unavailable
                )
                st.caption(f"Only on tradingview.com: {links}")

    with news_col:
        st.subheader(":material/newspaper: Top stories")
        market = st.selectbox(
            "News feed", list(NEWS_MARKETS), format_func=NEWS_MARKETS.get, key="news_market",
            label_visibility="collapsed",
        )
        st.iframe(top_stories_page(market=market, fallback_theme=theme), height=NEWS_HEIGHT)
