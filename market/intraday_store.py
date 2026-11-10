"""SQLite store for F&O stock history: 1-minute bars plus daily open/close.

One file, ``data/market.db`` (git-ignored, rebuilt by
``scripts/kite.py intraday``). Two tables and one view:

  minute_bars  symbol, ts, open, high, low, close, volume, oi
  daily_bars   symbol, date, open, high, low, close, volume
  daily_gaps   view: each day's open against the previous stored close

Why SQLite and not another CSV: 210 stocks x 60 days x ~360 bars is ~4.5M
rows. A CSV that size has to be read whole to answer "RELIANCE on 12 Sep";
SQLite answers it from the primary key and upserts a re-fetched window
without rewriting the file.

This module owns the file and the connection. Other features keep their own tables in the same
file by handing their schema to ``connect(extra_schema=...)``, and read it through
``connect_readonly()``: see ``market/dhan_movers_store.py`` (the Dhan gainers/losers history).

Timestamps are IST wall-clock text, ``YYYY-MM-DD HH:MM`` for bars and
``YYYY-MM-DD`` for days, so they sort, compare and ``LIKE``-filter as text.
A bar is stamped with the minute it *starts* (Kite's convention).

Daily opens and closes come from the broker's **daily** candles, never from
minute bars. NSE's official close is a volume-weighted average of the last
30 minutes, not the last minute bar's close, and the official open is the
pre-open auction price - so the gap in ``daily_gaps`` must use daily data.
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from market.market_hours import IST

logger = logging.getLogger(__name__)

DB_PATH = os.path.join("data", "market.db")
BACKFILL_SCRIPT = "scripts/kite.py intraday"

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


def connect(path: str = DB_PATH, extra_schema: str = "", timeout: float = 5.0) -> sqlite3.Connection:
    """Open (creating if needed) the store with its schema in place.

    ``extra_schema`` is another feature's ``CREATE ... IF NOT EXISTS`` script, applied to the same
    file so one database holds every history. ``timeout`` is how long to wait for another process
    holding the database, including while the file is first being created.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        if extra_schema:
            conn.executescript(extra_schema)
    except BaseException:
        conn.close()  # a half-opened handle would keep the file locked (Windows will not delete it)
        raise
    return conn


def store_stamp(path: str = DB_PATH) -> float:
    """When the database last changed, as a number that rises with every write.

    A cache key: a dashboard passes it to its cached loaders, so a fresh run of a script shows up on
    the next rerun. It includes the write-ahead log, which is where a write lands first.
    """
    return max((os.path.getmtime(p) for p in (path, path + "-wal") if os.path.exists(p)), default=0.0)


def connect_readonly(path: str = DB_PATH) -> Optional[sqlite3.Connection]:
    """A read-only handle on an existing store, or None if there is no file yet.

    Never creates or writes the database, so a dashboard can open it while a script is filling it
    (the store runs in WAL mode, so readers and the writer do not block each other).
    """
    if not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


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


def dhan_daily_rows(symbol: str, payload, exclude_date: Optional[str] = None) -> List[DailyRow]:
    """Dhan ``/charts/historical`` parallel arrays -> ``daily_bars`` rows, dropping ``exclude_date``.

    Dhan stamps a daily candle with the session's midnight IST in epoch seconds. Its prices are the
    raw traded ones (no corporate-action adjustment), the basis ``daily_bars`` is kept in.

    Dhan sometimes sends two candles for one day. Usually they are identical (CANBK, TMPV: kept once).
    For MOTHERSON up to 2024-04-29 they differ: two price series about 2:3 apart, after which only
    one continues (seen 2026-11-08). Then the candle whose close is nearest the next later day's
    kept close wins, so the stored series follows the one Dhan itself carries on with, without a
    false jump where the second series stops.
    """
    if not isinstance(payload, dict):
        return []
    columns = [payload.get(name) or [] for name in ("timestamp", "open", "high", "low", "close", "volume")]
    by_day = {}
    for stamp, *values in zip(*columns):
        try:
            day = datetime.fromtimestamp(int(stamp), IST).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        prices = [_price(v) for v in values[:4]]
        if day == exclude_date or None in prices:
            continue
        row = (symbol, day, *prices, int(values[4] or 0))
        if row not in by_day.setdefault(day, []):
            by_day[day].append(row)
    rows, later_close, ambiguous = [], None, 0
    for day in sorted(by_day, reverse=True):
        candidates = by_day[day]
        if len(candidates) > 1:
            ambiguous += 1
        row = candidates[-1] if later_close is None else min(candidates, key=lambda r: abs(r[5] - later_close))
        rows.append(row)
        later_close = row[5]
    if ambiguous:
        logger.warning("  %s: Dhan sent two different candles on %d day(s); kept the series that continues", symbol,
                    ambiguous)
    return rows[::-1]


#: Minutes kept from Groww: the continuous session. Groww also sends a pre-open bar (09:0x, volume
#: only) and 15:15-15:59 bars (closing auction session and after); neither is a regular minute bar.
GROWW_FIRST_MINUTE, GROWW_LAST_MINUTE = "09:15", "15:14"


def groww_minute_rows(symbol: str, candles, opens: Optional[dict] = None) -> List[MinuteRow]:
    """Groww ``[[iso_ts, o, h, l, c, v, oi], ...]`` (IST, no offset) -> ``minute_bars`` rows.

    Keeps 09:15-15:14 only. ``opens`` maps a date to the day's official open (from the daily candle):
    Groww's first bar opens at the first continuous trade, not at the pre-open auction price, so the
    09:15 bar's open is replaced by it and its high/low widened to include it.
    """
    rows = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        try:
            ts = datetime.fromisoformat(str(candle[0])).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if not GROWW_FIRST_MINUTE <= ts[11:] <= GROWW_LAST_MINUTE:
            continue
        o, h, l, c = (_price(v) for v in candle[1:5])
        if None in (o, h, l, c):
            continue
        official = (opens or {}).get(ts[:10]) if ts[11:] == GROWW_FIRST_MINUTE else None
        if official:
            o, h, l = official, max(h, official), min(l, official)
        oi = int(candle[6]) if len(candle) > 6 and candle[6] is not None else None
        rows.append((symbol, ts, o, h, l, c, int(candle[5] or 0), oi))
    return rows


def replace_days(conn: sqlite3.Connection, table: str, symbol: str, days: Iterable[str]) -> None:
    """Delete ``symbol``'s rows on ``days`` from ``minute_bars`` or ``daily_bars`` before re-inserting them.

    A source switch must not leave the old source's rows behind: a minute one broker has and the
    other skips would otherwise stay, mixed into the new day.
    """
    if table == "minute_bars":
        conn.executemany("DELETE FROM minute_bars WHERE symbol = ? AND ts LIKE ?",
                         [(symbol, f"{day}%") for day in sorted(set(days))])
    elif table == "daily_bars":
        conn.executemany("DELETE FROM daily_bars WHERE symbol = ? AND date = ?",
                         [(symbol, day) for day in sorted(set(days))])
    else:
        raise ValueError(table)


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
