"""API wrapper for Groww Trading API calls."""

import logging
from typing import Dict, Any, List, Optional, Tuple

from groww_api.client import GrowwAPIClient

logger = logging.getLogger(__name__)


def batched_ltp(session, exchange: str, segment: str, symbols: List[str]) -> Dict[str, float]:
    """LTP by trading symbol via the SDK ``session.get_ltp``, 50 ``EXCHANGE_SYMBOL`` keys per call.

    Symbols without a positive price are left out, so the caller treats them as unpriced
    rather than worth zero. One unknown symbol makes Groww refuse the whole batch ("Invalid
    trading symbol"), so that batch is retried one symbol at a time. Any other failure (no
    data plan, an outage) fails every call the same way and stops the fetch.
    """
    prefix = f"{exchange}_"
    keys = [s.strip() if s.strip().startswith(prefix) else prefix + s.strip() for s in symbols]

    def fetch(batch):
        return session.get_ltp(
            segment=segment,
            exchange_trading_symbols=batch if len(batch) > 1 else batch[0],
            timeout=10,
        ) or {}

    result: Dict[str, float] = {}
    for i in range(0, len(keys), 50):
        batch = tuple(keys[i : i + 50])
        try:
            resp = fetch(batch)
        except Exception as e:
            if len(batch) == 1 or "invalid trading symbol" not in str(e).lower():
                logger.warning("%s %s LTP failed, so those symbols are unpriced: %s", exchange, segment, e)
                break
            resp = {}
            for key in batch:
                try:
                    resp.update(fetch((key,)))
                except Exception as e:
                    logger.warning("No LTP for %s: %s", key, e)
        for key, value in resp.items():
            if value and float(value) > 0:
                result[key[len(prefix):] if key.startswith(prefix) else key] = float(value)
    logger.info("Fetched LTP for %d/%d %s %s symbols", len(result), len(symbols), exchange, segment)
    return result


class GrowwAPIService:
    """
    Wraps all API calls to Groww Trading API.
    Uses singleton client from GrowwAPIClient.
    """

    def __init__(self, client: Optional[GrowwAPIClient] = None):
        """
        Initialize service with a GrowwAPIClient.
        If none provided, uses the singleton instance.
        """
        self.client = client or GrowwAPIClient.get_instance()
        if not self.client.is_connected:
            raise RuntimeError(self.client.auth_error or "Client not authenticated")

    def get_user_profile(self) -> Dict[str, Any]:
        """Fetch user profile details."""
        try:
            return self.client.session.get_user_profile()
        except Exception as e:
            logger.error("Error fetching user profile: %s", e)
            return {}

    def get_margins(self) -> Dict[str, Any]:
        """Fetch available margin and fund balance."""
        try:
            return self.client.session.get_available_margin_details()
        except Exception as e:
            logger.error("Error fetching margins: %s", e)
            return {}

    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch long term delivery holdings for user (the ``holdings`` list of the response)."""
        try:
            resp = self.client.session.get_holdings_for_user(timeout=15)
            return resp.get("holdings", []) if isinstance(resp, dict) else []
        except Exception as e:
            logger.error("Error fetching holdings: %s", e)
            return []

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open positions (cash/MTF)."""
        try:
            resp = self.client.session.get_positions_for_user()
            if isinstance(resp, dict):
                return resp.get("positions", [])
            elif isinstance(resp, list):
                return resp
            return []
        except Exception as e:
            logger.error("Error fetching positions: %s", e)
            return []

    def place_order(
        self,
        trading_symbol: str,
        quantity: int,
        price: float,
        validity: str,
        exchange: str,
        segment: str,
        product: str,
        order_type: str,
        transaction_type: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Place an order via the underlying Groww API session.

        The SDK waits forever by default. With ``timeout`` a slow answer raises instead, but the
        order may still have reached Groww: check the order book before sending it again.
        """
        return self.client.session.place_order(
            timeout=timeout,
            trading_symbol=trading_symbol,
            quantity=quantity,
            price=price,
            validity=validity,
            exchange=exchange,
            segment=segment,
            product=product,
            order_type=order_type,
            transaction_type=transaction_type,
        )

    def get_order_status(self, segment: str, groww_order_id: str) -> Dict[str, Any]:
        """Fetch the current status of a previously placed order."""
        return self.client.session.get_order_status(
            segment=segment,
            groww_order_id=groww_order_id,
        )

    def get_ltp_for_nse_fno(self, symbols: List[str]) -> Dict[str, float]:
        """LTP for NSE F&O contracts, keyed by trading symbol."""
        from growwapi import GrowwAPI

        return batched_ltp(self.client.session, GrowwAPI.EXCHANGE_NSE, GrowwAPI.SEGMENT_FNO, symbols)

    def get_ltp_for_mcx(self, symbols: List[str]) -> Dict[str, float]:
        """LTP for MCX contracts, keyed by trading symbol.

        Batched ``get_ltp`` with ``MCX_`` keys and segment COMMODITY works on the paid data plan
        (seen 2026-10-18), although Groww's docs only show CASH and FNO examples.
        """
        from growwapi import GrowwAPI

        return batched_ltp(self.client.session, GrowwAPI.EXCHANGE_MCX, GrowwAPI.SEGMENT_COMMODITY, symbols)

    def get_greeks(self, exchange: str, underlying: str, trading_symbol: str, expiry: str,
                   timeout: float = 10) -> Dict[str, Any]:
        """The ``greeks`` dict (delta, gamma, theta, vega, rho, iv) for one option contract.

        ``GrowwAPI.get_greeks`` is the only SDK call without a timeout argument (its request has
        no timeout at all), so it runs on a daemon thread and is abandoned after ``timeout``. A
        daemon, not an executor worker: Python joins executor threads at exit, so a hung request
        would stall shutdown.
        """
        import threading

        outcome = {}

        def call():
            try:
                outcome["resp"] = self.client.session.get_greeks(
                    exchange=exchange, underlying=underlying, trading_symbol=trading_symbol, expiry=expiry)
            except Exception as e:  # handed back to the caller below
                outcome["error"] = e

        worker = threading.Thread(target=call, name="groww-greeks", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError(f"get_greeks gave no answer within {timeout:g} s")
        if "error" in outcome:
            raise outcome["error"]
        return (outcome.get("resp") or {}).get("greeks") or {}

    # ------------------------------------------------------------------
    # NSE CASH (equity) helpers - used by the live sector heatmap
    # ------------------------------------------------------------------

    def get_instruments(self):
        """Return Groww's full instrument master as a DataFrame."""
        return self.client.session.get_all_instruments()

    def resolve_nse_cash_instruments(
        self, symbols: List[str]
    ) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
        """
        Resolve NSE CASH trading symbols to their instrument metadata.

        Exchange tokens are never hardcoded - they come from Groww's
        instrument master.

        Returns:
            (resolved, missing) where `resolved` maps trading_symbol to a dict
            with exchange / segment / exchange_token / name, and `missing` lists
            the symbols that could not be found.
        """
        resolved: Dict[str, Dict[str, Any]] = {}
        missing: List[str] = []

        if not symbols:
            return resolved, missing

        try:
            instruments = self.get_instruments()
        except Exception as e:
            logger.error("Could not load Groww instrument master: %s", e)
            return resolved, list(symbols)

        try:
            nse_cash = instruments[
                (instruments["exchange"] == "NSE")
                & (instruments["segment"] == "CASH")
            ]
            lookup = nse_cash.set_index("trading_symbol")
        except Exception as e:
            logger.error("Unexpected instrument master layout: %s", e)
            return resolved, list(symbols)

        for symbol in symbols:
            try:
                row = lookup.loc[symbol]
            except KeyError:
                logger.warning("Missing exchange token for %s (not in instrument master)", symbol)
                missing.append(symbol)
                continue

            # Duplicate trading symbols would yield a DataFrame; take the first.
            if hasattr(row, "iloc") and getattr(row, "ndim", 1) > 1:
                row = row.iloc[0]

            token = row.get("exchange_token")
            if token is None or str(token).strip() in ("", "nan"):
                logger.warning("Missing exchange token for %s (blank in instrument master)", symbol)
                missing.append(symbol)
                continue

            resolved[symbol] = {
                "trading_symbol": symbol,
                "exchange": "NSE",
                "segment": "CASH",
                "exchange_token": str(token).strip(),
                "name": row.get("name"),
            }

        logger.info(
            "Resolved %d/%d NSE CASH instruments from the instrument master",
            len(resolved),
            len(symbols),
        )
        return resolved, missing

    def _nse_cash_batches(self, symbols: List[str], batch_size: int = 50):
        """Yield (batch_of_symbols, prefixed_tuple) pairs for batched endpoints."""
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            yield batch, tuple(f"NSE_{s}" for s in batch)

    def get_previous_close_nse_cash(
        self, symbols: List[str], batch_size: int = 50, timeout: Optional[int] = 15
    ) -> Dict[str, float]:
        """
        Fetch the previous trading day's closing price for NSE CASH symbols.

        Uses Groww's OHLC endpoint, whose `close` field is the previous
        session's close (today's close is not known until the session ends).
        This is reference data: call it on startup, not on every refresh.
        """
        result: Dict[str, float] = {}
        if not symbols:
            return result

        from growwapi import GrowwAPI

        for batch, prefixed in self._nse_cash_batches(symbols, batch_size):
            try:
                resp = self.client.session.get_ohlc(
                    segment=GrowwAPI.SEGMENT_CASH,
                    exchange_trading_symbols=prefixed,
                    timeout=timeout,
                )
            except Exception as e:
                logger.warning(
                    "OHLC request failed for %d symbols (%s ...): %s",
                    len(batch),
                    batch[0],
                    e,
                )
                continue

            if not isinstance(resp, dict):
                continue

            for key, ohlc in resp.items():
                symbol = key[4:] if key.startswith("NSE_") else key
                if not isinstance(ohlc, dict):
                    continue
                close = ohlc.get("close")
                try:
                    close = float(close)
                except (TypeError, ValueError):
                    close = 0.0
                if close > 0:
                    result[symbol] = close
                else:
                    logger.warning("Missing previous close for %s", symbol)

        logger.info("Resolved previous close for %d/%d symbols", len(result), len(symbols))
        return result

    def get_ltp_nse_cash(
        self, symbols: List[str], batch_size: int = 50, timeout: Optional[int] = 10
    ) -> Dict[str, float]:
        """
        Batched LTP snapshot for NSE CASH symbols.

        This is the REST fallback used only when the websocket feed is
        unavailable - the live feed is the primary price source.

        An explicit timeout is essential: the SDK defaults to no timeout, and a
        stalled request would otherwise freeze the polling loop indefinitely.
        """
        result: Dict[str, float] = {}
        if not symbols:
            return result

        from growwapi import GrowwAPI

        for batch, prefixed in self._nse_cash_batches(symbols, batch_size):
            try:
                resp = self.client.session.get_ltp(
                    segment=GrowwAPI.SEGMENT_CASH,
                    exchange_trading_symbols=prefixed,
                    timeout=timeout,
                )
            except Exception as e:
                logger.warning(
                    "LTP request failed for %d symbols (%s ...): %s",
                    len(batch),
                    batch[0],
                    e,
                )
                continue

            if not isinstance(resp, dict):
                continue

            for key, value in resp.items():
                symbol = key[4:] if key.startswith("NSE_") else key
                try:
                    price = float(value)
                except (TypeError, ValueError):
                    continue
                if price > 0:
                    result[symbol] = price

        return result
