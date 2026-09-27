"""SQLite store for F&O stock history: 1-minute bars plus daily open/close.

One file, ``data/market.db`` (git-ignored, rebuilt by
``scripts/backfill_intraday.py``). Two tables and one view:

  minute_bars  symbol, ts, open, high, low, close, volume, oi
  daily_bars   symbol, date, open, high, low, close, volume
  daily_gaps   view: each day's open against the previous stored close

Why SQLite and not another CSV: 210 stocks x 60 days x ~360 bars is ~4.5M
rows. A CSV that size has to be read whole to answer "RELIANCE on 12 Sep";
SQLite answers it from the primary key and upserts a re-fetched window
without rewriting the file.

Timestamps are IST wall-clock text, ``YYYY-MM-DD HH:MM`` for bars and
``YYYY-MM-DD`` for days, so they sort, compare and ``LIKE``-filter as text.
A bar is stamped with the minute it *starts* (Kite's convention).

Daily opens and closes come from the broker's **daily** candles, never from
minute bars. NSE's official close is a volume-weighted average of the last
30 minutes, not the last minute bar's close, and the official open is the
pre-open auction price - so the gap in ``daily_gaps`` must use daily data.
"""

import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

DB_PATH = os.path.join("data", "market.db")
BACKFILL_SCRIPT = "scripts/backfill_intraday.py"

SCHEMA = """
CREATE TABLE IF NOT EXISTS minute_bars (
    symbol TEXT NOT NULL,
    ts     TEXT NOT NULL,          -- 'YYYY-MM-DD HH:MM' IST, bar start
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume INTEGER NOT NULL,
    oi     INTEGER,                -- NULL for cash stocks
    PRIMARY KEY (symbol, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS daily_bars (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,          -- 'YYYY-MM-DD'
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (symbol, date)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS daily_bars_by_date ON daily_bars (date);

-- The previous row for the symbol is the previous trading day, so holidays
-- and weekends are skipped without a calendar.
CREATE VIEW IF NOT EXISTS daily_gaps AS
SELECT symbol, date, open, close,
       prev_close,
       ROUND((open / prev_close - 1) * 100, 4) AS gap_pct
FROM (
    SELECT symbol, date, open, close,
           LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev_close
    FROM daily_bars
)
WHERE prev_close IS NOT NULL;
"""

MinuteRow = Tuple[str, str, float, float, float, float, int, Optional[int]]
DailyRow = Tuple[str, str, float, float, float, float, int]


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the store with its schema in place."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def _ist_text(stamp: str, minutes: bool) -> Optional[str]:
    """Kite's ``2026-09-24T09:15:00+0530`` -> ``2026-09-24 09:15`` (or the date)."""
    try:
        moment = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None
    return moment.strftime("%Y-%m-%d %H:%M" if minutes else "%Y-%m-%d")


def _price(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def kite_minute_rows(symbol: str, candles) -> List[MinuteRow]:
    """Kite ``[[iso_ts, o, h, l, c, v(, oi)], ...]`` -> ``minute_bars`` rows.

    Rows with an unreadable stamp or a missing price are dropped, not
    zero-filled: a bar that says 0 would read as a crash.
    """
    rows = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        ts = _ist_text(candle[0], minutes=True)
        prices = [_price(v) for v in candle[1:5]]
        if ts is None or None in prices:
            continue
        oi = int(candle[6]) if len(candle) > 6 and candle[6] is not None else None
        rows.append((symbol, ts, *prices, int(candle[5] or 0), oi))
    return rows


def kite_daily_rows(symbol: str, candles, exclude_date: Optional[str] = None) -> List[DailyRow]:
    """Kite daily candles -> ``daily_bars`` rows, dropping ``exclude_date``.

    ``exclude_date`` is today while the session is open: its "close" is only
    the live price.
    """
    rows = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        day = _ist_text(candle[0], minutes=False)
        prices = [_price(v) for v in candle[1:5]]
        if day is None or day == exclude_date or None in prices:
            continue
        rows.append((symbol, day, *prices, int(candle[5] or 0)))
    return rows


def upsert_minutes(conn: sqlite3.Connection, rows: Iterable[MinuteRow]) -> int:
    """Insert or overwrite bars; a re-fetched window replaces what was stored."""
    cur = conn.executemany(
        "INSERT INTO minute_bars (symbol, ts, open, high, low, close, volume, oi) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, ts) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, volume=excluded.volume, oi=excluded.oi",
        list(rows),
    )
    return cur.rowcount


def upsert_daily(conn: sqlite3.Connection, rows: Iterable[DailyRow]) -> int:
    cur = conn.executemany(
        "INSERT INTO daily_bars (symbol, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, volume=excluded.volume",
        list(rows),
    )
    return cur.rowcount


def last_minute(conn: sqlite3.Connection, symbol: str) -> Optional[str]:
    """The latest stored bar stamp for ``symbol``, or None."""
    row = conn.execute("SELECT MAX(ts) FROM minute_bars WHERE symbol = ?", (symbol,)).fetchone()
    return row[0] if row else None


def summary(conn: sqlite3.Connection) -> dict:
    """Row counts and date span, for the end-of-run log line."""
    bars, symbols, first, last = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(ts), MAX(ts) FROM minute_bars"
    ).fetchone()
    days, first_day, last_day = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM daily_bars"
    ).fetchone()
    return {
        "minute_bars": bars, "symbols": symbols, "first_bar": first, "last_bar": last,
        "daily_bars": days, "first_day": first_day, "last_day": last_day,
    }
