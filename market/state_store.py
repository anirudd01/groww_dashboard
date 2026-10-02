"""Small runtime state, kept in the shared SQLite store.

The Dhan, INDmoney and Kite access tokens and this PC's clock offset are rows in the
``runtime_state`` table of ``data/market.db``, the file ``market/intraday_store.py`` owns and every
other history lives in.

  runtime_state  name -> a JSON object (the saved session, or the offset), and when it was written
  state_locks    a lease row per name, so two processes starting together mint one token

Each name holds one document: ``dhan_session``, ``indmoney_session``, ``kite_session``,
``clock_offset``. ``read`` never raises and never creates the database; ``write`` does.

**The tokens are live credentials, and they are in a file you may back up.** All of them expire
within a day (Kite at 06:00 IST, Dhan after 24 hours, INDmoney at 07:00), so a stale backup holds
nothing usable, but the file is not for sharing. It is git-ignored.

``PULSE_STATE_DB`` points all of this at another database file (the tests use it).
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Optional

from market import intraday_store
from market.market_hours import IST

logger = logging.getLogger(__name__)

PATH_ENV = "PULSE_STATE_DB"

#: The repository root, so every process finds the same file whatever its working directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: A held lock older than this is taken to belong to a process that died.
LOCK_STALE_SECONDS = 120
#: How long a write waits for another writer before giving up. Token writes are tiny, but the
#: F&O backfill holds the database for short bursts.
BUSY_TIMEOUT_MS = 30000
#: Attempts to open the database before a creation race is treated as a failure.
CONNECT_TRIES = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_state (
    name       TEXT PRIMARY KEY,   -- dhan_session | indmoney_session | kite_session | clock_offset
    payload    TEXT NOT NULL,      -- one JSON object
    updated_at TEXT NOT NULL       -- IST ISO time it was last written
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS state_locks (
    name        TEXT PRIMARY KEY,
    acquired_at REAL NOT NULL      -- Unix time the lease was taken
) WITHOUT ROWID;
"""


def db_path() -> str:
    """``$PULSE_STATE_DB`` if set, else ``data/market.db`` at the repository root."""
    return os.getenv(PATH_ENV) or os.path.join(REPO_ROOT, intraday_store.DB_PATH)


def connect_shared(path: Optional[str], schema: str) -> sqlite3.Connection:
    """The shared store with ``schema`` added. A few tries, because several processes starting together
    on a fresh machine all create the file at once and SQLite can refuse the first switch to WAL."""
    for attempt in range(CONNECT_TRIES):
        try:
            return intraday_store.connect(path or db_path(), schema, timeout=BUSY_TIMEOUT_MS / 1000)
        except sqlite3.OperationalError:
            if attempt == CONNECT_TRIES - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    return connect_shared(path, SCHEMA)


def read(name: str, path: Optional[str] = None) -> Optional[dict]:
    """The stored document, or None if there is none or it cannot be read. Never raises.

    Does not create the database: a machine that has never logged in simply has nothing yet.
    """
    path = path or db_path()
    conn = intraday_store.connect_readonly(path)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT payload FROM runtime_state WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        document = json.loads(row[0])
        return document if isinstance(document, dict) else None
    except sqlite3.OperationalError:
        return None  # a store built before this table existed
    except (sqlite3.Error, ValueError) as exc:
        logger.warning("Could not read the %s state from %s: %s", name, path, exc)
        return None
    finally:
        conn.close()


def write(name: str, document: dict, path: Optional[str] = None) -> None:
    """Store ``document`` under ``name``, replacing what was there. Raises ``sqlite3.Error`` on failure."""
    conn = _connect(path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO runtime_state (name, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (name) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
                (name, json.dumps(document), datetime.now(IST).isoformat(timespec="seconds")),
            )
    finally:
        conn.close()


def delete(name: str, path: Optional[str] = None) -> bool:
    """Remove a stored document. True if there was one."""
    path = path or db_path()
    if not os.path.exists(path):
        return False
    conn = _connect(path)
    try:
        with conn:
            return conn.execute("DELETE FROM runtime_state WHERE name = ?", (name,)).rowcount > 0
    finally:
        conn.close()


class Lock:
    """Cross-process lock on a name: a lease row, taken atomically and cleared if abandoned.

    Holding it does **not** hold the database: the lease is one
    short write, so a token request that takes seconds does not block anything else writing.
    """

    def __init__(self, name: str, path: Optional[str] = None, timeout: float = 90.0, error=RuntimeError,
                 stale_after: float = LOCK_STALE_SECONDS):
        self.name, self.path, self.timeout = name, path, timeout
        self.error, self.stale_after = error, stale_after
        self._taken_at: Optional[float] = None

    def _try_acquire(self) -> bool:
        conn = _connect(self.path)
        try:
            now = time.time()
            with conn:
                conn.execute("DELETE FROM state_locks WHERE name = ? AND acquired_at < ?",
                             (self.name, now - self.stale_after))
                try:
                    conn.execute("INSERT INTO state_locks (name, acquired_at) VALUES (?, ?)", (self.name, now))
                except sqlite3.IntegrityError:
                    return False  # someone holds it
            self._taken_at = now
            return True
        finally:
            conn.close()

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if self._try_acquire():
                    return self
            except sqlite3.OperationalError as exc:
                raise self.error(f"Could not take the {self.name} lock in {self.path or db_path()}: {exc}") from exc
            if time.monotonic() > deadline:
                raise self.error(f"Timed out waiting for the {self.name} lock - clear the state_locks row if no "
                                 "other process is running")
            time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            conn = _connect(self.path)
            try:
                with conn:  # only our own lease, not one taken after ours went stale
                    conn.execute("DELETE FROM state_locks WHERE name = ? AND acquired_at = ?",
                                 (self.name, self._taken_at))
            finally:
                conn.close()
        except sqlite3.Error:
            pass
