"""Pulse Tester market dashboards behind one always-expanded top navigation bar.

    Sectors:  Nifty 50 Sectors | Sectoral Indices | Treemap: Sectors | Treemap: Indices
    F&O:      Nifty 50 Movers | All F&O Movers | F&O Heatmap | Dhan Movers
    Insights: Breadth | Overnight vs Intraday | Rotation | Gap Fills | Gap Streaks
    MCX:      MCX Futures

Every page is a direct link (ui/navbar.py): no dropdown to open first, no
"more" menu. The Insights pages read only the stored history
(data/fno_daily_closes.csv, and data/market.db for Gap Fills).

Visualisation only - it places no orders and generates no signals.

    streamlit run pulse_dashboard.py
"""

import streamlit as st

from apps import dhan_movers_dashboard
from apps import fno_breadth_dashboard as breadth
from apps import fno_gap_fills_dashboard as gap_fills
from apps import fno_gap_streaks_dashboard as gap_streaks
from apps import fno_heatmap_dashboard, fno_movers_dashboard
from apps import fno_rotation_dashboard as rotation
from apps import fno_session_split_dashboard as session_split
from apps import mcx_futures_dashboard as mcx
from apps import sector_heatmap_dashboard as sectors
from ui.navbar import pages_by_section, render_navbar


def nav_spec():
    """Every page, grouped by section, with its navbar label. Also read by the tests."""
    # (section, [(page, link label)]). url_paths never change, so old links and bookmarks keep working.
    return [
        ("Sectors", [
            (st.Page(sectors.page_sectors, title="Nifty 50 Sectors", icon=":material/grid_view:",
                     url_path="nifty50-sectors", default=True), "Nifty 50 Sectors"),
            (st.Page(sectors.page_indices, title="NSE Sectoral Indices", icon=":material/monitoring:",
                     url_path="sectoral-indices"), "Sectoral Indices"),
            (st.Page(sectors.page_treemap_sectors, title="Treemap: Nifty 50 Sectors", icon=":material/account_tree:",
                     url_path="treemap-sectors"), "Treemap: Sectors"),
            (st.Page(sectors.page_treemap_indices, title="Treemap: NSE Indices", icon=":material/account_tree:",
                     url_path="treemap-indices"), "Treemap: Indices"),
        ]),
        ("F&O", [
            (st.Page(fno_movers_dashboard.page_nifty50, title="F&O Nifty 50", icon=":material/trending_up:",
                     url_path="fno-nifty50"), "Nifty 50 Movers"),
            (st.Page(fno_movers_dashboard.page_all, title="F&O All Stocks", icon=":material/list_alt:",
                     url_path="fno-all"), "All F&O Movers"),
            (st.Page(fno_heatmap_dashboard.main, title="F&O Heatmap", icon=":material/grid_on:",
                     url_path="fno-heatmap"), "F&O Heatmap"),
            (st.Page(dhan_movers_dashboard.page_dhan_movers, title="Dhan Movers", icon=":material/leaderboard:",
                     url_path="dhan-movers"), "Dhan Movers"),
        ]),
        ("Insights", [
            (st.Page(breadth.main, title="Market Breadth", icon=":material/stacked_line_chart:",
                     url_path="market-breadth"), "Breadth"),
            (st.Page(session_split.main, title="Overnight vs Intraday", icon=":material/contrast:",
                     url_path="overnight-intraday"), "Overnight vs Intraday"),
            (st.Page(rotation.main, title="Relative Rotation", icon=":material/360:",
                     url_path="relative-rotation"), "Rotation"),
            (st.Page(gap_fills.main, title="Gap Fills", icon=":material/vertical_align_center:",
                     url_path="gap-fills"), "Gap Fills"),
            (st.Page(gap_streaks.main, title="Gap Streaks", icon=":material/keyboard_double_arrow_up:",
                     url_path="gap-streaks"), "Gap Streaks"),
        ]),
        ("MCX", [
            (st.Page(mcx.page_mcx_futures, title="MCX Commodity Futures", icon=":material/oil_barrel:",
                     url_path="mcx-futures"), "MCX Futures"),
        ]),
    ]


def main() -> None:
    st.set_page_config(
        page_title="Pulse Tester: Market Dashboards",
        page_icon=":material/dashboard:",
        layout="wide",
    )

    nav = nav_spec()
    # Streamlit routes ("hidden" = no bar of its own); ui/navbar.py draws every link, always expanded.
    page = st.navigation(pages_by_section(nav), position="hidden")
    render_navbar(nav)
    page.run()


if __name__ == "__main__":
    main()
