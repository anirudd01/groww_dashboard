"""Market breadth over the stored F&O history: how many stocks take part in a move.

An index can rise on a handful of heavyweights while most stocks fall. Breadth
counts the stocks instead. For each trading day in the stored daily closes (``daily_bars`` in ``data/market.db``):

* **advances / declines**: stocks that closed above / below their previous close;
* **A/D line**: running total of advances minus declines, so it rises when more
  stocks go up than down, however big the moves;
* **% above the 20- and 50-day average**: share of stocks whose close is above
  their own simple moving average (only stocks with a full window count);
* **new highs / lows**: stocks closing above / below every close of the
  previous N days (closes, not intraday highs, as the file is a close history);
* **equal-weight index**: the average stock, for context.

Descriptive only: it says what happened, not what will.
"""

from dataclasses import dataclass

import pandas as pd

from market.price_panel import daily_returns, equal_weight_index

SHORT_MA = 20
LONG_MA = 50
HIGH_LOW_DAYS = 20

#: % of stocks above their 50-day average at or above which breadth reads "broad strength".
STRONG_PCT = 60.0
#: At or below this it reads "broad weakness"; in between, "mixed".
WEAK_PCT = 40.0


def breadth_table(
    closes: pd.DataFrame,
    short_ma: int = SHORT_MA,
    long_ma: int = LONG_MA,
    high_low_days: int = HIGH_LOW_DAYS,
) -> pd.DataFrame:
    """One row per day (from the second stored day) with every breadth measure.

    Columns: ``advances, declines, unchanged, traded, net, ad_line,
    pct_above_short, pct_above_long, new_highs, new_lows, ew_index``.
    ``pct_above_*`` is NaN on days where no stock has a full window yet.
    """
    if closes.empty or len(closes) < 2:
        return pd.DataFrame()
    change = daily_returns(closes)
    advances = (change > 0).sum(axis=1)
    declines = (change < 0).sum(axis=1)
    traded = change.notna().sum(axis=1)

    def pct_above(window: int) -> pd.Series:
        average = closes.rolling(window, min_periods=window).mean()
        has = average.notna() & closes.notna()
        above = (closes > average) & has
        counted = has.sum(axis=1)
        return (above.sum(axis=1) / counted * 100).where(counted > 0)

    prior_max = closes.shift(1).rolling(high_low_days, min_periods=high_low_days).max()
    prior_min = closes.shift(1).rolling(high_low_days, min_periods=high_low_days).min()

    table = pd.DataFrame({
        "advances": advances,
        "declines": declines,
        "unchanged": traded - advances - declines,
        "traded": traded,
        "net": advances - declines,
        "pct_above_short": pct_above(short_ma),
        "pct_above_long": pct_above(long_ma),
        "new_highs": (closes > prior_max).sum(axis=1),
        "new_lows": (closes < prior_min).sum(axis=1),
        "ew_index": equal_weight_index(closes),
    }).iloc[1:]
    table["ad_line"] = table["net"].cumsum()
    # Before a full high/low window exists nothing can be a new high, so those days are NaN, not 0.
    has_window = prior_max.notna().any(axis=1).iloc[1:]
    table.loc[~has_window, ["new_highs", "new_lows"]] = float("nan")
    return table


@dataclass
class Regime:
    label: str
    detail: str


def regime(pct_above_long: float) -> Regime:
    """A plain-words reading of % above the 50-day average. Descriptive, not a signal."""
    if pct_above_long != pct_above_long:  # NaN
        return Regime("Not enough history", f"Needs {LONG_MA} stored days.")
    if pct_above_long >= STRONG_PCT:
        return Regime("Broad strength", f"{pct_above_long:.0f}% of stocks are above their {LONG_MA}-day average.")
    if pct_above_long <= WEAK_PCT:
        return Regime("Broad weakness", f"Only {pct_above_long:.0f}% of stocks are above their {LONG_MA}-day average.")
    return Regime("Mixed", f"{pct_above_long:.0f}% of stocks are above their {LONG_MA}-day average.")
