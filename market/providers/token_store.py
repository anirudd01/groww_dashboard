"""Shared plumbing for brokers whose tokens are minted here and saved to a file.

Dhan (``dhan_session``) and INDmoney (``indmoney_session``) both generate
access tokens from TOTP and share them between processes through a
git-ignored JSON file at the repository root. The file handling is identical,
so it lives here once:

  - ``write_json_atomic`` - never leaves a half-written token file behind
  - ``read_json``         - the file's contents, or None; never raises
  - ``FileLock``          - cross-process lock so two processes starting
                            together mint one token between them
  - ``jwt_claims``        - a token's JWT payload, decoded but not verified
  - ``env_first``         - the first non-empty value among env var spellings

What differs per broker (endpoints, expiry rules, whether a new token revokes
the old one) stays in that broker's own session module.
"""

import base64
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

#: The repository root, where session files live.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: A lock file older than this is treated as abandoned by a crashed process.
LOCK_STALE_SECONDS = 120


def env_first(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def repo_file(env_name: str, default_name: str) -> str:
    """``$env_name`` if set, else ``default_name`` at the repository root."""
    return os.getenv(env_name) or os.path.join(REPO_ROOT, default_name)


def jwt_claims(token: str) -> dict:
    """The JWT payload of ``token``, decoded but not verified. {} if unreadable."""
    try:
        payload = (token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def write_json_atomic(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_json(path: str, label: str = "session") -> Optional[dict]:
    """The file's JSON object, or None if missing or unreadable. Never raises."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the %s file %s: %s", label, path, exc)
        return None


class FileLock:
    """Cross-process lock: an exclusively created ``<path>.lock``, cleared if abandoned."""

    def __init__(self, path: str, timeout: float = 90.0, error=RuntimeError,
                 stale_after: float = LOCK_STALE_SECONDS):
        self.path = f"{path}.lock"
        self.timeout = timeout
        self.error = error
        self.stale_after = stale_after

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale_after:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise self.error(f"Timed out waiting for {self.path} - delete it if no other process is running")
                time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
