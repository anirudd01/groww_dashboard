"""F&O and MCX positions from Groww, priced and described for the F&O dashboard.

What a Groww position carries (docs/api/GROWW_API_PORTFOLIO.md): signed net ``quantity``,
``credit_*`` for what was bought and ``debit_*`` for what was sold (and ``carry_forward_*`` for
earlier days), ``net_price``, ``product`` and ``realised_pnl``. It carries no expiry, strike,
lot size, tick size or Greeks; those come from the instrument list (groww_api/instruments.py)
and, for Greeks, from ``get_greeks``.

Rules this module keeps, each one a bug it used to have:

* **Shorts are positions too.** Quantity is negative, P&L is ``quantity * (ltp - entry)``, and
  values are notional (``|quantity| * price``) so they add up across longs and shorts.
* **No price means no P&L.** Groww refuses market data without the paid data plan; the price,
  value and P&L are then None, never the entry price passed off as a live one.
* **The entry price is the open quantity's cost, not ``net_price``.** ``net_price`` is the
  average of every buy, so after a partial exit it double-counts what ``realised_pnl`` already
  booked (GOLD, 2026-10-16: 500 bought, 400 sold; ``net_price`` 148240.8, real cost of the last
  100 148400). See ``open_entry_price``.
* **Closed today still counts.** A position squared off today has quantity 0 and a realised P&L;
  it is kept so that P&L is not lost.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from groww_api.api_calls import GrowwAPIService
from groww_api.instruments import ContractInfo, contracts_by_symbol
from utils import ASSET_TYPE_COMMODITY, ASSET_TYPE_EQUITY

logger = logging.getLogger(__name__)

DERIVATIVE_SEGMENTS = ("FNO", "COMMODITY")


def _number(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def open_entry_price(p: Dict[str, Any]) -> float:
    """Average cost of the open quantity, in rupees; 0.0 when the position is flat.

    Groww's ``realised_pnl`` is what the closed part made, so the open part's cost is whatever of
    the money in and out it does not explain: (bought - sold + realised) / quantity. That holds for
    longs and shorts (quantity is signed) and equals ``net_price`` when nothing was closed. Falls
    back to ``net_price``, then the opening side's price, if the fills do not add up to a price.
    """
    quantity = _number(p.get("quantity"))
    if not quantity:
        return 0.0
    bought = (_number(p.get("credit_quantity")) * _number(p.get("credit_price"))
              + _number(p.get("carry_forward_credit_quantity")) * _number(p.get("carry_forward_credit_price")))
    sold = (_number(p.get("debit_quantity")) * _number(p.get("debit_price"))
            + _number(p.get("carry_forward_debit_quantity")) * _number(p.get("carry_forward_debit_price")))
    entry = (bought - sold + _number(p.get("realised_pnl"))) / quantity
    if entry > 0:
        return entry
    entry = _number(p.get("net_price"))
    if entry > 0:
        return entry
    return _number(p.get("credit_price") if quantity > 0 else p.get("debit_price"))


def build_position(p: Dict[str, Any], ltp: Optional[float], info: Optional[ContractInfo]) -> Dict[str, Any]:
    """One raw Groww position as the dashboard's row. ``ltp`` None means it could not be priced."""
    symbol = p.get("trading_symbol", "UNKNOWN")
    exchange = str(p.get("exchange") or "NSE").upper()
    quantity = int(_number(p.get("quantity")))
    entry = open_entry_price(p)
    ltp = float(ltp) if ltp is not None and ltp > 0 else None

    entry_value = abs(quantity) * entry
    if quantity == 0:
        total_value, pnl, pnl_pct = 0.0, 0.0, 0.0
    elif ltp is None:
        total_value = pnl = pnl_pct = None
    else:
        total_value = abs(quantity) * ltp
        pnl = quantity * (ltp - entry)
        pnl_pct = pnl / entry_value * 100.0 if entry_value > 0 else 0.0

    return {
        "symbol": symbol,
        "type": ASSET_TYPE_COMMODITY if exchange == "MCX" else ASSET_TYPE_EQUITY,
        "exchange": exchange,
        "segment": str(p.get("segment") or "").upper(),
        "product": p.get("product") or "",
        "quantity": quantity,
        "side": "LONG" if quantity > 0 else "SHORT" if quantity < 0 else "CLOSED",
        "entry_price": round(entry, 2),
        "ltp": round(ltp, 2) if ltp is not None else None,
        "priced": quantity == 0 or ltp is not None,
        "entry_value": round(entry_value, 2),
        "total_value": round(total_value, 2) if total_value is not None else None,
        "unrealized_pnl": round(pnl, 2) if pnl is not None else None,
        "unrealized_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "realised_pnl": round(_number(p.get("realised_pnl")), 2),
        # From the instrument list; None when the contract was not found there.
        "underlying": info.underlying if info else symbol,
        "kind": info.kind if info else "UNKNOWN",
        "expiry_date": info.expiry_date if info else None,
        "strike": info.strike if info else None,
        "lot_size": info.lot_size if info else None,
        "tick": info.tick if info else None,
    }


class PositionProcessor:
    """Builds the F&O dashboard's positions from Groww's positions, prices and instrument list."""

    def __init__(self, api_service: GrowwAPIService):
        self.api = api_service

    def _contracts(self, positions) -> Dict[Tuple[str, str], ContractInfo]:
        try:
            instruments = self.api.get_instruments()
        except Exception as e:
            logger.warning("Groww instrument list unavailable, so no expiry, lot or tick size: %s", e)
            return {}
        keys = [(str(p.get("exchange") or "NSE"), p.get("trading_symbol", "")) for p in positions]
        return contracts_by_symbol(instruments, keys)

    def get_fno_positions(self) -> List[Dict[str, Any]]:
        """Open F&O and MCX positions, plus any closed today that still carry a realised P&L."""
        positions = [
            p for p in self.api.get_positions()
            if str(p.get("segment", "")).upper() in DERIVATIVE_SEGMENTS
            and (int(_number(p.get("quantity"))) != 0 or _number(p.get("realised_pnl")) != 0)
        ]
        if not positions:
            return []

        open_symbols = {"MCX": [], "NSE": []}
        for p in positions:
            if int(_number(p.get("quantity"))) != 0:
                exchange = "MCX" if str(p.get("exchange", "")).upper() == "MCX" else "NSE"
                open_symbols[exchange].append(p["trading_symbol"])

        ltp_map: Dict[str, float] = {}
        if open_symbols["NSE"]:
            ltp_map.update(self.api.get_ltp_for_nse_fno(open_symbols["NSE"]))
        if open_symbols["MCX"]:
            ltp_map.update(self.api.get_ltp_for_mcx(open_symbols["MCX"]))
        wanted = len(open_symbols["NSE"]) + len(open_symbols["MCX"])
        if len(ltp_map) < wanted:
            logger.warning("Priced %d of %d open F&O positions; the rest show no P&L", len(ltp_map), wanted)

        contracts = self._contracts(positions)
        return [
            build_position(p, ltp_map.get(p.get("trading_symbol")),
                           contracts.get((str(p.get("exchange") or "NSE").upper(), p.get("trading_symbol"))))
            for p in positions
        ]

    def get_option_greeks(self, positions: List[Dict[str, Any]]) -> Tuple[Dict[str, dict], Optional[str]]:
        """``({symbol: greeks}, error)`` for the open option positions.

        MCX options are skipped: on the paid plan ``get_greeks`` answers "Internal error occurred"
        for every MCX option tried (2026-10-18) and the option chain does not know MCX underlyings.
        Stops at the first other failure: without the data plan every call is refused the same
        way, so the reason is reported once instead of being retried per contract.
        """
        greeks: Dict[str, dict] = {}
        error = None
        for pos in positions:
            if pos.get("kind") not in ("CALL", "PUT") or not pos.get("quantity") or not pos.get("expiry_date"):
                continue
            if pos.get("exchange") == "MCX":
                error = "Groww gives no Greeks for MCX options."
                continue
            try:
                greeks[pos["symbol"]] = self.api.get_greeks(
                    exchange=pos["exchange"], underlying=pos["underlying"],
                    trading_symbol=pos["symbol"], expiry=pos["expiry_date"])
            except Exception as e:
                return greeks, str(e)
        return greeks, error
