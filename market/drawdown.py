"""Drop from a high: how far each stock now trades below its highest price in a window.

The window is any start date up to an "as of" day: 52 weeks, the year to date, 2 or 5 years, or a
date you pick. A stock's high is the highest daily ``high`` in the window, which is the intraday
high (NSE's and every broker's definition of a 52-week high); its drop is the as-of close against
that high.

Everything is computed in SQLite over ``daily_bars`` (``market/intraday_store.py``): one query
returns one row per stock, so the page never holds the years of daily bars in memory. The
history comes from ``scripts/kite.py history`` (5 years with ``--full --history-days 1830``).

Corporate actions
-----------------
Kite adjusts its candles for splits and bonuses but not for demergers, so a demerged stock's
pre-demerger high stays in the history and its "drop" is mostly the part that left. Falls that look
like a split ratio (``fno_movers.split_ratio``) are found with SQL too, and with ``reset_after_actions``
such a stock is measured only from the day of the fall. A fall confirmed as real with
``scripts/confirm_fno_move.py`` is not reset.

Nothing here talks to a broker; it is pure data handling.
"""

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from market import intraday_store, state_store
from market.fno_movers import CorporateAction, load_confirmed_moves, split_ratio

WINDOW_52W = "52 weeks"
WINDOW_YTD = "Year to date"
WINDOW_2Y = "2 years"
WINDOW_5Y = "5 years"
WINDOW_CUSTOM = "Since a date"
WINDOWS = (WINDOW_52W, WINDOW_YTD, WINDOW_2Y, WINDOW_5Y, WINDOW_CUSTOM)

#: A stock whose first bar in the window is this many days after the window's start (a recent
#: listing, or a history that does not reach back) is measured over a partial window.
PARTIAL_AFTER_DAYS = 7
#: "Near the high" for the summary counts.
NEAR_HIGH_PCT = 5.0
#: "Deep drop" for the summary counts.
DEEP_DROP_PCT = 20.0


def window_start(window: str, as_of: str, custom: Optional[str] = None) -> str:
    """The first day of ``window`` ending on ``as_of`` (both ``YYYY-MM-DD``)."""
    end = date.fromisoformat(as_of)
    if window == WINDOW_52W:
        return (end - timedelta(weeks=52)).isoformat()
    if window == WINDOW_YTD:
        return date(end.year, 1, 1).isoformat()
    if window in (WINDOW_2Y, WINDOW_5Y):
        years = 2 if window == WINDOW_2Y else 5
        try:
            return end.replace(year=end.year - years).isoformat()
        except ValueError:  # 29 Feb
            return end.replace(year=end.year - years, day=28).isoformat()
    if window == WINDOW_CUSTOM:
        if not custom:
            raise ValueError("a custom window needs a start date")
        return custom
    raise ValueError(f"unknown window {window!r}")


@dataclass(frozen=True)
class Drawdown:
    """One stock's position against its high in the window."""

    symbol: str
    close: float
    #: The day of ``close``: the as-of day, or the stock's last bar before it.
    last_date: str
    high: float
    high_date: str
    low: float
    #: First bar actually used (after the window start, or after a reset).
    first_date: str
    #: Bars in the window.
    sessions: int
    #: Sessions after the one that set the high.
    sessions_since_high: int
    #: Set when the stock is measured only from a suspected corporate action.
    reset_on: Optional[str] = None
    #: True when the history starts well after the window does.
    partial: bool = False

    @property
    def drop_pct(self) -> float:
        """Close against the high, as a percentage: 0 at the high, negative below it."""
        return (self.close / self.high - 1.0) * 100.0

    @property
    def above_low_pct(self) -> float:
        return (self.close / self.low - 1.0) * 100.0


def _connect(path: Optional[str]) -> Optional[sqlite3.Connection]:
    return intraday_store.connect_readonly(path or state_store.db_path())


def stored_range(path: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """``(first, last)`` stored day in ``daily_bars``, or ``(None, None)``."""
    conn = _connect(path)
    if conn is None:
        return None, None
    try:
        return tuple(conn.execute("SELECT MIN(date), MAX(date) FROM daily_bars").fetchone())
    except sqlite3.Error:
        return None, None
    finally:
        conn.close()


def _placeholders(count: int) -> str:
    return ",".join("?" * count)


def suspected_actions(symbols: Sequence[str], start: str, as_of: str, path: Optional[str] = None,
                      confirmed: Optional[set] = None) -> List[CorporateAction]:
    """Split-like one-day falls between ``start`` and ``as_of``, newest first.

    SQL picks the falls of ``MIN_SPLIT_DROP_PCT`` or more (a handful of rows out of years);
    ``split_ratio`` then keeps the ones matching a ratio, the same rule the F&O pages use.
    The previous close is the symbol's previous stored bar.
    """
    from market.fno_movers import MIN_SPLIT_DROP_PCT

    symbols = list(symbols)
    conn = _connect(path)
    if conn is None or not symbols:
        return []
    # The LAG needs the bar before ``start``; ten calendar days covers any holiday run.
    lead_in = (date.fromisoformat(start) - timedelta(days=10)).isoformat()
    query = f"""
        SELECT symbol, date, prev_close, close FROM (
            SELECT symbol, date, close,
                   LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev_close
            FROM daily_bars
            WHERE symbol IN ({_placeholders(len(symbols))}) AND date BETWEEN ? AND ?
        )
        WHERE date >= ? AND prev_close IS NOT NULL AND close <= prev_close * ?
    """
    try:
        rows = conn.execute(query, (*symbols, lead_in, as_of, start, 1 - MIN_SPLIT_DROP_PCT / 100)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    confirmed = load_confirmed_moves(path) if confirmed is None else confirmed
    found = []
    for symbol, day, previous, close in rows:
        ratio = split_ratio(previous, close)
        if ratio and (symbol, day) not in confirmed:
            found.append(CorporateAction(symbol, day, previous, close, ratio))
    return sorted(found, key=lambda a: (a.date, a.symbol), reverse=True)


def drawdowns(symbols: Iterable[str], start: str, as_of: str, path: Optional[str] = None,
              resets: Optional[Dict[str, str]] = None) -> List[Drawdown]:
    """One ``Drawdown`` per stock in ``symbols`` with a bar in ``[start, as_of]``, deepest drop first.

    ``resets`` is symbol -> a later start for that stock (the day of a suspected corporate action).
    The high, the low and the last close are all found in one query; the page gets one row per stock.
    """
    resets = resets or {}
    starts = [(s, max(start, resets.get(s, start))) for s in sorted(set(symbols))]
    conn = _connect(path)
    if conn is None or not starts:
        return []
    # One aggregate pass per stock over its (symbol, date) primary-key range, then key lookups for
    # the day of the high, the bars since it and the last close. Every subquery reads daily_bars
    # through the key, never a CTE: SQLite recomputes a CTE each time it is referenced, and a
    # window-function version had to sort every bar; both were 5-20x slower on 5 years.
    query = f"""
        WITH starts(symbol, start, end_day) AS (VALUES {",".join("(?, ?, ?)" for _ in starts)}),
        agg AS (
            SELECT s.symbol, s.start, s.end_day, MAX(d.high) AS hi, MIN(d.low) AS lo,
                   MIN(d.date) AS first_day, MAX(d.date) AS last_day, COUNT(*) AS sessions
            FROM starts s JOIN daily_bars d ON d.symbol = s.symbol AND d.date BETWEEN s.start AND s.end_day
            GROUP BY s.symbol
        ),
        peak AS (
            SELECT a.*, (SELECT MAX(x.date) FROM daily_bars x
                         WHERE x.symbol = a.symbol AND x.date BETWEEN a.start AND a.end_day
                           AND x.high = a.hi) AS hi_date
            FROM agg a
        )
        SELECT p.symbol, d.close, p.last_day, p.hi, p.hi_date, p.lo, p.first_day, p.sessions,
               (SELECT COUNT(*) FROM daily_bars y
                WHERE y.symbol = p.symbol AND y.date > p.hi_date AND y.date <= p.end_day)
        FROM peak p JOIN daily_bars d ON d.symbol = p.symbol AND d.date = p.last_day
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
    for symbol, close, last_day, high, high_date, low, first_day, sessions, since in rows:
        if not high or not close:
            continue
        reset_on = resets[symbol] if resets.get(symbol, "") > start else None
        result.append(Drawdown(symbol=symbol, close=close, last_date=last_day, high=high, high_date=high_date,
                               low=low, first_date=first_day, sessions=sessions, sessions_since_high=since,
                               reset_on=reset_on, partial=reset_on is None and first_day > partial_after))
    return sorted(result, key=lambda d: (d.drop_pct, d.symbol))


def resets_for(actions: Iterable[CorporateAction]) -> Dict[str, str]:
    """Symbol -> the day of its latest suspected action (``actions`` may hold several per stock)."""
    latest: Dict[str, str] = {}
    for action in actions:
        latest[action.symbol] = max(latest.get(action.symbol, ""), action.date)
    return latest


# -- summaries -----------------------------------------------------------------


@dataclass(frozen=True)
class GroupSummary:
    """A set of stocks (a sector, or the whole universe) in one line."""

    name: str
    count: int
    median_drop_pct: float
    #: Drop averaged by weight (free-float market cap); the plain mean when no weights are known.
    weighted_drop_pct: float
    near_high: int
    deep_drop: int
    worst: str


def weighted_drop(rows: Sequence[Drawdown], weights: Optional[Dict[str, float]] = None) -> float:
    """Weight-averaged drop. A stock without a weight counts at the median weight of the others."""
    if not rows:
        return 0.0
    weights = weights or {}
    known = [weights[r.symbol] for r in rows if weights.get(r.symbol)]
    fallback = statistics.median(known) if known else 1.0
    pairs = [(weights.get(r.symbol) or fallback, r.drop_pct) for r in rows]
    total = sum(w for w, _ in pairs)
    return sum(w * d for w, d in pairs) / total


def summarise(name: str, rows: Sequence[Drawdown], weights: Optional[Dict[str, float]] = None) -> GroupSummary:
    drops = [r.drop_pct for r in rows]
    worst = min(rows, key=lambda r: r.drop_pct).symbol if rows else ""
    return GroupSummary(
        name=name,
        count=len(rows),
        median_drop_pct=statistics.median(drops) if drops else 0.0,
        weighted_drop_pct=weighted_drop(rows, weights),
        near_high=sum(1 for d in drops if d >= -NEAR_HIGH_PCT),
        deep_drop=sum(1 for d in drops if d <= -DEEP_DROP_PCT),
        worst=worst,
    )


def by_sector(rows: Sequence[Drawdown], sectors: Dict[str, str], weights: Optional[Dict[str, float]] = None,
              unknown: str = "Other") -> List[GroupSummary]:
    """One summary per sector, deepest weighted drop first."""
    groups: Dict[str, List[Drawdown]] = {}
    for row in rows:
        groups.setdefault(sectors.get(row.symbol) or unknown, []).append(row)
    summaries = [summarise(name, members, weights) for name, members in groups.items()]
    return sorted(summaries, key=lambda s: (s.weighted_drop_pct, s.name))
