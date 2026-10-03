"""MCX commodity futures: the contract list, month selection, and quote/candle rows.

Which provider
--------------
Dhan first, Kite as the fallback (``PROVIDERS``). Of the four brokers this repo uses
(docs/PROVIDER_GUIDE.md), only Kite and Dhan serve MCX: INDmoney's REST rejects every MCX code, and
Groww is only used for positions here. Both were tested live on 2026-10-03 and returned identical
prices, OHLC and OI. Dhan leads because its token is minted from TOTP with no one at the machine
and it keeps the session's volume after the close; Kite needs a browser login every morning and
reports volume as 0 once the session ends.

Contracts
---------
Read from the ``mcx_futures`` set in the shared database, which ``scripts/fetch_mcx_futures.py``
fills from both brokers' public instrument lists (164 ``FUTCOM`` rows, 28 commodities, on
2026-10-03), matched on commodity and expiry. Never downloaded at runtime - same rule as
``market/instruments.py``. Re-run the script monthly: new expiries are listed as old ones lapse.

Visualisation only - nothing here places orders.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from market import reference_store, state_store
from market.market_hours import IST
from market.providers.base import SEGMENT_MCX_FUTURES, InstrumentRef

logger = logging.getLogger(__name__)

MCX_SET = "mcx_futures"
#: Broker order: the first one that answers serves the page.
PROVIDERS = ("dhan", "kite")
SCRIPT = "scripts/fetch_mcx_futures.py"

#: Commodity -> group, for filtering and ordering. Anything new on MCX lands in "Other".
GROUPS = {
    "Bullion": ("GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL", "GOLDTEN",
                "SILVER", "SILVERM", "SILVERMIC", "SILVER100"),
    "Energy": ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "ELECDMBL"),
    "Base metals": ("COPPER", "ALUMINIUM", "ALUMINI", "ZINC", "ZINCMINI",
                    "LEAD", "LEADMINI", "NICKEL", "STEELREBAR"),
    "Agri": ("CARDAMOM", "COTTON", "COTTONOIL", "KAPAS", "MENTHAOIL"),
}
GROUP_ORDER = list(GROUPS) + ["Other"]
GROUP_OF = {commodity: group for group, members in GROUPS.items() for commodity in members}

#: Smaller-lot copies of a main contract. Same price story, so hidden by default.
MINI_CONTRACTS = frozenset({"GOLDM", "GOLDGUINEA", "GOLDPETAL", "GOLDTEN", "SILVERM", "SILVERMIC",
                            "SILVER100", "CRUDEOILM", "NATGASMINI", "ALUMINI", "ZINCMINI", "LEADMINI"})

#: The headline commodities shown as metric cards, in order.
HEADLINE = ("GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER")

#: Which contract to show per commodity.
MOST_ACTIVE = "Most active"
MONTHS = ("Near", "Next", "Far")
PICKS = (MOST_ACTIVE,) + MONTHS

#: A last trade newer than this means the market is trading now.
LIVE_WITHIN = timedelta(minutes=5)


@dataclass(frozen=True)
class Contract:
    security_id: str
    commodity: str
    name: str  # Dhan's display name, e.g. "CRUDEOIL OCT FUT"
    expiry: date
    #: Kite's instrument_token and tradingsymbol (``CRUDEOIL26OCTFUT``); blank if Kite does not list it.
    kite_token: str = ""
    kite_symbol: str = ""

    @property
    def group(self) -> str:
        return GROUP_OF.get(self.commodity, "Other")

    @property
    def is_mini(self) -> bool:
        return self.commodity in MINI_CONTRACTS

    def ref(self, provider: str = "dhan") -> Optional[InstrumentRef]:
        """This contract addressed to one broker, or None if that broker has no id for it."""
        if provider == "kite":
            if not (self.kite_token and self.kite_symbol):
                return None
            return InstrumentRef(symbol=self.kite_symbol, provider_id=self.kite_token, exchange="MCX",
                                 segment=SEGMENT_MCX_FUTURES)
        return InstrumentRef(symbol=self.name, provider_id=self.security_id, exchange="MCX",
                             segment=SEGMENT_MCX_FUTURES)


@dataclass(frozen=True)
class FutureQuote:
    contract: Contract
    ltp: Optional[float]
    prev_close: Optional[float]
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    volume: Optional[int]
    oi: Optional[int]
    last_trade: Optional[datetime]

    @property
    def change(self) -> Optional[float]:
        if self.ltp is None or self.prev_close is None:
            return None
        return self.ltp - self.prev_close

    @property
    def change_pct(self) -> Optional[float]:
        change = self.change
        return None if change is None else change / self.prev_close * 100


# -- contracts ---------------------------------------------------------------


def contracts_from_master(rows: Iterable[dict]) -> List[Contract]:
    """MCX commodity futures out of Dhan's instrument-master CSV rows (``csv.DictReader``)."""
    found = []
    for row in rows:
        if row.get("EXCH_ID") != "MCX" or row.get("INSTRUMENT") != "FUTCOM":
            continue
        security_id = (row.get("SECURITY_ID") or "").strip()
        commodity = (row.get("UNDERLYING_SYMBOL") or "").strip()
        try:
            expiry = date.fromisoformat((row.get("SM_EXPIRY_DATE") or "").strip()[:10])
        except ValueError:
            continue
        if security_id and commodity:
            name = (row.get("DISPLAY_NAME") or "").strip() or f"{commodity} {expiry:%b}".upper()
            found.append(Contract(security_id, commodity, name, expiry))
    return found


def attach_kite(contracts: Iterable[Contract], kite_rows: Iterable[dict]) -> List[Contract]:
    """Add Kite's ids to each contract, matched on commodity and expiry.

    ``kite_rows`` are rows of Kite's public ``/instruments/MCX`` CSV. Only ``FUT`` rows in the
    ``MCX-FUT`` segment count. A contract Kite does not list keeps blank Kite ids.
    """
    kite = {}
    for row in kite_rows:
        if row.get("segment") == "MCX-FUT" and row.get("instrument_type") == "FUT":
            kite[((row.get("name") or "").strip(), (row.get("expiry") or "").strip())] = row
    out = []
    for c in contracts:
        row = kite.get((c.commodity, c.expiry.isoformat()))
        if row:
            c = replace(c, kite_token=str(row.get("instrument_token") or "").strip(),
                        kite_symbol=str(row.get("tradingsymbol") or "").strip())
        out.append(c)
    return out


def to_document(contracts: Sequence[Contract], sources: Sequence[str]) -> dict:
    """The stored form: ``contracts`` is Dhan ``security_id -> fields``."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": ", ".join(sources),
        "provider": "dhan+kite",
        "note": f"Generated by {SCRIPT}. Re-run monthly: new expiries are listed as old ones lapse.",
        "contracts": {c.security_id: {"commodity": c.commodity, "name": c.name, "expiry": c.expiry.isoformat(),
                                      "kite_token": c.kite_token, "kite_symbol": c.kite_symbol}
                      for c in sorted(contracts, key=lambda c: (c.commodity, c.expiry))},
    }


def save_contracts(contracts: Sequence[Contract], sources: Sequence[str] = (), path: Optional[str] = None) -> int:
    return reference_store.save_document(MCX_SET, to_document(contracts, sources), sections=("contracts",),
                                         path=path)


def load_contracts(path: Optional[str] = None):
    """``(contracts, generated_at, error)``. Never raises; the error says what to run."""
    database = path or state_store.db_path()
    document = reference_store.load_document(MCX_SET, database)
    if not document or not document.get("contracts"):
        return [], None, f"No MCX contracts stored in {database}. Run 'python {SCRIPT}'."
    contracts = []
    for security_id, fields in document["contracts"].items():
        try:
            contracts.append(Contract(str(security_id), fields["commodity"], fields["name"],
                                      date.fromisoformat(fields["expiry"]),
                                      str(fields.get("kite_token") or ""), str(fields.get("kite_symbol") or "")))
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring malformed MCX contract %s", security_id)
    generated = document.get("generated_at")
    try:
        generated = datetime.fromisoformat(generated) if generated else None
    except ValueError:
        generated = None
    return contracts, generated, ""


def live_contracts(contracts: Iterable[Contract], today: date) -> List[Contract]:
    """Unexpired contracts. A contract trades on its expiry day, so that day still counts."""
    return [c for c in contracts if c.expiry >= today]


def choose(quotes: Iterable["FutureQuote"], pick: str = MOST_ACTIVE) -> List["FutureQuote"]:
    """One contract per commodity: the most active (highest OI, then volume), or the near/next/far month.

    Most active is the default because MCX liquidity does not follow the calendar: in the week
    GOLD OCT expires it had 169 lots of OI while GOLD DEC carried the market. Commodities with
    fewer live expiries than asked for are left out. Sorted by group, then commodity.
    """
    by_commodity: Dict[str, List[FutureQuote]] = {}
    for quote in quotes:
        by_commodity.setdefault(quote.contract.commodity, []).append(quote)
    chosen = []
    for listed in by_commodity.values():
        listed.sort(key=lambda q: q.contract.expiry)
        if pick == MOST_ACTIVE:
            chosen.append(max(listed, key=lambda q: (q.oi or 0, q.volume or 0, -listed.index(q))))
        elif MONTHS.index(pick) < len(listed):
            chosen.append(listed[MONTHS.index(pick)])
    return sorted(chosen, key=lambda q: (GROUP_ORDER.index(q.contract.group), q.contract.commodity))


def last_expiry(contracts: Iterable[Contract]) -> Optional[date]:
    return max((c.expiry for c in contracts), default=None)


# -- quotes ------------------------------------------------------------------


def _number(value, cast=float):
    try:
        number = cast(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _trade_time(value) -> Optional[datetime]:
    """Dhan's ``01/10/2026 23:29:58`` or Kite's ``2026-10-01 23:29:58`` (both IST).

    A contract that never traded says ``01/01/1980`` on Dhan and ``1970-01-01 05:30:00`` on Kite.
    """
    for layout in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            when = datetime.strptime(str(value), layout).replace(tzinfo=IST)
        except ValueError:
            continue
        return when if when.year >= 2000 else None
    return None


def parse_quote(contract: Contract, entry: Optional[dict]) -> FutureQuote:
    """One Dhan ``/marketfeed/quote`` or Kite ``/quote`` entry (the fields used here have the same
    names on both). Zeros mean "no value" and become None."""
    entry = entry or {}
    ohlc = entry.get("ohlc") or {}
    return FutureQuote(
        contract=contract,
        ltp=_number(entry.get("last_price")),
        prev_close=_number(ohlc.get("close")),  # the previous session's close (see DhanProvider.get_quotes)
        open=_number(ohlc.get("open")),
        high=_number(ohlc.get("high")),
        low=_number(ohlc.get("low")),
        volume=_number(entry.get("volume"), int),
        oi=_number(entry.get("oi"), int),
        last_trade=_trade_time(entry.get("last_trade_time")),
    )


def fetch_quotes(provider, contracts: Sequence[Contract]) -> List[FutureQuote]:
    """One quote call for every contract the provider can address (Dhan takes 1000 per call, Kite
    500; MCX lists ~160 live). Contracts the provider has no id for are left out."""
    refs = {c: c.ref(provider.name) for c in contracts}
    refs = {c: ref for c, ref in refs.items() if ref is not None}
    raw = provider.get_quotes(list(refs.values())) if refs else {}
    return [parse_quote(c, raw.get(ref.symbol)) for c, ref in refs.items()]


def quotes_with_fallback(connect, contracts: Sequence[Contract], order: Sequence[str] = PROVIDERS):
    """Quotes from the first broker in ``order`` that returns any price.

    ``connect(name)`` returns a connected provider or raises. A broker that connects but prices
    nothing counts as failed too: Dhan's quote helper logs an API error and returns an empty
    result rather than raising. Returns ``(quotes, source, failures)``, where ``failures`` maps
    each broker that was tried and failed to the reason; ``source`` is "" if every broker failed.
    """
    failures: Dict[str, str] = {}
    for name in order:
        try:
            quotes = fetch_quotes(connect(name), contracts)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            failures[name] = str(exc) or type(exc).__name__
            continue
        if any(q.ltp for q in quotes):
            return quotes, name, failures
        failures[name] = "returned no prices"
    return [], "", failures


def candles_with_fallback(connect, contract: Contract, interval_label: str, now: datetime,
                          order: Sequence[str] = PROVIDERS):
    """Candles from the first broker in ``order`` that returns any. ``(rows, source, failures)``."""
    failures: Dict[str, str] = {}
    for name in order:
        try:
            rows = fetch_candles(connect(name), contract, interval_label, now)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            failures[name] = str(exc) or type(exc).__name__
            continue
        if rows:
            return rows, name, failures
        failures[name] = "returned no candles"
    return [], "", failures


def latest_trade(quotes: Iterable[FutureQuote]) -> Optional[datetime]:
    return max((q.last_trade for q in quotes if q.last_trade), default=None)


def is_live(quotes: Iterable[FutureQuote], now: datetime) -> bool:
    """Trading now, judged by the data itself, so MCX's own hours and holidays need no calendar."""
    latest = latest_trade(quotes)
    return latest is not None and now - latest <= LIVE_WITHIN


# -- candles -----------------------------------------------------------------

#: Chart choices: label -> (Dhan interval in minutes or None for daily, calendar days to fetch).
#: Dhan serves up to 90 days of minute candles per call.
INTERVALS = {
    "5 min": (5, 4),
    "15 min": (15, 10),
    "1 hour": (60, 30),
    "Daily": (None, 365),
}


def fetch_candles(provider, contract: Contract, interval_label: str, now: datetime) -> List[dict]:
    interval, days = INTERVALS[interval_label]
    ref = contract.ref(provider.name)
    if ref is None:
        return []
    end = now.replace(tzinfo=None) + timedelta(days=1)
    payload = provider.get_candles(ref, end - timedelta(days=days + 1), end, interval)
    return candle_rows(payload)


def candle_rows(payload: Optional[dict]) -> List[dict]:
    """Parallel candle arrays (Dhan's shape; Kite's are converted to it) as one dict per candle,
    times in IST (naive, for charting)."""
    if not payload:
        return []
    times = payload.get("timestamp") or []
    columns = ("open", "high", "low", "close", "volume", "open_interest")
    arrays = {name: payload.get(name) or [] for name in columns}
    rows = []
    for i, stamp in enumerate(times):
        try:
            when = datetime.fromtimestamp(float(stamp), IST).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            continue
        row = {"time": when}
        for name in columns:
            values = arrays[name]
            row[name] = values[i] if i < len(values) else None
        if row["close"] is not None:
            rows.append(row)
    return rows
