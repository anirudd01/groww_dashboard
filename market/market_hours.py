"""NSE market-session helpers.

Intentionally minimal: weekday + clock check against the normal NSE equity
session. Exchange holidays are NOT tracked - on a holiday the session window
looks open but no ticks arrive, and the feed's staleness detection surfaces
that instead of the dashboard pretending prices are live.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_MARKET_OPEN = time(9, 0)

SESSION_PRE_MARKET = "PRE-MARKET"
SESSION_OPEN = "OPEN"
SESSION_CLOSED = "CLOSED"
SESSION_WEEKEND = "WEEKEND"


def now_ist() -> datetime:
    return datetime.now(IST)


def session_state(now: datetime = None) -> str:
    """Classify the current moment into a coarse session bucket."""
    now = now or now_ist()
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    if now.weekday() >= 5:  # Saturday / Sunday
        return SESSION_WEEKEND

    clock = now.time()
    if PRE_MARKET_OPEN <= clock < MARKET_OPEN:
        return SESSION_PRE_MARKET
    if MARKET_OPEN <= clock <= MARKET_CLOSE:
        return SESSION_OPEN
    return SESSION_CLOSED


def is_market_open(now: datetime = None) -> bool:
    """True during the normal NSE continuous session (holidays not checked)."""
    return session_state(now) == SESSION_OPEN


def todays_session_date(now: datetime = None) -> Optional[date]:
    """Today's date once today's session has begun, otherwise ``None``.

    Answers one narrow question: does the latest available price belong to
    *today*? A previous-close lookup built on daily candles needs it to know
    whether to step over today's own candle. Before 09:15 and at the weekend
    the latest price comes from an earlier session, so this returns None and
    the caller falls back to "the candle before the most recent one".

    Holidays are not tracked (see the module docstring), so on a holiday this
    returns today's date. The candle lookup then finds no candle for today and
    measures against the last real session's close, which reads +0.00% rather
    than reporting a move that did not happen.
    """
    now = now or now_ist()
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    if now.weekday() >= 5:
        return None
    return now.date() if now.time() >= MARKET_OPEN else None
