"""Groww provider - a thin adapter over the project's existing Groww stack.

This deliberately owns no authentication and no API logic of its own. It reuses
``GrowwAPIClient`` (singleton auth) and ``GrowwAPIService`` exactly as the other
dashboards do, and only translates between them and the broker-agnostic
interface in ``market/providers/base.py``.

Known issue: Groww's socket gateway currently accepts CONNECT and then stops
processing client input, so ``open_feed`` normally fails. See
docs/SECTOR_HEATMAP.md. The REST paths work fine, which is why Groww remains
useful as a fallback provider.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

from groww_api import GrowwAPIClient, GrowwAPIService
from market.providers.base import FeedHandle, InstrumentRef, MarketDataProvider

logger = logging.getLogger(__name__)


class GrowwFeedHandle(FeedHandle):
    """Wraps ``GrowwFeed`` so it looks like any other feed handle.

    Groww buffers the last message per subscribed topic internally, so
    ``latest_prices`` reads that buffer rather than receiving pushes. The
    per-tick callback only records liveness.
    """

    def __init__(self, feed, refs: List[InstrumentRef]):
        self._feed = feed
        self._refs = list(refs)
        self._by_token = {str(r.provider_id): r.symbol for r in refs}
        self._alive = True

    @property
    def is_alive(self) -> bool:
        return self._alive and self._feed is not None

    def latest_prices(self) -> Dict[str, float]:
        if self._feed is None:
            return {}
        try:
            payload = self._feed.get_ltp()
        except Exception as e:
            logger.warning("Groww feed read failed: %s", e)
            self._alive = False
            return {}

        prices: Dict[str, float] = {}
        # Shape: {exchange: {segment: {exchange_token: {"ltp": ...}}}}
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
                        if ltp > 0:
                            prices[symbol] = ltp
        except AttributeError:
            logger.warning("Malformed Groww feed payload ignored")
        return prices

    def close(self) -> None:
        feed, self._feed = self._feed, None
        self._alive = False
        if feed is None:
            return
        try:
            feed.unsubscribe_ltp(
                [
                    {
                        "exchange": r.exchange,
                        "segment": r.segment,
                        "exchange_token": r.provider_id,
                    }
                    for r in self._refs
                ]
            )
        except Exception:
            logger.debug("Groww unsubscribe failed (ignored)", exc_info=True)


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
        self, symbols: List[str]
    ) -> Tuple[Dict[str, InstrumentRef], List[str]]:
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
        feed = GrowwFeed(self.service.client.session)
        feed.subscribe_ltp(instruments, lambda meta: None)
        return GrowwFeedHandle(feed, refs)
