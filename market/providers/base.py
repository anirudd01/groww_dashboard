"""Broker-agnostic market-data provider interface.

Everything above this layer (LiveMarketDataService, aggregation, UI) works only
with canonical NSE trading symbols and plain floats. Broker-specific ids,
endpoints, auth and wire formats stay behind these two abstractions:

    MarketDataProvider  - reference data + REST snapshots + feed factory
    FeedHandle          - one live websocket connection

Adding a broker (Kite, etc.) means implementing these two and registering the
provider in ``market/providers/registry.py``. No other file changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class InstrumentRef:
    """A constituent resolved to one broker's identifier.

    ``symbol`` is the canonical NSE trading symbol (e.g. "RELIANCE") and is the
    only key used above this layer. ``provider_id`` is whatever that broker
    needs on the wire - Groww's ``exchange_token``, Dhan's ``SecurityId``.
    """

    symbol: str
    provider_id: str
    exchange: str = "NSE"
    segment: str = "CASH"


class FeedHandle(ABC):
    """One live connection. Implementations must be safe to read from any thread."""

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """False once the connection has dropped or been closed."""

    @abstractmethod
    def latest_prices(self) -> Dict[str, float]:
        """Latest LTP per symbol seen so far. Cheap - no network calls.

        Called on a timer by the worker, so implementations should return a
        snapshot of in-memory state rather than doing work per call.
        """

    def previous_closes(self) -> Dict[str, float]:
        """Previous-day closes the feed itself reported, if it does.

        Dhan pushes an explicit previous-close packet on subscribe; Groww does
        not. Default is "none", so providers that lack it need not override.
        This is exchange-published reference data, never inferred from a tick.
        """
        return {}

    @abstractmethod
    def close(self) -> None:
        """Tear down the connection. Must be idempotent and must not raise."""


class MarketDataProvider(ABC):
    """Reference data and price access for one broker."""

    #: short lowercase id used in config, e.g. "dhan"
    name: str = "unknown"
    #: human-readable, used in the UI and logs
    label: str = "Unknown"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials for this broker are present.

        Must not perform network I/O - it decides whether to even try.
        """

    @abstractmethod
    def connect(self) -> None:
        """Authenticate / prepare. Raise on failure."""

    @abstractmethod
    def resolve_instruments(
        self, symbols: List[str]
    ) -> Tuple[Dict[str, InstrumentRef], List[str]]:
        """Map canonical symbols to this broker's ids.

        Returns ``(resolved, missing)``. Ids come from the broker's instrument
        master - never hardcoded.
        """

    @abstractmethod
    def get_previous_close(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Previous trading day's close per symbol. Reference data, called rarely."""

    @abstractmethod
    def get_ltp_snapshot(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Batched REST price snapshot - the fallback when the feed is down."""

    @abstractmethod
    def open_feed(self, refs: List[InstrumentRef]) -> FeedHandle:
        """Open a live feed. Raise if it cannot be established.

        May block; the worker calls this on a dedicated thread.
        """
