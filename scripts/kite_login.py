"""Log in to Zerodha Kite Connect for today and save the session.

Kite access tokens die at 06:00 IST every morning, so run this once per
trading day before starting the dashboard with the Kite provider:

    python scripts/kite_login.py                 # opens the login page, then asks for the redirect URL
    python scripts/kite_login.py --no-browser    # just print the login URL
    python scripts/kite_login.py --request-token XYZ   # skip the prompt
    python scripts/kite_login.py --status        # is today's session still valid? (checks with Kite)
    python scripts/kite_login.py --logout        # revoke the saved session on Kite's side

How it works (https://kite.trade/docs/connect/v3/user/):
1. You log in on Zerodha's own page. This script never sees your password or TOTP.
2. Zerodha redirects the browser to the redirect URL registered for your app
   on https://developers.kite.trade, with ``request_token=...`` in the address.
   That page may well fail to load - it does not matter. Copy the address.
3. Paste it here. The script exchanges it (it is valid for a few minutes, once)
   for the day's access token and saves it to ``.kite_session.json``, which
   is git-ignored. The API secret is used for the checksum and never stored.

Needs ``KITE_API_KEY`` (or ``KITE_APIKEY``) and ``KITE_API_SECRET`` in ``.env``.
Places no orders. Prints no tokens.
"""

import argparse
import os
import sys
import webbrowser

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from market.providers.kite_session import (  # noqa: E402
    API_KEY_ENVS,
    API_ROOT,
    API_SECRET_ENV,
    DEVELOPER_CONSOLE,
    KITE_VERSION,
    KiteAuthError,
    api_key_from_env,
    api_secret_from_env,
    error_of,
    exchange_request_token,
    extract_request_token,
    invalidate_session,
    load_session,
    login_url,
    save_session,
    session_path,
)


def _masked(user_id: str) -> str:
    return f"{user_id[:2]}****" if user_id else "(unknown user)"


def check_status(api_key: str) -> int:
    session = load_session(api_key)
    if session is None:
        print(f"No valid Kite session in {session_path()} - run this script without --status.")
        return 1
    print(f"Saved session for {_masked(session.user_id)}, expires {session.expires_at} "
          f"({session.hours_left():.1f} h left)")
    response = requests.get(
        f"{API_ROOT}/user/profile",
        headers={
            "X-Kite-Version": KITE_VERSION,
            "Authorization": f"token {api_key}:{session.access_token}",
        },
        timeout=15,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = error_of(response.status_code, body)
    if error:
        print(f"Kite rejected the saved token: {error}. Log in again.")
        return 1
    print("Kite accepted the token.")
    return 0


def logout(api_key: str) -> int:
    session = load_session(api_key)
    if session is None:
        print("No valid saved session to revoke.")
        return 0
    error = invalidate_session(api_key, session.access_token)
    try:
        os.remove(session_path())
    except OSError:
        pass
    if error:
        print(f"Kite did not confirm the logout ({error}); the local session file was removed anyway.")
        return 1
    print("Session revoked on Kite and removed locally.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request-token", help="Use this request_token (or redirect URL) instead of prompting")
    parser.add_argument("--no-browser", action="store_true", help="Print the login URL without opening it")
    parser.add_argument("--status", action="store_true", help="Check the saved session with Kite and exit")
    parser.add_argument("--logout", action="store_true", help="Revoke the saved session and delete it")
    args = parser.parse_args()

    # Loaded here, not at import, so importing this module (tests) reads no secrets.
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"), override=True)
    except ImportError:
        pass

    api_key = api_key_from_env()
    if not api_key:
        print(f"Set {API_KEY_ENVS[0]} (or {API_KEY_ENVS[1]}) in .env - it is on {DEVELOPER_CONSOLE}")
        return 1
    if args.status:
        return check_status(api_key)
    if args.logout:
        return logout(api_key)

    api_secret = api_secret_from_env()
    if not api_secret:
        print(f"Set {API_SECRET_ENV} in .env - it is on {DEVELOPER_CONSOLE}")
        return 1

    existing = load_session(api_key)
    if existing is not None and not args.request_token:
        print(f"Note: a session for {_masked(existing.user_id)} is already saved and valid for "
              f"{existing.hours_left():.1f} more hours. Logging in again replaces it.\n")

    raw = args.request_token
    if not raw:
        url = login_url(api_key)
        print("1. Log in to Zerodha at:\n")
        print(f"   {url}\n")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        print("2. After logging in, the browser lands on your app's redirect URL (it may")
        print("   show an error page - that is fine). Copy the whole address from the bar.\n")
        try:
            raw = input("3. Paste it here: ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1

    try:
        request_token = extract_request_token(raw)
        session = exchange_request_token(api_key, api_secret, request_token)
    except (ValueError, KiteAuthError) as exc:
        print(f"\nLogin failed: {exc}")
        return 1
    except requests.RequestException as exc:
        print(f"\nCould not reach Kite: {exc}")
        return 1

    path = save_session(session)
    print(f"\nLogged in as {_masked(session.user_id)}. Session saved to {path}")
    print(f"Valid until {session.expires_at} ({session.hours_left():.1f} h).")
    print("Start the dashboard, or verify with: python scripts/check_heatmap_universe.py --provider kite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
