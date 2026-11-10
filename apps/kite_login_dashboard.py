"""Kite login from the dashboard: the browser flow of scripts/kite_login.py, for a server.

Kite's access token comes out of a browser login and dies at 06:00 IST, so a server needs a way
to log in again without a terminal. This page is that way. It is not in the navbar; open it at
``/kite-login``. Register that address as the app's redirect URL on developers.kite.trade.

Flow (https://kite.trade/docs/connect/v3/user/):

1. The operator unlocks the page. In public mode (``PULSE_PUBLIC_MODE=1``) that needs
   ``PULSE_ADMIN_PASSWORD``; without that variable the page refuses to log in at all. Five wrong
   passwords lock the page for everyone for 15 minutes.
2. Unlocking mints a one-time ``state`` code (10 minutes, single use, kept in this process only)
   and links to Zerodha's login page with ``redirect_params=state=<code>``. Zerodha hands it back.
3. Zerodha redirects here with ``request_token``. The token is exchanged only if ``state`` is a
   live code from step 2, so a stranger who reaches the redirect URL with their own token gets
   nothing exchanged.
4. If ``KITE_USER_ID`` is set, a session for any other Zerodha user is refused (and logged out on
   Kite's side). The session is saved where the provider reads it (``kite_session`` in the state
   database); the API secret is used for the checksum and never stored.

Places no orders. Shows no tokens.
"""

import hmac
import logging
import os
import secrets
import threading
import time
from urllib.parse import urlencode

import streamlit as st

from market.providers import kite_session as ks
from utils.public_mode import is_public

logger = logging.getLogger(__name__)

ADMIN_PASSWORD_ENV = "PULSE_ADMIN_PASSWORD"
USER_ID_ENV = "KITE_USER_ID"
STATE_TTL_SECONDS = 600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 900

_lock = threading.Lock()
_states = {}  # one-time code -> expiry (monotonic)
_failures = []  # monotonic times of recent wrong passwords


def _mint_state() -> str:
    code = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _lock:
        for old in [c for c, exp in _states.items() if exp < now]:
            del _states[old]
        _states[code] = now + STATE_TTL_SECONDS
    return code


def _take_state(code: str) -> bool:
    """True once for a live code; the code is spent either way."""
    with _lock:
        expiry = _states.pop(code or "", None)
    return expiry is not None and expiry >= time.monotonic()


def _locked_for() -> int:
    """Seconds left on the wrong-password lockout, 0 if not locked."""
    now = time.monotonic()
    with _lock:
        _failures[:] = [t for t in _failures if now - t < LOCKOUT_SECONDS]
        if len(_failures) >= MAX_FAILURES:
            return int(LOCKOUT_SECONDS - (now - _failures[0])) + 1
    return 0


def _check_password(given: str) -> bool:
    expected = (os.getenv(ADMIN_PASSWORD_ENV) or "").strip()
    ok = bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
    if not ok:
        with _lock:
            _failures.append(time.monotonic())
        logger.warning("Kite login page: wrong admin password")
    return ok


def _masked(user_id: str) -> str:
    return user_id[:2] + "*" * max(0, len(user_id) - 2) if user_id else "unknown user"


def _status(api_key: str) -> None:
    session = ks.load_session(api_key)
    if session:
        st.success(f"Kite session active for {_masked(session.user_id)}, "
                   f"{session.hours_left():.1f} h left (until 06:00 IST).", icon=":material/check_circle:")
    else:
        st.info("No valid Kite session. Kite tokens die at 06:00 IST every day.", icon=":material/key_off:")


def _handle_redirect(api_key: str, api_secret: str) -> None:
    params = st.query_params
    request_token = params.get("request_token", "")
    state = params.get("state", "")
    status = params.get("status", "")
    st.query_params.clear()  # the token works once; don't leave it in the address bar

    if status and status.lower() != "success":
        st.error(f"Zerodha reported the login as {status!r}.")
        return
    if not _take_state(state):
        logger.warning("Kite login page: redirect with a missing, spent or expired state code")
        st.error("This login link is not valid or has expired. Unlock the page and start again.")
        return
    try:
        session = ks.exchange_request_token(api_key, api_secret, request_token)
    except ks.KiteAuthError as exc:
        st.error(str(exc))
        return

    expected_user = (os.getenv(USER_ID_ENV) or "").strip().upper()
    if expected_user and session.user_id.upper() != expected_user:
        ks.invalidate_session(api_key, session.access_token)
        logger.warning("Kite login page: refused a session for another Zerodha user")
        st.error("That Zerodha account is not the one this server is set up for. Nothing was saved.")
        return

    ks.save_session(session)
    logger.info("Kite login page: saved a session for %s", _masked(session.user_id))
    st.success(f"Logged in to Kite as {_masked(session.user_id)}. Kite pages can use it now.",
               icon=":material/check_circle:")


def _hand_to_local_script() -> None:
    """A login started by scripts/kite_login.py on a laptop: show the address to paste there.

    Nothing is exchanged or saved here, and no password is needed: the request token is already
    in this visitor's own address bar, and it is useless without the API secret.
    """
    params = st.query_params
    status = params.get("status", "")
    if status and status.lower() != "success":
        st.error(f"Zerodha reported the login as {status!r}.")
        return
    query = urlencode({"request_token": params.get("request_token", ""), "status": status or "success"})
    st.info("This login was started by scripts/kite_login.py. Copy the line below and paste it into "
            "the script. This server keeps nothing.", icon=":material/content_copy:")
    st.code(f"https://kite-login/?{query}", language=None)


def main() -> None:
    st.title("Kite login")
    api_key, api_secret = ks.api_key_from_env(), ks.api_secret_from_env()
    if not (api_key and api_secret):
        st.warning("Kite is not set up on this server (KITE_API_KEY and KITE_API_SECRET).")
        return
    if is_public() and not (os.getenv(ADMIN_PASSWORD_ENV) or "").strip():
        st.warning(f"Logging in from this page is disabled: {ADMIN_PASSWORD_ENV} is not set.")
        return

    if "request_token" in st.query_params and st.query_params.get("dest") == "local":
        _hand_to_local_script()
        return
    if "request_token" in st.query_params:
        _handle_redirect(api_key, api_secret)
    _status(api_key)

    if is_public() and not st.session_state.get("kite_admin_ok"):
        wait = _locked_for()
        if wait:
            st.error(f"Too many wrong passwords. Try again in {wait // 60 + 1} min.")
            return
        with st.form("kite_admin"):
            given = st.text_input("Admin password", type="password")
            if st.form_submit_button("Unlock"):
                if _check_password(given):
                    st.session_state["kite_admin_ok"] = True
                    st.rerun()
                st.error("Wrong password.")
        return

    target = f"{ks.login_url(api_key)}&{urlencode({'redirect_params': urlencode({'state': _mint_state()})})}"
    st.link_button("Log in to Kite (Zerodha)", target, type="primary", icon=":material/login:")
    st.caption("You log in on Zerodha's own page; this app never sees your password or TOTP. "
               "Zerodha sends you back here and the day's token is saved for every page. "
               "The link works once, for 10 minutes.")


def page_kite_login() -> None:
    main()
