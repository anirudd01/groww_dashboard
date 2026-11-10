"""Has an exchange traded today? Asked of the broker, never read from a holiday calendar.

Neither Dhan nor Groww publishes an "NSE open / MCX open" endpoint (checked 2026-11-10: Dhan's only
market-status endpoint covers its US stocks; the Groww SDK has none). What both do publish is
*when* an instrument last traded. If a liquid instrument has a trade dated today, the exchange is
trading today; if it does not, the exchange is shut for the day. On the NSE holiday of 2026-11-10
Dhan returned empty NSE quotes, while MCX gold showed trades minutes old in the evening session.

Rules:

* Nothing is asked before the session has had a minute to trade (NSE 09:16, MCX 09:01). Until
  then the answer is ``None``, "not known yet", and callers carry on as if it were a normal day:
  at 09:15 the live feed tries for prices as usual.
* Every answer, open or closed, is kept for ``TTL_SECONDS`` (5 minutes) and then asked again.
  One wrong reply (yesterday's data, a broker glitch) therefore costs at most five minutes.
* A failed request answers ``None`` too, and is also kept for 5 minutes, so a broker outage is
  asked about once per 5 minutes, not on every loop pass.
* ``peek()`` never touches the network: the Streamlit thread uses it. ``traded_today()`` may ask.

The verdict lives in memory, per process. The dashboard's live feeds share one cache; the daily
jobs run in their own process and ask for themselves.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from typing import Callable, Dict, List, Optional

from market.market_hours import IST, now_ist

logger = logging.getLogger(__name__)

NSE = "NSE"
MCX = "MCX"

#: How long one answer is trusted before the broker is asked again.
TTL_SECONDS = 5 * 60

#: The first moment a missing trade means something: the session opened a minute before.
FIRST_CHECK = {NSE: dtime(9, 16), MCX: dtime(9, 1)}

#: Liquid NSE instruments to look for a trade on (Dhan ids). Any one dated today is enough.
NSE_PROBES = (("RELIANCE", "2885", "CASH"), ("HDFCBANK", "1333", "CASH"), ("NIFTY", "13", "INDEX"))

#: MCX commodities whose nearest live contract is probed.
MCX_PROBE_COMMODITIES = ("GOLD", "CRUDEOIL", "SILVER")


@dataclass
class _Entry:
    verdict: Optional[bool]
    checked_at: float  # time.monotonic()
    detail: str = ""


#: ``probe(exchange, today) -> True / False``; raises when the broker could not answer.
Probe = Callable[[str, date], bool]


class ExchangeStatus:
    """Per-exchange "traded today?" verdicts, each trusted for ``ttl`` seconds."""

    def __init__(self, probe: Optional[Probe] = None, ttl: float = TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = now_ist):
        self._probe = probe or dhan_probe
        self._ttl = ttl
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._entries: Dict[str, _Entry] = {}
        self._day: Optional[date] = None

    def peek(self, exchange: str) -> Optional[bool]:
        """The current verdict without asking anyone: True, False, or None (not known)."""
        with self._lock:
            self._roll_day()
            entry = self._entries.get(exchange)
            if entry is None or self._clock() - entry.checked_at > self._ttl:
                return None
            return entry.verdict

    def traded_today(self, exchange: str) -> Optional[bool]:
        """True / False once the broker has said so in the last 5 minutes, asking if needed.

        ``None`` before the session's first minute is over, or when the broker could not answer.
        """
        now = self._now()
        if now.time() < FIRST_CHECK.get(exchange, dtime(9, 16)):
            return None
        with self._lock:
            self._roll_day()
            entry = self._entries.get(exchange)
            if self._ttl > 0 and entry is not None and self._clock() - entry.checked_at <= self._ttl:
                return entry.verdict
        # Asked outside the lock: a probe is a network call, and peek() must never wait on it.
        try:
            verdict: Optional[bool] = bool(self._probe(exchange, now.date()))
            detail = "trading today" if verdict else "no trade today"
        except Exception as exc:  # noqa: BLE001 - "not known" is the honest answer
            verdict, detail = None, f"check failed: {exc}"
        with self._lock:
            previous = self._entries.get(exchange)
            self._entries[exchange] = _Entry(verdict, self._clock(), detail)
        if previous is None or previous.verdict != verdict:
            logger.info("%s market status: %s", exchange, detail)
        return verdict

    def record_trade(self, exchange: str) -> None:
        """A live price arrived during the session: the exchange is trading, no need to ask."""
        with self._lock:
            self._roll_day()
            self._entries[exchange] = _Entry(True, self._clock(), "live prices arriving")

    def _roll_day(self) -> None:
        """Forget yesterday's verdicts at midnight. Hold the lock."""
        today = self._now().date()
        if self._day != today:
            self._entries.clear()
            self._day = today


# ---------------------------------------------------------------------------
# The broker question
# ---------------------------------------------------------------------------
def _nse_refs():
    from market.providers.base import InstrumentRef

    return [InstrumentRef(symbol=s, provider_id=i, exchange="NSE", segment=seg) for s, i, seg in NSE_PROBES]


def _mcx_refs(today: date):
    from market.mcx_futures import live_contracts, load_contracts

    contracts, _, error = load_contracts()
    if error:
        raise RuntimeError(error)
    refs = []
    for commodity in MCX_PROBE_COMMODITIES:
        live = sorted((c for c in live_contracts(contracts, today) if c.commodity == commodity),
                      key=lambda c: c.expiry)
        if live:
            refs.append(live[0].ref("dhan"))
    if not refs:
        raise RuntimeError("no live MCX contract stored to check")
    return refs


_provider_lock = threading.Lock()
_provider = None


def _dhan():
    global _provider
    with _provider_lock:
        if _provider is None:
            from market.providers.dhan import DhanProvider

            # A short timeout: the check runs inside the live feed's worker
            # loop, and a hung Dhan must not stall the board for long.
            provider = DhanProvider(timeout=5)
            provider.connect()
            _provider = provider
        return _provider


def dhan_probe(exchange: str, today: date) -> bool:
    """Ask Dhan when a few liquid instruments last traded; any trade dated today means open.

    Raises when Dhan could not answer, so that an error is never mistaken for a holiday (on a
    holiday Dhan answers successfully with no NSE prices at all).
    """
    global _provider
    refs: List = _nse_refs() if exchange == NSE else _mcx_refs(today)
    try:
        times = _dhan().get_last_trade_times(refs, strict=True)
    except Exception:
        # An expired token or a dead session: start from a fresh login on the next check.
        with _provider_lock:
            _provider = None
        raise
    return any(t.astimezone(IST).date() == today for t in times.values())


_shared: Optional[ExchangeStatus] = None
_shared_lock = threading.Lock()


def shared() -> ExchangeStatus:
    """The process-wide cache every live feed in this process consults."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ExchangeStatus()
        return _shared
