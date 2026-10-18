"""Dhan trade journal: fills and ledger from Dhan's statement APIs, round trips and statistics.

Where the data comes from (docs/DHAN_JOURNAL.md has the details and the checks behind them):

  GET /v2/trades/{from}/{to}/{page}   every fill in a date range, 20 per page, each with its charges
  GET /v2/trades                      today's fills, without charges
  GET /v2/ledger?from-date=&to-date=  the account ledger: daily settlement per segment, funds, interest, fees

These are account APIs: they need the access token but not the Data API plan.

What was checked against the ledger on 2026-10-18 (189 fills since 2026-09-04):

* ``tradedQuantity`` is in the unit the price is quoted in, so P&L is quantity x price change with no
  lot multiplier (GOLD: 200 = 2 lots; ELECDMBL likewise). Closed P&L minus charges matched the ledger's
  NSE F&O total to Rs 1.51 and NSE cash to Rs 0.05.
* The ledger's "Trades Executed for the Day" lines for **MCX and NSE F&O are daily mark-to-market**,
  net of charges: on a day with nothing carried overnight the line equals that day's closed P&L minus
  charges exactly. So they are the true daily P&L, carried positions included. For **NSE cash** the
  line is the money paid and received, not P&L, so equity days come from closed round trips instead.
* ``exchangeTradeId`` is always "0" and ``orderType`` is null in the history, so a fill has no unique
  id. Syncing replaces whole days instead of merging fills.

A **round trip** is one position on one contract and product, from flat back to flat: every fill
that adds to it or reduces it belongs to it. A fill that flips the position is split, charges
pro rata. Prices are averaged within the trip, so a closed trip's gross P&L is exactly money
received minus money paid. Each trip has a stable id: security id, product and first order id.

Tables (in the shared ``data/market.db``; ``PULSE_STATE_DB`` moves it, as for the other state):

  dhan_fills    one row per fill
  dhan_ledger   one row per ledger entry (the opening and closing balance rows are left out)

Read-only towards Dhan: it places no orders.
"""

import logging
import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from market import intraday_store, state_store
from market.market_hours import IST
from market.providers import dhan_session

logger = logging.getLogger(__name__)

REST_BASE = "https://api.dhan.co/v2"
#: Dhan's trade history page size (observed; it is not documented).
PAGE_SIZE = 20
#: Days before the newest stored fill that a sync fetches again, so late corrections are picked up.
RESYNC_DAYS = 5
#: Default daily loss limit the page checks against (the account holder's choice, 2026-10-18).
DAILY_LOSS_LIMIT = 50_000.0

SYNC_STATE = "dhan_journal_sync"

#: Dhan's charge fields on a fill, and the names stored here.
CHARGE_FIELDS = {
    "brokerageCharges": "brokerage",
    "stt": "stt",
    "exchangeTransactionCharges": "exchange_charges",
    "sebiTax": "sebi_fee",
    "stampDuty": "stamp_duty",
    "serviceTax": "gst",
}
CHARGE_COLUMNS = tuple(CHARGE_FIELDS.values())

#: Ledger lines that are daily mark-to-market, net of charges (see the module docstring).
MTM_LEDGER_EXCHANGES = {"MCX": "MCX", "NSE_FNO": "NSE F&O"}
SEGMENT_LABELS = {"MCX_COMM": "MCX", "NSE_FNO": "NSE F&O", "NSE_EQ": "NSE cash", "BSE_FNO": "BSE F&O",
                  "BSE_EQ": "BSE cash", "NSE_CURRENCY": "NSE currency"}
#: Delivery products: a sell from flat here sold shares bought before the stored history.
DELIVERY_PRODUCTS = ("", "CNC", "MTF")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dhan_fills (
    trade_date       TEXT NOT NULL,     -- 'YYYY-MM-DD' IST
    seq              INTEGER NOT NULL,  -- order within the day, as fetched (fills have no unique id)
    exchange_time    TEXT NOT NULL,     -- 'YYYY-MM-DDTHH:MM:SS' IST
    order_id         TEXT NOT NULL,
    exchange_order_id TEXT,
    security_id      TEXT NOT NULL,
    segment          TEXT NOT NULL,     -- Dhan exchangeSegment: NSE_EQ, NSE_FNO, MCX_COMM, ...
    product          TEXT NOT NULL,     -- INTRADAY, MARGIN, CNC, MTF; '' when Dhan gives none
    instrument       TEXT,              -- EQUITY, FUTIDX, FUTSTK, OPTIDX, FUTCOM, ...
    symbol           TEXT NOT NULL,     -- Dhan's customSymbol, e.g. 'GOLD DEC FUT'
    expiry           TEXT,
    option_type      TEXT,              -- CALL | PUT | NULL
    strike           REAL,
    side             TEXT NOT NULL,     -- BUY | SELL
    quantity         INTEGER NOT NULL,  -- in the unit the price is quoted in (no lot multiplier)
    price            REAL NOT NULL,
    brokerage        REAL NOT NULL,
    stt              REAL NOT NULL,
    exchange_charges REAL NOT NULL,
    sebi_fee         REAL NOT NULL,
    stamp_duty       REAL NOT NULL,
    gst              REAL NOT NULL,
    charges_known    INTEGER NOT NULL,  -- 0 for today's fills, which Dhan gives without charges
    PRIMARY KEY (trade_date, seq)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS dhan_ledger (
    entry_date   TEXT NOT NULL,         -- 'YYYY-MM-DD'
    seq          INTEGER NOT NULL,
    exchange     TEXT NOT NULL,         -- MCX | NSE_FNO | NSE_CASH
    description  TEXT NOT NULL,         -- Dhan's voucherdesc
    narration    TEXT NOT NULL,
    voucher      TEXT NOT NULL,
    debit        REAL NOT NULL,
    credit       REAL NOT NULL,
    balance      REAL,                  -- running balance after the entry
    PRIMARY KEY (entry_date, seq)
) WITHOUT ROWID;
"""

FILL_COLUMNS = ("trade_date", "seq", "exchange_time", "order_id", "exchange_order_id", "security_id", "segment",
                "product", "instrument", "symbol", "expiry", "option_type", "strike", "side", "quantity", "price",
                *CHARGE_COLUMNS, "charges_known")
LEDGER_COLUMNS = ("entry_date", "seq", "exchange", "description", "narration", "voucher", "debit", "credit",
                  "balance")


class DhanJournalError(RuntimeError):
    """A Dhan statement call failed."""


# -- Dhan ----------------------------------------------------------------------


class DhanAccount:
    """GET calls to Dhan's account APIs with the shared, auto-renewed access token."""

    def __init__(self, http=requests, sleep: Callable[[float], None] = time.sleep, timeout: int = 30):
        self.http, self.sleep, self.timeout = http, sleep, timeout
        self.token = dhan_session.get_access_token()

    def _headers(self) -> dict:
        from market.providers.dhan import client_id_from_token

        client_id = client_id_from_token(self.token) or dhan_session.client_id_from_env()
        return {"access-token": self.token, "client-id": client_id, "Accept": "application/json"}

    def get(self, path: str, params: Optional[dict] = None):
        renewed = False
        for attempt in range(4):
            resp = self.http.get(f"{REST_BASE}{path}", headers=self._headers(), params=params, timeout=self.timeout)
            try:
                body = resp.json()
            except ValueError:
                body = None
            error = _error_of(body) if isinstance(body, dict) else None
            if error is None and resp.status_code < 400 and body is not None:
                return body
            code, message = error or (str(resp.status_code), (resp.text or "")[:200])
            if (resp.status_code == 401 or code == "DH-901") and not renewed:
                # A token revoked early (a login elsewhere): mint a replacement once.
                self.token = dhan_session.get_access_token(force_new=True, rejected=self.token)
                renewed = True
                continue
            if (resp.status_code == 429 or code in ("DH-904", "805")) and attempt < 3:
                self.sleep(1.0 + attempt)
                continue
            raise DhanJournalError(f"Dhan {path.split('?')[0]}: {code} {message}".strip())
        raise DhanJournalError(f"Dhan {path}: no answer after retries")

    def fills(self, start: date, end: date, pause: float = 0.25) -> List[dict]:
        """Every fill from ``start`` to ``end`` (inclusive), walking the pages until one is empty."""
        rows: List[dict] = []
        for page in range(1000):
            batch = self.get(f"/trades/{start.isoformat()}/{end.isoformat()}/{page}")
            if not isinstance(batch, list):
                raise DhanJournalError(f"Dhan trade history page {page}: unexpected answer {str(batch)[:200]}")
            if not batch:
                return rows
            rows.extend(batch)
            self.sleep(pause)
        raise DhanJournalError("Dhan trade history: more than 1000 pages")

    def todays_fills(self) -> List[dict]:
        body = self.get("/trades")
        return body if isinstance(body, list) else []

    def ledger(self, start: date, end: date) -> List[dict]:
        body = self.get("/ledger", params={"from-date": start.isoformat(), "to-date": end.isoformat()})
        if not isinstance(body, list):
            raise DhanJournalError(f"Dhan ledger: unexpected answer {str(body)[:200]}")
        return body

    def last_prices(self, by_segment: Dict[str, List[str]]) -> Dict[str, float]:
        """``{security_id: last price}`` from ``/marketfeed/ltp`` (needs the Data API plan)."""
        body = {segment: [int(s) for s in ids] for segment, ids in by_segment.items() if ids}
        if not body:
            return {}
        resp = self.http.post(f"{REST_BASE}/marketfeed/ltp", headers={**self._headers(), "Content-Type": "application/json"},
                              json=body, timeout=self.timeout)
        payload = resp.json() if resp.content else {}
        error = _error_of(payload) if isinstance(payload, dict) else None
        if error:
            raise DhanJournalError(f"Dhan last prices: {error[0]} {error[1]}")
        prices = {}
        for entries in (payload.get("data") or {}).values():
            for security_id, entry in (entries or {}).items():
                price = (entry or {}).get("last_price")
                if price:
                    prices[str(security_id)] = float(price)
        return prices


def _error_of(payload: dict) -> Optional[Tuple[str, str]]:
    """``(code, message)`` for Dhan's error shapes, else None."""
    if payload.get("errorCode") or payload.get("errorMessage"):
        return str(payload.get("errorCode") or ""), str(payload.get("errorMessage") or "")
    if str(payload.get("status", "")).lower() in ("failed", "failure"):
        data = payload.get("data")
        if isinstance(data, dict) and data:
            code, message = next(iter(data.items()))
            return str(code), str(message)
        return "", str(payload.get("remarks") or "failed")
    return None


# -- parsing -------------------------------------------------------------------


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return None if text in ("", "NA", "None", "null") else text


def _time(raw: dict) -> Optional[str]:
    """The fill's exchange time as ``YYYY-MM-DDTHH:MM:SS``; the history writes a T, the trade book a space."""
    for key in ("exchangeTime", "updateTime", "createTime"):
        text = _text(raw.get(key))
        if not text:
            continue
        try:
            return datetime.fromisoformat(text.replace(" ", "T")[:19]).isoformat()
        except ValueError:
            continue
    return None


def parse_fills(raw_fills: Iterable[dict], charges_known: bool = True) -> List[dict]:
    """Dhan fills as stored rows, in time order, numbered within each day. Unreadable fills are skipped."""
    rows = []
    for raw in raw_fills:
        when = _time(raw)
        side = str(raw.get("transactionType") or "").upper()
        quantity = int(_number(raw.get("tradedQuantity")))
        price = _number(raw.get("tradedPrice"))
        if not when or side not in ("BUY", "SELL") or quantity <= 0 or price <= 0:
            logger.warning("Skipping a Dhan fill I cannot read: %s", {k: raw.get(k) for k in
                           ("orderId", "exchangeTime", "transactionType", "tradedQuantity", "tradedPrice")})
            continue
        strike = _number(raw.get("drvStrikePrice"))
        row = {
            "trade_date": when[:10],
            "exchange_time": when,
            "order_id": str(raw.get("orderId") or ""),
            "exchange_order_id": _text(raw.get("exchangeOrderId")),
            "security_id": str(raw.get("securityId") or ""),
            "segment": str(raw.get("exchangeSegment") or ""),
            "product": _text(raw.get("productType")) or "",
            "instrument": _text(raw.get("instrument")),
            "symbol": _text(raw.get("customSymbol")) or _text(raw.get("tradingSymbol")) or str(raw.get("securityId")),
            "expiry": _text(raw.get("drvExpiryDate")),
            "option_type": _text(raw.get("drvOptionType")),
            "strike": strike or None,
            "side": side,
            "quantity": quantity,
            "price": price,
            "charges_known": 1 if charges_known else 0,
        }
        for dhan_name, name in CHARGE_FIELDS.items():
            row[name] = _number(raw.get(dhan_name)) if charges_known else 0.0
        rows.append(row)
    rows.sort(key=lambda r: (r["exchange_time"], r["order_id"]))
    counters: Dict[str, int] = defaultdict(int)
    for row in rows:
        row["seq"] = counters[row["trade_date"]]
        counters[row["trade_date"]] += 1
    return rows


def parse_ledger(raw_rows: Iterable[dict]) -> List[dict]:
    """Ledger entries as stored rows, oldest first; the opening and closing balance rows are dropped."""
    rows = []
    for raw in raw_rows:
        description = str(raw.get("voucherdesc") or "").strip()
        if "BALANCE" in description.upper() and not raw.get("vouchernumber"):
            continue
        try:
            when = datetime.strptime(str(raw.get("voucherdate")).strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            logger.warning("Skipping a ledger entry with an unreadable date: %s", raw.get("voucherdate"))
            continue
        rows.append({
            "entry_date": when,
            "exchange": str(raw.get("exchange") or ""),
            "description": description,
            "narration": str(raw.get("narration") or "").strip(),
            "voucher": str(raw.get("vouchernumber") or ""),
            "debit": _number(raw.get("debit")),
            "credit": _number(raw.get("credit")),
            "balance": _number(raw.get("runbal"), default=None),
        })
    # Dhan lists newest first; keep its order within a day, reversed to oldest first.
    rows.reverse()
    rows.sort(key=lambda r: r["entry_date"])
    counters: Dict[str, int] = defaultdict(int)
    for row in rows:
        row["seq"] = counters[row["entry_date"]]
        counters[row["entry_date"]] += 1
    return rows


CHARGE_LABELS = {"brokerage": "Brokerage", "exchange_charges": "Exchange charges", "sebi_fee": "SEBI fee",
                 "stamp_duty": "Stamp duty", "gst": "GST"}


def charges_by_kind(fills: Iterable[dict]) -> Dict[str, float]:
    """Total of each charge. Dhan reports STT and MCX's CTT in one field (``stt``); split here by segment."""
    totals: Dict[str, float] = defaultdict(float)
    for fill in fills:
        totals["CTT" if fill["segment"] == "MCX_COMM" else "STT"] += _number(fill.get("stt"))
        for name, label in CHARGE_LABELS.items():
            totals[label] += _number(fill.get(name))
    return dict(totals)


def fill_charges(fill: dict) -> float:
    return sum(_number(fill.get(name)) for name in CHARGE_COLUMNS)


# -- store ---------------------------------------------------------------------


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    conn = state_store.connect_shared(path, SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(path: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """A read-only handle, or None if there is no database or no journal in it yet."""
    conn = intraday_store.connect_readonly(path or state_store.db_path())
    if conn is None:
        return None
    conn.row_factory = sqlite3.Row
    found = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'dhan_fills'").fetchone()[0]
    if not found:
        conn.close()
        return None
    return conn


def _insert(table: str, columns: Sequence[str]) -> str:
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"


def replace_range(conn: sqlite3.Connection, start: str, end: str, fills: List[dict], ledger: List[dict]) -> None:
    """Replace every stored fill and ledger entry dated ``start``..``end`` with these, in one transaction."""
    with conn:
        conn.execute("DELETE FROM dhan_fills WHERE trade_date BETWEEN ? AND ?", (start, end))
        conn.execute("DELETE FROM dhan_ledger WHERE entry_date BETWEEN ? AND ?", (start, end))
        conn.executemany(_insert("dhan_fills", FILL_COLUMNS), [{c: f.get(c) for c in FILL_COLUMNS} for f in fills])
        conn.executemany(_insert("dhan_ledger", LEDGER_COLUMNS), [{c: r.get(c) for c in LEDGER_COLUMNS} for r in ledger])


def load_fills(conn: sqlite3.Connection) -> List[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM dhan_fills ORDER BY exchange_time, trade_date, seq")]


def load_ledger(conn: sqlite3.Connection) -> List[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM dhan_ledger ORDER BY entry_date, seq")]


def newest_fill_date(conn: sqlite3.Connection) -> Optional[str]:
    return conn.execute("SELECT MAX(trade_date) FROM dhan_fills").fetchone()[0]


# -- sync ----------------------------------------------------------------------


def financial_year_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


PERIOD_KINDS = ("Financial year", "Month", "Week")


def period_start(kind: str, count: int, today: date) -> date:
    """First day of the last ``count`` periods up to ``today``: 1 = this financial year, month or week
    (weeks start on Monday), 2 = this one and the one before, and so on."""
    back = max(int(count), 1) - 1
    if kind == "Financial year":
        start = financial_year_start(today)
        return date(start.year - back, 4, 1)
    if kind == "Month":
        months = today.year * 12 + today.month - 1 - back
        return date(months // 12, months % 12 + 1, 1)
    if kind == "Week":
        return today - timedelta(days=today.weekday() + 7 * back)
    raise ValueError(f"unknown period {kind!r}")


@dataclass
class SyncResult:
    start: str
    end: str
    fills: int
    todays_fills: int
    ledger_rows: int
    open_trips: int
    prices: int
    price_error: Optional[str] = None

    def summary(self) -> str:
        text = (f"{self.fills} fills and {self.ledger_rows} ledger entries for {self.start} to {self.end}"
                + (f", including {self.todays_fills} of today's fills without charges yet" if self.todays_fills else ""))
        if self.open_trips:
            text += (f"; {self.prices} of {self.open_trips} open positions priced"
                     + (f" ({self.price_error})" if self.price_error else ""))
        return text


def sync(account: DhanAccount, today: date, since: Optional[date] = None, path: Optional[str] = None) -> SyncResult:
    """Fetch fills and ledger from ``since`` (default: a few days before the newest stored fill, or the
    start of the financial year) to ``today`` and replace that range in the store.

    Today's fills come from the history when Dhan has them there, else from the trade book, without
    charges, until a later sync replaces them. Open positions are priced at the last traded price
    (needs the Data API plan) so the page can show them; that is saved with the sync time.
    """
    conn = connect(path)
    try:
        if since is None:
            newest = newest_fill_date(conn)
            since = (date.fromisoformat(newest) - timedelta(days=RESYNC_DAYS)) if newest else financial_year_start(today)
        since = min(since, today)
        fills = parse_fills(account.fills(since, today))
        todays = []
        if not any(f["trade_date"] == today.isoformat() for f in fills):
            todays = [f for f in parse_fills(account.todays_fills(), charges_known=False)
                      if f["trade_date"] == today.isoformat()]
        ledger = parse_ledger(account.ledger(since, today))
        replace_range(conn, since.isoformat(), today.isoformat(), fills + todays, ledger)
        trips = round_trips(load_fills(conn))
    finally:
        conn.close()

    open_trips = [t for t in trips if t.is_open]
    prices, price_error = {}, None
    if open_trips:
        by_segment: Dict[str, List[str]] = defaultdict(list)
        for trip in open_trips:
            by_segment[trip.segment].append(trip.security_id)
        try:
            prices = account.last_prices(by_segment)
        except Exception as exc:  # noqa: BLE001 - the journal still works without them
            price_error = str(exc)
    result = SyncResult(since.isoformat(), today.isoformat(), len(fills), len(todays), len(ledger),
                        len(open_trips), len(prices), price_error)
    state_store.write(SYNC_STATE, {
        "synced_at": datetime.now(IST).isoformat(timespec="seconds"),
        "start": result.start, "end": result.end, "summary": result.summary(),
        "prices": prices, "price_error": price_error,
    }, path)
    return result


def last_sync(path: Optional[str] = None) -> Optional[dict]:
    return state_store.read(SYNC_STATE, path)


# -- round trips -----------------------------------------------------------------


@dataclass
class Trip:
    trip_id: str
    security_id: str
    segment: str
    product: str
    symbol: str
    instrument: Optional[str]
    expiry: Optional[str]
    option_type: Optional[str]
    strike: Optional[float]
    side: str                      # LONG | SHORT
    opened_at: str
    closed_at: Optional[str] = None
    fills: int = 0
    max_quantity: int = 0
    open_quantity: int = 0         # signed; 0 once closed
    entry_quantity: int = 0
    entry_value: float = 0.0
    exit_quantity: int = 0
    exit_value: float = 0.0
    charges: float = 0.0
    charges_known: bool = True
    #: A delivery sell from flat: the shares were bought before the stored history, so the P&L is unknown.
    incomplete: bool = False

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def sign(self) -> int:
        return 1 if self.side == "LONG" else -1

    @property
    def avg_entry(self) -> float:
        return self.entry_value / self.entry_quantity if self.entry_quantity else 0.0

    @property
    def avg_exit(self) -> Optional[float]:
        return self.exit_value / self.exit_quantity if self.exit_quantity else None

    @property
    def booked(self) -> float:
        """P&L of the quantity closed so far, before charges, at the trip's average entry price."""
        return self.sign * self.exit_quantity * ((self.avg_exit or 0.0) - self.avg_entry)

    @property
    def gross(self) -> Optional[float]:
        """Closed trips: money received minus money paid, before charges."""
        return None if self.is_open else self.booked

    @property
    def net(self) -> Optional[float]:
        return None if self.is_open else self.booked - self.charges

    def unrealised(self, price: Optional[float]) -> Optional[float]:
        if not self.is_open or not price:
            return None
        return self.open_quantity * (price - self.avg_entry)

    @property
    def underlying(self) -> str:
        """``GOLD`` for 'GOLD DEC FUT', 'NIFTY' for 'NIFTY 27 OCT 23000 CALL'; a stock's own name."""
        if self.instrument == "EQUITY" or self.segment.endswith("_EQ"):
            return self.symbol
        return self.symbol.split()[0] if self.symbol else self.security_id

    @property
    def holding_seconds(self) -> Optional[float]:
        if self.is_open:
            return None
        return (datetime.fromisoformat(self.closed_at) - datetime.fromisoformat(self.opened_at)).total_seconds()

    @property
    def overnight(self) -> bool:
        return (self.closed_at or "")[:10] != self.opened_at[:10]


def spread_day_charges(fills: Sequence[dict]) -> List[dict]:
    """Copies of the fills with STT/CTT and stamp duty spread over each contract's fills of the day.

    Dhan books a whole day's STT (or MCX's CTT) and stamp duty for a contract on **one** fill (2026-10-16:
    Rs 60,042 STT on one of four NIFTY sells, 0.05% of all four). The day's total is right; the per-fill
    split is not, so it would load one round trip with the day's tax. Spread by trade value over the
    side that pays it: STT on sells (both sides for delivery equity), stamp duty on buys. Totals are kept.
    """
    out = [dict(f) for f in fills]
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for fill in out:
        groups[(fill["trade_date"], fill["security_id"])].append(fill)
    for members in groups.values():
        delivery = members[0]["segment"].endswith("_EQ") and all((m.get("product") or "") in DELIVERY_PRODUCTS
                                                                   for m in members)
        for charge, sides in (("stt", ("BUY", "SELL") if delivery else ("SELL",)), ("stamp_duty", ("BUY",))):
            total = sum(_number(m.get(charge)) for m in members)
            if not total:
                continue
            payers = [m for m in members if m["side"] in sides] or members
            value = sum(m["quantity"] * m["price"] for m in payers)
            for m in members:
                m[charge] = total * m["quantity"] * m["price"] / value if m in payers else 0.0
    return out


def round_trips(fills: Sequence[dict]) -> List[Trip]:
    """Round trips from fills (any order), per contract and product. Closed ones in closing order,
    then the open ones in opening order. A day's STT and stamp duty are spread first (``spread_day_charges``)."""
    ordered = sorted(spread_day_charges(fills), key=lambda f: (f["exchange_time"], f["trade_date"], f["seq"]))
    position: Dict[Tuple[str, str], int] = defaultdict(int)
    current: Dict[Tuple[str, str], Trip] = {}
    closed: List[Trip] = []
    used_ids: set = set()

    for fill in ordered:
        key = (fill["security_id"], fill.get("product") or "")
        quantity = int(fill["quantity"])
        remaining = quantity if fill["side"] == "BUY" else -quantity
        charge_per_unit = fill_charges(fill) / quantity
        touched = set()
        while remaining:
            held = position[key]
            if held == 0:
                trip_id = f"{key[0]}:{key[1] or '-'}:{fill['order_id']}"
                while trip_id in used_ids:  # one order opening two trips (a flip within a partial fill)
                    trip_id += "+"
                used_ids.add(trip_id)
                current[key] = Trip(
                    trip_id=trip_id, security_id=key[0], segment=fill["segment"], product=key[1],
                    symbol=fill["symbol"], instrument=fill.get("instrument"), expiry=fill.get("expiry"),
                    option_type=fill.get("option_type"), strike=fill.get("strike"),
                    side="LONG" if remaining > 0 else "SHORT", opened_at=fill["exchange_time"],
                    incomplete=(remaining < 0 and fill["segment"].endswith("_EQ") and key[1] in DELIVERY_PRODUCTS),
                )
            trip = current[key]
            if trip.trip_id not in touched:
                touched.add(trip.trip_id)
                trip.fills += 1
            trip.charges_known = trip.charges_known and bool(fill.get("charges_known", 1))
            if held == 0 or (held > 0) == (remaining > 0):
                leg = abs(remaining)
                trip.entry_quantity += leg
                trip.entry_value += leg * fill["price"]
                position[key] = held + remaining
                remaining = 0
            else:
                leg = min(abs(remaining), abs(held))
                trip.exit_quantity += leg
                trip.exit_value += leg * fill["price"]
                step = leg if remaining > 0 else -leg
                position[key] = held + step
                remaining -= step
            trip.charges += leg * charge_per_unit
            trip.max_quantity = max(trip.max_quantity, abs(position[key]))
            trip.open_quantity = position[key]
            if position[key] == 0:
                trip.closed_at = fill["exchange_time"]
                closed.append(trip)
                del current[key]
    still_open = sorted(current.values(), key=lambda t: t.opened_at)
    return closed + still_open


# -- statistics ------------------------------------------------------------------


def scored(trips: Iterable[Trip]) -> List[Trip]:
    """Closed trips whose P&L is known: complete history and charges in."""
    return [t for t in trips if not t.is_open and not t.incomplete and t.charges_known]


def trip_stats(trips: Sequence[Trip]) -> dict:
    """Win rate, expectancy and the rest over closed trips (net of charges), in closing order."""
    trips = sorted(scored(trips), key=lambda t: t.closed_at)
    nets = [t.net for t in trips]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    equity, peak, drawdown = 0.0, 0.0, 0.0
    streak, worst_streak = 0, 0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
        streak = streak + 1 if n < 0 else 0
        worst_streak = max(worst_streak, streak)
    gross = sum(t.gross for t in trips)
    charges = sum(t.charges for t in trips)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    holding = [t.holding_seconds for t in trips]
    return {
        "trips": len(trips),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trips) if trips else None,
        "gross": gross,
        "charges": charges,
        "net": sum(nets),
        "expectancy": sum(nets) / len(nets) if nets else None,
        "avg_win": avg_win if wins else None,
        "avg_loss": avg_loss if losses else None,
        "payoff": avg_win / abs(avg_loss) if wins and losses else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "max_drawdown": drawdown,
        "worst_losing_streak": worst_streak,
        "charges_share": charges / (gross) if gross > 0 else None,
        "median_holding_seconds": sorted(holding)[len(holding) // 2] if holding else None,
    }


def breakdown(trips: Sequence[Trip], key: Callable[[Trip], str]) -> List[dict]:
    """Stats per group, biggest net P&L first."""
    groups: Dict[str, List[Trip]] = defaultdict(list)
    for trip in scored(trips):
        groups[key(trip)].append(trip)
    rows = []
    for name, members in groups.items():
        stats = trip_stats(members)
        rows.append({"group": name, **{k: stats[k] for k in ("trips", "win_rate", "net", "expectancy", "gross",
                                                              "charges", "avg_win", "avg_loss", "profit_factor")}})
    return sorted(rows, key=lambda r: r["net"], reverse=True)


def holding_bucket(trip: Trip) -> str:
    if trip.overnight:
        return "Overnight"
    seconds = trip.holding_seconds or 0
    if seconds < 5 * 60:
        return "Under 5 min"
    if seconds < 30 * 60:
        return "5-30 min"
    if seconds < 2 * 3600:
        return "30 min-2 h"
    return "Over 2 h, same day"


def daily_pnl(ledger: Sequence[dict], trips: Sequence[Trip]) -> List[dict]:
    """P&L per day, net of charges: the ledger's daily settlement for MCX and NSE F&O (carried positions
    marked to market), plus closed cash-equity round trips on the day they closed. Oldest first."""
    days: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in ledger:
        label = MTM_LEDGER_EXCHANGES.get(row["exchange"])
        if label and row["description"].startswith("Trades Executed"):
            days[row["entry_date"]][label] += row["credit"] - row["debit"]
    for trip in scored(trips):
        if trip.segment.endswith("_EQ"):
            days[trip.closed_at[:10]][SEGMENT_LABELS.get(trip.segment, trip.segment)] += trip.net
    rows = []
    for day in sorted(days):
        parts = dict(days[day])
        rows.append({"date": day, **parts, "total": sum(parts.values())})
    return rows


def other_costs(ledger: Sequence[dict]) -> List[dict]:
    """Ledger debits that are neither trading nor money moved out: interest, account and data fees,
    square-off charges. One row per kind, largest first."""
    kinds: Dict[str, float] = defaultdict(float)
    for row in ledger:
        text = row["description"]
        if text.startswith("Trades Executed") or text.startswith(("Money withdrawn", "Money added")):
            continue
        amount = row["debit"] - row["credit"]
        if not amount:
            continue
        for cut in (" Trx Dt", " for Period"):
            text = text.split(cut)[0]
        kinds[text.strip()] += amount
    return sorted(({"kind": k, "amount": v} for k, v in kinds.items()), key=lambda r: -r["amount"])


def reconcile(ledger: Sequence[dict], trips: Sequence[Trip], prices: Dict[str, float]) -> List[dict]:
    """Per MCX / NSE F&O: the ledger's settlement total against closed trips' net plus open trips at the
    last price. They differ by the open positions' move from the last settlement price to that price."""
    rows = []
    for exchange, label in MTM_LEDGER_EXCHANGES.items():
        ledger_total = sum(r["credit"] - r["debit"] for r in ledger
                           if r["exchange"] == exchange and r["description"].startswith("Trades Executed"))
        segment = "MCX_COMM" if exchange == "MCX" else "NSE_FNO"
        mine = [t for t in trips if t.segment == segment]
        closed_net = sum(t.net for t in mine if not t.is_open)
        open_value = sum(t.booked - t.charges + (t.unrealised(prices.get(t.security_id)) or 0.0)
                         for t in mine if t.is_open)
        unpriced = sum(1 for t in mine if t.is_open and not prices.get(t.security_id))
        rows.append({"segment": label, "ledger": ledger_total, "journal": closed_net + open_value,
                     "difference": closed_net + open_value - ledger_total, "unpriced_open": unpriced})
    return rows
