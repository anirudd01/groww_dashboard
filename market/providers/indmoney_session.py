"""INDmoney access tokens, generated from TOTP and shared through a session file.

The pasted ``IND_MONEY_ACCESS_TOKEN`` died at 07:00 IST every morning, and
nothing in the repo could make a new one. This module mints them itself
(docs/indstocks-api-docs.md, "Method 2: TOTP-based token generation")::

    POST https://api.indstocks.com/generate/token
    x-api-key: <IND_MONEY_CLIENT_ID>          body: {"mpin": .., "totp": ..}

and keeps the result in ``.indmoney_session.json`` at the repository root
(git-ignored - it holds a live token). Every process - dashboards, scripts -
calls ``get_access_token()``, which returns the saved token while it has more
than ``REFRESH_MARGIN`` left and only then generates a new one, under a file
lock (``token_store.FileLock``), exactly as ``dhan_session`` does for Dhan.

Credentials, all from ``.env``; none is ever logged:
  ``IND_MONEY_CLIENT_ID``   - the Client ID shown after TOTP setup; sent as ``x-api-key``
  ``IND_MONEY_MPIN``        - the account MPIN
  ``IND_MONEY_TOTP_SECRET`` - base32 secret from Setup TOTP

INDmoney is stricter than Dhan, and this module is written around it:
  - **A new token revokes the previous one.** So a token is generated only
    when none is saved, the saved one is about to expire, or the server has
    rejected it - never "to be safe". A process that sees its token rejected
    first checks whether another process already saved a replacement.
  - **One generation per 60 s.** A second request inside that gap waits it out.
  - **5 wrong codes in 15 min lock generation out for 15 min.** Codes come
    from the NTP-corrected clock (``market.clock_offset.totp_code``) and a
    rejected code is retried at most once, in the next window.
  - Tokens last until **07:00 IST the next day** (verified 2026-09-25). The
    expiry is read from the token's JWT ``exp``, then the response's
    ``expires_in`` (an absolute epoch), and only then assumed to be 07:00.

This module places no orders and calls no order endpoint.
"""

import hashlib
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Optional

import requests

from market import clock_offset
from market.market_hours import IST, now_ist
from market.providers import token_store

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.indstocks.com/generate/token"
TOKEN_PAGE = "https://www.indstocks.com/app/api-trading/access-tokens"

CLIENT_ID_ENV = "IND_MONEY_CLIENT_ID"
MPIN_ENVS = ("IND_MONEY_MPIN", "IND_MONEY_PIN")
TOTP_SECRET_ENVS = ("IND_MONEY_TOTP_SECRET", "IND_MONEY_TOPT_SECRET")
SESSION_FILE_ENV = "PULSE_INDMONEY_SESSION_FILE"

#: Relative to the repository root. Git-ignored - it holds a live token.
DEFAULT_SESSION_PATH = ".indmoney_session.json"

#: Replace a token with less than this left. Short, because replacing one
#: revokes it for every other process too.
REFRESH_MARGIN = timedelta(minutes=10)
#: INDmoney accepts one generation per this many seconds.
MIN_GENERATION_GAP = 60
MIN_SECONDS_LEFT = 3
#: When the token and the response both leave the expiry out.
DEFAULT_EXPIRY_TIME = dtime(7, 0)

_THREAD_LOCK = threading.Lock()


class IndMoneyAuthError(RuntimeError):
    """Token generation failed; the message says what to fix."""


def _placeholder(value: str) -> bool:
    return value.lower().startswith(("your_", "<", "xxx"))


def client_id_from_env() -> str:
    value = token_store.env_first(CLIENT_ID_ENV)
    return "" if _placeholder(value) else value


def fingerprint(client_id: str) -> str:
    """Identifies the account in the session file without storing the API key."""
    return hashlib.sha256(client_id.encode()).hexdigest()[:12] if client_id else ""


def has_totp_credentials() -> bool:
    """Whether .env holds everything needed to mint a token. No network I/O."""
    return bool(client_id_from_env() and token_store.env_first(*MPIN_ENVS)
                and token_store.env_first(*TOTP_SECRET_ENVS))


def session_path() -> str:
    return token_store.repo_file(SESSION_FILE_ENV, DEFAULT_SESSION_PATH)


def _next_expiry(generated: datetime) -> datetime:
    expiry = datetime.combine(generated.date(), DEFAULT_EXPIRY_TIME, IST)
    return expiry if expiry > generated else expiry + timedelta(days=1)


def _epoch(value) -> Optional[int]:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number // 1000 if number > 10 ** 11 else number  # milliseconds -> seconds


@dataclass
class IndMoneySession:
    client: str  # fingerprint of IND_MONEY_CLIENT_ID, not the key itself
    access_token: str
    generated_at: str = ""  # ISO, IST
    expires_at: str = ""  # ISO, IST

    @staticmethod
    def _parse(value: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @property
    def expires(self) -> Optional[datetime]:
        return self._parse(self.expires_at)

    @property
    def generated(self) -> Optional[datetime]:
        return self._parse(self.generated_at)

    def usable(self, now: Optional[datetime] = None, margin: timedelta = REFRESH_MARGIN) -> bool:
        """Unknown expiry counts as unusable - a token we cannot date is not trusted."""
        expires = self.expires
        return bool(self.access_token) and expires is not None and (now or now_ist()) + margin < expires

    def hours_left(self, now: Optional[datetime] = None) -> float:
        expires = self.expires
        if expires is None:
            return 0.0
        return max(0.0, (expires - (now or now_ist())).total_seconds() / 3600)


def session_from_token(access_token: str, client_id: str = "", expires_in=None) -> IndMoneySession:
    """Wrap a token, dating it from its JWT ``exp``, else ``expires_in``, else 07:00."""
    generated = now_ist()
    expiry = _epoch(token_store.jwt_claims(access_token).get("exp")) or _epoch(expires_in)
    expires = datetime.fromtimestamp(expiry, IST) if expiry else _next_expiry(generated)
    return IndMoneySession(
        client=fingerprint(client_id or client_id_from_env()),
        access_token=access_token,
        generated_at=generated.isoformat(),
        expires_at=expires.isoformat(),
    )


def save_session(session: IndMoneySession, path: Optional[str] = None) -> str:
    return token_store.write_json_atomic(path or session_path(), asdict(session))


def load_session(path: Optional[str] = None) -> Optional[IndMoneySession]:
    """The saved session, whatever its age, or None. Never raises, no network I/O."""
    raw = token_store.read_json(path or session_path(), "INDmoney session")
    if raw is None:
        return None
    return IndMoneySession(
        client=str(raw.get("client") or ""),
        access_token=str(raw.get("access_token") or ""),
        generated_at=str(raw.get("generated_at") or ""),
        expires_at=str(raw.get("expires_at") or ""),
    )


def _for_this_account(session: Optional[IndMoneySession], client_id: str) -> bool:
    return session is not None and (not client_id or not session.client or session.client == fingerprint(client_id))


def saved_token(path: Optional[str] = None) -> str:
    """A saved token that is still usable for this account, else "". No network I/O."""
    session = load_session(path)
    if not _for_this_account(session, client_id_from_env()) or not session.usable():
        return ""
    return session.access_token


# -- generation ----------------------------------------------------------------


def _message(body) -> str:
    if not isinstance(body, dict):
        return ""
    parts = [str(body[key]) for key in ("error_type", "message", "debug_info", "error") if body.get(key)]
    return " - ".join(parts)


def _token_of(body) -> tuple:
    """(token, expires_in) from a success body; the docs name the field ``token``."""
    if not isinstance(body, dict):
        return "", None
    for block in (body, body.get("data")):
        if isinstance(block, dict):
            token = block.get("token") or block.get("access_token")
            if token:
                return str(token), block.get("expires_in")
    return "", None


def generate_session(timeout: int = 20, sleep=time.sleep, last_generated: Optional[datetime] = None) -> IndMoneySession:
    """Mint a fresh token from TOTP. This revokes the previous one. Raises IndMoneyAuthError."""
    client_id = client_id_from_env()
    mpin = token_store.env_first(*MPIN_ENVS)
    secret = token_store.env_first(*TOTP_SECRET_ENVS)
    if not (client_id and mpin and secret):
        raise IndMoneyAuthError(
            f"INDmoney TOTP login needs {CLIENT_ID_ENV}, {MPIN_ENVS[0]} and {TOTP_SECRET_ENVS[0]} in .env "
            f"(set up TOTP at {TOKEN_PAGE})"
        )
    if last_generated is not None:
        wait = MIN_GENERATION_GAP - (now_ist() - last_generated).total_seconds()
        if wait > 0:
            logger.info("INDmoney allows one token per %d s - waiting %.0f s", MIN_GENERATION_GAP, wait)
            sleep(wait + 1)

    headers = {"x-api-key": client_id, "Content-Type": "application/json", "Accept": "application/json"}
    message, status = "", 0
    for attempt in range(2):
        if attempt:
            # Only after a rejected code: re-measure the clock and use the next
            # window. Wrong codes count toward a 15-minute lockout, so never more.
            now = time.time() + clock_offset.offset(refresh=True)
            sleep(30 - (now % 30) + 1)
        code = clock_offset.totp_code(secret, MIN_SECONDS_LEFT, sleep=sleep)
        response = requests.post(AUTH_URL, headers=headers, json={"mpin": mpin, "totp": code}, timeout=timeout)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        token, expires_in = _token_of(body)
        if response.ok and token:
            session = session_from_token(token, client_id, expires_in)
            logger.info("Generated a new INDmoney access token (valid to %s)", session.expires_at)
            return session
        message = _message(body) or (response.text or "")[:120]
        lowered = message.lower()
        if "totp" not in lowered or "lock" in lowered:
            break  # wrong MPIN, throttle or lockout: the next window will not help
        logger.info("INDmoney rejected the TOTP code (%s) - retrying once in the next window", message)
    raise IndMoneyAuthError(
        f"INDmoney token generation failed (HTTP {status}: {message or 'no message'}). "
        f"Check {CLIENT_ID_ENV}, {MPIN_ENVS[0]} and {TOTP_SECRET_ENVS[0]} in .env. "
        "Five wrong codes lock generation out for 15 minutes - do not retry in a loop."
    )


def get_access_token(force_new: bool = False, rejected: str = "", path: Optional[str] = None) -> str:
    """A usable INDmoney token: the saved one, or a newly generated one.

    ``force_new`` asks for a new token because the server rejected
    ``rejected``. If another process has already replaced that token, its
    replacement is returned instead - generating again would revoke it.
    """
    path = path or session_path()
    client_id = client_id_from_env()
    with _THREAD_LOCK:
        if not force_new:
            token = saved_token(path)
            if token:
                return token
        with token_store.FileLock(path, error=IndMoneyAuthError):
            session = load_session(path)
            if _for_this_account(session, client_id) and session.usable():
                if not force_new or (rejected and session.access_token != rejected):
                    return session.access_token
            last = session.generated if _for_this_account(session, client_id) else None
            session = generate_session(last_generated=last)
            save_session(session, path)
            return session.access_token
