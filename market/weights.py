"""Constituent weights for market-cap weighted sector aggregation.

Weights are **read from the local database, never fetched at runtime.** The
dashboard must not depend on a third-party fundamentals source being reachable
while the market is open, and a weight that silently changes mid-session would
make two refreshes of the same screen disagree.

They are produced offline by ``scripts/fetch_index_weights.py`` and stored in the
shared SQLite database by ``market/reference_store.py``. Run the script
manually, weekly or monthly - share
counts move slowly, so a stale-by-a-week weight is a rounding error, while a
failed network call at startup would not be.

If the weights are missing, unreadable or empty the dashboard falls back to equal
weighting and says so. It never guesses a weight.

Manual alternative
------------------
A set is a plain ``symbol -> figures`` map, so it can equally be filled in by
hand from NSE's published index factsheet if the automated source ever breaks
(``reference_store.save_document``). Only the ratios within a sector matter, so
any consistent unit works.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from market import reference_store, state_store

logger = logging.getLogger(__name__)

#: The stored set.
WEIGHTS_SET = "index_weights"

#: Which figure in the file is used as the weight. Free-float market cap is the
#: basis NSE itself uses for index weighting, so it is the default.
BASIS_FREE_FLOAT = "free_float_market_cap"
BASIS_MARKET_CAP = "market_cap"

#: Beyond this the UI warns that the weights are getting old. Not an error -
#: share counts change slowly - but worth knowing before trusting the number.
STALE_AFTER_DAYS = 45


@dataclass
class WeightSet:
    """Loaded weights plus enough provenance to judge whether to trust them."""

    weights: Dict[str, float] = field(default_factory=dict)
    generated_at: Optional[datetime] = None
    source: str = ""
    basis: str = BASIS_FREE_FLOAT
    universe: str = ""
    path: str = ""
    #: Populated when the weights could not be loaded. The UI shows this
    #: verbatim rather than silently degrading to equal weighting.
    error: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.weights)

    @property
    def age_days(self) -> Optional[float]:
        if self.generated_at is None:
            return None
        now = datetime.now(timezone.utc)
        generated = self.generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return (now - generated).total_seconds() / 86400.0

    @property
    def is_stale(self) -> bool:
        age = self.age_days
        return age is not None and age > STALE_AFTER_DAYS

    def describe(self) -> str:
        """One line for the UI stating where the weights came from and when."""
        if not self.is_usable:
            return self.error or "No weights loaded"
        when = (
            self.generated_at.astimezone().strftime("%d %b %Y")
            if self.generated_at
            else "unknown date"
        )
        return f"{len(self.weights)} weights - {self.basis}, generated {when}"


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("Weights have an unparseable generated_at: %r", value)
        return None


def load_weights(
    path: Optional[str] = None, basis: str = BASIS_FREE_FLOAT
) -> WeightSet:
    """Read the stored weights. Never raises - a bad set means equal weighting.

    A weight is only accepted if it is a positive, finite number. Anything else
    (null, zero, negative, a string) is dropped with a log line, so a partially
    broken set degrades one symbol rather than the whole board. ``path`` is a
    database file, for tests; the default is the shared one.
    """
    database = path or state_store.db_path()
    label = f"{WEIGHTS_SET} in {database}"
    payload = reference_store.load_document(WEIGHTS_SET, database)

    if payload is None:
        return WeightSet(
            path=label,
            error=(
                f"No weights stored ({label}). Run "
                "'python scripts/fetch_index_weights.py' to generate them."
            ),
        )

    raw = payload.get("weights")
    if not isinstance(raw, dict):
        return WeightSet(path=label, error=f"{label} has no 'weights' section")

    weights: Dict[str, float] = {}
    skipped = []
    for symbol, figures in raw.items():
        value = figures.get(basis) if isinstance(figures, dict) else figures
        try:
            number = float(value)
        except (TypeError, ValueError):
            skipped.append(symbol)
            continue
        if number > 0 and number == number and number != float("inf"):
            weights[symbol] = number
        else:
            skipped.append(symbol)

    if skipped:
        logger.warning(
            "Ignored %d symbol(s) with no usable %s in %s: %s",
            len(skipped),
            basis,
            label,
            ", ".join(sorted(skipped)[:10]),
        )

    if not weights:
        return WeightSet(
            path=label,
            error=f"{label} contained no usable '{basis}' values",
        )

    return WeightSet(
        weights=weights,
        generated_at=_parse_timestamp(payload.get("generated_at")),
        source=str(payload.get("source", "")),
        basis=basis,
        universe=str(payload.get("universe", "")),
        path=label,
    )
