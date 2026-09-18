"""DhanHQ v2 market-data provider.

Implements the documented Dhan REST and WebSocket APIs directly rather than
depending on the ``dhanhq`` SDK - the live feed is a small, fully-specified
binary protocol, and going direct keeps the dependency surface unchanged
(``websockets`` and ``requests`` are already installed).

References (DhanHQ API v2):
  - Instrument master : https://images.dhan.co/api-data/api-scrip-master-detailed.csv
  - LTP / OHLC        : POST https://api.dhan.co/v2/marketfeed/{ltp,ohlc}
  - Live feed         : wss://api-feed.dhan.co?version=2&token=..&clientId=..&authType=2

Credentials come from the environment. Only ``DHAN_ACCESS_TOKEN`` is required -
Dhan embeds the client id in the token, so ``DHAN_CLIENT_ID`` is an optional
override. Neither is ever logged.
"""

import asyncio
import base64
import io
import json
import logging
import os
import struct
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from market.providers.base import FeedHandle, InstrumentRef, MarketDataProvider

logger = logging.getLogger(__name__)

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
REST_BASE = "https://api.dhan.co/v2"
FEED_URL = "wss://api-feed.dhan.co"

# Dhan exchange-segment key for NSE cash equities.
NSE_EQ = "NSE_EQ"

# Feed request codes (Annexure: Feed Request Code)
REQUEST_SUBSCRIBE_TICKER = 15
REQUEST_DISCONNECT = 12

# Feed response codes (Annexure: Feed Response Code)
RESPONSE_TICKER = 2
RESPONSE_PREV_CLOSE = 6
RESPONSE_MARKET_STATUS = 7
RESPONSE_DISCONNECT = 50

# Total packet sizes (header + payload) for the codes we care about. Used to
# validate the length field in the header before advancing the read offset.
PACKET_SIZES = {
    RESPONSE_TICKER: 16,
    RESPONSE_PREV_CLOSE: 16,
    RESPONSE_DISCONNECT: 10,
}

# Dhan limits: 100 instruments per subscribe message, 5000 per connection,
# 1000 per REST quote request, 1 quote request/second.
SUBSCRIBE_BATCH = 100
REST_BATCH = 1000

#: Dhan error code returned when the account has no Data API plan.
DATA_APIS_NOT_SUBSCRIBED = "806"
#: Dhan error code for rate limiting.
RATE_LIMITED = "805"
#: Dhan allows 1 request/second across all market-quote endpoints, so calls to
#: ltp/ohlc/quote share one throttle.
MIN_QUOTE_INTERVAL = 1.1


def client_id_from_token(access_token: str) -> str:
    """Extract ``dhanClientId`` from a Dhan access token.

    Dhan's JWT carries the client id in its payload, so the dashboard needs
    only the access token. Returns "" if it cannot be read - the caller then
    falls back to an explicitly configured DHAN_CLIENT_ID.

    The token is only decoded, never verified (we are not the issuer) and
    never logged.
    """
    try:
        payload = (access_token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return str(claims.get("dhanClientId") or "").strip()
    except Exception:
        return ""


def token_expiry(access_token: str) -> Optional[int]:
    """Unix expiry of a Dhan access token, or None if unreadable."""
    try:
        payload = (access_token or "").split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        expiry = claims.get("exp")
        return int(expiry) if expiry is not None else None
    except Exception:
        return None


class DhanFeedHandle(FeedHandle):
    """One Dhan market-feed websocket, driven on its own daemon thread.

    The socket runs an asyncio loop in a background thread and writes into
    plain dicts guarded by a lock; ``latest_prices()`` just copies them, so the
    caller never touches asyncio.
    """

    def __init__(self, access_token: str, client_id: str, refs: List[InstrumentRef]):
        self._token = access_token
        self._client_id = client_id
        self._refs = list(refs)
        self._by_id: Dict[int, str] = {}
        for ref in self._refs:
            try:
                self._by_id[int(ref.provider_id)] = ref.symbol
            except (TypeError, ValueError):
                logger.warning("Dhan: bad security id %r for %s", ref.provider_id, ref.symbol)

        self._lock = threading.Lock()
        self._prices: Dict[str, float] = {}
        self._prev_closes: Dict[str, float] = {}

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._alive = False
        self._logged_first_packet = False
        self._thread = threading.Thread(
            target=self._run, name="dhan-feed", daemon=True
        )

    # -- lifecycle ------------------------------------------------------
    def start(self, timeout: float = 20.0) -> "DhanFeedHandle":
        """Start the socket and block until subscribed (or raise)."""
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise TimeoutError(
                f"Dhan feed did not connect within {timeout:.0f}s"
            )
        if self._error is not None:
            raise self._error
        return self

    @property
    def is_alive(self) -> bool:
        return self._alive and self._thread.is_alive() and not self._stop.is_set()

    def latest_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._prices)

    def previous_closes(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._prev_closes)

    def close(self) -> None:
        self._stop.set()
        self._alive = False

    # -- socket ---------------------------------------------------------
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except BaseException as e:  # noqa: BLE001 - surfaced via start()/is_alive
            self._error = e
            logger.warning("Dhan feed stopped: %s: %s", type(e).__name__, e)
        finally:
            self._alive = False
            self._ready.set()
            try:
                loop.close()
            except Exception:
                pass

    async def _main(self) -> None:
        import websockets

        url = (
            f"{FEED_URL}?version=2&token={self._token}"
            f"&clientId={self._client_id}&authType=2"
        )
        # Dhan pings every 10s and drops the connection after 40s of silence;
        # the library answers pings automatically.
        async with websockets.connect(
            url, ping_interval=None, close_timeout=5, max_size=None
        ) as ws:
            await self._subscribe(ws)
            self._alive = True
            self._ready.set()
            logger.info(
                "Dhan feed connected - subscribed to %d instruments", len(self._by_id)
            )
            while not self._stop.is_set():
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if isinstance(message, bytes):
                    self._parse(message)
            try:
                await ws.send('{"RequestCode": %d}' % REQUEST_DISCONNECT)
            except Exception:
                pass

    async def _subscribe(self, ws) -> None:
        for i in range(0, len(self._refs), SUBSCRIBE_BATCH):
            batch = self._refs[i : i + SUBSCRIBE_BATCH]
            await ws.send(
                json.dumps(
                    {
                        "RequestCode": REQUEST_SUBSCRIBE_TICKER,
                        "InstrumentCount": len(batch),
                        "InstrumentList": [
                            {
                                "ExchangeSegment": NSE_EQ,
                                "SecurityId": str(r.provider_id),
                            }
                            for r in batch
                        ],
                    }
                )
            )

    # -- binary parsing -------------------------------------------------
    def _parse(self, data: bytes) -> None:
        """Decode one websocket frame, which may hold several packets.

        Header (8 bytes, little endian): code:uint8, length:int16,
        segment:uint8, security_id:int32.
        """
        offset, size = 0, len(data)
        prices: Dict[str, float] = {}
        prev: Dict[str, float] = {}

        while offset + 8 <= size:
            code, length, _segment, security_id = struct.unpack_from(
                "<BHBi", data, offset
            )

            if not self._logged_first_packet:
                self._logged_first_packet = True
                logger.debug(
                    "Dhan first packet: code=%s length=%s security_id=%s frame=%s bytes",
                    code, length, security_id, size,
                )

            # Trust the documented size where we know it; the length field is
            # only used for packets we do not decode.
            step = PACKET_SIZES.get(code, length)
            if step < 8 or offset + step > size:
                step = length if 8 <= length <= size - offset else 0
                if step == 0:
                    break

            symbol = self._by_id.get(security_id)
            if symbol is not None:
                if code == RESPONSE_TICKER and offset + 16 <= size:
                    ltp, _ltt = struct.unpack_from("<fi", data, offset + 8)
                    if ltp > 0:
                        prices[symbol] = float(ltp)
                elif code == RESPONSE_PREV_CLOSE and offset + 16 <= size:
                    close, _oi = struct.unpack_from("<fi", data, offset + 8)
                    if close > 0:
                        prev[symbol] = float(close)
            elif code == RESPONSE_DISCONNECT:
                reason = (
                    struct.unpack_from("<H", data, offset + 8)[0]
                    if offset + 10 <= size
                    else -1
                )
                logger.warning("Dhan feed sent disconnect packet, reason code %s", reason)
                self._alive = False
                self._stop.set()
                return

            offset += step

        if prices or prev:
            with self._lock:
                self._prices.update(prices)
                self._prev_closes.update(prev)


class DhanProvider(MarketDataProvider):
    """DhanHQ v2 provider: instrument master, REST snapshots, live feed."""

    name = "dhan"
    label = "Dhan"

    def __init__(
        self,
        access_token: Optional[str] = None,
        client_id: Optional[str] = None,
        timeout: int = 15,
    ):
        self._token = (access_token or os.getenv("DHAN_ACCESS_TOKEN") or "").strip()
        self._client_id = self._resolve_client_id(
            client_id or os.getenv("DHAN_CLIENT_ID")
        )
        self._timeout = timeout
        self._instruments = None
        self._quote_lock = threading.Lock()
        self._last_quote_at = 0.0

    def _throttle_quotes(self) -> None:
        """Space out market-quote requests to stay inside Dhan's 1/sec limit.

        Shared by ltp and ohlc because the limit spans all quote endpoints.
        """
        with self._quote_lock:
            wait = MIN_QUOTE_INTERVAL - (time.monotonic() - self._last_quote_at)
            if wait > 0:
                time.sleep(wait)
            self._last_quote_at = time.monotonic()

    def _resolve_client_id(self, configured: Optional[str]) -> str:
        """Client id from the token, which is authoritative.

        Dhan embeds ``dhanClientId`` in the access token, so DHAN_CLIENT_ID is
        optional. A configured value is only used when the token has none, and
        an obvious placeholder is ignored outright - a stale
        ``DHAN_CLIENT_ID=your_dhan_client_id`` left in .env would otherwise turn
        a clear "Data APIs not subscribed" error into a confusing auth failure.
        """
        configured = (configured or "").strip()
        if configured and (
            configured.lower().startswith(("your_", "<", "xxx")) or not configured.isdigit()
        ):
            logger.warning(
                "Ignoring placeholder DHAN_CLIENT_ID=%r - reading the client id "
                "from the access token instead",
                configured,
            )
            configured = ""

        from_token = client_id_from_token(self._token)
        if from_token:
            if configured and configured != from_token:
                logger.warning(
                    "DHAN_CLIENT_ID does not match the access token's client id; "
                    "using the token's value"
                )
            return from_token
        return configured

    # -- config / auth --------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self._token and self._client_id)

    def _headers(self) -> Dict[str, str]:
        return {
            "access-token": self._token,
            "client-id": self._client_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def connect(self) -> None:
        if not self.is_configured():
            raise RuntimeError(
                "Dhan credentials missing - set DHAN_ACCESS_TOKEN "
                "(DHAN_CLIENT_ID is optional; it is read from the token)"
            )
        expiry = token_expiry(self._token)
        if expiry is not None:
            remaining = expiry - int(time.time())
            if remaining <= 0:
                raise RuntimeError(
                    "Dhan access token has expired - generate a new one"
                )
            logger.info("Dhan access token valid for %.1f more hours", remaining / 3600)
        # /profile is a non-trading endpoint: it validates the token even when
        # the Data API plan is inactive, so it gives a precise diagnosis.
        profile = self._json(
            requests.get(
                f"{REST_BASE}/profile", headers=self._headers(), timeout=self._timeout
            )
        )
        error = self._error_of(profile)
        if error or not profile.get("dhanClientId"):
            code, message = error or ("", "token rejected")
            raise RuntimeError(f"Dhan authentication failed: {code} {message}".strip())

        data_plan = str(profile.get("dataPlan", "")).strip()
        logger.info(
            "Dhan authenticated (client %s..., data plan: %s, token valid to %s)",
            self._client_id[:4],
            data_plan or "unknown",
            profile.get("tokenValidity", "?"),
        )

        # Market data - REST and the live feed alike - needs the Data API plan.
        resp = requests.post(
            f"{REST_BASE}/marketfeed/ltp",
            headers=self._headers(),
            json={NSE_EQ: [1333]},
            timeout=self._timeout,
        )
        error = self._error_of(self._json(resp))
        if error:
            code, message = error
            if code == DATA_APIS_NOT_SUBSCRIBED or "not subscribed" in message.lower():
                raise RuntimeError(
                    "Dhan Data API plan is not active on this account "
                    f"(dataPlan={data_plan or 'Deactive'}, error {code}: {message}). "
                    "Market quotes and the live feed both require it - subscribe "
                    "under Dhan -> Profile -> DhanHQ Trading APIs -> Data APIs."
                )
            raise RuntimeError(f"Dhan market data unavailable: {code} {message}")
        resp.raise_for_status()

    @staticmethod
    def _json(resp) -> dict:
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _error_of(payload: dict):
        """Return (code, message) for a Dhan error body, or None if it is not one.

        Dhan reports failures as ``{"status": "failed", "data": {"806": "..."}}``
        with the key casing varying between "data" and "Data", and elsewhere as
        ``{"status": "failure", "errorCode": ..., "errorMessage": ...}``.
        """
        if not isinstance(payload, dict):
            return None
        status = str(payload.get("status", "")).lower()
        if status not in ("failed", "failure"):
            return None
        if payload.get("errorCode") or payload.get("errorMessage"):
            return str(payload.get("errorCode") or ""), str(payload.get("errorMessage") or "")
        block = payload.get("data") or payload.get("Data") or {}
        if isinstance(block, dict) and block:
            code, message = next(iter(block.items()))
            return str(code), str(message)
        return "", "unknown Dhan error"

    # -- reference data -------------------------------------------------
    def _load_instruments(self):
        if self._instruments is not None:
            return self._instruments
        import pandas as pd

        logger.info("Downloading Dhan instrument master ...")
        resp = requests.get(SCRIP_MASTER_URL, timeout=120)
        resp.raise_for_status()
        frame = pd.read_csv(io.StringIO(resp.text), dtype=str, low_memory=False)
        self._instruments = frame[
            (frame["EXCH_ID"] == "NSE")
            & (frame["SEGMENT"] == "E")
            & (frame["INSTRUMENT"] == "EQUITY")
        ]
        logger.info("Dhan instrument master: %d NSE equities", len(self._instruments))
        return self._instruments

    def resolve_instruments(
        self, symbols: List[str]
    ) -> Tuple[Dict[str, InstrumentRef], List[str]]:
        resolved: Dict[str, InstrumentRef] = {}
        missing: List[str] = []
        if not symbols:
            return resolved, missing

        try:
            frame = self._load_instruments()
        except Exception as e:
            logger.error("Dhan instrument master unavailable: %s", e)
            return resolved, list(symbols)

        # UNDERLYING_SYMBOL carries the NSE trading symbol for cash equities.
        lookup = {}
        for symbol, security_id in zip(
            frame["UNDERLYING_SYMBOL"], frame["SECURITY_ID"]
        ):
            if symbol and symbol not in lookup:
                lookup[symbol] = security_id

        for symbol in symbols:
            security_id = lookup.get(symbol)
            if not security_id or str(security_id).strip() in ("", "nan"):
                logger.warning("Dhan: no security id for %s", symbol)
                missing.append(symbol)
                continue
            resolved[symbol] = InstrumentRef(
                symbol=symbol, provider_id=str(security_id).strip()
            )

        logger.info("Dhan resolved %d/%d instruments", len(resolved), len(symbols))
        return resolved, missing

    def _post_marketfeed(self, endpoint: str, refs: List[InstrumentRef]) -> dict:
        ids = []
        for ref in refs:
            try:
                ids.append(int(ref.provider_id))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}

        merged: dict = {}
        for i in range(0, len(ids), REST_BATCH):
            chunk = ids[i : i + REST_BATCH]
            payload, error = {}, None
            # One retry: a 805 usually just means we were a little too quick.
            for attempt in range(2):
                self._throttle_quotes()
                resp = requests.post(
                    f"{REST_BASE}/marketfeed/{endpoint}",
                    headers=self._headers(),
                    json={NSE_EQ: chunk},
                    timeout=self._timeout,
                )
                payload = self._json(resp)
                error = self._error_of(payload)
                if error is None or error[0] != RATE_LIMITED:
                    break
                if attempt == 0:
                    logger.debug("Dhan %s rate limited - retrying", endpoint)
                    time.sleep(MIN_QUOTE_INTERVAL)
            if error:
                logger.warning("Dhan %s error: %s %s", endpoint, *error)
                continue
            section = (payload.get("data") or {}).get(NSE_EQ) or {}
            merged.update(section)
        return merged

    def _by_symbol(
        self, refs: List[InstrumentRef], raw: dict, extract
    ) -> Dict[str, float]:
        by_id = {str(r.provider_id): r.symbol for r in refs}
        out: Dict[str, float] = {}
        for security_id, entry in (raw or {}).items():
            symbol = by_id.get(str(security_id))
            if symbol is None:
                continue
            try:
                value = extract(entry)
            except (TypeError, ValueError, AttributeError):
                continue
            if value and value > 0:
                out[symbol] = float(value)
        return out

    def get_previous_close(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        """Previous-day close from the OHLC endpoint.

        Dhan's OHLC block reports the previous session's close while the market
        is open. Anything non-positive is treated as missing, and the feed's
        explicit previous-close packet fills the gaps.
        """
        raw = self._post_marketfeed("ohlc", refs)
        closes = self._by_symbol(
            refs, raw, lambda e: (e.get("ohlc") or {}).get("close")
        )
        logger.info("Dhan resolved previous close for %d/%d", len(closes), len(refs))
        return closes

    def get_ltp_snapshot(self, refs: List[InstrumentRef]) -> Dict[str, float]:
        raw = self._post_marketfeed("ltp", refs)
        return self._by_symbol(refs, raw, lambda e: e.get("last_price"))

    def open_feed(self, refs: List[InstrumentRef]) -> FeedHandle:
        return DhanFeedHandle(self._token, self._client_id, refs).start()
