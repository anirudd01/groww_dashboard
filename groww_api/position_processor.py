"""Business logic for processing FnO positions and calculating metrics."""

import logging
import re
from typing import Dict, Any, List, Optional

from groww_api.api_calls import GrowwAPIService
from utils import (
    ASSET_TYPE_EQUITY,
    ASSET_TYPE_COMMODITY,
    INDEX_KEYWORDS,
    COMMODITY_KEYWORDS,
    format_expiry_date,
)

logger = logging.getLogger(__name__)


class PositionProcessor:
    """Processes and enriches FnO positions with LTP and P&L calculations."""

    def __init__(self, api_service: GrowwAPIService):
        self.api = api_service

    def get_fno_positions(self) -> List[Dict[str, Any]]:
        """
        Fetch all open F&O (Futures & Options) positions with calculated values.
        Returns both NSE FnO and MCX Commodity positions.
        """
        # Get raw positions from API
        positions = self.api.get_positions()

        if not positions:
            return []

        # Separate NSE and MCX symbols for LTP fetching
        nse_symbols = []
        mcx_symbols = []
        symbol_to_exchange = {}

        for p in positions:
            symbol = p.get("trading_symbol")
            exchange = p.get("exchange", "NSE").upper()
            segment = str(p.get("segment", "")).upper()

            # Only process FnO and COMMODITY segments
            if segment not in ["FNO", "COMMODITY"]:
                continue

            if symbol:
                symbol_to_exchange[symbol] = exchange
                if exchange == "MCX":
                    mcx_symbols.append(symbol)
                else:
                    nse_symbols.append(symbol)

        # Fetch LTP for all symbols
        ltp_map = {}
        if nse_symbols:
            ltp_map.update(self.api.get_ltp_for_nse_fno(nse_symbols))
        if mcx_symbols:
            ltp_map.update(self.api.get_ltp_for_mcx(mcx_symbols))

        total_symbols = len(nse_symbols) + len(mcx_symbols)
        logger.info(f"Fetched LTP for {len(ltp_map)}/{total_symbols} FnO contracts")

        # Process each position
        fno_positions = []
        for p in positions:
            segment = str(p.get("segment", "")).upper()
            if segment not in ["FNO", "COMMODITY"]:
                continue

            # Extract basic values
            symbol = p.get("trading_symbol", "UNKNOWN")
            quantity = float(
                p.get("quantity", 0.0)
                or p.get("net_carry_forward_quantity", 0.0)
                or 0.0
            )

            # For FnO positions, net_price is the entry/average price
            entry_price = float(
                p.get("net_price", 0.0) or p.get("average_price", 0.0) or 0.0
            )

            # Get current LTP from bulk fetch
            ltp = float(ltp_map.get(symbol, 0.0))

            # Fallback strategy if LTP not available
            if ltp <= 0:
                if (
                    p.get("credit_quantity", 0) > 0
                    and p.get("credit_price", 0) != 0
                ):
                    ltp = float(p.get("credit_price"))
                elif (
                    p.get("debit_quantity", 0) > 0
                    and p.get("debit_price", 0) != 0
                ):
                    ltp = float(p.get("debit_price"))
                else:
                    ltp = entry_price

            # Calculate values
            total_value = quantity * ltp if ltp > 0 else 0.0
            entry_value = quantity * entry_price if entry_price > 0 else 0.0
            unrealized_pnl = total_value - entry_value

            # Calculate P&L percentage
            if entry_value > 0:
                unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100.0
            else:
                unrealized_pnl_pct = 0.0

            # Determine asset type
            asset_type = self._classify_asset_type(
                symbol, p.get("exchange", "NSE")
            )

            # Get expiry date
            expiry = self._get_expiry_date(p, symbol)

            processed = {
                "symbol": symbol,
                "type": asset_type,
                "quantity": quantity,
                "entry_price": round(entry_price, 2),
                "ltp": round(ltp, 2),
                "entry_value": round(entry_value, 2),
                "total_value": round(total_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                "expiry_date": str(expiry),
                "exchange": p.get("exchange", "NSE"),
                "segment": p.get("segment", "FNO"),
                "delta": float(p.get("delta", 0.0) or 0.0),
                "gamma": float(p.get("gamma", 0.0) or 0.0),
                "theta": float(p.get("theta", 0.0) or 0.0),
                "vega": float(p.get("vega", 0.0) or 0.0),
            }

            # Only add if we have meaningful data
            if quantity > 0 or total_value > 0 or entry_value > 0:
                fno_positions.append(processed)

        return fno_positions

    def _classify_asset_type(self, symbol: str, exchange: str) -> str:
        """Classify symbol as EQUITY or COMMODITY based on symbol and exchange."""
        symbol_upper = str(symbol).upper()
        exchange = str(exchange).upper()

        # MCX = Commodity
        if exchange == "MCX":
            return ASSET_TYPE_COMMODITY

        # Index symbols = Equity
        if any(x in symbol_upper for x in INDEX_KEYWORDS):
            return ASSET_TYPE_EQUITY

        # Commodity keywords = Commodity
        if any(x in symbol_upper for x in COMMODITY_KEYWORDS):
            return ASSET_TYPE_COMMODITY

        # Default = Equity
        return ASSET_TYPE_EQUITY

    def _get_expiry_date(self, position: Dict[str, Any], symbol: str) -> str:
        """Extract expiry date from position or parse from symbol."""
        expiry = position.get("expiry_date") or position.get("expiry") or position.get("expiryDate")

        if expiry and expiry != "N/A":
            try:
                # Format if it's a timestamp
                if isinstance(expiry, (int, float)):
                    from datetime import datetime
                    if expiry > 1000000000:
                        expiry = datetime.fromtimestamp(expiry / 1000).strftime("%Y-%m-%d")
                    else:
                        expiry = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
            except Exception:
                pass
        else:
            # Try to parse from symbol
            expiry = self._parse_expiry_from_symbol(symbol)

        return expiry or "N/A"

    def _parse_expiry_from_symbol(self, symbol: str) -> str:
        """
        Parse expiry date from FnO symbol.
        Example: EICHERMOT26SEP7900CE -> 2026 Sept 26
        """
        try:
            # Look for date pattern like 26SEP, 31DEC, etc.
            match = re.search(
                r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)",
                symbol.upper(),
            )
            if match:
                day = match.group(1)
                month_str = match.group(2)
                # Most likely current or next year
                from datetime import datetime
                current_year = datetime.now().year
                date_str = f"{day}{month_str}{current_year % 100:02d}"
                return format_expiry_date(date_str)
        except Exception:
            pass
        return "N/A"
