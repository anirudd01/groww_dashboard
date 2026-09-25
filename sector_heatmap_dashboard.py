"""Live Nifty 50 sector heatmap - Streamlit entry point.

A market-visualisation tool only. It places no orders, produces no signals and
makes no predictions.

Run with:
    streamlit run sector_heatmap_dashboard.py
"""

import dataclasses
import logging
import os
import threading

import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover - mirrors the other dashboards
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as handle:
                for line in handle:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass

from market.config import HeatmapConfig, ORDER_ALPHABETICAL, ORDER_BY_PERFORMANCE
from market.live_feed import LiveMarketDataService
from market.market_hours import session_state
from market.providers.registry import (
    available_provider_names,
    canonical_provider_name,
    provider_label,
)
from market.models import (
    PREV_CLOSE_DAILY_CANDLE,
    SOURCE_REST,
    SOURCE_WEBSOCKET,
    STATUS_CLOSED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_INITIALISING,
    STATUS_LIVE,
    STATUS_STALE,
)
from market.sector_aggregation import (
    AGGREGATION_LABELS,
    EQUAL_WEIGHT,
    MARKET_CAP,
    aggregate_sectors,
    lagging_sector_highlights,
    leading_sector_highlights,
    rank_sectors,
    sort_sectors_alphabetically,
)
from market.index_mapping import index_by_label
from market.universe import INDEX_UNIVERSE_KEY, get_universe
from market.weights import load_weights
import pandas as pd

from ui.colours import change_background, scale_limit
from ui.sector_detail import build_constituent_table, style_constituent_table
from ui.sector_heatmap import build_sector_treemap
from ui.sector_highlights import (
    build_highlight_table,
    combined_scale_limit,
    style_highlight_table,
)
from ui.index_board import build_index_table, format_index_summary, index_tooltip
from ui.sector_tiles import render_sector_tiles

logging.basicConfig(
    level=os.getenv("PULSE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("sector_heatmap")

#: Pages. The index board is a separate page rather than a mode of the
#: first one: it has its own feed, its own universe and its own drill-down.
PAGE_SECTORS = "sectors"
PAGE_INDICES = "indices"
PAGE_LABELS = {
    PAGE_SECTORS: "Nifty 50 Sectors",
    PAGE_INDICES: "NSE Sectoral Indices",
}

VIEW_HEATMAP = "heatmap"
VIEW_SECTOR = "sector"

#: The equity board backing an index drill-down.
DEFAULT_EQUITY_UNIVERSE = "NIFTY50"

# Tiles are real Streamlit buttons and can be clicked; the Plotly treemap
# cannot report clicks back to Streamlit (see ui/sector_tiles.py).
STYLE_TILES = "tiles"
STYLE_TREEMAP = "treemap"

#: Sidebar provider choice meaning "the configured preference order, with
#: failover". Any other value pins the boards to that one broker.
PROVIDER_AUTO = "auto"


# ---------------------------------------------------------------------------
# Service bootstrap
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _service_registry():
    """``{(universe_key, provider_choice): service}`` plus the lock guarding it.

    Held in st.cache_resource so the background threads and their websockets
    outlive Streamlit's rerun cycle - navigating between views never
    reconnects a feed.
    """
    return {}, threading.Lock()


def get_service(universe_key: str, provider_choice: str = PROVIDER_AUTO) -> LiveMarketDataService:
    """One live-feed service per universe for the chosen provider.

    Switching provider stops the board's previous service before starting
    the new one: brokers cap concurrent sockets (INDmoney at 3, Dhan at 5),
    and a feed nobody is looking at would otherwise hold one of them open.
    The registry is process-wide, so the switch applies to every open tab.
    """
    services, lock = _service_registry()
    key = (universe_key, provider_choice)
    with lock:
        for other in [k for k in services if k[0] == universe_key and k != key]:
            logger.info("Provider switched for %s - stopping the %s feed", universe_key, other[1])
            services.pop(other).stop()
        service = services.get(key)
        if service is None:
            config = HeatmapConfig.from_env()
            if provider_choice != PROVIDER_AUTO:
                # Pinned: exactly this broker, no failover, so a comparison
                # between brokers never quietly shows a third one's numbers.
                config = dataclasses.replace(config, providers=(provider_choice,))
            service = LiveMarketDataService(
                universe=get_universe(universe_key), config=config
            ).start()
            services[key] = service
        return service


def provider_options():
    """Sidebar choices: Auto first, then every implemented broker."""
    return [PROVIDER_AUTO] + available_provider_names()


def provider_option_label(choice: str, config: HeatmapConfig) -> str:
    if choice == PROVIDER_AUTO:
        chain = " → ".join(provider_label(name) for name in config.providers)
        return f"Auto ({chain})"
    return provider_label(choice)


def init_session_state() -> None:
    st.session_state.setdefault("page", PAGE_SECTORS)
    st.session_state.setdefault("view", VIEW_HEATMAP)
    st.session_state.setdefault("selected_sector", None)
    st.session_state.setdefault("index_view", VIEW_HEATMAP)
    st.session_state.setdefault("selected_index", None)
    # Bumped on "back", which gives the treemap a fresh widget key so a stale
    # click does not immediately bounce the user back into the detail view.
    st.session_state.setdefault("heatmap_epoch", 0)


def go_to_sector(sector: str) -> None:
    st.session_state.view = VIEW_SECTOR
    st.session_state.selected_sector = sector


def go_to_heatmap() -> None:
    st.session_state.view = VIEW_HEATMAP
    st.session_state.selected_sector = None
    st.session_state.heatmap_epoch += 1


def go_to_index(label: str) -> None:
    st.session_state.index_view = VIEW_SECTOR
    st.session_state.selected_index = label


def go_to_index_board() -> None:
    st.session_state.index_view = VIEW_HEATMAP
    st.session_state.selected_index = None
    st.session_state.heatmap_epoch += 1


# ---------------------------------------------------------------------------
# Status indicator
# ---------------------------------------------------------------------------
_STATUS_COLOURS = {
    STATUS_LIVE: "#1a9850",
    STATUS_STALE: "#e08214",
    STATUS_DISCONNECTED: "#b2182b",
    STATUS_ERROR: "#b2182b",
    STATUS_CLOSED: "#7f7f7f",
    STATUS_INITIALISING: "#7f7f7f",
}


def status_label(status) -> str:
    """Human-readable status that never implies data is fresher than it is."""
    state = status.state
    age = status.seconds_since_tick

    if state == STATUS_ERROR:
        return "ERROR"
    if state == STATUS_INITIALISING:
        return "CONNECTING"
    if state == STATUS_DISCONNECTED:
        return "DISCONNECTED"
    if state == STATUS_CLOSED:
        broker = f" - {status.provider}" if status.provider else ""
        return f"MARKET {session_state()}{broker}"
    if state == STATUS_STALE:
        seconds = int(age or 0)
        return f"STALE - last update {seconds}s ago"

    source = "websocket" if status.source == SOURCE_WEBSOCKET else "REST polling"
    broker = f"{status.provider} " if status.provider else ""
    return f"LIVE ({broker}{source})"


def render_status_bar(status) -> None:
    colour = _STATUS_COLOURS.get(status.state, "#7f7f7f")
    last_update = (
        status.last_tick_at.strftime("%H:%M:%S") if status.last_tick_at else "-"
    )

    left, middle, right = st.columns([3, 2, 2])
    with left:
        st.markdown(
            f"<span style='color:{colour};font-size:1.15rem;'>&#9679;</span> "
            f"<span style='font-weight:600;'>{status_label(status)}</span>",
            unsafe_allow_html=True,
        )
    with middle:
        st.markdown(
            f"<span style='color:#888;'>Last update</span> "
            f"<span style='font-weight:600;'>{last_update}</span>",
            unsafe_allow_html=True,
        )
    with right:
        broker = f" via <b>{status.provider}</b>" if status.provider else ""
        st.markdown(
            f"<span style='color:#888;'>Instruments</span> "
            f"<span style='font-weight:600;'>{status.priced_count}/"
            f"{status.requested_count}</span> priced{broker}",
            unsafe_allow_html=True,
        )

    if status.state == STATUS_ERROR:
        st.error(f"Live data unavailable: {status.detail}")
    elif status.source == SOURCE_REST:
        # The detail says whether the socket has actually failed or is merely
        # still connecting - Groww's handshake can take a minute - so the
        # banner itself only states the fact that these are not socket ticks.
        st.warning(
            "Prices below are REST snapshots refreshed every few seconds, not "
            f"the live websocket. {status.detail}",
            icon=":material/warning:",
        )
    elif status.state == STATUS_STALE:
        st.warning("No tick received recently - the values below are not current.")

    if status.previous_close_source == PREV_CLOSE_DAILY_CANDLE:
        st.caption(
            "Outside market hours the broker's OHLC endpoint reports *today's* "
            "close, so percentages here are measured against the previous "
            "session's close taken from daily candles instead."
        )
    elif (
        not status.market_open
        and status.previous_close_source == ""
        and status.missing_previous_close
    ):
        st.warning(
            "No previous close could be resolved outside market hours, so no "
            "percentage change can be shown. Prices below are last known "
            "values only.",
            icon=":material/warning:",
        )

    problems = []
    if status.unresolved_symbols:
        problems.append(
            f"{len(status.unresolved_symbols)} symbol(s) missing an exchange token: "
            + ", ".join(status.unresolved_symbols)
        )
    if status.missing_previous_close:
        problems.append(
            f"{len(status.missing_previous_close)} symbol(s) missing a previous close: "
            + ", ".join(status.missing_previous_close)
        )
    if problems:
        with st.expander(f"Data gaps ({len(problems)})", expanded=False):
            for problem in problems:
                st.caption(problem)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_weights(path: str):
    """Load the weights file once per process.

    Cached because it is a static file read whose result must not change
    mid-session: two refreshes of the same screen have to agree.
    """
    return load_weights(path)


def render_breadth_summary(sectors) -> None:
    """Market-wide advance/decline and day-range context.

    Every figure is derived from the same snapshot the tiles are drawn from, so
    the summary can never disagree with the board above it.
    """
    priced = [s for s in sectors if s.change_pct is not None]
    if not priced:
        return

    advancing = sum(s.positive_count for s in sectors)
    declining = sum(s.negative_count for s in sectors)
    unchanged = sum(s.unchanged_count for s in sectors)
    total = advancing + declining + unchanged

    up_sectors = sum(1 for s in priced if s.change_pct > 0)
    down_sectors = sum(1 for s in priced if s.change_pct < 0)

    ranged = [s for s in sectors if s.avg_range_position_pct is not None]
    range_count = sum(s.range_count for s in sectors)

    columns = st.columns(4 if ranged else 3)
    columns[0].metric(
        "Stocks advancing",
        f"{advancing}/{total}" if total else "-",
        help="Constituents up on the previous close, out of those with a live price.",
    )
    columns[1].metric(
        "Stocks declining",
        f"{declining}/{total}" if total else "-",
        help="Constituents down on the previous close.",
    )
    columns[2].metric(
        "Sectors up / down",
        f"{up_sectors} / {down_sectors}",
        help="Sectors with a positive vs negative aggregate change.",
    )
    if ranged:
        mean_position = sum(
            s.avg_range_position_pct * s.range_count for s in ranged
        ) / max(1, sum(s.range_count for s in ranged))
        columns[3].metric(
            "Avg day-range position",
            f"{mean_position:.0f}%",
            help=(
                f"Where prices sit between the day's low (0%) and high (100%), "
                f"averaged over the {range_count} constituents whose range the "
                f"feed reports. Above 50% means most stocks are nearer their high."
            ),
        )


def render_highlight_tables(snapshot, sectors, config) -> None:
    """The two tables under the heatmap: leading and lagging sectors.

    One row per sector. Advancing sectors show their strongest constituent;
    declining sectors show their weakest. These describe what has moved - they
    are not recommendations.
    """
    limit = config.highlight_table_limit or None
    leaders = leading_sector_highlights(snapshot.stocks, sectors, limit=limit)
    laggards = lagging_sector_highlights(snapshot.stocks, sectors, limit=limit)

    if not leaders and not laggards:
        return

    leader_frame = build_highlight_table(leaders, stock_column="Best Stock")
    laggard_frame = build_highlight_table(laggards, stock_column="Worst Stock")

    # One scale across both tables, so -2% and +2% are equally dark.
    scale = combined_scale_limit(
        [leader_frame, laggard_frame], config.min_colour_scale_pct
    )

    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown("##### Leading sectors")
        if leaders:
            st.dataframe(
                style_highlight_table(leader_frame, limit=scale),
                width="stretch",
                hide_index=True,
            )
            st.caption("Each advancing sector with its best-performing stock.")
        else:
            st.caption("No sector is up right now.")
    with right:
        st.markdown("##### Lagging sectors")
        if laggards:
            st.dataframe(
                style_highlight_table(laggard_frame, limit=scale),
                width="stretch",
                hide_index=True,
            )
            st.caption("Each declining sector with its worst-performing stock.")
        else:
            st.caption("No sector is down right now.")


# ---------------------------------------------------------------------------
# Page 2: NSE sectoral indices
# ---------------------------------------------------------------------------
def render_index_board(service: LiveMarketDataService, order: str) -> None:
    """Tiles of real NSE index values - no aggregation of any kind.

    Each universe constituent is its own index, so grouping by label yields one
    row per index carrying that index's own change.
    """
    snapshot = service.snapshot()
    render_status_bar(snapshot.status)

    sectors = aggregate_sectors(snapshot.stocks)
    ordered = (
        sort_sectors_alphabetically(sectors)
        if order == ORDER_ALPHABETICAL
        else rank_sectors(sectors)
    )
    if not ordered:
        st.info("Waiting for the first index snapshot ...")
        return

    clicked = render_sector_tiles(
        ordered,
        columns=service.config.heatmap_columns,
        min_colour_scale_pct=service.config.min_colour_scale_pct,
        tooltip=index_tooltip,
    )
    st.caption(
        "Each tile is a real NSE index measured against its own previous "
        "close - nothing here is averaged from Nifty 50 members, so these "
        "numbers can differ from the Nifty 50 Sectors board."
    )
    if clicked:
        go_to_index(clicked)
        st.rerun(scope="app")

    st.divider()
    st.markdown("##### All indices")
    st.dataframe(
        style_index_table(build_index_table(snapshot.stocks), service.config),
        width="stretch",
        hide_index=True,
    )


def style_index_table(frame, config):
    """Format the index table and colour-grade its Change % column."""
    limit = scale_limit(list(frame["Change %"]), config.min_colour_scale_pct)
    return frame.style.format(
        {
            "LTP": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
            "Previous Close": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
            "Open": lambda v: "-" if pd.isna(v) else f"{v:,.2f}",
            "Change %": lambda v: "-" if pd.isna(v) else f"{v:+.2f}%",
        }
    ).map(
        lambda v: change_background(None if pd.isna(v) else float(v), limit),
        subset=["Change %"],
    )


def render_index_detail(index_service: LiveMarketDataService, label: str) -> None:
    """Drill-down for one index tile.

    Shows the **Nifty 50 members of the matching sector**, which is emphatically
    not the index's real constituent list - neither broker publishes that. The
    caption says so, because a table headed "Nifty Auto" that actually lists six
    Nifty 50 car makers would otherwise be read as the index's contents.
    """
    snapshot = index_service.snapshot()
    render_status_bar(snapshot.status)

    definition = index_by_label().get(label)
    index_stock = next((s for s in snapshot.stocks if s.sector == label), None)

    st.markdown(f"### {label}")
    st.markdown(format_index_summary(index_stock))

    if definition is None:
        st.warning(f"{label} is not a configured index.")
        return

    if definition.sector is None:
        if definition.is_benchmark:
            st.info(
                f"{label} is a broad market benchmark, not a sector. It has no "
                "constituent breakdown on this board."
            )
        else:
            st.info(
                f"No Nifty 50 constituent is classified under {label}'s sector, "
                "so there is nothing to break down here. The index value above "
                "is live and correct."
            )
        return

    equity_snapshot = get_service(
        get_universe(DEFAULT_EQUITY_UNIVERSE).key,
        st.session_state.get("provider_choice", PROVIDER_AUTO),
    ).snapshot()
    members = equity_snapshot.for_sector(definition.sector)

    st.markdown(f"##### Nifty 50 members classified as {definition.sector}")
    st.caption(
        f"These are the **{len(members)} Nifty 50 constituents** we classify as "
        f"{definition.sector} - **not** the real constituent list of {label}, "
        "which is wider and is not published by either broker. The two move "
        "differently, which is exactly why both boards exist."
    )

    if not members:
        st.info("No constituents mapped to this sector.")
        return

    st.dataframe(
        style_constituent_table(
            build_constituent_table(members),
            min_colour_scale_pct=index_service.config.min_colour_scale_pct,
        ),
        width="stretch",
        hide_index=True,
    )


def render_heatmap_view(
    service: LiveMarketDataService, order: str, style: str, method: str
) -> None:
    snapshot = service.snapshot()
    render_status_bar(snapshot.status)

    weight_set = get_weights(service.config.weights_path)
    if method == MARKET_CAP and not weight_set.is_usable:
        # Never present an unweighted number as weighted.
        st.warning(
            f"Market-cap weighting is unavailable, showing equal weighted. "
            f"{weight_set.error}"
        )
        method = EQUAL_WEIGHT

    sectors = aggregate_sectors(
        snapshot.stocks, method=method, weights=weight_set.weights
    )
    if order == ORDER_ALPHABETICAL:
        ordered = sort_sectors_alphabetically(sectors)
    else:
        ordered = rank_sectors(sectors)

    if not ordered:
        st.info("Waiting for the first market snapshot ...")
        return

    if style == STYLE_TREEMAP:
        # Display only: Plotly treemaps emit plotly_treemapclick, which
        # Streamlit does not listen for, so tiles here cannot be clicked.
        st.plotly_chart(
            build_sector_treemap(
                ordered, min_colour_scale_pct=service.config.min_colour_scale_pct
            ),
            width="stretch",
        )
        st.caption(
            "Treemap view is display-only - Streamlit cannot receive treemap "
            "clicks. Use the selector below, or switch to Tiles to click through."
        )
        names = [s.sector for s in sorted(ordered, key=lambda s: s.sector)]
        picker, button = st.columns([4, 1])
        with picker:
            choice = st.selectbox(
                "Sector", names, index=None, placeholder="Select a sector ...",
                label_visibility="collapsed", key="sector_picker",
            )
        with button:
            if st.button("View constituents", width="stretch") and choice:
                go_to_sector(choice)
                st.rerun(scope="app")

        st.divider()
        render_breadth_summary(ordered)
        if service.config.show_highlight_tables:
            st.divider()
            render_highlight_tables(snapshot, ordered, service.config)
        return

    clicked = render_sector_tiles(
        ordered,
        columns=service.config.heatmap_columns,
        min_colour_scale_pct=service.config.min_colour_scale_pct,
    )
    st.caption(
        "Tile colour = sector percentage change; darker means a bigger move. "
        "Tile size is constant and carries no meaning. Click a tile to see its "
        "constituents."
    )
    if clicked:
        go_to_sector(clicked)
        st.rerun(scope="app")

    st.divider()
    render_breadth_summary(ordered)

    if service.config.show_highlight_tables:
        st.divider()
        render_highlight_tables(snapshot, ordered, service.config)


def render_sector_view(service: LiveMarketDataService, sector: str) -> None:
    snapshot = service.snapshot()
    render_status_bar(snapshot.status)

    members = snapshot.for_sector(sector)
    if not members:
        st.warning(f"No constituents configured for {sector}.")
        return

    aggregated = aggregate_sectors(members)
    summary = aggregated[0]

    change = (
        "no data" if summary.change_pct is None else f"{summary.change_pct:+.2f}%"
    )
    st.markdown(f"### {sector} &nbsp; `{change}`")
    st.caption(
        f"Equal-weighted average of {summary.priced_count} of "
        f"{summary.constituent_count} constituents &nbsp;|&nbsp; "
        f"{summary.positive_count} advancing, {summary.negative_count} declining"
    )

    st.dataframe(
        style_constituent_table(
            build_constituent_table(members),
            min_colour_scale_pct=service.config.min_colour_scale_pct,
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Sorted by live percentage change, highest first. Shade intensity "
        "tracks the size of the move."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Pulse Tester: Sector Heatmap",
        page_icon=":material/dashboard:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_session_state()

    config = HeatmapConfig.from_env()
    try:
        universe = get_universe(config.universe_key)
    except (KeyError, ValueError) as e:
        st.error(str(e))
        st.stop()

    heading = st.empty()

    with st.sidebar:
        st.markdown("### Board")
        page = st.radio(
            "Board",
            options=[PAGE_SECTORS, PAGE_INDICES],
            format_func=lambda v: PAGE_LABELS[v],
            index=0 if st.session_state.page == PAGE_SECTORS else 1,
            key="page",
            label_visibility="collapsed",
            help=(
                "Nifty 50 Sectors aggregates the 50 constituents we track. "
                "NSE Sectoral Indices shows the real index values, whose "
                "constituent lists are wider."
            ),
        )

        st.markdown("### Data provider")
        options = provider_options()
        default_choice = canonical_provider_name(os.getenv("PULSE_HEATMAP_PROVIDER", ""))
        if st.session_state.get("provider_choice") not in options:
            st.session_state.provider_choice = (
                default_choice if default_choice in options else PROVIDER_AUTO
            )
        provider_choice = st.radio(
            "Data provider",
            options=options,
            format_func=lambda v: provider_option_label(v, config),
            key="provider_choice",
            label_visibility="collapsed",
            help=(
                "Auto uses the first broker in PULSE_MARKET_PROVIDERS that "
                "works and fails over to the next. Picking one broker uses "
                "only that broker, so two brokers can be compared honestly."
            ),
        )
        st.caption(
            "Switching reconnects the board's feed. It applies to every open tab."
        )

        st.markdown("### Display")
        order = st.radio(
            "Sector tile order",
            options=[ORDER_BY_PERFORMANCE, ORDER_ALPHABETICAL],
            format_func=lambda v: (
                "Strongest first (tiles move)"
                if v == ORDER_BY_PERFORMANCE
                else "Alphabetical (tiles stay put)"
            ),
            index=0 if config.sector_order == ORDER_BY_PERFORMANCE else 1,
            key="sector_order",
        )
        st.caption(
            "Colour and percentages update every second in both modes; only "
            "the tile positions differ."
        )

        st.markdown("### Sector maths")
        weight_set = get_weights(config.weights_path)
        method = st.radio(
            "Sector % is",
            options=[EQUAL_WEIGHT, MARKET_CAP],
            format_func=lambda v: AGGREGATION_LABELS[v],
            index=0 if config.aggregation_method == EQUAL_WEIGHT else 1,
            key="aggregation_method",
            help=(
                "Equal weighted: the average constituent's move. "
                "Market-cap weighted: the sector's larger names count for more."
            ),
        )
        if method == MARKET_CAP:
            if weight_set.is_usable:
                st.caption(weight_set.describe())
                if weight_set.is_stale:
                    st.caption(
                        ":warning: Weights are over "
                        f"{int(weight_set.age_days)} days old. Re-run "
                        "scripts/fetch_index_weights.py."
                    )
            else:
                st.caption(f":warning: {weight_set.error}")

        style = st.radio(
            "Heatmap style",
            options=[STYLE_TILES, STYLE_TREEMAP],
            format_func=lambda v: (
                "Tiles (clickable)" if v == STYLE_TILES else "Treemap (display only)"
            ),
            index=0,
            key="heatmap_style",
        )

    # Only the active board's feed is started, so opening the dashboard on the
    # sector page never connects a second websocket you are not looking at.
    active_key = INDEX_UNIVERSE_KEY if page == PAGE_INDICES else universe.key
    try:
        service = get_service(active_key, provider_choice)
    except Exception as e:
        st.error(f"Could not start the live market data service: {e}")
        st.stop()

    heading.markdown(
        f"## {'NSE Sectoral Indices' if page == PAGE_INDICES else universe.label + ' Sector Heatmap'}"
    )

    refresh = f"{max(0.5, service.config.ui_refresh_seconds)}s"

    if page == PAGE_INDICES:
        if st.session_state.index_view == VIEW_SECTOR and st.session_state.selected_index:
            if st.button(":material/arrow_back: Back to Index Heatmap"):
                go_to_index_board()
                st.rerun()

            @st.fragment(run_every=refresh)
            def _index_detail_fragment():
                render_index_detail(service, st.session_state.selected_index)

            _index_detail_fragment()
        else:

            @st.fragment(run_every=refresh)
            def _index_board_fragment():
                render_index_board(service, order)

            _index_board_fragment()
        return

    if st.session_state.view == VIEW_SECTOR and st.session_state.selected_sector:
        if st.button(":material/arrow_back: Back to Sector Heatmap"):
            go_to_heatmap()
            st.rerun()

        @st.fragment(run_every=refresh)
        def _sector_fragment():
            render_sector_view(service, st.session_state.selected_sector)

        _sector_fragment()
    else:

        @st.fragment(run_every=refresh)
        def _heatmap_fragment():
            render_heatmap_view(service, order, style, method)

        _heatmap_fragment()


if __name__ == "__main__":
    main()
