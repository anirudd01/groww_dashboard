"""API wrapper for Groww Trading API calls."""

import logging
from typing import Dict, Any, List, Optional

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
        """Fetch long term delivery holdings for user."""
        try:
            return self.client.session.get_holdings()
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
    ) -> Dict[str, Any]:
        """Place an order via the underlying Groww API session."""
        return self.client.session.place_order(
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
        Fetch LTP for MCX commodity contracts.
        Uses get_quote() API for each symbol individually.
        """
        if not symbols:
            return {}

        result = {}

        try:
            from growwapi import GrowwAPI

            logger.debug(f"Fetching LTP for {len(symbols)} MCX commodity symbols...")

            # For MCX, we need to call get_quote with correct parameters
            for symbol in symbols:
                try:
                    # get_quote needs: exchange, segment, trading_symbol
                    quote = self.client.session.get_quote(
                        exchange=GrowwAPI.EXCHANGE_MCX,
                        segment=GrowwAPI.SEGMENT_COMMODITY,
                        trading_symbol=symbol.strip(),
                    )

                    if quote:
                        ltp = self._extract_ltp_from_quote(quote)
                        if ltp and ltp > 0:
                            result[symbol] = ltp
                            logger.debug(f"Fetched LTP for {symbol}: {ltp}")

                except AttributeError as e:
                    # EXCHANGE_MCX or SEGMENT_COMMODITY might not exist
                    logger.warning(f"MCX constants not available: {e}")
                    # Fall back to trying get_ltp with MCX prefix
                    try:
                        resp = self.client.session.get_ltp(
                            segment="COMMODITY",
                            exchange_trading_symbols=f"MCX_{symbol.strip()}",
                        )
                        if isinstance(resp, dict):
                            for k, v in resp.items():
                                symbol_key = k.replace("MCX_", "")
                                result[symbol_key] = float(v) if v else 0.0
                    except Exception as e2:
                        logger.debug(f"MCX fallback also failed for {symbol}: {e2}")

                except Exception as e:
                    logger.debug(f"Failed to get quote for MCX symbol {symbol}: {e}")
                    continue

            logger.info(f"Fetched LTP for {len(result)}/{len(symbols)} MCX positions")

        except Exception as e:
            logger.warning(f"MCX LTP fetch error: {e}")

        return result

    def _extract_ltp_from_quote(self, quote) -> Optional[float]:
        """
        Extract LTP value from get_quote() response.
        Handles different response formats.
        """
        if not quote:
            return None

        if isinstance(quote, (int, float)):
            return float(quote)

        if isinstance(quote, dict):
            # Check common field names for LTP
            for field in ["ltp", "lastPrice", "last_price", "price", "LTP"]:
                if field in quote:
                    val = quote[field]
                    if val and val > 0:
                        return float(val)

        return None

    def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """
        Generic LTP fetch - attempts to determine symbol type and fetch appropriately.
        """
        if not symbols:
            return {}

        # Check if symbols are FnO or commodity by looking at patterns
        from utils import COMMODITY_KEYWORDS

        nse_symbols = []
        mcx_symbols = []

        for symbol in symbols:
            symbol_upper = symbol.upper()
            if any(kw in symbol_upper for kw in COMMODITY_KEYWORDS):
                mcx_symbols.append(symbol)
            else:
                nse_symbols.append(symbol)

        result = {}
        if nse_symbols:
            result.update(self.get_ltp_for_nse_fno(nse_symbols))
        if mcx_symbols:
            result.update(self.get_ltp_for_mcx(mcx_symbols))

        return result
