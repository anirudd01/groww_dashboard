"""Relative rotation (RRG-style): who is leading the market, and who is turning.

Each stock or sector is plotted against a benchmark on two axes:

* **RS-Ratio** (x): is it beating the benchmark? Relative strength ``RS = price /
  benchmark``. RS-Ratio is RS against its own ``lookback``-day average, x100, and
  smoothed over ``smooth`` days. Above 100 = outperforming lately.
* **RS-Momentum** (y): is that edge growing? RS-Ratio against its own value
  ``momentum`` days earlier, x100. Above 100 = relative strength improving.

That gives four quadrants, which names usually cycle through clockwise:

    Improving (x<100, y>100)  |  Leading   (x>100, y>100)
    --------------------------+--------------------------
    Lagging   (x<100, y<100)  |  Weakening (x>100, y<100)

The benchmark is an **equal-weight Nifty 50** built from its 50 members' closes,
because the repo stores no index series (see ``price_panel.equal_weight_index``).
These formulas are an open approximation of the idea. The JdK RS-Ratio and
RS-Momentum behind commercial RRG charts are proprietary, so values will not
match those charts.
"""

from typing import Dict, Iterable, List, Tuple

import pandas as pd

from market.price_panel import equal_weight_index

LOOKBACK = 20
MOMENTUM = 5
SMOOTH = 3

LEADING = "Leading"
WEAKENING = "Weakening"
LAGGING = "Lagging"
IMPROVING = "Improving"
QUADRANTS = (LEADING, WEAKENING, LAGGING, IMPROVING)


def sector_indices(closes: pd.DataFrame, sector_of: Dict[str, str]) -> pd.DataFrame:
    """One equal-weight index per sector (date x sector), from the members present in ``closes``."""
    members: Dict[str, List[str]] = {}
    for symbol, sector in sector_of.items():
        if symbol in closes.columns:
            members.setdefault(sector, []).append(symbol)
    return pd.DataFrame({sector: equal_weight_index(closes[symbols]) for sector, symbols in sorted(members.items())})


def rotation(
    series: pd.DataFrame,
    benchmark: pd.Series,
    lookback: int = LOOKBACK,
    momentum: int = MOMENTUM,
    smooth: int = SMOOTH,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """``(rs_ratio, rs_momentum)``, both date x name. NaN until enough history exists."""
    rs = series.div(benchmark, axis=0)
    ratio = 100 * rs / rs.rolling(lookback, min_periods=lookback).mean()
    if smooth > 1:
        ratio = ratio.rolling(smooth, min_periods=smooth).mean()
    mom = 100 * ratio / ratio.shift(momentum)
    return ratio, mom


def quadrant(ratio: float, mom: float) -> str:
    if ratio >= 100:
        return LEADING if mom >= 100 else WEAKENING
    return IMPROVING if mom >= 100 else LAGGING


def latest(ratio: pd.DataFrame, mom: pd.DataFrame, since: int = 5) -> pd.DataFrame:
    """Latest point per name with its quadrant, and the quadrant ``since`` days earlier.

    Names with no valid latest point are left out.
    """
    valid = ratio.notna() & mom.notna()
    if not valid.any().any():
        return pd.DataFrame(columns=["rs_ratio", "rs_momentum", "quadrant", "was"])
    rows = {}
    for name in ratio.columns:
        days = valid.index[valid[name]]
        if not len(days) or days[-1] != valid.index[-1]:
            continue
        r, m = ratio.at[days[-1], name], mom.at[days[-1], name]
        was = ""
        if len(days) > since:
            then = days[-1 - since]
            was = quadrant(ratio.at[then, name], mom.at[then, name])
        rows[name] = {"rs_ratio": r, "rs_momentum": m, "quadrant": quadrant(r, m), "was": was}
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "name"
    return table


def trails(ratio: pd.DataFrame, mom: pd.DataFrame, names: Iterable[str], length: int) -> pd.DataFrame:
    """Long frame ``name, date, rs_ratio, rs_momentum`` with the last ``length`` valid points per name."""
    parts = []
    for name in names:
        if name not in ratio.columns:
            continue
        frame = pd.DataFrame({"rs_ratio": ratio[name], "rs_momentum": mom[name]}).dropna().iloc[-length:]
        frame["name"] = name
        parts.append(frame.rename_axis("date").reset_index())
    if not parts:
        return pd.DataFrame(columns=["name", "date", "rs_ratio", "rs_momentum"])
    return pd.concat(parts, ignore_index=True)
