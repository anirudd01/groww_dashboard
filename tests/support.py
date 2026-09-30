"""Shared test isolation for brokers whose tokens are minted from TOTP.

A test that reached a real token endpoint would mint a token - and for
INDmoney that revokes the live one every dashboard is using. So every test
module that builds a Dhan or INDmoney provider starts with ``isolate()``:
the real credentials are removed from the environment and the session files
point into a temp directory.
"""

import os
import tempfile
from unittest import mock

#: Env var prefixes that carry broker credentials minted into tokens here.
CREDENTIAL_PREFIXES = ("DHAN_", "IND_MONEY_")


class isolate:
    """Start in ``setUpModule`` (or ``setUp``), ``stop()`` in the matching teardown."""

    def __init__(self, extra: dict = None):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if not k.startswith(CREDENTIAL_PREFIXES)}
        env["PULSE_DHAN_SESSION_FILE"] = self.path("dhan_session.json")
        env["PULSE_INDMONEY_SESSION_FILE"] = self.path("indmoney_session.json")
        env.update(extra or {})
        self._patch = mock.patch.dict(os.environ, env, clear=True)
        self._patch.start()

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def stop(self) -> None:
        self._patch.stop()
        self.tmp.cleanup()
