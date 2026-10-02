"""Overnight vs intraday: where each stock's move was made.

Every close-to-close move has two parts:

* **overnight**: previous close to today's open, the gap, made while the market was shut;
* **intraday**: today's open to today's close, made during the session.

Summed over a window (as log returns, so the parts add up exactly to the total)
this shows whether a stock's trend comes from gaps, from the session, or from
both, and whether the two fight each other (gaps up, then sold all day).

Source: ``open`` and ``close`` in the stored daily closes (``daily_bars``). The open is
Kite's daily-candle open, NSE's official pre-open auction price. A day counts
only if the stock also has a row on the previous trading day in the file, so a
gap in the data is never read as one overnight move.
"""

import numpy as np
import pandas as pd

#: Overnight share of the total move (by absolute log size) at or above which a stock is "gap-driven".
GAP_DRIVEN_SHARE = 0.65


def split_returns(opens: pd.DataFrame, closes: pd.DataFrame):
    """``(overnight, intraday)`` log-return frames, date x symbol, NaN where a day is missing."""
    opens, closes = opens.align(closes, join="outer")
    overnight = np.log(opens / closes.shift(1))
    intraday = np.log(closes / opens)
    both = overnight.notna() & intraday.notna()
    return overnight.where(both), intraday.where(both)


def last_days(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    return frame.iloc[-window:] if window and window < len(frame) else frame


def split_summary(overnight: pd.DataFrame, intraday: pd.DataFrame, window: int) -> pd.DataFrame:
    """One row per stock over the last ``window`` days.

    Columns: ``days, overnight_pct, intraday_pct, total_pct, gap_up_days,
    overnight_share, pattern``. The ``*_pct`` columns are compounded % moves; total
    = overnight and intraday compounded together. ``overnight_share`` is the
    overnight part's share of the absolute log movement, from 0 (all intraday) to 1
    (all gaps).
    """
    on = last_days(overnight, window)
    intra = last_days(intraday, window)
    days = on.notna().sum()
    on_log, in_log = on.sum(), intra.sum()
    size = on_log.abs() + in_log.abs()
    summary = pd.DataFrame({
        "days": days,
        "overnight_pct": np.expm1(on_log) * 100,
        "intraday_pct": np.expm1(in_log) * 100,
        "total_pct": np.expm1(on_log + in_log) * 100,
        "gap_up_days": (on > 0).sum(),
        "overnight_share": (on_log.abs() / size).where(size > 0, 0.5),
    })
    summary = summary[summary["days"] > 0]
    summary["pattern"] = [pattern(o, i) for o, i in zip(summary["overnight_pct"], summary["intraday_pct"])]
    summary.index.name = "symbol"
    return summary


def pattern(overnight_pct: float, intraday_pct: float) -> str:
    """Which part made the move, in words."""
    total = abs(overnight_pct) + abs(intraday_pct)
    if total == 0:
        return "Flat"
    if (overnight_pct > 0) != (intraday_pct > 0) and overnight_pct and intraday_pct:
        return "Gaps up, sold in session" if overnight_pct > 0 else "Gaps down, bought in session"
    share = abs(overnight_pct) / total
    direction = "up" if overnight_pct + intraday_pct > 0 else "down"
    if share >= GAP_DRIVEN_SHARE:
        return f"Gap-driven {direction}"
    if share <= 1 - GAP_DRIVEN_SHARE:
        return f"Session-driven {direction}"
    return f"Both, {direction}"


def universe_split(overnight: pd.DataFrame, intraday: pd.DataFrame, window: int) -> pd.DataFrame:
    """The average stock, day by day: cumulative overnight, intraday and total %, from 0."""
    on = last_days(overnight, window).mean(axis=1).fillna(0.0)
    intra = last_days(intraday, window).mean(axis=1).fillna(0.0)
    return pd.DataFrame({
        "Overnight": np.expm1(on.cumsum()) * 100,
        "Intraday": np.expm1(intra.cumsum()) * 100,
        "Total": np.expm1((on + intra).cumsum()) * 100,
    })
