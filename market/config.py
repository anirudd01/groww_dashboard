"""Configuration for the sector heatmap dashboard.

Every knob has a sensible default and can be overridden with an environment
variable (so it can live in ``.env`` alongside the Groww credentials).
No credentials are read or stored here.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Tuple

from market.providers.registry import DEFAULT_PROVIDER_ORDER
from market.sector_aggregation import EQUAL_WEIGHT, MARKET_CAP
from market.universe import DEFAULT_UNIVERSE_KEY
from market.weights import DEFAULT_WEIGHTS_PATH

# Sector tile ordering strategies (see docs/SECTOR_HEATMAP.md).
ORDER_BY_PERFORMANCE = "performance"
ORDER_ALPHABETICAL = "alphabetical"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_choice(name: str, default: str, allowed) -> str:
    """An env value restricted to a known set; anything else falls back.

    A typo in .env should not crash the dashboard, but it must not silently
    change what the numbers mean either - hence the log line.
    """
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in allowed:
        return raw
    logging.getLogger(__name__).warning(
        "Ignoring %s=%r - expected one of %s. Using %r.",
        name, raw, ", ".join(sorted(allowed)), default,
    )
    return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class HeatmapConfig:
    """Runtime settings for the live feed service and the UI."""

    # --- providers ------------------------------------------------------
    # Broker preference order. The service uses the first one that
    # authenticates and resolves instruments; the rest are fallbacks.
    # Known: dhan, indmoney, groww, kite (alias: zerodha).
    providers: Tuple[str, ...] = DEFAULT_PROVIDER_ORDER

    # --- universe -------------------------------------------------------
    universe_key: str = DEFAULT_UNIVERSE_KEY

    # --- aggregation ----------------------------------------------------
    # How a sector's percentage change is computed from its constituents.
    # "equal_weight" (default) treats every stock alike; "market_cap" weights
    # by the figures in the weights file below. Both are selectable in the UI.
    aggregation_method: str = EQUAL_WEIGHT
    # Weights are read from this file at startup and never fetched live.
    # Generate it with scripts/fetch_index_weights.py.
    weights_path: str = DEFAULT_WEIGHTS_PATH

    # --- UI -------------------------------------------------------------
    ui_refresh_seconds: float = 1.0
    sector_order: str = ORDER_BY_PERFORMANCE
    #: Tiles per row in the clickable heatmap grid.
    heatmap_columns: int = 4
    #: Show the leaders/laggards tables beneath the heatmap.
    show_highlight_tables: bool = True
    #: Cap on rows in each of those tables. 0 means "every qualifying sector".
    highlight_table_limit: int = 0
    # Colour scale saturates at +/- this many percent, so a flat day still
    # shows contrast instead of an all-grey board.
    min_colour_scale_pct: float = 0.75

    # --- live feed ------------------------------------------------------
    # How often the background worker drains the in-memory feed buffer.
    # This is local work only - it makes no network calls.
    feed_drain_seconds: float = 0.5
    # No tick for this long while the market is open => show STALE.
    stale_after_seconds: float = 10.0
    # A connected websocket that produces no tick for this long during market
    # hours is treated as gone and reconnected. It also covers a feed that
    # never delivered anything at all, since the clock starts at connect time.
    feed_silence_seconds: float = 10.0
    # Backoff before reconnecting the *same* broker after its socket dropped
    # or went quiet. Deliberately short: a dropped socket is usually back on
    # the next attempt, and the preferred broker is worth getting back fast
    # rather than conceding the board to a fallback over one hiccup.
    feed_reconnect_seconds: float = 1.0
    # How many of those quick reconnects to try before handing the socket to
    # the next broker. Covers both failure modes with one counter: a socket
    # that connects then goes silent, and one that never connects at all
    # (which has no feed to drain, so nothing else would ever notice it).
    feed_recovery_attempts: int = 2
    # Backoff once every broker has been tried and none of them works. The
    # board is on REST by then, so retrying gently beats hammering - and with
    # Groww, connection churn measurably makes the next handshake worse.
    feed_retry_seconds: float = 30.0

    # --- REST fallback --------------------------------------------------
    # Only used when the websocket cannot be established or delivers nothing.
    # One batched request covers the whole universe, so this is gentle on the
    # API - but it is NOT the live feed, and the UI labels it as such.
    rest_fallback_enabled: bool = True
    rest_poll_seconds: float = 3.0
    # The SDK defaults to no HTTP timeout; without this a throttled or stalled
    # request would hang the worker loop and freeze the dashboard.
    rest_timeout_seconds: int = 10

    # --- reference data -------------------------------------------------
    # Previous closes are refreshed at most this often (they only change
    # once per trading day; the refresh exists to pick up a new session).
    previous_close_refresh_seconds: int = 900
    api_batch_size: int = 50
    # Outside market hours the broker's OHLC "close" field reports *today's*
    # close, so starting the dashboard after 15:30 would read +0.00% on every
    # tile. When this is on, the previous close then comes from daily candles
    # instead. Turn it off to skip that lookup and accept the flat board.
    historical_previous_close: bool = True

    @classmethod
    def from_env(cls) -> "HeatmapConfig":
        order = (os.getenv("PULSE_HEATMAP_SECTOR_ORDER", "") or ORDER_BY_PERFORMANCE).strip().lower()
        if order not in (ORDER_BY_PERFORMANCE, ORDER_ALPHABETICAL):
            order = ORDER_BY_PERFORMANCE
        raw_providers = (os.getenv("PULSE_MARKET_PROVIDERS", "") or "").strip()
        providers = tuple(
            part.strip().lower() for part in raw_providers.split(",") if part.strip()
        ) or DEFAULT_PROVIDER_ORDER
        return cls(
            providers=providers,
            universe_key=os.getenv("PULSE_HEATMAP_UNIVERSE", DEFAULT_UNIVERSE_KEY),
            ui_refresh_seconds=_env_float("PULSE_HEATMAP_UI_REFRESH_SECONDS", 1.0),
            sector_order=order,
            heatmap_columns=max(1, _env_int("PULSE_HEATMAP_COLUMNS", 4)),
            aggregation_method=_env_choice(
                "PULSE_HEATMAP_AGGREGATION", EQUAL_WEIGHT, (EQUAL_WEIGHT, MARKET_CAP)
            ),
            weights_path=os.getenv("PULSE_HEATMAP_WEIGHTS_FILE", "")
            or DEFAULT_WEIGHTS_PATH,
            show_highlight_tables=_env_bool("PULSE_HEATMAP_HIGHLIGHT_TABLES", True),
            highlight_table_limit=max(0, _env_int("PULSE_HEATMAP_HIGHLIGHT_LIMIT", 0)),
            min_colour_scale_pct=_env_float("PULSE_HEATMAP_MIN_COLOUR_SCALE_PCT", 0.75),
            feed_drain_seconds=_env_float("PULSE_HEATMAP_FEED_DRAIN_SECONDS", 0.5),
            stale_after_seconds=_env_float("PULSE_HEATMAP_STALE_AFTER_SECONDS", 10.0),
            feed_silence_seconds=_env_float("PULSE_HEATMAP_FEED_SILENCE_SECONDS", 10.0),
            feed_reconnect_seconds=_env_float("PULSE_HEATMAP_FEED_RECONNECT_SECONDS", 1.0),
            feed_recovery_attempts=max(
                1, _env_int("PULSE_HEATMAP_FEED_RECOVERY_ATTEMPTS", 2)
            ),
            feed_retry_seconds=_env_float("PULSE_HEATMAP_FEED_RETRY_SECONDS", 30.0),
            rest_fallback_enabled=_env_bool("PULSE_HEATMAP_REST_FALLBACK", True),
            rest_poll_seconds=_env_float("PULSE_HEATMAP_REST_POLL_SECONDS", 3.0),
            rest_timeout_seconds=_env_int("PULSE_HEATMAP_REST_TIMEOUT_SECONDS", 10),
            previous_close_refresh_seconds=_env_int(
                "PULSE_HEATMAP_PREV_CLOSE_REFRESH_SECONDS", 900
            ),
            api_batch_size=_env_int("PULSE_HEATMAP_API_BATCH_SIZE", 50),
            historical_previous_close=_env_bool(
                "PULSE_HEATMAP_HISTORICAL_PREV_CLOSE", True
            ),
        )
