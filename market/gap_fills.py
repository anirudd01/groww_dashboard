"""Gap fills: after a stock opens away from yesterday's close, does it come back?

A gap is "filled" when the price trades back to the previous close during the
same session: a gap-up fills when a minute bar's low reaches the previous close,
and a gap-down fills when a high does. The time to fill is measured from 09:15.

Sources, both in ``data/market.db`` (``scripts/backfill_intraday.py``):

* the gap itself comes from the ``daily_gaps`` view (official open against the
  previous official close, from daily candles; see ``market/intraday_store.py``
  for why never from minute bars);
* the fill comes from ``minute_bars`` for that day.

A day is used only if it has a full session of minute bars (``MIN_SESSION_BARS``),
so a backfill that stopped mid-session cannot pass for a gap that never filled.

Continuous trading ends at 15:15 (since August 2026). 15:15-15:30 is the closing
auction, which has no minute bars (docs/INTRADAY_HISTORY.md). A gap whose official
close is back through the previous close, but which no minute bar reached, filled
in that auction. It counts as filled at 15:15 (``AUCTION_MINUTE``).
"""

from typing import Optional

import numpy as np
import pandas as pd

from market.intraday_store import DB_PATH, connect_readonly

#: Gaps smaller than this are not loaded at all (the page's smallest threshold).
MIN_LOADED_GAP_PCT = 0.25
#: A full day is 360 one-minute bars (09:15-15:14) since August 2026, 375 (to 15:29) before.
#: Below this a day is incomplete; the slack allows a few missing minutes.
MIN_SESSION_BARS = 350
#: Minutes from 09:15 to the closing auction, the fill time given to auction-only fills.
AUCTION_MINUTE = 360
SESSION_OPEN = "09:15"
SESSION_LAST_BAR = "15:29"

#: Gap-size buckets for the fill-rate chart: (label, lower bound inclusive, upper bound exclusive), in |gap| %.
BUCKETS = (("0.25–0.5%", 0.25, 0.5), ("0.5–1%", 0.5, 1.0), ("1–2%", 1.0, 2.0),
           ("2–3%", 2.0, 3.0), ("3%+", 3.0, float("inf")))

OUTCOME_FILLED = "Filled"
OUTCOME_GO = "Gap and go"
OUTCOME_HELD = "Held, faded"
OUTCOMES = (OUTCOME_FILLED, OUTCOME_HELD, OUTCOME_GO)

GAPS_SQL = f"""
SELECT g.symbol, g.date, g.prev_close, g.open, g.close, g.gap_pct,
       (SELECT MIN(m.ts) FROM minute_bars m
         WHERE m.symbol = g.symbol
           AND m.ts BETWEEN g.date || ' {SESSION_OPEN}' AND g.date || ' {SESSION_LAST_BAR}'
           AND ((g.gap_pct > 0 AND m.low <= g.prev_close)
             OR (g.gap_pct < 0 AND m.high >= g.prev_close))) AS fill_ts,
       (SELECT COUNT(*) FROM minute_bars m
         WHERE m.symbol = g.symbol
           AND m.ts BETWEEN g.date || ' {SESSION_OPEN}' AND g.date || ' {SESSION_LAST_BAR}') AS bars
FROM daily_gaps g
WHERE ABS(g.gap_pct) >= ?
"""


def load_gaps(path: str = DB_PATH, min_gap_pct: float = MIN_LOADED_GAP_PCT) -> pd.DataFrame:
    """Every gap of at least ``min_gap_pct`` on a complete session, with its fill.

    Columns: ``symbol, date, prev_close, open, close, gap_pct, abs_gap, direction,
    filled, fill_minutes, outcome, bucket``. Empty frame if the store is missing.
    Read-only: it never creates or writes the database.
    """
    conn = connect_readonly(path)
    if conn is None:
        return pd.DataFrame()
    try:
        raw = pd.read_sql_query(GAPS_SQL, conn, params=(min_gap_pct,))
    finally:
        conn.close()
    return classify(raw)


def classify(raw: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns to raw gap rows (split out so it can be tested without SQLite)."""
    if raw.empty:
        return raw.assign(abs_gap=[], direction=[], filled=[], fill_minutes=[], outcome=[], bucket=[])
    gaps = raw[raw["bars"] >= MIN_SESSION_BARS].drop(columns="bars").copy()
    gaps["abs_gap"] = gaps["gap_pct"].abs()
    gaps["direction"] = np.where(gaps["gap_pct"] > 0, "Gap up", "Gap down")
    up = gaps["gap_pct"] > 0
    fill_time = pd.to_datetime(gaps["fill_ts"], format="%Y-%m-%d %H:%M", errors="coerce")
    open_time = pd.to_datetime(gaps["date"] + " " + SESSION_OPEN, format="%Y-%m-%d %H:%M")
    gaps["fill_minutes"] = (fill_time - open_time).dt.total_seconds() / 60
    in_auction = gaps["fill_ts"].isna() & np.where(up, gaps["close"] <= gaps["prev_close"],
                                                    gaps["close"] >= gaps["prev_close"])
    gaps.loc[in_auction, "fill_minutes"] = AUCTION_MINUTE
    gaps["filled"] = gaps["fill_minutes"].notna()
    beyond_open = np.where(up, gaps["close"] > gaps["open"], gaps["close"] < gaps["open"])
    gaps["outcome"] = np.select(
        [gaps["filled"], beyond_open], [OUTCOME_FILLED, OUTCOME_GO], default=OUTCOME_HELD)
    gaps["bucket"] = bucket_of(gaps["abs_gap"])
    return gaps.drop(columns="fill_ts").reset_index(drop=True)


def bucket_of(abs_gap: pd.Series) -> pd.Series:
    labels = pd.Series("", index=abs_gap.index)
    for label, low, high in BUCKETS:
        labels[(abs_gap >= low) & (abs_gap < high)] = label
    return labels


def fill_rates(gaps: pd.DataFrame) -> pd.DataFrame:
    """Fill rate by gap-size bucket and direction: ``bucket, direction, gaps, filled_pct``."""
    if gaps.empty:
        return pd.DataFrame(columns=["bucket", "direction", "gaps", "filled_pct"])
    order = [b[0] for b in BUCKETS]
    table = (gaps.groupby(["bucket", "direction"], observed=True)["filled"]
             .agg(gaps="size", filled_pct="mean").reset_index())
    table["filled_pct"] *= 100
    table["bucket"] = pd.Categorical(table["bucket"], categories=order, ordered=True)
    return table.sort_values(["bucket", "direction"]).reset_index(drop=True)


def fill_curve(gaps: pd.DataFrame, step: int = 5) -> pd.DataFrame:
    """Cumulative % of gaps filled by each minute after 09:15, per direction (index: minutes)."""
    minutes = np.arange(0, AUCTION_MINUTE + step, step)
    curves = {}
    for direction, group in gaps.groupby("direction"):
        filled = group["fill_minutes"].dropna().to_numpy()
        curves[direction] = [(filled <= m).sum() / len(group) * 100 for m in minutes]
    return pd.DataFrame(curves, index=pd.Index(minutes, name="minutes"))


def per_stock(gaps: pd.DataFrame, min_gaps: int = 3) -> pd.DataFrame:
    """Per stock: gaps, fill rates overall / up / down, median minutes to fill, gap-and-go rate."""
    if gaps.empty:
        return pd.DataFrame()
    grouped = gaps.groupby("symbol")
    table = pd.DataFrame({
        "gaps": grouped.size(),
        "filled_pct": grouped["filled"].mean() * 100,
        "up_filled_pct": gaps[gaps["gap_pct"] > 0].groupby("symbol")["filled"].mean() * 100,
        "down_filled_pct": gaps[gaps["gap_pct"] < 0].groupby("symbol")["filled"].mean() * 100,
        "median_fill_minutes": grouped["fill_minutes"].median(),
        "gap_and_go_pct": grouped["outcome"].apply(lambda s: (s == OUTCOME_GO).mean() * 100),
        "avg_abs_gap": grouped["abs_gap"].mean(),
    })
    return table[table["gaps"] >= min_gaps].sort_values(["filled_pct", "gaps"], ascending=False)


def filter_gaps(gaps: pd.DataFrame, min_gap: float, symbols: Optional[set] = None,
                direction: Optional[str] = None) -> pd.DataFrame:
    out = gaps[gaps["abs_gap"] >= min_gap]
    if symbols is not None:
        out = out[out["symbol"].isin(symbols)]
    if direction:
        out = out[out["direction"] == direction]
    return out
