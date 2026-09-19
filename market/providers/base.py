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
from typing import Dict, List, Optional, Tuple

#: Segments a universe can ask for. Brokers map these onto their own names.
SEGMENT_CASH = "CASH"
SEGMENT_INDEX = "INDEX"


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


@dataclass(frozen=True)
class DayBar:
    """Today's session bar for one instrument.

    Every field is optional because not every broker publishes every field,
    and a broker that publishes none is a supported case rather than an
    error. Consumers must check before using: a missing high is "unknown",
    never zero.

    ``close`` is deliberately absent - the previous close is reference data
    with its own dedicated path, and mixing it in here would invite exactly
    the "previous close inferred from the live feed" mistake the design
    avoids.
    """

    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None

    @property
    def has_range(self) -> bool:
        """True when high/low describe a usable range."""
        return (
            self.high is not None
            and self.low is not None
            and self.high > self.low > 0
        )


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

    def day_bars(self) -> Dict[str, "DayBar"]:
        """Today's open/high/low/volume per symbol, where the feed carries it.

        Dhan's quote packets carry it; Groww's LTP feed does not. Default is
        "none", so a provider without it needs no override and the breadth
        panel simply shows fewer columns rather than inventing values.
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
        self, symbols: List[str], segment: str = SEGMENT_CASH
    ) -> Tuple[Dict[str, InstrumentRef], List[str]]:
        """Map canonical symbols to this broker's ids.

        Returns ``(resolved, missing)``. Ids come from the broker's instrument
        master - never hardcoded.

        ``segment`` is ``SEGMENT_CASH`` for equities or ``SEGMENT_INDEX`` for
        index values. A provider that cannot serve a segment returns every
        symbol as missing rather than raising, so the service can fail over
        to the next broker.
        """

    @abstractmethod
    def get_previous_close(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Previous trading day's close per symbol. Reference data, called rarely."""

    def get_prior_session_close(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Close of the trading day *before* the most recent completed session.

        Optional, and the answer to a question ``get_previous_close`` cannot
        answer outside market hours. That method reads the broker's OHLC block,
        which reports the previous session's close only while trading is live:
        once the session ends brokers repoint the same field at *today's*
        close, so a dashboard started after 15:30 would measure today against
        itself and read +0.00% on every tile.

        Daily candles do not move when the session ends, so they can still say
        what the previous close was. A provider without a historical endpoint
        returns nothing and the caller keeps whatever it already had - it must
        never quietly fall back to the OHLC field, which is known to be wrong
        at exactly the moment this path is used.
        """
        return {}

    @abstractmethod
    def get_ltp_snapshot(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Batched REST price snapshot - the fallback when the feed is down."""

    def get_day_bars(self, refs: List[InstrumentRef]) -> Dict[str, DayBar]:
        """Batched REST session bars, for brokers whose quote endpoint has them.

        Optional: the default returns nothing, and callers degrade to showing
        breadth without the day-range column.
        """
        return {}

    @abstractmethod
    def open_feed(self, refs: List[InstrumentRef]) -> FeedHandle:
        """Open a live feed. Raise if it cannot be established.

        May block; the worker calls this on a dedicated thread.
        """
