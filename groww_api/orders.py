"""Exit orders for F&O and MCX positions: side, quantity and a tick-aligned marketable limit price.

Only builds the order; ``GrowwAPIService.place_order`` sends it. Every refusal is a ValueError
whose message the dashboard shows as is, so a missing price or tick size stops the order instead
of letting Groww reject it (or worse, fill it at a made-up price).
"""

from decimal import Decimal
from typing import Any, Dict

from groww_api.instruments import round_to_tick

#: How far through the last price the exit limit is set, so it fills like a market order.
EXIT_SLIPPAGE = 0.005


def build_exit_order(pos: Dict[str, Any], slippage: float = EXIT_SLIPPAGE) -> Dict[str, Any]:
    """``place_order`` arguments that flatten one position from the position processor.

    A long is sold at ``ltp * (1 - slippage)`` rounded down to the tick, a short is bought back at
    ``ltp * (1 + slippage)`` rounded up. The product is the position's own (an NRML exit for an
    MIS position would open a new carry-forward position instead of closing the intraday one).
    """
    quantity = int(pos.get("quantity") or 0)
    if quantity == 0:
        raise ValueError("position is already flat")
    ltp = pos.get("ltp")
    if not ltp:
        raise ValueError("no live price for this contract (Groww's market data needs its paid data plan)")
    tick = pos.get("tick")
    if not tick:
        raise ValueError("tick size unknown: the contract is not in Groww's instrument list")
    lot = pos.get("lot_size")
    if lot and abs(quantity) % lot:
        raise ValueError(f"quantity {abs(quantity)} is not a whole number of lots of {lot}")

    sell = quantity > 0
    target = ltp * (1 - slippage) if sell else ltp * (1 + slippage)
    price = round_to_tick(target, Decimal(str(tick)), up=not sell)
    if price <= 0:
        # A long trading at one tick (a near-worthless option at 0.05) rounds down to 0.
        raise ValueError(f"exit price rounds to {price} at last price {ltp}; exit it in the Groww app")
    return {
        "trading_symbol": pos["symbol"],
        "quantity": abs(quantity),
        "price": price,
        "validity": "DAY",
        "exchange": pos["exchange"],
        "segment": pos["segment"],
        "product": pos.get("product") or "NRML",
        "order_type": "LIMIT",
        "transaction_type": "SELL" if sell else "BUY",
    }
