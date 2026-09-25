"""Zerodha Kite Connect login and the saved daily session.

Kite is the only broker here whose token cannot simply be pasted into
``.env``: it comes out of a browser login, and it dies at **06:00 IST the next
morning** (a regulatory requirement), so it has to be regenerated every
trading day. The flow (https://kite.trade/docs/connect/v3/user/):

1. Open ``login_url(api_key)`` and log in on Zerodha's own page. Zerodha never
   shares the password with us, and this code never asks for it.
2. Zerodha redirects to the redirect URL registered for the app, with a
   short-lived ``request_token`` in the query string.
3. ``exchange_request_token`` POSTs that token plus
   ``checksum = sha256(api_key + request_token + api_secret)`` to
   ``/session/token`` and gets the ``access_token`` back.

``scripts/kite_login.py`` drives those steps and saves the result with
``save_session``. The provider then reads it with ``load_session``, which
refuses a session that belongs to another API key or has passed 06:00.

The session file (``.kite_session.json`` at the repository root) holds a live
access token, so it is git-ignored. The API secret is never written anywhere;
it is used once, to compute the checksum.

Credentials, all from ``.env``:
  ``KITE_API_KEY``    (``KITE_APIKEY`` also accepted) - the app's public key
  ``KITE_API_SECRET`` - needed only by the login script
  ``KITE_ACCESS_TOKEN`` - optional; overrides the session file when set

This module places no orders and calls no order endpoint.
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from market.market_hours import IST, now_ist

logger = logging.getLogger(__name__)

API_ROOT = "https://api.kite.trade"
LOGIN_ROOT = "https://kite.zerodha.com/connect/login"
DEVELOPER_CONSOLE = "https://developers.kite.trade/apps"
KITE_VERSION = "3"

API_KEY_ENVS = ("KITE_API_KEY", "KITE_APIKEY")
API_SECRET_ENV = "KITE_API_SECRET"
ACCESS_TOKEN_ENV = "KITE_ACCESS_TOKEN"
SESSION_FILE_ENV = "PULSE_KITE_SESSION_FILE"

#: Relative to the repository root. Git-ignored - it holds a live token.
DEFAULT_SESSION_PATH = ".kite_session.json"
LOGIN_SCRIPT = "scripts/kite_login.py"

#: Kite access tokens expire at this IST wall-clock time.
TOKEN_EXPIRY_TIME = dtime(6, 0)


def _clean(value: Optional[str]) -> str:
    value = (value or "").strip()
    # Placeholders copied from .env.example are "not configured", not a key.
    return "" if value.lower().startswith(("your_", "<")) else value


def api_key_from_env() -> str:
    for name in API_KEY_ENVS:
        value = _clean(os.getenv(name))
        if value:
            return value
    return ""


def api_secret_from_env() -> str:
    return _clean(os.getenv(API_SECRET_ENV))


def session_path() -> str:
    return os.getenv(SESSION_FILE_ENV) or DEFAULT_SESSION_PATH


def login_url(api_key: str) -> str:
    """The Zerodha-hosted login page for this app."""
    return f"{LOGIN_ROOT}?{urlencode({'v': KITE_VERSION, 'api_key': api_key})}"


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    """``sha256(api_key + request_token + api_secret)``, hex - Kite's token-exchange proof."""
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode("utf-8")).hexdigest()


def extract_request_token(text: str) -> str:
    """The ``request_token`` from a pasted redirect URL, or the text itself.

    Accepts the whole address-bar URL Zerodha redirected to (the easy thing to
    copy) or just the token. Raises ValueError when the URL reports a failed
    login or carries no token.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing was pasted")
    if "://" not in text and "request_token=" not in text:
        return text

    query = parse_qs(urlparse(text).query) if "://" in text else parse_qs(text.split("?", 1)[-1])
    status = (query.get("status") or [""])[0]
    if status and status.lower() != "success":
        raise ValueError(f"Zerodha reported the login as {status!r}")
    token = (query.get("request_token") or [""])[0].strip()
    if not token:
        raise ValueError("That URL has no request_token in it")
    return token


def expiry_after(login_at: datetime) -> datetime:
    """The first 06:00 IST strictly after ``login_at`` - when the token dies.

    A login at 03:00 is therefore treated as expiring at 06:00 the same
    morning. Kite's docs say "6 AM on the next day" without covering that
    case, and the earlier reading is the one that cannot overstate validity.
    """
    if login_at.tzinfo is None:
        login_at = login_at.replace(tzinfo=IST)
    local = login_at.astimezone(IST)
    expiry = datetime.combine(local.date(), TOKEN_EXPIRY_TIME, IST)
    if expiry <= local:
        expiry += timedelta(days=1)
    return expiry


class KiteAuthError(RuntimeError):
    """Kite rejected a login or a token."""


def error_of(status_code: int, payload) -> Optional[str]:
    """Human-readable reason for a failed Kite response, or None if it succeeded.

    Kite's error body is ``{"status": "error", "error_type": ..., "message": ...}``.
    """
    body = payload if isinstance(payload, dict) else {}
    if status_code < 400 and str(body.get("status", "success")).lower() != "error":
        return None
    parts = [str(body[key]) for key in ("error_type", "message") if body.get(key)]
    return f"HTTP {status_code}: " + (" - ".join(parts) if parts else "no error detail")


@dataclass
class KiteSession:
    """What the login script saves. Never includes the API secret."""

    api_key: str
    access_token: str
    user_id: str = ""
    login_at: str = ""  # ISO, IST
    expires_at: str = ""  # ISO, IST

    @property
    def expires(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError):
            return None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Unknown expiry counts as expired - a token we cannot date is not trusted."""
        expires = self.expires
        return expires is None or (now or now_ist()) >= expires

    def hours_left(self, now: Optional[datetime] = None) -> float:
        expires = self.expires
        if expires is None:
            return 0.0
        return max(0.0, (expires - (now or now_ist())).total_seconds() / 3600)


def exchange_request_token(
    api_key: str, api_secret: str, request_token: str, timeout: int = 15
) -> KiteSession:
    """Swap a one-time ``request_token`` for the day's access token."""
    if not (api_key and api_secret and request_token):
        raise KiteAuthError("api_key, api_secret and request_token are all required")
    response = requests.post(
        f"{API_ROOT}/session/token",
        headers={"X-Kite-Version": KITE_VERSION},
        data={
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum(api_key, request_token, api_secret),
        },
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = error_of(response.status_code, body)
    if error:
        raise KiteAuthError(
            f"Kite token exchange failed ({error}). A request_token lasts only a "
            "few minutes and works once - log in again for a fresh one."
        )
    data = body.get("data") or {}
    access_token = str(data.get("access_token") or "")
    if not access_token:
        raise KiteAuthError("Kite token exchange returned no access_token")
    login_at = now_ist()
    return KiteSession(
        api_key=api_key,
        access_token=access_token,
        user_id=str(data.get("user_id") or ""),
        login_at=login_at.isoformat(),
        expires_at=expiry_after(login_at).isoformat(),
    )


def save_session(session: KiteSession, path: Optional[str] = None) -> str:
    path = path or session_path()
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
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


def load_session(
    api_key: str, path: Optional[str] = None, now: Optional[datetime] = None
) -> Optional[KiteSession]:
    """The saved session if it is for ``api_key`` and still valid, else None.

    Never raises and does no network I/O, so ``is_configured`` can call it.
    Why a session was rejected is logged, because "Kite is not configured"
    alone would send someone looking at the wrong thing.
    """
    path = path or session_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        session = KiteSession(
            api_key=str(raw.get("api_key") or ""),
            access_token=str(raw.get("access_token") or ""),
            user_id=str(raw.get("user_id") or ""),
            login_at=str(raw.get("login_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
        )
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Could not read the Kite session file %s: %s", path, exc)
        return None

    if not session.access_token:
        return None
    if api_key and session.api_key != api_key:
        logger.warning(
            "Kite session in %s belongs to a different API key - run 'python %s'",
            path, LOGIN_SCRIPT,
        )
        return None
    if session.is_expired(now):
        logger.info(
            "Kite session in %s expired at %s - run 'python %s' to log in for today",
            path, session.expires_at or "an unknown time", LOGIN_SCRIPT,
        )
        return None
    return session


def invalidate_session(api_key: str, access_token: str, timeout: int = 15) -> Optional[str]:
    """Log the API session out on Kite's side. Returns an error string or None."""
    response = requests.delete(
        f"{API_ROOT}/session/token",
        headers={"X-Kite-Version": KITE_VERSION},
        params={"api_key": api_key, "access_token": access_token},
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return error_of(response.status_code, body)
