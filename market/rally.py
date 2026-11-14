"""Rise from a low: how far each stock now trades above its lowest price in a window.

The mirror of ``market/drawdown.py``. Over the same windows (52 weeks, the year to date, 2 or 5
years, or since a date) a stock's low is the lowest daily ``low`` in the window, which is the
intraday low (NSE's definition of a 52-week low); its rise is the as-of close against that low.
The high is found in the same pass, so each row also says where the stock stands against its high
and whether the low came before or after it.

The windows, the corporate-action detection and the resets are ``market.drawdown``'s own, so both
pages agree on what a window is and which stocks are measured from a suspected split or demerger.
A demerger left unadjusted in Kite's history drops the price for good, so without the reset the
post-demerger days would set a fake low.

Everything is computed in SQLite over ``daily_bars``; the page gets one row per stock. Nothing here
talks to a broker; it is pure data handling.
"""

import sqlite3
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from market.drawdown import PARTIAL_AFTER_DAYS, _connect

#: "Near the low" for the summary counts.
NEAR_LOW_PCT = 5.0
#: "Strong rise" for the summary counts.
STRONG_RISE_PCT = 20.0


@dataclass(frozen=True)
class Rally:
    """One stock's position against its low (and its high) in the window."""

    symbol: str
    close: float
    #: The day of ``close``: the as-of day, or the stock's last bar before it.
    last_date: str
    low: float
    low_date: str
    high: float
    high_date: str
    #: First bar actually used (after the window start, or after a reset).
    first_date: str
    #: Bars in the window.
    sessions: int
    #: Sessions after the one that set the low.
    sessions_since_low: int
    #: Set when the stock is measured only from a suspected corporate action.
    reset_on: str | None = None
    #: True when the history starts well after the window does.
    partial: bool = False

    @property
    def rise_pct(self) -> float:
        """Close against the low, as a percentage: 0 at the low, positive above it."""
        return (self.close / self.low - 1.0) * 100.0

    @property
    def from_high_pct(self) -> float:
        """Close against the window's high: 0 at the high, negative below it."""
        return (self.close / self.high - 1.0) * 100.0

    @property
    def low_after_high(self) -> bool:
        """True when the low came after the high: the stock fell first and is bouncing off the bottom."""
        return self.low_date > self.high_date

    @property
    def recovered_pct(self) -> float | None:
        """For a low after the high: how much of the fall from the high has been won back (0 to 100).

        ``None`` when the low came first (the stock rose from the low to the high, so there is no
        fall to recover) or when high and low are the same price.
        """
        if not self.low_after_high or self.high <= self.low:
            return None
        return (self.close - self.low) / (self.high - self.low) * 100.0


def rallies(symbols: Iterable[str], start: str, as_of: str, path: str | None = None,
            resets: dict[str, str] | None = None) -> list[Rally]:
    """One ``Rally`` per stock in ``symbols`` with a bar in ``[start, as_of]``, biggest rise first.

    ``resets`` is symbol -> a later start for that stock (the day of a suspected corporate action).
    Same query shape as ``drawdown.drawdowns``: one aggregate pass over each stock's primary-key
    range, then key lookups for the day of the low, the day of the high, the bars since the low
    and the last close.
    """
    resets = resets or {}
    starts = [(s, max(start, resets.get(s, start))) for s in sorted(set(symbols))]
    conn = _connect(path)
    if conn is None or not starts:
        return []
    query = f"""
        WITH starts(symbol, start, end_day) AS (VALUES {",".join("(?, ?, ?)" for _ in starts)}),
        agg AS (
            SELECT s.symbol, s.start, s.end_day, MAX(d.high) AS hi, MIN(d.low) AS lo,
                   MIN(d.date) AS first_day, MAX(d.date) AS last_day, COUNT(*) AS sessions
            FROM starts s JOIN daily_bars d ON d.symbol = s.symbol AND d.date BETWEEN s.start AND s.end_day
            GROUP BY s.symbol
        ),
        marks AS (
            SELECT a.*,
                   (SELECT MAX(x.date) FROM daily_bars x
                    WHERE x.symbol = a.symbol AND x.date BETWEEN a.start AND a.end_day AND x.low = a.lo) AS lo_date,
                   (SELECT MAX(x.date) FROM daily_bars x
                    WHERE x.symbol = a.symbol AND x.date BETWEEN a.start AND a.end_day AND x.high = a.hi) AS hi_date
            FROM agg a
        )
        SELECT m.symbol, d.close, m.last_day, m.lo, m.lo_date, m.hi, m.hi_date, m.first_day, m.sessions,
               (SELECT COUNT(*) FROM daily_bars y
                WHERE y.symbol = m.symbol AND y.date > m.lo_date AND y.date <= m.end_day)
        FROM marks m JOIN daily_bars d ON d.symbol = m.symbol AND d.date = m.last_day
    """
    params = [value for symbol, first in starts for value in (symbol, first, as_of)]
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    partial_after = (date.fromisoformat(start) + timedelta(days=PARTIAL_AFTER_DAYS)).isoformat()
    result = []
    for symbol, close, last_day, low, low_date, high, high_date, first_day, sessions, since in rows:
        if not low or not close or not high:
            continue
        reset_on = resets[symbol] if resets.get(symbol, "") > start else None
        result.append(Rally(symbol=symbol, close=close, last_date=last_day, low=low, low_date=low_date,
                            high=high, high_date=high_date, first_date=first_day, sessions=sessions,
                            sessions_since_low=since, reset_on=reset_on,
                            partial=reset_on is None and first_day > partial_after))
    return sorted(result, key=lambda r: (-r.rise_pct, r.symbol))


# -- summaries -----------------------------------------------------------------


@dataclass(frozen=True)
class GroupSummary:
    """A set of stocks (a sector, or the whole universe) in one line."""

    name: str
    count: int
    median_rise_pct: float
    #: Rise averaged by weight (free-float market cap); the plain mean when no weights are known.
    weighted_rise_pct: float
    near_low: int
    strong_rise: int
    #: The biggest riser.
    best: str


def weighted_rise(rows: Sequence[Rally], weights: dict[str, float] | None = None) -> float:
    """Weight-averaged rise. A stock without a weight counts at the median weight of the others."""
    if not rows:
        return 0.0
    weights = weights or {}
    known = [weights[r.symbol] for r in rows if weights.get(r.symbol)]
    fallback = statistics.median(known) if known else 1.0
    pairs = [(weights.get(r.symbol) or fallback, r.rise_pct) for r in rows]
    total = sum(w for w, _ in pairs)
    return sum(w * x for w, x in pairs) / total


def summarise(name: str, rows: Sequence[Rally], weights: dict[str, float] | None = None) -> GroupSummary:
    rises = [r.rise_pct for r in rows]
    best = max(rows, key=lambda r: r.rise_pct).symbol if rows else ""
    return GroupSummary(
        name=name,
        count=len(rows),
        median_rise_pct=statistics.median(rises) if rises else 0.0,
        weighted_rise_pct=weighted_rise(rows, weights),
        near_low=sum(1 for x in rises if x <= NEAR_LOW_PCT),
        strong_rise=sum(1 for x in rises if x >= STRONG_RISE_PCT),
        best=best,
    )


def by_sector(rows: Sequence[Rally], sectors: dict[str, str], weights: dict[str, float] | None = None,
              unknown: str = "Other") -> list[GroupSummary]:
    """One summary per sector, biggest weighted rise first."""
    groups: dict[str, list[Rally]] = {}
    for row in rows:
        groups.setdefault(sectors.get(row.symbol) or unknown, []).append(row)
    summaries = [summarise(name, members, weights) for name, members in groups.items()]
    return sorted(summaries, key=lambda s: (-s.weighted_rise_pct, s.name))
