"""Broker instrument ids for the tracked universes.

Ids are **read from a local JSON file, never fetched at runtime.** Dhan
publishes them only as a 35 MB CSV, served uncompressed, containing every F&O
contract on every exchange - 206,659 rows, of which this dashboard uses about
sixty. Downloading that on every boot cost 15-40 s for data that changes at
most once a day, and in practice changes meaningfully only when NSE
reconstitutes an index.

The file is produced offline by ``scripts/fetch_instrument_master.py`` and is
meant to be regenerated manually - monthly, or whenever a symbol stops
resolving. It is small enough to read at a glance and to diff in a commit, so a
reconstitution shows up as a handful of changed lines.

Same contract as ``market/weights.py``: generated offline, committed, loaded at
startup, never fetched live.

What is *not* in here
---------------------
Sector membership. That lives in ``market/sector_mapping.py`` and is the
editable source of truth for which symbols the dashboard tracks. This file only
answers "what number does the broker call RELIANCE".

If the file is missing or a symbol is absent from it, resolution fails loudly
and names the script to run. There is no fallback download: a dashboard that
silently pulls 35 MB during market hours is exactly what this replaces, and an
id that cannot be verified must never be guessed.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

#: Default location, relative to the repository root. One file per broker,
#: because a security id is only meaningful to the broker that issued it.
DEFAULT_INSTRUMENTS_PATH = os.path.join("data", "dhan_instruments.json")

#: Beyond this the loader warns that the file is getting old. Not an error:
#: security ids of existing instruments are stable, and NSE reconstitutes the
#: Nifty indices twice a year (end of March and end of September) plus ad-hoc
#: changes for mergers and demergers. 90 days therefore spans one scheduled
#: reshuffle, which is the point at which it is worth re-running the script.
STALE_AFTER_DAYS = 90


@dataclass
class InstrumentSet:
    """Loaded ids plus enough provenance to judge whether to trust them."""

    #: segment -> symbol -> {"security_id": ..., "isin": ..., ...}
    instruments: Dict[str, Dict[str, dict]] = field(default_factory=dict)
    generated_at: Optional[datetime] = None
    source: str = ""
    provider: str = ""
    universes: tuple = ()
    path: str = ""
    #: Populated when the file could not be loaded. Shown verbatim rather than
    #: degrading into a live download.
    error: str = ""

    @property
    def is_usable(self) -> bool:
        return any(self.instruments.values())

    @property
    def symbol_count(self) -> int:
        return sum(len(rows) for rows in self.instruments.values())

    def security_ids(self, segment: str) -> Dict[str, str]:
        """``symbol -> security id`` for one segment. Empty if unknown."""
        rows = self.instruments.get((segment or "").upper()) or {}
        ids = {}
        for symbol, fields in rows.items():
            value = str((fields or {}).get("security_id") or "").strip()
            if value and value.lower() != "nan":
                ids[symbol] = value
        return ids

    @property
    def age_days(self) -> Optional[float]:
        if self.generated_at is None:
            return None
        generated = self.generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - generated).total_seconds() / 86400.0

    @property
    def is_stale(self) -> bool:
        age = self.age_days
        return age is not None and age > STALE_AFTER_DAYS

    def describe(self) -> str:
        """One line stating where the ids came from and when."""
        if not self.is_usable:
            return self.error or "No instrument ids loaded"
        when = (
            self.generated_at.astimezone().strftime("%d %b %Y")
            if self.generated_at
            else "unknown date"
        )
        return f"{self.symbol_count} instrument ids - {self.provider or '?'}, generated {when}"


def regenerate_hint(path: str) -> str:
    """The one instruction that fixes every problem this module reports."""
    return (
        f"Run 'python scripts/fetch_instrument_master.py' to regenerate {path} "
        "(downloads the broker's instrument master once; not needed at runtime)."
    )


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("Instruments file has an unparseable generated_at: %r", value)
        return None


def load_instruments(path: Optional[str] = None) -> InstrumentSet:
    """Read the instruments file. Never raises - callers check ``is_usable``.

    A malformed segment or row is dropped with a log line rather than failing
    the whole file, so one bad entry costs one symbol.
    """
    path = path or os.getenv("PULSE_INSTRUMENTS_FILE") or DEFAULT_INSTRUMENTS_PATH

    if not os.path.exists(path):
        return InstrumentSet(
            path=path,
            error=f"No instruments file at {path}. {regenerate_hint(path)}",
        )

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return InstrumentSet(path=path, error=f"Could not read {path}: {exc}")

    if not isinstance(payload, dict):
        return InstrumentSet(path=path, error=f"{path} is not a JSON object")

    raw = payload.get("instruments")
    if not isinstance(raw, dict):
        return InstrumentSet(path=path, error=f"{path} has no 'instruments' object")

    instruments: Dict[str, Dict[str, dict]] = {}
    for segment, rows in raw.items():
        if not isinstance(rows, dict):
            logger.warning("Ignoring non-object segment %r in %s", segment, path)
            continue
        cleaned = {
            symbol: fields
            for symbol, fields in rows.items()
            if isinstance(fields, dict) and fields.get("security_id")
        }
        dropped = len(rows) - len(cleaned)
        if dropped:
            logger.warning(
                "Ignored %d entry/entries with no security_id in %s (%s)",
                dropped,
                path,
                segment,
            )
        instruments[str(segment).upper()] = cleaned

    if not any(instruments.values()):
        return InstrumentSet(
            path=path, error=f"{path} contained no usable instrument ids"
        )

    loaded = InstrumentSet(
        instruments=instruments,
        generated_at=_parse_timestamp(payload.get("generated_at")),
        source=str(payload.get("source", "")),
        provider=str(payload.get("provider", "")),
        universes=tuple(payload.get("universes") or ()),
        path=path,
    )
    if loaded.is_stale:
        logger.warning(
            "%s was generated %.0f days ago - NSE reconstitutes the Nifty "
            "indices twice a year, so it is worth regenerating. %s",
            path,
            loaded.age_days or 0,
            regenerate_hint(path),
        )
    return loaded
