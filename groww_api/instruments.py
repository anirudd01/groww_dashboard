"""Contract facts from Groww's instrument list: lot size, tick size, expiry, strike, CE/PE/FUT.

Positions and orders carry only a trading symbol. Everything else about the contract comes from
here, never from parsing the symbol: Groww's symbols use three different date layouts, and a
regex that fits one misreads the others.

* ``NIFTY26OCTFUT`` - NSE monthly: year, then month (expires 27 Oct 2026, not on the 26th)
* ``NIFTY26O1918150CE`` - NSE weekly: year, one-letter month, day (19 Oct 2026)
* ``GOLD04DEC26FUT`` - MCX: day, month, year

Units, checked against the live CSV on 2026-10-17 (docs/api/GROWW_API_INSTRUMENTS.md):

* Every column is text (the SDK reads the CSV with ``dtype=str``).
* MCX ``tick_size`` is in **paise**: GOLD and CRUDEOIL 100.0 (Rs 1), NATURALGAS 10.0 (Rs 0.10),
  COPPER 5.0 (Rs 0.05). NSE and BSE ticks are in rupees (NIFTY options 0.05).
* ``lot_size`` is the quantity of one lot, in the same unit as position and order quantities:
  NIFTY 65, GOLD 100, GOLDM 10, CRUDEOIL 100, CRUDEOILM 10.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Dict, Iterable, Optional, Tuple

#: Exchanges whose ``tick_size`` column is in paise rather than rupees.
PAISE_TICK_EXCHANGES = {"MCX"}

OPTION_KINDS = {"CE": "CALL", "PE": "PUT"}


@dataclass(frozen=True)
class ContractInfo:
    trading_symbol: str
    exchange: str
    instrument_type: str  # EQ, IDX, FUT, CE or PE
    underlying: str
    expiry_date: Optional[str]  # yyyy-mm-dd
    strike: Optional[float]
    lot_size: Optional[int]
    tick: Optional[Decimal]  # rupees

    @property
    def kind(self) -> str:
        """CALL, PUT or FUTURE (EQ/IDX come back as their own type)."""
        if self.instrument_type in OPTION_KINDS:
            return OPTION_KINDS[self.instrument_type]
        return "FUTURE" if self.instrument_type == "FUT" else self.instrument_type


def _text(value) -> str:
    """A CSV cell as stripped text; pandas hands missing cells over as NaN floats."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _decimal(value) -> Optional[Decimal]:
    try:
        number = Decimal(_text(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def tick_in_rupees(exchange: str, tick_size) -> Optional[Decimal]:
    """The minimum price step in rupees, or None when the cell is blank or zero."""
    tick = _decimal(tick_size)
    if tick is None:
        return None
    return tick / 100 if _text(exchange).upper() in PAISE_TICK_EXCHANGES else tick


def contract_from_row(row: dict) -> ContractInfo:
    exchange = _text(row.get("exchange")).upper()
    lot = _decimal(row.get("lot_size"))
    strike = _decimal(row.get("strike_price"))
    return ContractInfo(
        trading_symbol=_text(row.get("trading_symbol")),
        exchange=exchange,
        instrument_type=_text(row.get("instrument_type")).upper(),
        underlying=_text(row.get("underlying_symbol")) or _text(row.get("trading_symbol")),
        expiry_date=_text(row.get("expiry_date")) or None,
        strike=float(strike) if strike is not None else None,
        lot_size=int(lot) if lot is not None else None,
        tick=tick_in_rupees(exchange, row.get("tick_size")),
    )


def contracts_by_symbol(instruments, keys: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str], ContractInfo]:
    """``{(exchange, trading_symbol): ContractInfo}`` for the wanted keys found in the instrument list.

    ``instruments`` is the DataFrame from ``GrowwAPI.get_all_instruments()``. Keys it does not
    contain are simply absent from the result.
    """
    wanted = {(str(e).upper(), str(s)) for e, s in keys}
    if not wanted or instruments is None:
        return {}
    symbols = {s for _, s in wanted}
    rows = instruments[instruments["trading_symbol"].isin(symbols)]
    found = {}
    for row in rows.to_dict("records"):
        info = contract_from_row(row)
        key = (info.exchange, info.trading_symbol)
        if key in wanted and key not in found:
            found[key] = info
    return found


def round_to_tick(price: float, tick: Decimal, up: bool) -> float:
    """``price`` moved onto the tick grid: up for a buy, down for a sell.

    Both directions move the price further through the market, so a marketable limit order
    stays marketable. Decimal arithmetic, because 0.05 steps in binary floats drift.
    """
    steps = (Decimal(str(price)) / tick).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR)
    return float(steps * tick)
