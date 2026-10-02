"""The Dhan gainers/losers history, as two tables in the shared ``data/market.db``.

The file and connection belong to ``market/intraday_store.py``; this module adds its tables to
that file (``connect(extra_schema=...)``) and reads them back (``connect_readonly``), in the same
style: composite primary keys, ``WITHOUT ROWID``, dates as ``YYYY-MM-DD`` text in IST.

  dhan_movers          one row per ranked stock: when, universe, gainer/loser, rank, symbol, price, % change
  dhan_movers_breadth  one row per universe per capture: how many stocks are up and down

``trading_date`` is the session the prices belong to (read from Dhan's last trade time), not the
day the script ran; ``captured_at`` is when it ran. See ``market/dhan_movers_history.py`` for how
a capture is taken, and ``docs/DHAN_MOVERS.md`` for the columns and how to read them.

Both tables are written in one transaction, so a capture is whole or absent. Volume and open
interest are deliberately not stored.
"""

import sqlite3
from typing import Dict, List, Optional

from market import intraday_store

DB_PATH = intraday_store.DB_PATH

KIND_CLOSE = "close"
GAINER, LOSER = "gainer", "loser"

SCHEMA = """
CREATE TABLE IF NOT EXISTS dhan_movers (
    trading_date TEXT NOT NULL,    -- 'YYYY-MM-DD', the session the prices belong to
    kind         TEXT NOT NULL,    -- 'close' | 'intraday'
    captured_at  TEXT NOT NULL,    -- IST ISO time the script ran
    universe     TEXT NOT NULL,    -- Dhan universe key, e.g. NIFTY_50
    side         TEXT NOT NULL,    -- 'gainer' | 'loser'
    rank         INTEGER NOT NULL, -- 1 = the biggest move on that side
    symbol       TEXT NOT NULL,
    name         TEXT NOT NULL,
    ltp          REAL NOT NULL,
    change_pct   REAL NOT NULL,    -- against the previous close
    PRIMARY KEY (trading_date, kind, captured_at, universe, side, rank)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS dhan_movers_by_symbol ON dhan_movers (symbol, trading_date);

CREATE TABLE IF NOT EXISTS dhan_movers_breadth (
    trading_date     TEXT NOT NULL,
    kind             TEXT NOT NULL,
    captured_at      TEXT NOT NULL,
    universe         TEXT NOT NULL,
    advancing        INTEGER NOT NULL,   -- stocks up on the day
    declining        INTEGER NOT NULL,
    advancing_capped INTEGER NOT NULL,   -- 1 where Dhan's 100-row limit cut the count short
    declining_capped INTEGER NOT NULL,
    PRIMARY KEY (trading_date, kind, captured_at, universe)
) WITHOUT ROWID;
"""

MOVER_COLUMNS = ("trading_date", "kind", "captured_at", "universe", "side", "rank",
                 "symbol", "name", "ltp", "change_pct")
BREADTH_COLUMNS = ("trading_date", "kind", "captured_at", "universe", "advancing", "declining",
                   "advancing_capped", "declining_capped")


def _named_insert(table: str, columns) -> str:
    return (f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)})")


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """The shared store with these tables in place (created if the file or tables are new)."""
    conn = intraday_store.connect(path or DB_PATH, SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(path: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """A read-only handle, or None if there is no database file yet."""
    conn = intraday_store.connect_readonly(path or DB_PATH)
    if conn is not None:
        conn.row_factory = sqlite3.Row
    return conn


def has_history(conn: sqlite3.Connection) -> bool:
    """Whether the tables exist: a store built by the F&O backfill alone does not have them."""
    found = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('dhan_movers', 'dhan_movers_breadth')"
    ).fetchone()[0]
    return found == 2


# -- writing -------------------------------------------------------------------


def save_capture(conn: sqlite3.Connection, mover_rows: List[dict], breadth_rows: List[dict]) -> None:
    """Store one capture: every mover row and every breadth row, or none of them."""
    with conn:
        conn.executemany(_named_insert("dhan_movers", MOVER_COLUMNS), mover_rows)
        conn.executemany(_named_insert("dhan_movers_breadth", BREADTH_COLUMNS), breadth_rows)


# -- reading -------------------------------------------------------------------


def has_session(conn: sqlite3.Connection, trading_date: str, kind: str = KIND_CLOSE) -> bool:
    """Whether that session's capture of this kind is already stored."""
    row = conn.execute("SELECT 1 FROM dhan_movers_breadth WHERE trading_date = ? AND kind = ? LIMIT 1",
                       (trading_date, kind)).fetchone()
    return row is not None


def session_dates(conn: sqlite3.Connection, kind: str = KIND_CLOSE) -> List[str]:
    """Stored session dates, newest first."""
    if not has_history(conn):
        return []
    rows = conn.execute("SELECT DISTINCT trading_date FROM dhan_movers_breadth WHERE kind = ? "
                        "ORDER BY trading_date DESC", (kind,))
    return [r[0] for r in rows]


def universes_on(conn: sqlite3.Connection, trading_date: str, kind: str = KIND_CLOSE) -> List[str]:
    """Universes captured for that session, in alphabetical order."""
    rows = conn.execute("SELECT DISTINCT universe FROM dhan_movers_breadth WHERE trading_date = ? AND kind = ? "
                        "ORDER BY universe", (trading_date, kind))
    return [r[0] for r in rows]


def movers_on(conn: sqlite3.Connection, trading_date: str, universe: str, kind: str = KIND_CLOSE,
              ) -> Dict[str, List[sqlite3.Row]]:
    """``{'gainer': [...], 'loser': [...]}``, each in rank order, for the latest capture of that session."""
    rows = conn.execute(
        "SELECT side, rank, symbol, name, ltp, change_pct FROM dhan_movers "
        "WHERE trading_date = ? AND kind = ? AND universe = ? AND captured_at = ("
        "  SELECT MAX(captured_at) FROM dhan_movers_breadth WHERE trading_date = ? AND kind = ? AND universe = ?) "
        "ORDER BY side, rank",
        (trading_date, kind, universe, trading_date, kind, universe)).fetchall()
    return {side: [r for r in rows if r["side"] == side] for side in (GAINER, LOSER)}


def breadth_history(conn: sqlite3.Connection, universe: str, kind: str = KIND_CLOSE) -> List[sqlite3.Row]:
    """Advancing and declining counts of one universe, one row per stored session, oldest first."""
    if not has_history(conn):
        return []
    return conn.execute(
        "SELECT trading_date, advancing, declining, advancing_capped, declining_capped "
        "FROM dhan_movers_breadth b WHERE universe = ? AND kind = ? AND captured_at = ("
        "  SELECT MAX(captured_at) FROM dhan_movers_breadth "
        "  WHERE trading_date = b.trading_date AND kind = b.kind AND universe = b.universe) "
        "ORDER BY trading_date", (universe, kind)).fetchall()


def repeat_movers(conn: sqlite3.Connection, universe: str, side: str, top: int = 10, limit: int = 20,
                  kind: str = KIND_CLOSE) -> List[sqlite3.Row]:
    """Stocks that keep appearing among the ``top`` gainers (or losers) of a universe.

    Each row: symbol, name, ``sessions`` it was in the top, and ``avg_move`` (mean % change on
    those days). Counted over every stored session of that kind.
    """
    if not has_history(conn):
        return []
    return conn.execute(
        "SELECT symbol, MAX(name) AS name, COUNT(DISTINCT trading_date) AS sessions, "
        "       ROUND(AVG(change_pct), 2) AS avg_move "
        "FROM dhan_movers WHERE universe = ? AND side = ? AND kind = ? AND rank <= ? "
        "GROUP BY symbol ORDER BY sessions DESC, ABS(avg_move) DESC, symbol LIMIT ?",
        (universe, side, kind, top, limit)).fetchall()


def summary(conn: sqlite3.Connection, kind: str = KIND_CLOSE) -> dict:
    """Sessions stored and their span, for a status line."""
    if not has_history(conn):
        return {"sessions": 0, "first": None, "last": None, "rows": 0}
    sessions, first, last = conn.execute(
        "SELECT COUNT(DISTINCT trading_date), MIN(trading_date), MAX(trading_date) "
        "FROM dhan_movers_breadth WHERE kind = ?", (kind,)).fetchone()
    rows = conn.execute("SELECT COUNT(*) FROM dhan_movers WHERE kind = ?", (kind,)).fetchone()[0]
    return {"sessions": sessions, "first": first, "last": last, "rows": rows}
