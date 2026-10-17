"""Tests for the pulse_tester dashboards."""

import atexit
import os
import shutil
import tempfile

# Tokens and the clock offset live in the shared SQLite database (market/state_store.py). A test
# that touched it without isolating it would overwrite the real saved sessions with test tokens,
# so the whole suite points at a throwaway database before any test module is imported.
_STATE_DIR = tempfile.mkdtemp(prefix="pulse-tests-")
os.environ["PULSE_STATE_DB"] = os.path.join(_STATE_DIR, "state.db")
atexit.register(shutil.rmtree, _STATE_DIR, ignore_errors=True)

# The universes (Nifty 50, Nifty Next 50) are read from the database, so the suite's own database
# starts with a fixed copy of NSE's lists.
from tests.support import seed_constituents  # noqa: E402

seed_constituents()
