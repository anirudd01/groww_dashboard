"""Shared plumbing for the F&O insight pages (breadth, overnight/intraday, rotation, gap fills).

Cached loaders keyed by when the database last changed, so a fresh run of
the update scripts shows up on the next rerun, plus the guard and sidebar
widgets every page repeats. Nothing here calls a broker.
"""

import pandas as pd
import streamlit as st

from market.fno_movers import (
    UPDATE_SCRIPT,
    closes_available,
    closes_stamp,
    load_closes,
    load_confirmed_moves,
    load_universe,
    suspected_corporate_actions,
)
from market.market_hours import now_ist
from market.price_panel import UNIVERSES, blank_out, price_panel, universe_sets
from market.universe import get_universe

#: The history is called stale once its last day is this many calendar days old.
STALE_AFTER_DAYS = 4


@st.cache_data(ttl="10m", show_spinner=False)
def _panels(stamp: float, hide_suspected: bool):
    """The panels, rebuilt when ``stamp`` (when the database last changed) moves on."""
    rows = load_closes()
    actions = suspected_corporate_actions(rows, load_confirmed_moves())
    pairs = [(a.symbol, a.date) for a in actions] if hide_suspected else []
    return {
        field: blank_out(price_panel(rows, field), pairs)
        for field in ("open", "high", "low", "close", "volume")
    }, len(actions)


def require_history():
    """The F&O universe, or stop the page with the reason (nothing stored yet)."""
    universe = load_universe()
    if not universe.is_usable:
        st.error(universe.error, icon=":material/error:")
        st.stop()
    if not closes_available():
        st.error(f"No close history stored. Run 'python {UPDATE_SCRIPT}'.", icon=":material/error:")
        st.stop()
    return universe


def panels(hide_suspected: bool = True):
    """``({field: date x symbol frame}, suspected_count)`` from the stored closes.

    With ``hide_suspected``, a suspected split's day is blanked, so it is never read
    as a market move (the stock's other days stay).
    """
    return _panels(closes_stamp(), hide_suspected)


def universe_options(universe) -> dict:
    nifty50 = get_universe("NIFTY50").symbols
    return universe_sets(universe.tokens, nifty50)


def universe_picker(universe, key: str, default: str = UNIVERSES[0], container=None):
    """Sidebar segmented control for Nifty 50 / All F&O / F&O outside Nifty 50. Returns (label, symbols)."""
    options = universe_options(universe)
    where = container or st.sidebar
    label = where.segmented_control("Stocks", list(UNIVERSES), default=default, required=True, key=key)
    return label, options[label]


def suspected_toggle(key: str) -> bool:
    return st.sidebar.toggle("Hide suspected splits/bonuses", value=True, key=key,
                             help="Blank a stock's day when its fall matches a split or bonus ratio, so a price "
                                  "adjustment is not read as a market move.")


def freshness(last_day, script: str = UPDATE_SCRIPT) -> None:
    """Warn when the data ends more than ``STALE_AFTER_DAYS`` calendar days ago."""
    if last_day is None:
        return
    age = (pd.Timestamp(now_ist().date()) - pd.Timestamp(last_day).normalize()).days
    if age > STALE_AFTER_DAYS:
        st.warning(f"The data ends on {pd.Timestamp(last_day):%a %d %b %Y}. Run 'python {script}' to catch up.",
                   icon=":material/history:")


def source_caption(extra: str = "") -> None:
    st.caption(f"Data: the stored daily closes in data/market.db (daily candles from Kite, written by {UPDATE_SCRIPT}). "
               "No live prices and no API call on this page. " + extra)
