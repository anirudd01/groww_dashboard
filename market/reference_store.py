"""Generated reference data, kept in the shared SQLite store.

Each broker's instrument ids (``dhan_instruments``, ``indmoney_instruments``, ``kite_instruments``),
the free-float weights (``index_weights``), the F&O stock list (``fno_universe``) and the confirmed
moves (``fno_confirmed_moves``) are sets here, in ``data/market.db``, the file
``market/intraday_store.py`` owns. A script generates each one, and the dashboards read it at startup
and never fetch it live: generated offline, read-only at runtime, and if it is missing the loader says
which script to run.

Every set has the same shape, a few fields about the set plus one or more sections of keyed rows, so
two tables hold them all:

  reference_sets  one row per set: its name, when it was generated, and its other top-level fields
  reference_rows  one row per entry: (set, section, key) and the entry itself as JSON. A section is
                  a top-level field, or ``field/group`` for the instrument files (``instruments/CASH``)

``save_document`` splits a set's JSON document into those rows (replacing the whole set in one
transaction, and recording the layout in the metadata), and ``load_document`` joins them back into
the same dictionary, so a loader parses a set as a plain dict. ``market/instruments.py``,
``market/weights.py`` and ``market/fno_movers.py`` are the readers.

``fno_confirmed_moves`` is the one set a person curates rather than a script: ``scripts/confirm_fno_move.py``
adds and removes entries, and each carries the note saying why.
"""

import json
import os
import sqlite3
from typing import Dict, Optional, Sequence

from market import intraday_store, state_store

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_sets (
    name         TEXT PRIMARY KEY,   -- dhan_instruments | indmoney_instruments | kite_instruments | index_weights | fno_universe
    generated_at TEXT,               -- the document's own generated_at, ISO UTC
    meta         TEXT NOT NULL       -- JSON: every other top-level field (source, note, counts, ...)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS reference_rows (
    set_name TEXT NOT NULL,
    section  TEXT NOT NULL,          -- e.g. CASH / INDEX for instruments, 'weights', 'tokens'
    key      TEXT NOT NULL,          -- usually the symbol
    entry    TEXT NOT NULL,          -- JSON: the row's fields (or a bare value such as a token)
    PRIMARY KEY (set_name, section, key)
) WITHOUT ROWID;
"""


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    return state_store.connect_shared(path, SCHEMA)


LAYOUT_KEY = "__layout__"


def save_document(name: str, document: dict, sections: Sequence[str] = (), nested: Sequence[str] = (),
                  path: Optional[str] = None) -> int:
    """Store ``document`` as the set ``name``, replacing any earlier version in one transaction.

    ``sections`` names top-level fields that are ``{key: entry}`` objects. ``nested`` names top-level
    fields that are ``{section: {key: entry}}`` (the instrument files: segment, then symbol). Every
    other field becomes the set's metadata. Returns how many rows were stored.
    """
    meta = {k: v for k, v in document.items() if k not in sections and k not in nested}
    meta[LAYOUT_KEY] = {"sections": list(sections),
                        "nested": {field: list((document.get(field) or {})) for field in nested}}
    rows = []
    for field in sections:
        entries = document.get(field) or {}
        if not isinstance(entries, dict):
            raise ValueError(f"{name}: {field!r} must be an object of key -> entry")
        rows.extend((name, field, str(key), json.dumps(entry)) for key, entry in entries.items())
    for field in nested:
        groups = document.get(field) or {}
        if not isinstance(groups, dict) or not all(isinstance(g, dict) for g in groups.values()):
            raise ValueError(f"{name}: {field!r} must be an object of section -> {{key: entry}}")
        for section, entries in groups.items():
            rows.extend((name, f"{field}/{section}", str(key), json.dumps(entry)) for key, entry in entries.items())
    conn = _connect(path)
    try:
        with conn:
            conn.execute("DELETE FROM reference_rows WHERE set_name = ?", (name,))
            conn.execute(
                "INSERT INTO reference_sets (name, generated_at, meta) VALUES (?, ?, ?) "
                "ON CONFLICT (name) DO UPDATE SET generated_at = excluded.generated_at, meta = excluded.meta",
                (name, document.get("generated_at"), json.dumps(meta)),
            )
            conn.executemany("INSERT INTO reference_rows (set_name, section, key, entry) VALUES (?, ?, ?, ?)", rows)
    finally:
        conn.close()
    return len(rows)


def load_document(name: str, path: Optional[str] = None) -> Optional[dict]:
    """The set as the dictionary it was saved from, or None if it is not stored. Never raises.

    Does not create the database: a machine that has never run the generating script has nothing yet.
    """
    conn = intraday_store.connect_readonly(path or state_store.db_path())
    if conn is None:
        return None
    try:
        head = conn.execute("SELECT meta, generated_at FROM reference_sets WHERE name = ?", (name,)).fetchone()
        if head is None:
            return None
        document: Dict[str, object] = json.loads(head[0])
        layout = document.pop(LAYOUT_KEY, {})
        for field in layout.get("sections", ()):
            document[field] = {}
        for field, groups in (layout.get("nested") or {}).items():
            document[field] = {group: {} for group in groups}
        for section, key, entry in conn.execute(
                "SELECT section, key, entry FROM reference_rows WHERE set_name = ? ORDER BY section, key", (name,)):
            if "/" in section:
                field, group = section.split("/", 1)
                document.setdefault(field, {}).setdefault(group, {})[key] = json.loads(entry)
            else:
                document.setdefault(section, {})[key] = json.loads(entry)
        if head[1] is not None:
            document["generated_at"] = head[1]
        return document
    except (sqlite3.Error, ValueError):
        return None
    finally:
        conn.close()


def delete_document(name: str, path: Optional[str] = None) -> bool:
    """Remove a stored set. True if there was one."""
    if not os.path.exists(path or state_store.db_path()):
        return False
    conn = _connect(path)
    try:
        with conn:
            conn.execute("DELETE FROM reference_rows WHERE set_name = ?", (name,))
            return conn.execute("DELETE FROM reference_sets WHERE name = ?", (name,)).rowcount > 0
    finally:
        conn.close()
