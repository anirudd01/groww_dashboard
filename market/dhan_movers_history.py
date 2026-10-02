"""Keep a history of Dhan's stock gainers and losers, in the shared SQLite database.

``scripts/store_dhan_movers.py`` calls this. Dhan's ``/data/marketmovers`` only ever answers
"today against the previous close", so a history exists only if it is saved as it happens.
Each capture asks Dhan for the gainers and losers of every chosen universe (F&O stocks,
Nifty 50, each NSE sector index, ...) and writes them to two tables of ``data/market.db``
(``market/dhan_movers_store.py`` has the schema and the reads):

``dhan_movers``, one row per ranked stock::

    trading_date, kind, captured_at, universe, side, rank, symbol, name, ltp, change_pct

``dhan_movers_breadth``, one row per universe per capture::

    trading_date, kind, captured_at, universe, advancing, declining, advancing_capped, declining_capped

Breadth is how many stocks of the universe are up and down. Dhan returns at most 100 per side
(there is no paging) and only stocks that moved, so a count under 100 is exact and ``*_capped``
marks a count that stopped at the limit. The sector-index universes make this the index-level
picture too.

Volume and open interest are deliberately not stored.

**``trading_date`` is the session the prices belong to, not the day the script ran.** Dhan's
rankings carry no date and answer with the last session at the weekend, on a holiday and before
the open, so the date is read from the feed (``dhan_movers.session_date``): run on Friday 2 Oct
2026, a holiday, the rows are filed under Thursday 1 Oct. ``captured_at`` is when it ran.

``kind`` is ``close`` (a finished session; the default and the point of this module) or
``intraday`` (taken while the market is open; only with ``intraday=True``). A close is taken once
the session is over: any later day, or after 16:00 IST on the day itself, once the closing figures
have settled. It is stored once per session date. A capture is written in one transaction.

Read-only against Dhan: it calls one ranking endpoint and places no orders.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Callable, List, Optional, Sequence, Tuple

from market import dhan_movers as dm
from market import dhan_movers_store as store
from market.market_hours import MARKET_OPEN

KIND_INTRADAY = "intraday"
KIND_CLOSE = store.KIND_CLOSE
GAINER, LOSER = store.GAINER, store.LOSER

#: Today's closing figures are trusted from this IST time, as in the F&O close history.
CLOSE_AFTER = time(16, 0)
#: Tries per universe. Dhan now and then times out on one call (seen on Nifty Smallcap 100 and
#: on the all-NSE universe), and a close capture is all-or-nothing.
ATTEMPTS = 2
#: Consecutive failing universes before a capture gives up (an expired token fails them all).
MAX_CONSECUTIVE_FAILURES = 3

# -- what a capture may be --------------------------------------------------------


def decide(now: datetime, session: date, intraday: bool = False) -> Tuple[Optional[str], str]:
    """What to capture now, given the session Dhan's prices belong to: (kind, why-not).

    ``close`` when that session is over: an earlier day (a weekend, a holiday, or before today's
    open), or today after 16:00. ``intraday`` while today's session runs, but only if asked for.
    Otherwise ``(None, reason)``.
    """
    if session < now.date():
        return KIND_CLOSE, ""
    clock = now.time()
    if clock < MARKET_OPEN:
        return None, "today's pre-open session is under way"
    if clock < CLOSE_AFTER:
        if clock <= time(15, 30) and intraday:
            return KIND_INTRADAY, ""
        if clock <= time(15, 30):
            return None, f"the market is open, and the close is stored after {CLOSE_AFTER:%H:%M} IST (intraday capture is off)"
        return None, f"the closing figures settle after {CLOSE_AFTER:%H:%M} IST"
    return KIND_CLOSE, ""


def resolve_universes(names: Optional[Sequence[str]]) -> List[str]:
    """Dhan universe keys for what the user typed: a key (``NIFTY_BANK``) or a label (``Nifty Bank``)."""
    if not names:
        return list(dm.UNIVERSES.values())
    by_label = {label.lower(): key for label, key in dm.UNIVERSES.items()}
    keys = set(dm.UNIVERSES.values())
    resolved = []
    for name in names:
        name = name.strip()
        key = name.upper() if name.upper() in keys else by_label.get(name.lower())
        if key is None:
            raise ValueError(f"Unknown universe {name!r}. Choose from: {', '.join(sorted(keys))}")
        if key not in resolved:
            resolved.append(key)
    return resolved


# -- fetching ------------------------------------------------------------------


@dataclass
class UniverseSnapshot:
    universe: str
    gainers: List[dm.Mover]
    losers: List[dm.Mover]


def collect(provider, universes: Sequence[str], fetch: Callable = dm.fetch,
            ) -> Tuple[List[UniverseSnapshot], List[Tuple[str, str]]]:
    """Gainers and losers of each universe. Returns (snapshots, [(universe, error)]).

    A universe is kept only if both its calls worked, since a half-known breadth is wrong.
    """
    snapshots, failed, streak = [], [], 0
    for universe in universes:
        for _ in range(ATTEMPTS):
            try:
                gainers = fetch(provider, dm.STOCKS, dm.PRICE_GAINERS, universe=universe, limit=dm.MAX_LIMIT)
                losers = fetch(provider, dm.STOCKS, dm.PRICE_LOSERS, universe=universe, limit=dm.MAX_LIMIT)
            except Exception as exc:  # noqa: BLE001 - retried, then recorded; the rest still run
                error = str(exc)
                continue
            snapshots.append(UniverseSnapshot(universe, gainers, losers))
            streak = 0
            break
        else:
            failed.append((universe, error))
            streak += 1
            if streak >= MAX_CONSECUTIVE_FAILURES:
                break
    return snapshots, failed


# -- rows ----------------------------------------------------------------------


def build_rows(captured_at: datetime, trading_date: date, kind: str, snapshots: Sequence[UniverseSnapshot],
               top: int) -> Tuple[List[dict], List[dict]]:
    """The rows for one capture: the top ``top`` of each side, and the breadth of each universe."""
    stamp = captured_at.isoformat(timespec="seconds")
    day = trading_date.isoformat()
    movers, breadth = [], []
    for snap in snapshots:
        for side, ranked in ((GAINER, snap.gainers), (LOSER, snap.losers)):
            for rank, m in enumerate(ranked[:top], start=1):
                movers.append({"trading_date": day, "kind": kind, "captured_at": stamp,
                               "universe": snap.universe, "side": side, "rank": rank,
                               "symbol": m.symbol, "name": m.name, "ltp": m.ltp,
                               "change_pct": round(m.change_pct, 4)})
        breadth.append({"trading_date": day, "kind": kind, "captured_at": stamp,
                        "universe": snap.universe, "advancing": len(snap.gainers),
                        "declining": len(snap.losers),
                        "advancing_capped": int(len(snap.gainers) >= dm.MAX_LIMIT),
                        "declining_capped": int(len(snap.losers) >= dm.MAX_LIMIT)})
    return movers, breadth


# -- one capture ---------------------------------------------------------------

STORED, SKIPPED, FAILED, DRY_RUN = "stored", "skipped", "failed", "dry-run"


@dataclass
class Capture:
    status: str
    message: str
    kind: str = ""
    session: Optional[date] = None
    mover_rows: List[dict] = field(default_factory=list)
    breadth_rows: List[dict] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)


def capture(provider, universes: Sequence[str], *, top: int, now: datetime, intraday: bool = False,
            db_path: Optional[str] = None, dry_run: bool = False, fetch: Callable = dm.fetch,
            session_of: Callable = dm.session_date) -> Capture:
    """Take one capture and store it, unless it should not be stored (and say why).

    ``dry_run`` fetches and builds the rows whatever the time or what is stored, and neither
    opens nor writes the database.
    """
    try:
        session = session_of(provider)
    except Exception as exc:  # noqa: BLE001 - reported
        return Capture(FAILED, f"Nothing stored: could not tell which session Dhan's prices belong to ({exc}).")

    kind, reason = decide(now, session, intraday)
    if kind is None and not dry_run:
        return Capture(SKIPPED, f"Nothing stored: {reason}.", session=session)
    kind = kind or KIND_INTRADAY

    conn = None if dry_run else store.connect(db_path)
    try:
        if conn is not None and kind == KIND_CLOSE and store.has_session(conn, session.isoformat(), KIND_CLOSE):
            return Capture(SKIPPED, f"The close for {session:%a %d %b %Y} is already stored. Dhan's latest prices "
                                    f"are still that session's, so there is nothing new.", kind, session)

        snapshots, failed = collect(provider, universes, fetch)
        if not snapshots:
            detail = f" First error: {failed[0][1]}" if failed else ""
            return Capture(FAILED, f"No universe could be fetched.{detail}", kind, session, failed=failed)
        if failed and kind == KIND_CLOSE and not dry_run:
            names = ", ".join(u for u, _ in failed)
            return Capture(FAILED, f"The close is incomplete ({names} failed), so nothing was stored. Run it again.",
                           kind, session, failed=failed)

        mover_rows, breadth_rows = build_rows(now, session, kind, snapshots, top)
        if dry_run:
            return Capture(DRY_RUN, f"Dry run, {kind} for {session:%a %d %b %Y}: {len(mover_rows)} rows for "
                                    f"{len(snapshots)} universes, nothing written.",
                           kind, session, mover_rows, breadth_rows, failed)
        store.save_capture(conn, mover_rows, breadth_rows)
        return Capture(STORED, f"Stored the {kind} for {session:%a %d %b %Y}: {len(mover_rows)} rows for "
                               f"{len(snapshots)} universes.", kind, session, mover_rows, breadth_rows, failed)
    finally:
        if conn is not None:
            conn.close()
