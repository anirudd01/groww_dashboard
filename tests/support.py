"""Shared test isolation for brokers whose tokens are minted from TOTP.

A test that reached a real token endpoint would mint a token - and for
INDmoney that revokes the live one every dashboard is using. So every test
module that builds a Dhan or INDmoney provider starts with ``isolate()``:
the real credentials are removed from the environment and the state database
(``PULSE_STATE_DB``: sessions and the clock offset) points into a temp directory.
"""

import os
import tempfile
from unittest import mock

#: The repository root, and the real database in it. Tests never write there: ``tests/__init__.py``
#: points the state database at a temp file. Checks of what the repo actually ships open this
#: one read-only, and skip when it has not been generated on this machine.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(ROOT, "data", "market.db")

#: Env var prefixes that carry broker credentials minted into tokens here.
CREDENTIAL_PREFIXES = ("DHAN_", "IND_MONEY_")


class isolate:
    """Start in ``setUpModule`` (or ``setUp``), ``stop()`` in the matching teardown."""

    def __init__(self, extra: dict = None):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if not k.startswith(CREDENTIAL_PREFIXES)}
        env["PULSE_STATE_DB"] = self.path("state.db")
        env.update(extra or {})
        self._patch = mock.patch.dict(os.environ, env, clear=True)
        self._patch.start()

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def stop(self) -> None:
        self._patch.stop()
        self.tmp.cleanup()


def real_closes_missing() -> bool:
    """True when this machine has no stored F&O closes (the real database, opened read-only)."""
    from market.fno_movers import closes_available

    return not closes_available(REAL_DB)


class seeded_fno:
    """Give the F&O pages data to run on: the stored closes, and a universe built from their symbols.

    The page tests run the real dashboards against the real stored history, but tests never write to
    the real database, and the suite's own database starts empty. So this copies the closes out of the
    real one (read-only) into a throwaway one, and lists their symbols as the F&O universe:
    ``start()`` in ``setUpClass`` and ``stop()`` in ``tearDownClass``. Pair it with
    ``@unittest.skipIf(real_closes_missing(), ...)``.
    """

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.dict(os.environ, {"PULSE_STATE_DB": os.path.join(self.tmp.name, "state.db")})

    def start(self):
        from market.fno_movers import load_closes, save_closes, save_universe

        rows = load_closes(REAL_DB)  # read before the environment is redirected
        self._patch.start()
        save_closes(rows)
        save_universe({symbol: "1" for symbol in sorted({symbol for _, symbol in rows})}, [])
        return self

    def stop(self):
        self._patch.stop()
        self.tmp.cleanup()
