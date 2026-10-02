"""Shared plumbing for brokers whose tokens are minted here.

Dhan (``dhan_session``) and INDmoney (``indmoney_session``) both generate access tokens from TOTP
and share them between processes. Where the token is kept, and the lock that stops two processes
minting at once, are in ``market/state_store.py`` (a table of the shared SQLite database). This holds
the small helpers the two have in common:

  - ``jwt_claims`` - a token's JWT payload, decoded but not verified
  - ``env_first``  - the first non-empty value among env var spellings

What differs per broker (endpoints, expiry rules, whether a new token revokes the old one) stays in
that broker's own session module.
"""

import base64
import json
import os

#: The repository root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: A lock held longer than this is treated as abandoned by a crashed process.
LOCK_STALE_SECONDS = 120


def env_first(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def jwt_claims(token: str) -> dict:
    """The JWT payload of ``token``, decoded but not verified. {} if unreadable."""
    try:
        payload = (token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}
