"""Groww provider - a thin adapter over the project's existing Groww stack.

This deliberately owns no authentication and no API logic of its own. It reuses
``GrowwAPIClient`` (singleton auth) and ``GrowwAPIService`` exactly as the other
dashboards do, and only translates between them and the broker-agnostic
interface in ``market/providers/base.py``.

Websocket status: Groww's socket gateway now completes the NATS handshake and
streams live LTP ticks - the total failure recorded for 2026-09-18 is fixed on
Groww's side. It behaves quite differently from Dhan's socket, though: the
handshake is slow and routinely has to be retried, the SDK buffers rather than
pushes, and nothing in it ever reports a dropped connection. Each difference is
absorbed by ``GrowwFeedHandle`` below; the measurements and the reasoning are
in docs/api/GROWW_API_FEED.md.
"""

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from groww_api import GrowwAPIClient, GrowwAPIService
from market.providers.base import SEGMENT_CASH, FeedHandle, InstrumentRef, MarketDataProvider

logger = logging.getLogger(__name__)


class GrowwFeedHandle(FeedHandle):
    """Wraps ``GrowwFeed`` so it looks like any other feed handle.

    Three things make Groww unlike a conventional push feed, and each is
    absorbed here rather than left to leak upwards:

    * **It is a buffer, not a stream.** ``GrowwFeed`` keeps the last message
      per subscribed topic and ``get_ltp()`` hands back that whole buffer on
      every call, so a feed that died an hour ago still answers with an
      hour-old price. ``latest_prices`` therefore returns only the entries
      whose exchange timestamp has advanced since the previous read: no new
      tick, no price. That is what the staleness and failover logic upstream
      assumes, and without it a dead socket would read as permanently live.
    * **Liveness is invisible.** No SDK call raises when the socket drops, so
      ``is_alive`` inspects the underlying NATS client directly.
    * **Nothing ever closes the connection.** ``GrowwFeed`` has no teardown
      method and memoises every NATS client it builds on a class attribute,
      so a reconnect loop strands live sockets, threads and event loops for
      the life of the process. ``close`` disconnects and evicts the entry.
    """

    def __init__(self, feed, refs: List[InstrumentRef]):
        self._feed = feed
        self._by_token = {str(r.provider_id): r.symbol for r in refs}
        #: last (timestamp, price) seen per symbol, for change detection
        self._last_seen: Dict[str, tuple] = {}
        self._closed = False

    @property
    def _nats_socket(self):
        """The SDK's ``nats.aio.client.Client``, or None if unreachable."""
        return getattr(getattr(self._feed, "_nats_client", None), "_socket", None)

    @property
    def is_alive(self) -> bool:
        if self._closed or self._feed is None:
            return False
        socket = self._nats_socket
        if socket is None:
            # An SDK change hid the internals. Assume alive and let the
            # no-ticks timer upstream decide, rather than killing a feed
            # that is very likely fine.
            return True
        if socket.is_closed:
            return False
        # A blip is nats-py's problem to solve: it reconnects on its own, and
        # tearing the feed down mid-reconnect only forces Groww's gateway to
        # authorise a fresh connection - which, as the handshake timings in
        # the feed doc show, is the expensive part. A reconnect that never
        # lands is still caught, by the no-ticks timer.
        return bool(socket.is_connected or socket.is_reconnecting)

    def latest_prices(self) -> Dict[str, float]:
        if self._feed is None:
            return {}
        try:
            payload = self._feed.get_ltp()
        except Exception as e:
            logger.warning("Groww feed read failed: %s", e)
            self._closed = True
            return {}

        prices: Dict[str, float] = {}
        # Shape: {exchange: {segment: {exchange_token: {"ltp": .., "tsInMillis": ..}}}}
        try:
            for segments in (payload or {}).values():
                for tokens in (segments or {}).values():
                    for token, data in (tokens or {}).items():
                        if not isinstance(data, dict):
                            continue
                        symbol = self._by_token.get(str(token))
                        if symbol is None:
                            continue
                        try:
                            ltp = float(data.get("ltp"))
                        except (TypeError, ValueError):
                            continue
                        if ltp <= 0:
                            continue
                        # The buffer is re-read on every drain, so without
                        # this a silent socket would keep re-reporting its
                        # final tick and the board would look live forever.
                        stamp = (data.get("tsInMillis"), ltp)
                        if self._last_seen.get(symbol) == stamp:
                            continue
                        self._last_seen[symbol] = stamp
                        prices[symbol] = ltp
        except AttributeError:
            logger.warning("Malformed Groww feed payload ignored")
        return prices

    def close(self) -> None:
        """Drop the connection outright, without unsubscribing first.

        ``unsubscribe_ltp`` would queue one fire-and-forget coroutine per
        instrument onto the SDK's event loop and return before any of them
        ran; tearing the loop down a moment later then destroys fifty pending
        tasks and fills the log with asyncio warnings. Closing the connection
        already discards every subscription on it, so the per-topic
        unsubscribe buys nothing here and costs a round trip each.
        """
        feed, self._feed = self._feed, None
        self._closed = True
        if feed is None:
            return
        self._disconnect(feed)

    @staticmethod
    def _disconnect(feed) -> None:
        """Close the NATS connection the SDK never closes by itself.

        ``GrowwFeed`` exposes no teardown and caches every client it builds in
        ``GrowwFeed._nats_clients``, keyed by a socket token it re-mints per
        instance - so that cache never hits, and every reconnect adds one more
        live websocket, daemon thread and event loop. Groww's gateway is also
        slower to authorise a connection the more of them an account already
        holds open, so leaking them makes the next reconnect worse, not merely
        untidy.

        Everything touched here is private SDK state, hence the defensive
        getattr and the swallowed exceptions: an SDK upgrade that renames any
        of it must degrade to the old leaky behaviour, never break the feed.
        """
        nats_client = getattr(feed, "_nats_client", None)
        loop = getattr(nats_client, "_loop", None)
        socket = getattr(nats_client, "_socket", None)
        if socket is not None and loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(socket.close(), loop).result(5)
            except Exception:
                logger.debug("Groww socket close failed (ignored)", exc_info=True)
        if loop is not None and not loop.is_closed():
            # The SDK's consume thread sits in loop.run_forever(); stopping
            # the loop is the only thing that lets that thread finish.
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                logger.debug("Groww feed loop stop failed (ignored)", exc_info=True)
        try:
            from growwapi import GrowwFeed

            GrowwFeed._nats_clients.pop(getattr(feed, "_client_key", None), None)
        except Exception:
            logger.debug("Groww client cache eviction failed (ignored)", exc_info=True)


class GrowwProvider(MarketDataProvider):
    name = "groww"
    label = "Groww"

    def __init__(self, api_service: Optional[GrowwAPIService] = None, batch_size: int = 50):
        self._service = api_service
        self._batch_size = batch_size

    def is_configured(self) -> bool:
        # Mirrors GrowwAPIClient's own credential handling.
        return bool(
            (os.getenv("GROWW_ACCESS_TOKEN") or "").strip()
            or ((os.getenv("GROWW_API_KEY") or "").strip()
                and ((os.getenv("GROWW_TOTP_SECRET") or "").strip()
                     or (os.getenv("GROWW_API_SECRET") or "").strip()))
        )

    def connect(self) -> None:
        if self._service is not None:
            return
        client = GrowwAPIClient.get_instance()
        if not client.is_connected:
            raise RuntimeError(client.auth_error or "Groww client not authenticated")
        self._service = GrowwAPIService(client)

    @property
    def service(self) -> GrowwAPIService:
        if self._service is None:
            self.connect()
        return self._service

    def resolve_instruments(
        self, symbols: List[str], segment: str = SEGMENT_CASH
    ) -> Tuple[Dict[str, InstrumentRef], List[str]]:
        """Groww serves NSE cash equities only in this adapter.

        Index values are reported as entirely missing rather than raising, so
        the service can fail over to a broker that does serve them instead of
        the whole board erroring out.
        """
        if (segment or SEGMENT_CASH).upper() != SEGMENT_CASH:
            logger.info(
                "Groww provider has no %s support; reporting %d symbol(s) as "
                "unresolved so another provider can take the board",
                segment, len(symbols),
            )
            return {}, list(symbols)

        resolved_raw, missing = self.service.resolve_nse_cash_instruments(symbols)
        resolved = {
            symbol: InstrumentRef(
                symbol=symbol,
                provider_id=meta["exchange_token"],
                exchange=meta["exchange"],
                segment=meta["segment"],
            )
            for symbol, meta in resolved_raw.items()
        }
        return resolved, missing

    def get_previous_close(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        return self.service.get_previous_close_nse_cash(
            [r.symbol for r in refs], batch_size=self._batch_size
        )

    def get_ltp_snapshot(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        return self.service.get_ltp_nse_cash(
            [r.symbol for r in refs], batch_size=self._batch_size
        )

    def open_feed(self, refs: List[InstrumentRef]) -> FeedHandle:
        from growwapi import GrowwFeed

        instruments = [
            {
                "exchange": r.exchange,
                "segment": r.segment,
                "exchange_token": r.provider_id,
            }
            for r in refs
        ]
        # The constructor mints a socket token and completes the NATS
        # handshake inline. Groww's gateway frequently lets that handshake
        # time out; nats-py retries it every ~4s behind the SDK's back and
        # the SDK logs each failure as a bare "Error:" line with no message,
        # so this call can return anywhere between one second and a couple of
        # minutes later having explained nothing. It runs on the service's
        # dedicated connect thread, so the wait costs the UI nothing - but it
        # is the single most confusing thing about this feed, so time it.
        started = time.monotonic()
        feed = GrowwFeed(self.service.client.session)
        logger.info(
            "Groww socket handshake completed in %.1fs", time.monotonic() - started
        )
        # subscribe_ltp only queues the SUBs onto the SDK's event loop, so it
        # returns at once; ticks start arriving over the next few seconds.
        feed.subscribe_ltp(instruments, lambda meta: None)
        return GrowwFeedHandle(feed, refs)
