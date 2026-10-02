"""How far this PC's clock is from real time, measured once and shared.

TOTP codes are derived from the current time, so a skewed clock produces
wrong codes. This PC ran **21.0 s slow** on 2026-09-28 (three NTP servers
agreed within 10 ms). Code that makes a TOTP code calls ``totp_code()``,
which computes it from ``time.time() + offset()`` instead of the raw clock -
so no login has to wait out a window "to be safe".

The offset is measured by SNTP (UDP 123; ~60 ms, millisecond precision) on
first use in each process and saved as the ``clock_offset`` row of the shared
SQLite database (``market/state_store.py``; per-machine, git-ignored). If no NTP server answers - a
firewall can block UDP 123 - it falls back to the HTTP ``Date`` header of a
few HTTPS sites (1 s resolution), then to the saved value while it is under a
day old, and finally to 0 with a warning.

Fixing the Windows clock itself (``w32tm /resync`` as admin) is still worth
doing; this module just stops the logins depending on it.
"""

import logging
import socket
import sqlite3
import statistics
import struct
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Callable, Optional, Tuple

from market import state_store

logger = logging.getLogger(__name__)

NTP_SERVERS = ("time.google.com", "time.cloudflare.com", "time.windows.com")
HTTP_SOURCES = ("https://www.google.com", "https://www.cloudflare.com")
#: The ``runtime_state`` row holding the last measurement.
STATE_NAME = "clock_offset"

#: Re-measure in a long-running process after this long; drift is slow.
REMEASURE_AFTER = 3600.0
#: A saved offset is trusted for this long when nothing can be measured.
SAVED_VALID_FOR = 86400.0
#: Replies slower than this are too imprecise to use.
MAX_RTT = 1.0
#: Seconds between 1900-01-01 (NTP epoch) and 1970-01-01.
NTP_EPOCH_DELTA = 2208988800

_LOCK = threading.Lock()
_cached: Optional[Tuple[float, float]] = None  # (offset, monotonic time measured)


def ntp_offset(host: str, timeout: float = 2.0) -> Tuple[float, float]:
    """(offset, round trip) from one SNTP query. Raises OSError on failure."""
    packet = b"\x1b" + 47 * b"\0"  # LI=0, version 3, mode 3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sent = time.time()
        sock.sendto(packet, (host, 123))
        data, _ = sock.recvfrom(48)
        received = time.time()
    if len(data) < 48:
        raise OSError(f"short NTP reply from {host}")

    def stamp(offset: int) -> float:
        seconds, fraction = struct.unpack("!II", data[offset:offset + 8])
        return seconds - NTP_EPOCH_DELTA + fraction / 2 ** 32

    server_rx, server_tx = stamp(32), stamp(40)
    return ((server_rx - sent) + (server_tx - received)) / 2, received - sent


def http_offset(url: str, timeout: float = 10.0) -> Tuple[float, float]:
    """(offset, round trip) from an HTTP ``Date`` header, good to about ±0.5 s."""
    import requests

    sent = time.time()
    response = requests.head(url, timeout=timeout)
    received = time.time()
    # Date is truncated to the second, so the true time is half a second later on average.
    server = parsedate_to_datetime(response.headers["Date"]).timestamp() + 0.5
    return server - (sent + received) / 2, received - sent


def measure(ntp: Callable = ntp_offset, http: Callable = http_offset) -> Tuple[Optional[float], str]:
    """A fresh offset and its source, or (None, "") if nothing answered."""
    readings = []
    for host in NTP_SERVERS:
        try:
            value, rtt = ntp(host)
        except (OSError, ValueError) as exc:
            logger.debug("NTP %s failed: %s", host, exc)
            continue
        if rtt <= MAX_RTT:
            readings.append(value)
        if len(readings) == 2:  # two agreeing servers are plenty
            break
    if readings:
        return statistics.median(readings), "ntp"
    for url in HTTP_SOURCES:
        try:
            value, rtt = http(url)
        except Exception as exc:  # noqa: BLE001 - any failure means "try the next"
            logger.debug("HTTP time from %s failed: %s", url, exc)
            continue
        if rtt <= MAX_RTT * 3:
            return value, "http-date"
    return None, ""


def _save(value: float, source: str, path: Optional[str]) -> None:
    payload = {
        "offset_seconds": round(value, 3),
        "source": source,
        "measured_at_local": time.time(),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() + value)),
        "note": "seconds to ADD to this PC's clock to get real time; written by market/clock_offset.py",
    }
    try:
        state_store.write(STATE_NAME, payload, path)
    except (OSError, sqlite3.Error) as exc:
        logger.debug("Could not save the clock offset: %s", exc)


def _load(path: Optional[str]) -> Optional[float]:
    """The saved offset if it is under a day old, else None."""
    raw = state_store.read(STATE_NAME, path)
    try:
        if raw is not None and time.time() - float(raw["measured_at_local"]) <= SAVED_VALID_FOR:
            return float(raw["offset_seconds"])
    except (ValueError, KeyError, TypeError):
        pass
    return None


def offset(refresh: bool = False, path: Optional[str] = None, measurer: Callable = measure) -> float:
    """Seconds to add to ``time.time()`` for real time.

    Measured once per process (and again after ``REMEASURE_AFTER``, or when
    ``refresh`` is set - e.g. after a TOTP code was rejected).
    """
    global _cached
    with _LOCK:
        if not refresh and _cached and time.monotonic() - _cached[1] < REMEASURE_AFTER:
            return _cached[0]
        value, source = measurer()
        if value is not None:
            if abs(value) >= 2:
                logger.info("This PC's clock is %.1f s %s real time (%s)",
                            abs(value), "behind" if value > 0 else "ahead of", source)
            _save(value, source, path)
        else:
            value = _load(path)
            if value is None:
                logger.warning("Could not measure the clock offset and none is saved - using the system clock")
                value = 0.0
            else:
                logger.info("Saved clock offset %+.1f s (nothing answered to re-measure)", value)
        _cached = (value, time.monotonic())
        return value


def now() -> float:
    """Real time as a Unix timestamp."""
    return time.time() + offset()


def totp_code(secret: str, min_seconds_left: float = 3.0, sleep: Callable = time.sleep,
              refresh: bool = False) -> str:
    """The current TOTP code for ``secret``, on the corrected clock.

    Waits only when fewer than ``min_seconds_left`` seconds remain in the
    30 s window - at most that long - so the code cannot expire in transit.
    """
    import pyotp

    corrected = offset(refresh=refresh)
    moment = time.time() + corrected
    left = 30 - (moment % 30)
    if left < min_seconds_left:
        sleep(left + 0.2)
        moment = time.time() + corrected
    return pyotp.TOTP(secret.replace(" ", "").upper()).at(moment)


def reset_cache() -> None:
    """Forget the in-process value (tests)."""
    global _cached
    with _LOCK:
        _cached = None
