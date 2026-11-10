"""Switches for the public deployment (Railway), off by default.

Set ``PULSE_PUBLIC_MODE=1`` on a server that strangers can reach. Then:

  - The personal pages (Dhan Trade Journal, Dhan API Explorer) are not registered at all, and their
    modules are never imported (pulse_dashboard.py). The deploy bundle leaves those files out too
    (deploy/stage_public.py).
  - The broker-facing "Refresh" buttons clear the shared caches at most once per
    ``REFRESH_COOLDOWN_SECONDS`` across *all* visitors, so nobody can hammer the broker's rate
    limit or force repeated logins by clicking.
  - The sector board's data-provider picker is hidden: switching it reconnects the feed for every
    open tab, so on a shared server it stays on the provider the operator configured.

Locally nothing changes: with the variable unset every function here is a no-op that says yes.
"""

import os
import threading
import time
from typing import Dict

ENV = "PULSE_PUBLIC_MODE"

#: Minimum gap between two cache-clearing refreshes of the same kind, server-wide.
REFRESH_COOLDOWN_SECONDS = 60

_lock = threading.Lock()
_last_refresh: Dict[str, float] = {}


def is_public() -> bool:
    return (os.getenv(ENV, "") or "").strip().lower() in ("1", "true", "yes", "on")


def allow_refresh(key: str) -> bool:
    """True if a forced refresh named ``key`` may run now. Always True outside public mode.

    The clock is process-wide (shared by every browser session), so one visitor's refresh counts
    for everyone. A refused refresh shows a toast; the page keeps its cached data.
    """
    if not is_public():
        return True
    now = time.monotonic()
    with _lock:
        last = _last_refresh.get(key)
        if last is not None and now - last < REFRESH_COOLDOWN_SECONDS:
            wait = int(REFRESH_COOLDOWN_SECONDS - (now - last)) + 1
            allowed = False
        else:
            _last_refresh[key] = now
            allowed = True
    if not allowed:
        import streamlit as st

        st.toast(f"Refreshed moments ago - data is shared by all visitors. Try again in {wait} s.",
                 icon=":material/schedule:")
    return allowed
