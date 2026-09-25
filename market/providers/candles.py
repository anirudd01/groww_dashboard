"""Broker-neutral helpers for daily candles and price fields.

Every broker with a historical endpoint answers the same question the same way
- "what was the close of the session before the current one" - so the answer
lives here rather than in each provider. Providers translate their own candle
format into the parallel-array shape below and call ``prior_close_from_candles``.
"""

from datetime import date, datetime
from typing import List, Optional

from market.market_hours import IST


def positive(value) -> Optional[float]:
    """``value`` as a float when it is a usable price, otherwise None.

    Brokers send 0 for any field they have no value for yet (Dhan before the
    first trade, INDmoney for index volume). Zero must stay "unknown" rather
    than becoming a price.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _candle_dates(stamps) -> List[Optional[date]]:
    """IST dates for a candle series' epoch timestamps, None where unreadable."""
    dates: List[Optional[date]] = []
    for stamp in stamps or []:
        try:
            dates.append(datetime.fromtimestamp(int(stamp), IST).date())
        except (TypeError, ValueError, OSError, OverflowError):
            dates.append(None)
    return dates


def prior_close_from_candles(payload: dict, session_date: Optional[date] = None):
    """The previous session's close from a daily-candle response.

    ``payload`` is the parallel-array format: ``{"close": [...],
    "timestamp": [...], ...}`` in ascending date order, timestamps in epoch
    seconds.

    ``session_date`` is the date the *current price* belongs to, or None when
    that price comes from a session earlier than today (weekend, or before
    today's open). This is the whole subtlety:

    - Given a session date, the answer is the last candle strictly *before*
      it. That is correct whether or not today's own candle has been written
      yet - after 15:30 it steps over today, and in the gap before the broker
      publishes today's candle it still lands on the right day.
    - Without one, the most recent candle *is* the session the current price
      came from, so the answer is the candle before it.

    Returns None rather than guessing when the series is too short or the
    close is not a usable price.
    """
    if not isinstance(payload, dict):
        return None
    closes = payload.get("close") or []
    if len(closes) < 2:
        return None

    dates = _candle_dates(payload.get("timestamp"))
    readable = any(day is not None for day in dates)
    if session_date is not None and readable and len(dates) == len(closes):
        for close, day in zip(reversed(closes), reversed(dates)):
            if day is not None and day < session_date:
                return positive(close)
        return None

    # No session date, or timestamps we cannot read: treat the last candle as
    # the current session and take the one before it.
    return positive(closes[-2])
