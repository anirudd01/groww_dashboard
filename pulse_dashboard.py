"""Pulse Tester market dashboards behind one top navigation bar.

    Nifty 50 Sectors | NSE Sectoral Indices | F&O Nifty 50 | F&O All Stocks
    | Treemap: Nifty 50 Sectors | Treemap: NSE Indices

Visualisation only - it places no orders and generates no signals.

    streamlit run pulse_dashboard.py
"""

import streamlit as st

import fno_movers_dashboard
import sector_heatmap_dashboard as sectors


def main() -> None:
    st.set_page_config(
        page_title="Pulse Tester: Market Dashboards",
        page_icon=":material/dashboard:",
        layout="wide",
    )

    pages = [
        st.Page(sectors.page_sectors, title="Nifty 50 Sectors",
                icon=":material/grid_view:", url_path="nifty50-sectors", default=True),
        st.Page(sectors.page_indices, title="NSE Sectoral Indices",
                icon=":material/monitoring:", url_path="sectoral-indices"),
        st.Page(fno_movers_dashboard.page_nifty50, title="F&O Nifty 50",
                icon=":material/trending_up:", url_path="fno-nifty50"),
        st.Page(fno_movers_dashboard.page_all, title="F&O All Stocks",
                icon=":material/list_alt:", url_path="fno-all"),
        st.Page(sectors.page_treemap_sectors, title="Treemap: Nifty 50 Sectors",
                icon=":material/account_tree:", url_path="treemap-sectors"),
        st.Page(sectors.page_treemap_indices, title="Treemap: NSE Indices",
                icon=":material/account_tree:", url_path="treemap-indices"),
    ]
    st.navigation(pages, position="top").run()


if __name__ == "__main__":
    main()
