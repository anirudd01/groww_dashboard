"""API wrapper for Groww Trading API calls."""

import logging
from typing import Dict, Any, List, Optional, Tuple

from groww_api.client import GrowwAPIClient

logger = logging.getLogger(__name__)


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
        """
        Fetch LTP for NSE FnO contracts.
        Uses get_ltp() API with NSE_ prefix and FNO segment.
        """
        if not symbols:
            return {}

        result = {}
        try:
            from growwapi import GrowwAPI

            # Format symbols with NSE_ prefix for the API
            formatted_symbols = []
            for s in symbols:
                formatted_s = s.strip()
                if not formatted_s.startswith("NSE_"):
                    formatted_s = f"NSE_{formatted_s}"
                formatted_symbols.append(formatted_s)

            # Batch the calls (50 symbols max per call)
            for i in range(0, len(formatted_symbols), 50):
                batch = tuple(formatted_symbols[i : i + 50])

                try:
                    logger.debug(f"Fetching LTP for {len(batch)} NSE FnO symbols...")
                    resp = self.client.session.get_ltp(
                        segment=GrowwAPI.SEGMENT_FNO,
                        exchange_trading_symbols=batch if len(batch) > 1 else batch[0],
                    )

                    if isinstance(resp, dict):
                        for k, v in resp.items():
                            symbol_key = k.replace("NSE_", "") if k.startswith("NSE_") else k
                            result[symbol_key] = float(v) if v else 0.0

                except Exception as e:
                    logger.warning(f"Failed to fetch NSE FnO LTP batch: {e}")
                    continue

            logger.info(f"Fetched LTP for {len(result)}/{len(symbols)} NSE FnO positions")

        except Exception as e:
            logger.warning(f"NSE FnO LTP fetch error: {e}")

        return result

    def get_ltp_for_mcx(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch LTP for MCX commodity contracts, one ``get_quote`` call each.

        Groww's docs name only CASH and FNO for the batched ``get_ltp``, so MCX stays on the
        per-contract quote until a batched COMMODITY call has been seen to work (that needs the
        paid data plan; see docs/api/GROWW_API_LIVE_DATA.md). Stops at the first failure: without
        the plan every call is refused the same way.
        """
        result: Dict[str, float] = {}
        from growwapi import GrowwAPI

        for symbol in symbols:
            try:
                quote = self.client.session.get_quote(
                    exchange=GrowwAPI.EXCHANGE_MCX,
                    segment=GrowwAPI.SEGMENT_COMMODITY,
                    trading_symbol=symbol.strip(),
                    timeout=10,
                )
            except Exception as e:
                logger.warning("MCX quote failed for %s, so MCX positions are unpriced: %s", symbol, e)
                break
            ltp = self._extract_ltp_from_quote(quote)
            if ltp and ltp > 0:
                result[symbol] = ltp

        logger.info("Fetched LTP for %d/%d MCX positions", len(result), len(symbols))
        return result

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

    def _extract_ltp_from_quote(self, quote) -> Optional[float]:
        """
        Extract LTP value from get_quote() response.
        Groww documents the field as ``last_price``; the others are kept as harmless fallbacks.
        """
        if not quote:
            return None

        if isinstance(quote, (int, float)):
            return float(quote)

        if isinstance(quote, dict):
            for field in ["last_price", "ltp", "lastPrice", "price", "LTP"]:
                if field in quote:
                    val = quote[field]
                    if val and val > 0:
                        return float(val)

        return None

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
