"""What the TradingView dashboard shows, grouped the way it is read.

TradingView widgets only stream exchanges TradingView has licensed for
third-party embedding. **NSE, MCX, NSEIX (GIFT Nifty), NYMEX and ICE are not
among them**: a widget pointed at ``MCX:CRUDEOIL1!`` or ``NSE:NIFTY`` renders
"Permission denied - This symbol is only available on TradingView". So each
instrument the user asked for is either

* shown through the closest symbol that *does* stream (a CFD or ETF proxy,
  with ``note`` saying what it stands in for), or
* listed in ``unavailable`` - rendered as a link to its TradingView page,
  never as a broken widget.

Every symbol here was checked in a real browser on 2026-09-26; the method and
the full result table are in docs/TRADINGVIEW_WIDGETS.md ("Symbol
availability"). Re-check there before adding a symbol.

Pure data - no Streamlit, no network.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

# Mini Chart ``time-frame`` values, in the order the sidebar offers them.
# Keys are the attribute values TradingView accepts; values are the labels
# its own wizard shows.
TIME_FRAMES = {
    "1D": "1 day",
    "7D": "1 week",
    "1M": "1 month",
    "3M": "3 months",
    "6M": "6 months",
    "12M": "1 year",
    "60M": "5 years",
    "YTD": "Year to date",
    "ALL": "All",
}


@dataclass(frozen=True)
class Instrument:
    """One symbol a widget can display.

    ``min_time_frame`` is set for end-of-day feeds (BSE): their widgets reject
    intraday ranges with "Unsupported interval", so the chart falls back to
    this range when the chosen one is shorter.
    """

    label: str
    symbol: str  # TradingView "EXCHANGE:TICKER"
    note: str = ""
    min_time_frame: Optional[str] = None


@dataclass(frozen=True)
class UnavailableInstrument:
    """Something the user wants that no widget can stream. Shown as a link."""

    label: str
    symbol: str
    reason: str


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    icon: str  # Material Symbols name, e.g. ":material/oil_barrel:"
    instruments: Tuple[Instrument, ...]
    unavailable: Tuple[UnavailableInstrument, ...] = field(default_factory=tuple)
    caption: str = ""


_NOT_LICENSED = "exchange not licensed for TradingView widgets"

CATEGORIES: Tuple[Category, ...] = (
    Category(
        key="crude",
        title="Crude oil",
        icon=":material/oil_barrel:",
        caption="USD per barrel. MCX crude is priced off WTI, so WTI x USD/INR is its driver.",
        instruments=(
            Instrument("WTI crude", "TVC:USOIL", "CFD tracking NYMEX WTI front month"),
            Instrument("Brent crude", "TVC:UKOIL", "CFD tracking ICE Brent front month"),
        ),
        unavailable=(
            UnavailableInstrument("MCX Crude Oil", "MCX:CRUDEOIL1!", _NOT_LICENSED),
        ),
    ),
    Category(
        key="natgas",
        title="Natural gas",
        icon=":material/local_fire_department:",
        caption="USD per MMBtu. MCX natural gas is priced off NYMEX Henry Hub.",
        instruments=(
            Instrument(
                "Natural gas (Henry Hub)",
                "OANDA:NATGASUSD",
                "CFD tracking NYMEX Henry Hub front month",
            ),
        ),
        unavailable=(
            UnavailableInstrument("NYMEX Natural Gas", "NYMEX:NG1!", _NOT_LICENSED),
            UnavailableInstrument("MCX Natural Gas", "MCX:NATURALGAS1!", _NOT_LICENSED),
        ),
    ),
    Category(
        key="currencies",
        title="Currencies",
        icon=":material/currency_exchange:",
        caption="Interbank reference rates (ICE Data Services), real time.",
        instruments=(
            Instrument("USD / INR", "FX_IDC:USDINR"),
            Instrument("EUR / INR", "FX_IDC:EURINR"),
        ),
    ),
    Category(
        key="india",
        title="Indian markets",
        icon=":material/account_balance:",
        caption=(
            "NSE indices are not licensed for widgets, so Nifty is shown through the "
            "BSE-listed index ETFs that track it. BSE data is end of day."
        ),
        instruments=(
            Instrument(
                "Nifty 50 (NIFTYBEES)",
                "BSE:NIFTYBEES",
                "Nippon India Nifty 50 ETF - tracks the Nifty 50",
                min_time_frame="3M",
            ),
            Instrument(
                "Nifty Next 50 (JUNIORBEES)",
                "BSE:JUNIORBEES",
                "Nippon India Nifty Next 50 ETF - tracks the Nifty Next 50",
                min_time_frame="3M",
            ),
            Instrument("Sensex", "BSE:SENSEX", "BSE's own index", min_time_frame="3M"),
        ),
        unavailable=(
            UnavailableInstrument("Nifty 50", "NSE:NIFTY", _NOT_LICENSED),
            UnavailableInstrument("Nifty Next 50", "NSE:NIFTYJR", _NOT_LICENSED),
            UnavailableInstrument("GIFT Nifty", "NSEIX:NIFTY1!", _NOT_LICENSED),
        ),
    ),
)

_TIME_FRAME_ORDER = tuple(TIME_FRAMES)
# YTD and ALL are not points on the 1D..60M scale; treat them as long enough
# for any end-of-day feed.
_LONG_RANGES = {"YTD", "ALL"}


def effective_time_frame(instrument: Instrument, requested: str) -> str:
    """The range to chart ``instrument`` over, given the user's choice.

    End-of-day feeds cannot draw intraday ranges, so a request shorter than
    ``min_time_frame`` is lifted to it. Everything else is passed through.
    """
    floor = instrument.min_time_frame
    if not floor or requested in _LONG_RANGES:
        return requested
    if requested not in _TIME_FRAME_ORDER or floor not in _TIME_FRAME_ORDER:
        return requested
    if _TIME_FRAME_ORDER.index(requested) < _TIME_FRAME_ORDER.index(floor):
        return floor
    return requested


def symbol_page_url(symbol: str) -> str:
    """tradingview.com page for a symbol: ``MCX:CRUDEOIL1!`` -> ``.../symbols/MCX-CRUDEOIL1!/``."""
    exchange, _, ticker = symbol.partition(":")
    slug = f"{exchange}-{ticker}" if ticker else exchange
    return f"https://www.tradingview.com/symbols/{slug}/"


def all_instruments(categories: Tuple[Category, ...] = CATEGORIES) -> Tuple[Instrument, ...]:
    return tuple(i for c in categories for i in c.instruments)
