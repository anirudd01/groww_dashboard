"""Dhan order placement for scripted strategies: contract lookup, prices, lots, and the REST calls.

Used by ``strategies/dhan_gold_band_strategy.py`` (docs/DHAN_GOLD_STRATEGY.md). Endpoints, all on
``https://api.dhan.co/v2`` and described in ``docs/dhan-api-docs.md`` (2026-10-09 export):

  POST /marketfeed/quote         market depth: best bid (``depth.buy[0]``) and ask (``depth.sell[0]``)
                                 (Data API plan; 1 request/second)
  GET  /fundlimit               available balance (``availabelBalance`` - Dhan's spelling)
  POST /margincalculator         margin for one order (contract, side, quantity, product, price)
  GET  /positions                open positions (a trade is refused while one is open)
  GET  /super/orders             today's super orders (a trade is refused while one is unfinished)
  POST /super/orders             entry + target + stop loss in one order (needs the static IP whitelisted)

Quantity on MCX: Dhan's instrument master gives every MCX future ``LOT_SIZE`` 1.0, and
``/v2/positions`` reports a 2-lot GOLD position as ``buyQty: 2`` (docs/DHAN_JOURNAL.md), so order
quantity is ``lots x LOT_SIZE`` = lots. (The trade *history* reports the same fills as 200, in the
unit the price is quoted in; that is a different endpoint.)

Tick size: the master's ``TICK_SIZE`` is in paise for MCX (GOLD 100.0 = Rs 1).

Contracts come from the ``mcx_futures`` set in ``data/market.db`` (``scripts/dhan.py --master``);
lot and tick size, which that set does not store, from the newest raw master CSV under
``data/instruments/`` (``scripts/dhan.py --master-only --keep-raw``). Nothing is downloaded here.

Auth reuses ``market.providers.dhan_session`` (the shared TOTP-minted token).
"""

import glob
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import requests

from market import mcx_futures
from market.providers import dhan_session

logger = logging.getLogger(__name__)

REST_BASE = "https://api.dhan.co/v2"
MCX_COMM = "MCX_COMM"
#: Carry-forward futures (Annexure, Product Type: "MARGIN - Carry Forward in Futures & Options").
PRODUCT_MARGIN = "MARGIN"
BUY, SELL = "BUY", "SELL"

#: Super-order statuses whose entry can still fill: another trade would stack on top of it.
LIVE_STATUSES = frozenset({"TRANSIT", "PENDING", "PART_TRADED"})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_MASTER_GLOB = os.path.join(ROOT, "data", "instruments", "dhan-scrip-master-detailed-*.csv")
MASTER_SCRIPT = "scripts/dhan.py --master-only --keep-raw"

#: Correlation ids: max 30 chars of ``a-zA-Z0-9-_`` (Place Order, dhan-api-docs.md).
CORRELATION_MAX = 30


class DhanOrderError(RuntimeError):
    """A Dhan call failed; ``code`` and ``message`` are Dhan's own."""

    def __init__(self, what: str, code: str = "", message: str = ""):
        self.code, self.message = str(code or ""), str(message or "")
        detail = " ".join(x for x in (self.code, self.message) if x) or "no detail"
        super().__init__(f"{what}: {detail}")


class NearExpiry(ValueError):
    """The chosen contract expires too soon to trade."""


# -- contract ----------------------------------------------------------------


@dataclass(frozen=True)
class TradableContract:
    security_id: str
    commodity: str
    name: str  # "GOLD DEC FUT"
    expiry: date
    lot_size: int  # Dhan's LOT_SIZE; order quantity = lots x lot_size
    tick: Decimal  # rupees


def pick_contract(contracts: Iterable[mcx_futures.Contract], commodity: str, year: Optional[int],
                  month: Optional[int], today: Optional[date] = None,
                  avoid_within_days: Optional[int] = None) -> mcx_futures.Contract:
    """The ``commodity`` future expiring in ``year``-``month``, or the nearest one when ``month`` is None.

    Raises ValueError naming the alternatives, and NearExpiry (naming the next contract) when the
    pick expires ``avoid_within_days`` days or fewer after ``today``.
    """
    commodity = commodity.strip().upper()
    same = [c for c in contracts if c.commodity == commodity]
    if today is not None:
        same = mcx_futures.live_contracts(same, today)
    same.sort(key=lambda c: c.expiry)
    if month is None:
        if not same:
            raise ValueError(f"No live {commodity} future in the stored mcx_futures set")
        match = same[:1]
    else:
        match = [c for c in same if c.expiry.year == year and c.expiry.month == month]
    if len(match) == 1:
        picked = match[0]
        days_left = (picked.expiry - today).days if today is not None else None
        if avoid_within_days is not None and days_left is not None and days_left <= avoid_within_days:
            later = [c for c in same if c.expiry > picked.expiry]
            hint = (f"Next: {later[0].name} (expires {later[0].expiry}); run with --month "
                    f"{later[0].expiry:%Y-%m}." if later else f"No later {commodity} contract is stored.")
            raise NearExpiry(f"{picked.name} expires on {picked.expiry}, {days_left} day(s) from today. Contracts "
                             f"within {avoid_within_days} days of expiry are not traded (higher margins, "
                             f"delivery). {hint}")
        return picked
    listed = ", ".join(f"{c.name} ({c.expiry})" for c in same) or "none"
    if not match:
        raise ValueError(f"No {commodity} future expiring {year}-{month:02d}. Live {commodity} futures: {listed}")
    raise ValueError(f"Several {commodity} futures expire {year}-{month:02d}: {listed}")


def latest_raw_master(pattern: str = RAW_MASTER_GLOB) -> Optional[str]:
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def master_row(security_id: str, path: str) -> Optional[Dict[str, str]]:
    """The MCX row for ``security_id`` in a raw detailed master CSV, as ``{column: value}``.

    Streams the 35 MB file line by line and only splits lines that start with ``MCX,M,<id>,``.
    """
    prefix = f"MCX,M,{security_id},"
    with open(path, encoding="utf-8-sig", newline="") as handle:
        header = handle.readline().rstrip("\r\n").split(",")
        for line in handle:
            if line.startswith(prefix):
                return dict(zip(header, line.rstrip("\r\n").split(",")))
    return None


def tick_in_rupees(raw: str) -> Decimal:
    """MCX ``TICK_SIZE`` (paise) as rupees. Raises ValueError on a blank, zero or junk value."""
    try:
        paise = Decimal(str(raw).strip())
    except Exception as exc:  # noqa: BLE001 - decimal raises its own InvalidOperation
        raise ValueError(f"unusable TICK_SIZE {raw!r}") from exc
    if not paise.is_finite() or paise <= 0:
        raise ValueError(f"unusable TICK_SIZE {raw!r}")
    return paise / 100


def tradable(contract: mcx_futures.Contract, row: Optional[Dict[str, str]]) -> TradableContract:
    if not row:
        raise ValueError(f"{contract.name} (security id {contract.security_id}) is not in the raw instrument "
                         f"master; run 'python {MASTER_SCRIPT}'")
    try:
        lot = float(row.get("LOT_SIZE") or "")
    except ValueError:
        lot = 0.0
    if lot <= 0 or lot != int(lot):
        raise ValueError(f"unusable LOT_SIZE {row.get('LOT_SIZE')!r} for {contract.name}")
    return TradableContract(contract.security_id, contract.commodity, contract.name, contract.expiry,
                            int(lot), tick_in_rupees(row.get("TICK_SIZE", "")))


def resolve_contract(commodity: str, year: Optional[int], month: Optional[int], today: date,
                     db_path: Optional[str] = None, master_path: Optional[str] = None,
                     avoid_within_days: Optional[int] = None) -> TradableContract:
    """Security id from the stored ``mcx_futures`` set; lot and tick size from the raw master CSV."""
    contracts, _, error = mcx_futures.load_contracts(db_path)
    if error:
        raise ValueError(error)
    contract = pick_contract(contracts, commodity, year, month, today, avoid_within_days)
    master_path = master_path or latest_raw_master()
    if not master_path:
        raise ValueError(f"No raw Dhan instrument master under data/instruments/ (lot and tick size); "
                         f"run 'python {MASTER_SCRIPT}'")
    return tradable(contract, master_row(contract.security_id, master_path))


# -- prices and lots ---------------------------------------------------------


def round_to_tick(price, tick: Decimal, up: bool) -> float:
    """``price`` on the tick grid, rounded up or down."""
    steps = (Decimal(str(price)) / tick).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR)
    return float(steps * tick)


@dataclass(frozen=True)
class Touch:
    """Top of the order book. ``bid``/``ask`` are None when that side of the book is empty."""
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]


def reference_price(side: str, touch: Touch) -> float:
    """The price a band is measured from: the best bid for a long, the best ask for a short.

    Not the LTP: MCX contracts trade thinly and the last trade can be 30+ points away from the
    book, so a band off the LTP can land on the wrong side of the touch and fill at once.
    """
    price, name = (touch.bid, "bid") if side == BUY else (touch.ask, "ask")
    if not price or price <= 0:
        raise DhanOrderError("Dhan market depth", "", f"no {name} in the order book - nothing to price the "
                             f"{'long' if side == BUY else 'short'} from")
    return float(price)


@dataclass(frozen=True)
class BandPlan:
    side: str  # entry side: BUY (long) or SELL (short)
    reference: float  # best bid (long) or best ask (short)
    entry: float
    target: float
    stop_loss: float

    @property
    def exit_side(self) -> str:
        return SELL if self.side == BUY else BUY


def band_prices(side: str, reference: float, offset: float, stop: float, tick: Decimal) -> BandPlan:
    """Entry and target ``offset`` either side of ``reference``; stop loss ``stop`` beyond the entry.

    Long (reference = best bid): BUY at bid - offset (rounded down), target SELL at bid + offset
    (rounded up), stop loss at entry - stop (rounded down).
    Short (reference = best ask): SELL at ask + offset (rounded up), target BUY at ask - offset
    (rounded down), stop loss at entry + stop (rounded up).
    Rounding away keeps every leg at least its distance from the price it is measured from.
    """
    if offset <= 0 or stop <= 0:
        raise ValueError("offset and stop loss must be positive")
    low = round_to_tick(reference - offset, tick, up=False)
    high = round_to_tick(reference + offset, tick, up=True)
    if side == BUY:
        plan = BandPlan(BUY, reference, low, high, round_to_tick(low - stop, tick, up=False))
    elif side == SELL:
        plan = BandPlan(SELL, reference, high, low, round_to_tick(high + stop, tick, up=True))
    else:
        raise ValueError(f"side must be BUY or SELL, not {side!r}")
    if min(plan.entry, plan.target, plan.stop_loss) <= 0:
        raise ValueError(f"offset {offset} / stop loss {stop} put a price at or below zero")
    return plan


def max_lots(available: float, margin_per_lot: float) -> int:
    """Whole lots the balance covers: ``floor(available / margin_per_lot)``, never negative."""
    if not margin_per_lot or margin_per_lot <= 0:
        raise ValueError(f"unusable margin per lot {margin_per_lot!r}")
    if available is None or available <= 0:
        return 0
    return max(0, math.floor(available / margin_per_lot + 1e-9))


def choose_lots(computed: int, requested: Optional[int]) -> Tuple[int, str]:
    """``(lots, warning)``: the request capped at the computed maximum, or the maximum."""
    if requested is None:
        return computed, ""
    if requested <= 0:
        raise ValueError("--lots must be at least 1")
    if requested > computed:
        return computed, f"--lots {requested} is more than the margin allows; capped at {computed}"
    return requested, ""


def entry_correlation(side: str, stamp: str) -> str:
    """``gbE-L-261018143005``: entry tag, side and time."""
    return f"gbE-{'L' if side == BUY else 'S'}-{stamp}"[:CORRELATION_MAX]


def super_order_body(client_id: str, contract: TradableContract, plan: BandPlan, quantity: int,
                     correlation_id: str) -> dict:
    """A LIMIT super order, carry-forward (MARGIN), on MCX: entry, target and a fixed stop loss.

    ``trailingJump`` is required; 0 means the stop loss does not trail (Modify Super Order:
    "Set to 0 to cancel trailing").
    """
    return {
        "dhanClientId": client_id,
        "correlationId": correlation_id,
        "transactionType": plan.side,
        "exchangeSegment": MCX_COMM,
        "productType": PRODUCT_MARGIN,
        "orderType": "LIMIT",
        "securityId": str(contract.security_id),
        "quantity": int(quantity),
        "price": float(plan.entry),
        "targetPrice": float(plan.target),
        "stopLossPrice": float(plan.stop_loss),
        "trailingJump": 0,
    }


def live_super_orders(super_orders: Iterable[dict], security_id: str) -> List[dict]:
    """Super orders on ``security_id`` whose entry can still fill."""
    return [o for o in super_orders or [] if isinstance(o, dict)
            and str(o.get("securityId")) == str(security_id)
            and str(o.get("orderStatus") or "").upper() in LIVE_STATUSES]


# -- REST ----------------------------------------------------------------------


def error_of(body) -> Optional[Tuple[str, str]]:
    """``(code, message)`` if ``body`` is a Dhan error, else None.

    Dhan answers errors as ``{"errorType", "errorCode", "errorMessage"}`` (with or without
    ``"status": "failure"``), and data errors as ``{"status": "failed", "data": {"806": "..."}}``.
    """
    if not isinstance(body, dict):
        return None
    if body.get("errorCode") or body.get("errorMessage"):
        return str(body.get("errorCode") or body.get("errorType") or ""), str(body.get("errorMessage") or "")
    if str(body.get("status", "")).lower() in ("failed", "failure"):
        block = body.get("data") or body.get("Data") or {}
        if isinstance(block, dict) and block:
            code, message = next(iter(block.items()))
            return str(code), str(message)
        return "", "unknown Dhan error"
    return None


class DhanTrading:
    """Dhan REST calls with the shared, auto-renewed token. ``http`` is injectable for tests."""

    def __init__(self, http=requests, sleep: Callable[[float], None] = time.sleep, timeout: int = 20,
                 token: Optional[str] = None):
        self.http, self.sleep, self.timeout = http, sleep, timeout
        self.token = token or dhan_session.get_access_token()

    @property
    def client_id(self) -> str:
        from market.providers.dhan import client_id_from_token

        return client_id_from_token(self.token) or dhan_session.client_id_from_env()

    def _headers(self) -> dict:
        return {"access-token": self.token, "client-id": self.client_id,
                "Accept": "application/json", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: Optional[dict] = None, retry_rate_limit: bool = True):
        """One call; renews a rejected token once. Rate limits are retried only when ``retry_rate_limit``."""
        renewed = False
        for attempt in range(4):
            resp = self.http.request(method, f"{REST_BASE}{path}", headers=self._headers(), json=body,
                                     timeout=self.timeout)
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            error = error_of(payload)
            if error is None and resp.status_code < 400 and payload is not None:
                return payload
            code, message = error or (str(resp.status_code), (getattr(resp, "text", "") or "")[:200])
            if (resp.status_code == 401 or code in ("DH-901", "807", "808", "809")) and not renewed:
                # A rejected token: nothing was placed, so asking again with a new one is safe.
                self.token = dhan_session.get_access_token(force_new=True, rejected=self.token)
                renewed = True
                continue
            if retry_rate_limit and (resp.status_code == 429 or code in ("DH-904", "805")) and attempt < 3:
                self.sleep(1.0 + attempt)
                continue
            raise DhanOrderError(f"Dhan {method} {path}", code, message)
        raise DhanOrderError(f"Dhan {method} {path}", "", "no answer after retries")

    # read-only
    def touch(self, segment: str, security_id: str) -> Touch:
        """Best bid and ask from the 5-level depth of POST /marketfeed/quote."""
        payload = self._call("POST", "/marketfeed/quote", {segment: [int(security_id)]})
        entry = ((payload.get("data") or {}).get(segment) or {}).get(str(security_id)) or {}
        depth = entry.get("depth") or {}

        def best(levels) -> Optional[float]:
            prices = [float(level.get("price") or 0) for level in levels or [] if isinstance(level, dict)]
            prices = [p for p in prices if p > 0]
            return prices[0] if prices else None

        last = entry.get("last_price")
        return Touch(best(depth.get("buy")), best(depth.get("sell")), float(last) if last else None)

    def available_balance(self) -> float:
        payload = self._call("GET", "/fundlimit")
        for key in ("availabelBalance", "availableBalance"):
            if payload.get(key) is not None:
                return float(payload[key])
        raise DhanOrderError("Dhan fund limit", "", f"no available balance in {sorted(payload)}")

    def margin(self, contract: TradableContract, side: str, quantity: int, price: float) -> dict:
        body = {"dhanClientId": self.client_id, "exchangeSegment": MCX_COMM, "transactionType": side,
                "quantity": int(quantity), "productType": PRODUCT_MARGIN,
                "securityId": str(contract.security_id), "price": float(price)}
        payload = self._call("POST", "/margincalculator", body)
        if not payload.get("totalMargin"):
            raise DhanOrderError("Dhan margin calculator", "", f"no totalMargin in {payload}")
        return payload

    def open_positions(self, segment: str = MCX_COMM) -> List[dict]:
        """Positions in ``segment`` with a non-zero ``netQty`` (GET /positions)."""
        payload = self._call("GET", "/positions")
        return [row for row in payload if isinstance(row, dict) and int(row.get("netQty") or 0)
                and str(row.get("exchangeSegment") or segment) == segment] if isinstance(payload, list) else []

    def super_orders(self) -> List[dict]:
        payload = self._call("GET", "/super/orders")
        return payload if isinstance(payload, list) else []

    def super_order_by_correlation(self, correlation_id: str) -> Optional[dict]:
        try:
            orders = self.super_orders()
        except DhanOrderError:
            return None
        return next((o for o in orders if isinstance(o, dict) and o.get("orderId")
                     and o.get("correlationId") == correlation_id), None)

    # placing
    def place_super_order(self, body: dict) -> dict:
        """POST /super/orders, never retried blindly: after a network error the order is looked up
        by its correlation id, so a request that did reach Dhan is not placed twice."""
        try:
            payload = self._call("POST", "/super/orders", body, retry_rate_limit=False)
        except requests.RequestException as exc:
            found = self.super_order_by_correlation(body.get("correlationId", ""))
            if found:
                logger.warning("Network error placing the order, but Dhan has it: %s", found.get("orderId"))
                return found
            raise DhanOrderError("Dhan POST /super/orders", "network", f"{exc} (check the super order book "
                                 f"for correlation id {body.get('correlationId')})") from exc
        if not payload.get("orderId"):
            raise DhanOrderError("Dhan POST /super/orders", "", f"no orderId in {payload}")
        return payload
