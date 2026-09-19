"""Background live-market-data service for the sector heatmap.

Architecture
------------
    provider websocket  ->  LiveMarketDataService  ->  MarketSnapshot  ->  UI

The service owns exactly one live connection on a daemon thread, entirely
outside Streamlit's rerun lifecycle. Streamlit only ever calls ``snapshot()``,
which returns a thread-safe copy of the current state.

Brokers sit behind ``market.providers``: the service asks for providers in
configured preference order (default Dhan, then Groww) and uses the first one
that authenticates and resolves instruments. If that provider's websocket
cannot deliver, the service fails over to the next provider.

Price sources, in order of preference:
  1. The provider's websocket - continuous ticks (primary).
  2. Batched REST snapshots - a clearly-labelled fallback. The UI always shows
     which source is live; polled data is never presented as socket-live.

Reference data (previous close, instrument ids) always comes from REST and is
fetched once at startup, never per tick.
"""

import logging
import threading
import time
from copy import copy
from datetime import datetime
from typing import Dict, List, Optional

from market.config import HeatmapConfig
from market.market_hours import (
    SESSION_OPEN,
    SESSION_PRE_MARKET,
    is_market_open,
    session_state,
)
from market.models import (
    PREV_CLOSE_DAILY_CANDLE,
    PREV_CLOSE_OHLC,
    SOURCE_NONE,
    SOURCE_REST,
    SOURCE_WEBSOCKET,
    STATUS_CLOSED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_INITIALISING,
    STATUS_LIVE,
    STATUS_STALE,
    FeedStatus,
    MarketSnapshot,
    StockMarketData,
)
from market.providers.base import InstrumentRef, MarketDataProvider
from market.providers.registry import build_providers
from market.universe import Universe

logger = logging.getLogger(__name__)


class LiveMarketDataService:
    """Maintains live market state for one universe on a background thread."""

    def __init__(
        self,
        universe: Universe,
        config: Optional[HeatmapConfig] = None,
        providers: Optional[List[MarketDataProvider]] = None,
    ):
        self.universe = universe
        self.config = config or HeatmapConfig()
        self._providers = providers

        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

        # Shared state - only ever touched while holding self._lock.
        self._stocks: Dict[str, StockMarketData] = {
            c.symbol: StockMarketData(
                symbol=c.symbol,
                sector=c.sector,
                exchange=c.exchange,
                segment=c.segment,
            )
            for c in universe.constituents
        }
        self._status = FeedStatus(
            state=STATUS_INITIALISING,
            requested_count=len(universe),
        )

        self._provider: Optional[MarketDataProvider] = None
        self._refs: List[InstrumentRef] = []
        self._feed = None
        self._first_tick_logged: set = set()
        self._prev_close_fetched_at: float = 0.0
        # Whether the active provider implements REST day bars at all. Checked
        # once on activation so the fallback loop does not fire a doomed extra
        # request every poll against a broker that has no such endpoint.
        self._day_bars_supported: bool = False
        # True only while the websocket is actually delivering prices. The REST
        # fallback runs whenever this is False, so a websocket that connects but
        # stays silent never leaves the dashboard without data.
        self._ws_delivering = False
        # Connection attempts run on their own thread: a provider's connect may
        # block for minutes (Groww's does), and that must never stall the UI.
        self._connect_thread: Optional[threading.Thread] = None
        self._connect_result = None
        self._next_connect_attempt = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "LiveMarketDataService":
        """Start the background worker. Idempotent and safe across reruns."""
        with self._lock:
            if self._started and self._thread and self._thread.is_alive():
                return self
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"live-feed-{self.universe.key}",
                daemon=True,
            )
            self._started = True
            self._thread.start()
            logger.info(
                "Live market data service started for %s (%d constituents)",
                self.universe.label,
                len(self.universe),
            )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._started = False
        logger.info("Live market data service stopped")

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Public read API (called from Streamlit)
    # ------------------------------------------------------------------
    def snapshot(self) -> MarketSnapshot:
        """Thread-safe point-in-time copy of the whole market state."""
        with self._lock:
            stocks = [copy(s) for s in self._stocks.values()]
            status = copy(self._status)
            status.missing_previous_close = list(status.missing_previous_close)
            status.unresolved_symbols = list(status.unresolved_symbols)
            status.priced_count = sum(1 for s in stocks if s.has_live_price)
        status.state = self._derive_state(status)
        return MarketSnapshot(stocks=stocks, status=status, taken_at=datetime.now())

    def _derive_state(self, status: FeedStatus) -> str:
        """Translate raw feed bookkeeping into what the UI should display."""
        if status.state in (STATUS_INITIALISING, STATUS_ERROR):
            return status.state
        if status.source == SOURCE_NONE or status.last_tick_at is None:
            return STATUS_DISCONNECTED

        market_open = is_market_open()
        status.market_open = market_open

        age = status.seconds_since_tick
        if age is None:
            return STATUS_LIVE if market_open else STATUS_CLOSED
        if not market_open:
            # Outside the session no new ticks are expected; showing the last
            # known values is correct, but they are explicitly not live.
            return STATUS_CLOSED
        if age > self.config.stale_after_seconds:
            return STATUS_STALE
        return STATUS_LIVE

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------
    def _run(self) -> None:
        candidates = self._providers
        if candidates is None:
            candidates = build_providers(list(self.config.providers))
        if not candidates:
            self._fail("No market data providers are configured")
            return

        # Activation can fail for transient reasons - a rate limit, a broker
        # hiccup, a network blip. Retrying beats leaving the board dead
        # until someone restarts the process.
        remaining = list(candidates)
        while not self._stop_event.is_set():
            if self._activate_provider(remaining):
                break
            if self._stop_event.wait(self.config.feed_retry_seconds):
                return
            logger.info("Retrying provider activation ...")
            remaining = list(candidates)
        if self._stop_event.is_set():
            return

        self._set_status(state=STATUS_DISCONNECTED, detail="Connecting to the live feed")

        connected_at: Optional[float] = None
        next_rest_poll = 0.0

        while not self._stop_event.is_set():
            now = time.monotonic()

            # 1. Establish / re-establish the websocket (on its own thread).
            if self._feed is None and self._connect_feed():
                connected_at = time.monotonic()

            # 2. Drain whatever the websocket has buffered (local work only).
            if self._feed is not None:
                if self._drain_feed():
                    if not self._ws_delivering:
                        logger.info(
                            "%s websocket is delivering live prices",
                            self._provider.label,
                        )
                    self._ws_delivering = True
                    self._set_status(source=SOURCE_WEBSOCKET, detail="")
                elif (
                    connected_at is not None
                    and (time.monotonic() - connected_at)
                    > self.config.feed_bootstrap_seconds
                    and session_state() == SESSION_OPEN
                ):
                    logger.warning(
                        "%s websocket delivered nothing for %.0fs during market hours",
                        self._provider.label,
                        self.config.feed_bootstrap_seconds,
                    )
                    self._teardown_feed()
                    connected_at = None
                    # Give the next provider a turn at the websocket.
                    if remaining and self._activate_provider(remaining):
                        self._next_connect_attempt = 0.0

            # 3. Fallback: batched REST polling, clearly labelled as such.
            if (
                self.config.rest_fallback_enabled
                and not self._ws_delivering
                and now >= next_rest_poll
            ):
                next_rest_poll = now + self.config.rest_poll_seconds
                if self._poll_rest():
                    self._set_status(
                        source=SOURCE_REST,
                        detail=(
                            f"{self._provider.label} websocket unavailable - "
                            "polling REST snapshots"
                        ),
                    )
                else:
                    self._set_status(
                        source=SOURCE_NONE,
                        detail="No price source is currently available",
                    )

            # 4. Refresh previous closes occasionally (e.g. across a new day).
            self._maybe_refresh_previous_close()

            self._stop_event.wait(self.config.feed_drain_seconds)

        self._teardown_feed()

    def _fail(self, message: str) -> None:
        logger.error("%s", message)
        self._set_status(state=STATUS_ERROR, detail=message, source=SOURCE_NONE)

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    def _activate_provider(self, remaining: List[MarketDataProvider]) -> bool:
        """Adopt the first remaining provider that authenticates and resolves.

        Mutates ``remaining`` so each provider is tried at most once.
        """
        skipped = []
        while remaining:
            provider = remaining.pop(0)
            if not provider.is_configured():
                logger.info("Provider %s has no credentials - skipping", provider.label)
                skipped.append(f"{provider.label}: no credentials")
                continue
            try:
                provider.connect()
                self._load_reference_data(provider)
            except Exception as e:
                logger.warning("Provider %s unavailable: %s", provider.label, e)
                skipped.append(f"{provider.label}: {e}")
                continue

            self._provider = provider
            self._teardown_feed()
            self._next_connect_attempt = 0.0
            # Base class returns {}; only a provider that overrides it has a
            # real endpoint worth calling.
            self._day_bars_supported = (
                type(provider).get_day_bars is not MarketDataProvider.get_day_bars
            )
            logger.info("Using %s as the market data provider", provider.label)
            self._set_status(provider=provider.label, detail="")
            return True

        if self._provider is None:
            self._fail("No usable market data provider. " + "; ".join(skipped))
        else:
            logger.warning("No further providers to fall back to; keeping %s",
                           self._provider.label)
        return False

    def _load_reference_data(self, provider: MarketDataProvider) -> None:
        """Resolve broker ids and previous closes before going live."""
        resolved, missing = provider.resolve_instruments(
            self.universe.symbols, segment=self.universe.segment
        )
        if missing:
            logger.warning(
                "%d constituent(s) unresolved on %s and will be skipped: %s",
                len(missing),
                provider.label,
                ", ".join(missing),
            )
        if not resolved:
            raise RuntimeError(
                f"{provider.label} resolved none of the universe's instruments"
            )

        refs = list(resolved.values())
        with self._lock:
            for symbol, ref in resolved.items():
                stock = self._stocks.get(symbol)
                if stock is not None:
                    stock.exchange_token = ref.provider_id
            self._status.unresolved_symbols = list(missing)
            self._status.subscribed_count = 0
        self._refs = refs

        self._fetch_previous_close(provider, refs)

    def _fetch_previous_close(
        self, provider: MarketDataProvider, refs: List[InstrumentRef]
    ) -> None:
        """Load previous closes from whichever source is honest right now.

        During the session (and pre-open) the broker's OHLC block reports the
        previous session's close and is by far the cheapest source: one
        batched call for the whole universe.

        The moment trading stops, that same field is repointed at *today's*
        close - Dhan demonstrably returns ``close == last_price`` after 15:30.
        Reading it then would measure today against itself and collapse every
        tile to +0.00%, silently erasing the day's move. So outside the session
        the previous close comes from daily candles instead, which do not move
        when the session ends.

        Symbols the candle lookup cannot cover are left unresolved rather than
        filled from the OHLC field: they then show up in the data-gaps panel as
        missing, which is true, instead of as +0.00%, which is not.
        """
        closes, source = self._previous_close_source(provider, refs)
        missing = []
        with self._lock:
            for ref in refs:
                stock = self._stocks.get(ref.symbol)
                if stock is None:
                    continue
                close = closes.get(ref.symbol)
                if close and close > 0:
                    stock.previous_close = close
                elif stock.previous_close is None:
                    missing.append(ref.symbol)
            self._status.missing_previous_close = missing
            self._status.previous_close_source = source if closes else ""
        self._prev_close_fetched_at = time.monotonic()
        if missing:
            logger.warning(
                "Missing previous close for %d symbol(s): %s",
                len(missing),
                ", ".join(missing),
            )

    def _previous_close_source(
        self, provider: MarketDataProvider, refs: List[InstrumentRef]
    ):
        """``(closes, source)`` from the path that is trustworthy right now."""
        in_session = session_state() in (SESSION_OPEN, SESSION_PRE_MARKET)
        if in_session or not self.config.historical_previous_close:
            return provider.get_previous_close(refs), PREV_CLOSE_OHLC

        closes = provider.get_prior_session_close(refs)
        if not closes:
            logger.warning(
                "%s returned no daily candles, so previous closes stay unknown "
                "outside market hours - its OHLC endpoint reports today's close "
                "once trading stops and would read +0.00%% everywhere",
                provider.label,
            )
        return closes, PREV_CLOSE_DAILY_CANDLE

    def _maybe_refresh_previous_close(self) -> None:
        """Re-fetch previous closes periodically, but never after the close.

        The refresh exists to pick up a new trading day without a restart. It
        must not run once the session has ended, because brokers repoint the
        OHLC ``close`` field at *today's* close the moment trading stops - Dhan
        demonstrably does, returning ``close == last_price``. Refreshing then
        would overwrite yesterday's close with today's and silently collapse
        every percentage on the board to +0.00%, wiping out the day's move for
        anyone who left the dashboard open past 15:30.

        Refreshing while the market is open or pre-open is safe and is what
        actually picks up a new session.
        """
        interval = self.config.previous_close_refresh_seconds
        if interval <= 0 or self._provider is None:
            return
        if (time.monotonic() - self._prev_close_fetched_at) < interval:
            return

        if session_state() not in (SESSION_OPEN, SESSION_PRE_MARKET):
            # Hold what we have and check again after the interval.
            self._prev_close_fetched_at = time.monotonic()
            logger.debug(
                "Skipping previous-close refresh outside market hours - the "
                "broker's close field now reports today's close"
            )
            return

        try:
            self._fetch_previous_close(self._provider, self._refs)
        except Exception as e:
            logger.warning("Previous-close refresh failed: %s", e)
            self._prev_close_fetched_at = time.monotonic()

    # ------------------------------------------------------------------
    # Websocket
    # ------------------------------------------------------------------
    def _connect_feed(self) -> bool:
        """Kick off a websocket attempt without blocking the worker loop.

        Returns True only once a feed is connected and subscribed.
        """
        if self._connect_result is not None:
            feed, error = self._connect_result
            self._connect_result = None
            self._connect_thread = None
            if feed is not None:
                self._feed = feed
                with self._lock:
                    self._status.subscribed_count = len(self._refs)
                logger.info(
                    "%s feed subscribed to %d instruments",
                    self._provider.label,
                    len(self._refs),
                )
                return True
            logger.warning("%s feed connection failed: %s", self._provider.label, error)
            with self._lock:
                self._status.subscribed_count = 0
            self._set_status(detail=f"{self._provider.label} websocket unavailable: {error}")
            return False

        if self._connect_thread is not None and self._connect_thread.is_alive():
            return False

        if time.monotonic() < self._next_connect_attempt:
            return False
        self._next_connect_attempt = time.monotonic() + self.config.feed_retry_seconds

        logger.info("Connecting to the %s live feed ...", self._provider.label)
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            args=(self._provider, list(self._refs)),
            name=f"live-feed-connect-{self.universe.key}",
            daemon=True,
        )
        self._connect_thread.start()
        return False

    def _connect_worker(
        self, provider: MarketDataProvider, refs: List[InstrumentRef]
    ) -> None:
        """Runs on its own thread; publishes its outcome via _connect_result."""
        try:
            self._connect_result = (provider.open_feed(refs), None)
        except Exception as e:
            self._connect_result = (None, e)

    def _teardown_feed(self) -> None:
        feed, self._feed = self._feed, None
        self._ws_delivering = False
        with self._lock:
            self._status.subscribed_count = 0
        if feed is None:
            return
        try:
            feed.close()
        except Exception:
            logger.debug("Feed close failed (ignored)", exc_info=True)

    def _drain_feed(self) -> bool:
        """Copy the feed's in-memory state into our market state.

        Makes no network calls - the handle keeps the latest price per symbol,
        so draining on a timer costs the same no matter how fast the exchange
        is publishing.
        """
        feed = self._feed
        if feed is None:
            return False

        if not feed.is_alive:
            logger.warning("%s feed dropped", self._provider.label)
            self._teardown_feed()
            self._set_status(detail=f"{self._provider.label} feed disconnected")
            return False

        try:
            prices = feed.latest_prices()
            # Some feeds publish the exchange's previous close explicitly.
            self._apply_previous_closes(feed.previous_closes())
            # Quote-style feeds also carry the day's range; ticker-only
            # feeds return nothing here and the breadth panel adapts.
            self._apply_day_bars(feed.day_bars())
        except Exception as e:
            logger.warning("Feed read failed: %s", e)
            self._teardown_feed()
            self._set_status(detail=f"Feed error: {e}")
            return False

        return self._apply_prices(prices) if prices else False

    # ------------------------------------------------------------------
    # REST fallback
    # ------------------------------------------------------------------
    def _poll_rest(self) -> bool:
        if self._provider is None or not self._refs:
            return False
        try:
            prices = self._provider.get_ltp_snapshot(self._refs)
        except Exception as e:
            logger.warning("REST price poll failed: %s", e)
            return False

        # Day bars are a nice-to-have on the fallback path: a broker that
        # does not supply them, or a call that fails, must not cost us the
        # prices we just fetched.
        if self._day_bars_supported:
            try:
                self._apply_day_bars(self._provider.get_day_bars(self._refs))
            except Exception as e:
                logger.debug("REST day-bar poll failed (non-fatal): %s", e)

        return self._apply_prices(prices) if prices else False

    # ------------------------------------------------------------------
    # Shared state helpers
    # ------------------------------------------------------------------
    def _apply_prices(self, prices: Dict[str, float]) -> bool:
        now = datetime.now()
        applied = 0
        with self._lock:
            for symbol, price in prices.items():
                stock = self._stocks.get(symbol)
                if stock is None or not price or price <= 0:
                    continue
                stock.ltp = float(price)
                stock.last_update = now
                applied += 1
                if symbol not in self._first_tick_logged:
                    self._first_tick_logged.add(symbol)
                    logger.info("Received first tick for %s", symbol)
            if applied:
                self._status.last_tick_at = now
        return applied > 0

    def _apply_day_bars(self, bars) -> None:
        """Record today's open/high/low/volume where a provider reports it.

        Only positive values are written, so a provider that sends 0 for a
        field it has not populated yet leaves the previous value (or None)
        in place rather than corrupting the day range.
        """
        if not bars:
            return
        with self._lock:
            for symbol, bar in bars.items():
                stock = self._stocks.get(symbol)
                if stock is None or bar is None:
                    continue
                if bar.open:
                    stock.day_open = float(bar.open)
                if bar.high:
                    stock.day_high = float(bar.high)
                if bar.low:
                    stock.day_low = float(bar.low)
                if bar.volume:
                    stock.volume = int(bar.volume)

    def _apply_previous_closes(self, closes: Dict[str, float]) -> None:
        """Fill in any previous closes REST could not supply."""
        if not closes:
            return
        filled = []
        with self._lock:
            for symbol, close in closes.items():
                stock = self._stocks.get(symbol)
                if stock is None or not close or close <= 0:
                    continue
                if stock.previous_close is None:
                    stock.previous_close = float(close)
                    filled.append(symbol)
            if filled:
                self._status.missing_previous_close = [
                    s for s in self._status.missing_previous_close if s not in filled
                ]
        if filled:
            logger.info(
                "Feed supplied previous close for %d symbol(s)", len(filled)
            )

    def _set_status(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._status, key, value)
