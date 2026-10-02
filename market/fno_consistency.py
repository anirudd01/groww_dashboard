"""Which F&O stocks moved *consistently* over the last N trading days.

The F&O heatmap page asks a different question from the movers page. The
movers page ranks by the biggest change from one close to another, and one
huge day can put a stock on top. Here every stock gets one row of N daily
moves, and the ranking rewards a run of days in the same direction.

The score is the **directional efficiency** of the window::

    efficiency = ln(last close / first close) / sum(|ln(close_i / close_i-1)|)

That is the net move divided by the total distance travelled, from -1 to +1:

* +1: it closed higher every day, however big or small each step was;
* near 0: choppy. It went up and down and got nowhere, even if one day was huge;
* -1: it closed lower every day.

Log returns make the numerator exactly the sum of the daily steps, so the
ratio is exact rather than approximate. The score shown is ``efficiency * 100``.

Data comes only from the stored daily closes (see ``market.fno_movers``);
nothing here calls a broker.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from market.fno_movers import _number, trading_days

#: How rows can be ranked: the label shown in the UI, and the attribute sorted on.
METRIC_CONSISTENCY = "Consistency"
METRIC_UP_DAYS = "Up days"
METRIC_NET_CHANGE = "Net change"
METRICS = (METRIC_CONSISTENCY, METRIC_UP_DAYS, METRIC_NET_CHANGE)


@dataclass
class ConsistencyRow:
    """One stock over the window: its daily moves and the scores derived from them.

    Built from closes (close-to-close moves, the F&O Heatmap page) or directly from
    per-day log returns via ``steps`` (any other daily series, such as the overnight
    gaps on the Gap Streaks page). Every score is computed from ``steps``.
    """

    symbol: str
    #: The N days whose moves are shown, oldest first (the first close's day is not included)
    dates: List[str]
    #: N+1 closes, from the day before ``dates[0]`` to ``dates[-1]``. Empty when built from ``steps``
    closes: List[float] = field(default_factory=list)
    #: N daily % changes, aligned with ``dates``
    changes: List[float] = field(default_factory=list)
    #: N daily log returns, aligned with ``dates``
    steps: List[float] = field(default_factory=list)
    #: A day whose |% change| is below this counts as neither up nor down
    flat_below: float = 0.0

    def __post_init__(self):
        if not self.steps:
            if self.closes:
                self.steps = [math.log(b / a) for a, b in zip(self.closes, self.closes[1:])]
            else:
                self.steps = [math.log1p(c / 100.0) for c in self.changes]
        if not self.changes:
            self.changes = [math.expm1(s) * 100.0 for s in self.steps]

    @property
    def days(self) -> int:
        return len(self.changes)

    @property
    def up_days(self) -> int:
        return sum(1 for c in self.changes if c > self.flat_below)

    @property
    def down_days(self) -> int:
        return sum(1 for c in self.changes if c < -self.flat_below)

    @property
    def net_change_pct(self) -> float:
        """The window's moves compounded: first close to last close when built from closes."""
        return math.expm1(sum(self.steps)) * 100.0

    @property
    def efficiency(self) -> float:
        """Net log move / total absolute log move, in [-1, 1]. 0 if it never moved."""
        travelled = sum(abs(s) for s in self.steps)
        return sum(self.steps) / travelled if travelled else 0.0

    @property
    def score(self) -> float:
        """``efficiency`` as -100..+100, the number the page shows."""
        return self.efficiency * 100.0

    @property
    def streak(self) -> int:
        """Consecutive up (+) or down (-) days ending on the last day; 0 if the last day was flat."""
        count, sign = 0, 0
        for change in reversed(self.changes):
            day = 1 if change > self.flat_below else -1 if change < -self.flat_below else 0
            if day == 0 or (sign and day != sign):
                break
            sign, count = day, count + 1
        return sign * count


def window_dates(rows: Dict[Tuple[str, str], dict], window: int) -> List[str]:
    """The last ``window + 1`` trading days in the file (one extra for the first move's base).

    Empty if the file has fewer days than that.
    """
    days = trading_days(rows)
    if window < 1 or len(days) < window + 1:
        return []
    return days[-1 - window:]


def consistency_rows(
    rows: Dict[Tuple[str, str], dict],
    window: int,
    symbols: Optional[Iterable[str]] = None,
    exclude: Optional[Set[Tuple[str, str]]] = None,
) -> Tuple[List[ConsistencyRow], List[str]]:
    """One row per stock that has a close on **every** day of the window.

    Returns ``(rows, left_out)``, where ``left_out`` lists the symbols missing at
    least one day. Their row would hide a gap or span two days in one cell, so
    they are listed rather than shown. ``exclude`` is a set of (symbol, date) pairs,
    such as suspected splits. A stock with one of those inside the window is left
    out as well, because its "move" that day is a price adjustment.
    """
    span = window_dates(rows, window)
    if not span:
        return [], []
    wanted = set(symbols) if symbols is not None else {s for _, s in rows}
    skip = {s for s, d in (exclude or set()) if span[0] < d <= span[-1]}
    result, left_out = [], []
    for symbol in sorted(wanted):
        if symbol in skip:
            continue
        closes = [_number((rows.get((day, symbol)) or {}).get("close")) for day in span]
        if any(c is None for c in closes):
            left_out.append(symbol)
            continue
        result.append(ConsistencyRow(symbol, span[1:], closes))
    return result, left_out


def sort_key(row: ConsistencyRow, metric: str) -> tuple:
    """Rank on ``metric``, with the net change, then the symbol, breaking ties."""
    if metric == METRIC_UP_DAYS:
        return (row.up_days - row.down_days, row.net_change_pct, row.symbol)
    if metric == METRIC_NET_CHANGE:
        return (row.net_change_pct, row.symbol)
    return (round(row.efficiency, 9), row.net_change_pct, row.symbol)


def rank(rows: List[ConsistencyRow], metric: str = METRIC_CONSISTENCY, best_first: bool = True) -> List[ConsistencyRow]:
    """Rows ordered by ``metric``: strongest first, or weakest first with ``best_first=False``."""
    return sorted(rows, key=lambda r: sort_key(r, metric), reverse=best_first)


def leaders(rows: List[ConsistencyRow], metric: str, limit: int) -> Tuple[List[ConsistencyRow], List[ConsistencyRow]]:
    """``(gainers, losers)``: the ``limit`` strongest rows and the ``limit`` weakest.

    Gainers must have risen over the window and losers fallen, so a market where
    everything fell does not show "consistent gainers" that are really small losers.
    """
    gainers = [r for r in rank(rows, metric, best_first=True) if r.net_change_pct > 0][:limit]
    losers = [r for r in rank(rows, metric, best_first=False) if r.net_change_pct < 0][:limit]
    return gainers, losers
