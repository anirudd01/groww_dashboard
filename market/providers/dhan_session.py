"""Dhan access tokens, generated from TOTP and shared through a session file.

Dhan access tokens last 24 hours. Rather than pasting one into ``.env`` every
day, this module mints them itself from the account's TOTP secret
(verified 2026-09-27)::

    POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=..&pin=..&totp=..

and keeps the result in ``.dhan_session.json`` at the repository root
(git-ignored - it holds a live token). Every process - dashboards, scripts -
calls ``get_access_token()``, which returns the saved token while it has more
than ``REFRESH_MARGIN`` left and only then generates a new one, under a file
lock so two processes starting together make one token between them.

Credentials, all from ``.env``; none is ever logged:
  ``DHAN_CLIENT_ID``   - the 10-digit client id (also inside every token)
  ``DHAN_PIN``         - the 6-digit Dhan PIN (``DHAN_MPIN`` also accepted)
  ``DHAN_TOTP_SECRET`` - base32 secret from Setup TOTP (``DHAN_TOPT_SECRET`` also accepted)

Behaviour seen against the live API on 2026-09-27, and handled here:
  - A rejected code comes back as HTTP **200** with
    ``{"status": "error", "message": "Invalid TOTP"}`` - read the body.
  - A code taken with 5 s left in its window was rejected once, when the
    clock correction came from an HTTP ``Date`` header (1 s resolution). One
    rejection is retried in the next window with a freshly measured offset.
  - Generating a token did **not** revoke the previous one (unlike INDmoney).
  - This PC's clock runs ~21 s slow, so codes come from
    ``market.clock_offset.totp_code`` (NTP-corrected), never the raw clock.

This module places no orders and calls no order endpoint.
"""

import base64
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

from market import clock_offset
from market.market_hours import IST, now_ist

logger = logging.getLogger(__name__)

AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"

CLIENT_ID_ENV = "DHAN_CLIENT_ID"
PIN_ENVS = ("DHAN_PIN", "DHAN_MPIN")
TOTP_SECRET_ENVS = ("DHAN_TOTP_SECRET", "DHAN_TOPT_SECRET")
SESSION_FILE_ENV = "PULSE_DHAN_SESSION_FILE"

#: Relative to the repository root. Git-ignored - it holds a live token.
DEFAULT_SESSION_PATH = ".dhan_session.json"

#: A token with less than this left is replaced rather than handed out, so a
#: board started late in the token's life does not die mid-session.
REFRESH_MARGIN = timedelta(hours=1)
#: Take a TOTP code only with at least this many seconds left in its window
#: (so it cannot expire in transit). With an NTP-corrected clock this wait is
#: at most 3 s, and usually nothing.
MIN_SECONDS_LEFT = 3
#: A lock file older than this is treated as abandoned by a crashed process.
LOCK_STALE_SECONDS = 120

_THREAD_LOCK = threading.Lock()


class DhanAuthError(RuntimeError):
    """Token generation failed; the message says what to fix."""


def _env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def client_id_from_env() -> str:
    value = _env(CLIENT_ID_ENV)
    return value if value.isdigit() else ""


def has_totp_credentials() -> bool:
    """Whether .env holds everything needed to mint a token. No network I/O."""
    return bool(client_id_from_env() and _env(*PIN_ENVS) and _env(*TOTP_SECRET_ENVS))


def session_path() -> str:
    configured = os.getenv(SESSION_FILE_ENV)
    if configured:
        return configured
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, DEFAULT_SESSION_PATH)


def token_claims(access_token: str) -> dict:
    """The JWT payload of a Dhan token, decoded but not verified. {} if unreadable."""
    try:
        payload = (access_token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


@dataclass
class DhanSession:
    client_id: str
    access_token: str
    generated_at: str = ""  # ISO, IST
    expires_at: str = ""  # ISO, IST

    @property
    def expires(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError):
            return None

    def usable(self, now: Optional[datetime] = None, margin: timedelta = REFRESH_MARGIN) -> bool:
        """Unknown expiry counts as unusable - a token we cannot date is not trusted."""
        expires = self.expires
        return bool(self.access_token) and expires is not None and (now or now_ist()) + margin < expires

    def hours_left(self, now: Optional[datetime] = None) -> float:
        expires = self.expires
        if expires is None:
            return 0.0
        return max(0.0, (expires - (now or now_ist())).total_seconds() / 3600)


def session_from_token(access_token: str, client_id: str = "") -> DhanSession:
    """Wrap a token, dating it from its own ``exp`` claim."""
    claims = token_claims(access_token)
    expires_at = ""
    if claims.get("exp"):
        expires_at = datetime.fromtimestamp(int(claims["exp"]), IST).isoformat()
    return DhanSession(
        client_id=str(claims.get("dhanClientId") or client_id),
        access_token=access_token,
        generated_at=now_ist().isoformat(),
        expires_at=expires_at,
    )


def save_session(session: DhanSession, path: Optional[str] = None) -> str:
    path = path or session_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(asdict(session), handle, indent=2)
        handle.write("\n")
    os.replace(temp, path)  # never leave a half-written token file behind
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load_session(path: Optional[str] = None) -> Optional[DhanSession]:
    """The saved session, whatever its age, or None. Never raises, no network I/O."""
    path = path or session_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return DhanSession(
            client_id=str(raw.get("client_id") or ""),
            access_token=str(raw.get("access_token") or ""),
            generated_at=str(raw.get("generated_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
        )
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Could not read the Dhan session file %s: %s", path, exc)
        return None


def saved_token(client_id: str = "", path: Optional[str] = None) -> str:
    """A saved token that is still usable for ``client_id``, else "". No network I/O."""
    session = load_session(path)
    if session is None or not session.usable():
        return ""
    if client_id and session.client_id and session.client_id != client_id:
        return ""
    return session.access_token


# -- generation ----------------------------------------------------------------


class _FileLock:
    """Cross-process lock: an exclusively created file, cleared if abandoned."""

    def __init__(self, path: str, timeout: float = 90.0):
        self.path = f"{path}.lock"
        self.timeout = timeout

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE_SECONDS:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise DhanAuthError(f"Timed out waiting for {self.path} - delete it if no other process is running")
                time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def generate_session(timeout: int = 20, sleep=time.sleep) -> DhanSession:
    """Mint a fresh token from TOTP. Raises DhanAuthError with a fix-it message."""
    client_id, pin, secret = client_id_from_env(), _env(*PIN_ENVS), _env(*TOTP_SECRET_ENVS)
    if not (client_id and pin and secret):
        raise DhanAuthError(
            f"Dhan TOTP login needs {CLIENT_ID_ENV}, {PIN_ENVS[0]} and {TOTP_SECRET_ENVS[0]} in .env"
        )
    message = ""
    for attempt in range(2):
        if attempt:
            # Only after a rejection: re-measure the clock and wait for the next
            # window, because the same code would be rejected again.
            now = time.time() + clock_offset.offset(refresh=True)
            sleep(30 - (now % 30) + 1)
        code = clock_offset.totp_code(secret, MIN_SECONDS_LEFT, sleep=sleep)
        response = requests.post(
            AUTH_URL, params={"dhanClientId": client_id, "pin": pin, "totp": code}, timeout=timeout
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        token = str(body.get("accessToken") or "") if isinstance(body, dict) else ""
        if response.ok and token:
            session = session_from_token(token, client_id)
            logger.info("Generated a new Dhan access token (valid to %s)", session.expires_at or "?")
            return session
        message = (body.get("message") or body.get("errorMessage") or response.text[:120]) if isinstance(body, dict) else ""
        if "totp" not in str(message).lower():
            break  # a wrong PIN or client id will not improve in the next window
        logger.info("Dhan rejected the TOTP code (%s) - retrying in the next window", message)
    raise DhanAuthError(
        f"Dhan token generation failed (HTTP {response.status_code}: {message or 'no message'}). "
        f"Check {PIN_ENVS[0]} and {TOTP_SECRET_ENVS[0]} in .env, and that TOTP is still enabled on Dhan."
    )


def get_access_token(force_new: bool = False, rejected: str = "", path: Optional[str] = None) -> str:
    """A usable Dhan token: the saved one, or a newly generated one.

    ``force_new`` asks for a new token because the server rejected
    ``rejected``. If another process has already replaced that token, its
    replacement is returned instead of generating a second one.
    """
    path = path or session_path()
    client_id = client_id_from_env()
    with _THREAD_LOCK:
        if not force_new:
            token = saved_token(client_id, path)
            if token:
                return token
        with _FileLock(path):
            # Another process may have refreshed while we waited for the lock.
            session = load_session(path)
            if session is not None and session.usable() and (not client_id or session.client_id == client_id):
                if not force_new or (rejected and session.access_token != rejected):
                    return session.access_token
            session = generate_session()
            save_session(session, path)
            return session.access_token
