import os
import logging
from typing import Dict, Any, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Basic fallback if python-dotenv is not installed
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass

def format_inr(value: float, precision: int = 2) -> str:
    """
    Formats a number into Indian currency shorthand (Cr, L, K) or full standard format.
    Examples: 1453500 -> '₹14.54 L', 29700000 -> '₹2.97 Cr', 2296.1 -> '₹2.30 K'
    """
    if value is None:
        return "₹0.00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 10_000_000:
        return f"{sign}₹{abs_val / 10_000_000:.{precision}f} Cr"
    elif abs_val >= 100_000:
        return f"{sign}₹{abs_val / 100_000:.{precision}f} L"
    elif abs_val >= 1_000:
        return f"{sign}₹{abs_val / 1_000:.{precision}f} K"
    else:
        return f"{sign}₹{abs_val:.{precision}f}"

def format_inr_full(value: float) -> str:
    """Full Indian comma-separated format, e.g. ₹14,53,500.00"""
    if value is None:
        return "₹0.00"
    s = f"{abs(value):.2f}"
    parts = s.split(".")
    int_part, dec_part = parts[0], parts[1]
    if len(int_part) > 3:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted_int = ",".join(groups) + "," + last3
    else:
        formatted_int = int_part
    sign = "-" if value < 0 else ""
    return f"{sign}₹{formatted_int}.{dec_part}"

logger = logging.getLogger(__name__)

class GrowwClient:
    """
    Wrapper around official Groww Trading API Python SDK (growwapi).
    Supports TOTP flow, API Key flow, Direct Token, and Demo/Mock mode for testing.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        totp_secret: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        auth_mode: Optional[str] = None,
        mock_mode: bool = False
    ):
        self.api_key = api_key or os.getenv("GROWW_API_KEY")
        self.totp_secret = totp_secret or os.getenv("GROWW_TOTP_SECRET")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET")
        self.access_token = access_token or os.getenv("GROWW_ACCESS_TOKEN")
        self.auth_mode = (auth_mode or os.getenv("GROWW_AUTH_MODE", "TOTP")).upper()
        self.mock_mode = mock_mode
        self.client = None
        self.auth_error = None

        if not self.mock_mode:
            self._authenticate()

    def _authenticate(self):
        """Authenticates with Groww API based on selected flow."""
        try:
            # Check if growwapi is installed
            from growwapi import GrowwAPI

            # 1. Direct access token provided
            if self.access_token and self.access_token.strip():
                self.client = GrowwAPI(self.access_token.strip())
                logger.info("Authenticated using direct access token.")
                return

            # 2. TOTP flow (Recommended)
            if self.auth_mode == "TOTP":
                if not self.api_key or not self.totp_secret:
                    self.auth_error = "GROWW_API_KEY (TOTP Token) or GROWW_TOTP_SECRET is missing."
                    return
                
                import pyotp
                totp_gen = pyotp.TOTP(self.totp_secret.replace(" ", "").strip())
                current_totp = totp_gen.now()
                token = GrowwAPI.get_access_token(api_key=self.api_key.strip(), totp=current_totp)
                self.access_token = token
                self.client = GrowwAPI(token)
                logger.info("Authenticated using TOTP flow.")
                return

            # 3. API Key and Secret flow
            if self.auth_mode in ("API_KEY", "SECRET"):
                if not self.api_key or not self.api_secret:
                    self.auth_error = "GROWW_API_KEY or GROWW_API_SECRET is missing."
                    return
                
                token = GrowwAPI.get_access_token(api_key=self.api_key.strip(), secret=self.api_secret.strip())
                self.access_token = token
                self.client = GrowwAPI(token)
                logger.info("Authenticated using API Key & Secret flow.")
                return

            self.auth_error = f"Unsupported auth mode: {self.auth_mode}"

        except ImportError as e:
            self.auth_error = f"Missing library: {e}. Run 'pip install growwapi pyotp'"
        except Exception as e:
            self.auth_error = f"Authentication failed: {str(e)}"
            logger.error("Authentication error: %s", e)

    @property
    def is_connected(self) -> bool:
        return self.client is not None or self.mock_mode

    def get_user_profile(self) -> Dict[str, Any]:
        """Fetch user profile details."""
        if self.mock_mode:
            return {
                "vendor_user_id": "demo-user-123",
                "ucc": "DEMO924189",
                "nse_enabled": True,
                "bse_enabled": True,
                "ddpi_enabled": True,
                "active_segments": ["CASH", "FNO"]
            }
        if not self.client:
            raise RuntimeError(self.auth_error or "Client not authenticated")
        return self.client.get_user_profile()

    def get_margins(self) -> Dict[str, Any]:
        """Fetch available margin and fund balance."""
        if self.mock_mode:
            return {
                "clear_cash": 125000.50,
                "net_margin_used": 285400.00,
                "brokerage_and_charges": 145.20,
                "collateral_used": 50000.00,
                "collateral_available": 140000.00,
                "adhoc_margin": 0.0,
                "fno_margin_details": {
                    "net_fno_margin_used": 0.0
                },
                "equity_margin_details": {
                    "net_equity_margin_used": 285400.00,
                    "cnc_margin_used": 0.0,
                    "mis_margin_used": 0.0,
                    "cnc_balance_available": 125000.50,
                    "mis_balance_available": 125000.50
                }
            }
        if not self.client:
            raise RuntimeError(self.auth_error or "Client not authenticated")
        return self.client.get_available_margin_details()

    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch long term delivery holdings for user."""
        if self.mock_mode:
            return [
                {
                    "isin": "INE002A01018",
                    "trading_symbol": "RELIANCE",
                    "quantity": 50.0,
                    "average_price": 2850.00,
                    "pledge_quantity": 30.0,           # Pledged as collateral for margin
                    "demat_locked_quantity": 0.0,
                    "groww_locked_quantity": 0.0,
                    "repledge_quantity": 0.0,
                    "t1_quantity": 0.0,
                    "demat_free_quantity": 20.0,        # Free delivery
                    "corporate_action_additional_quantity": 0,
                    "active_demat_transfer_quantity": 0
                },
                {
                    "isin": "INE009A01021",
                    "trading_symbol": "INFY",
                    "quantity": 100.0,
                    "average_price": 1720.00,
                    "pledge_quantity": 0.0,
                    "demat_locked_quantity": 0.0,
                    "groww_locked_quantity": 0.0,
                    "repledge_quantity": 0.0,
                    "t1_quantity": 0.0,
                    "demat_free_quantity": 100.0,       # 100% Free delivery
                    "corporate_action_additional_quantity": 0,
                    "active_demat_transfer_quantity": 0
                },
                {
                    "isin": "INE040A01034",
                    "trading_symbol": "HDFCBANK",
                    "quantity": 150.0,
                    "average_price": 1580.00,
                    "pledge_quantity": 100.0,          # Pledged as collateral for margin
                    "demat_locked_quantity": 0.0,
                    "groww_locked_quantity": 0.0,
                    "repledge_quantity": 0.0,
                    "t1_quantity": 0.0,
                    "demat_free_quantity": 50.0,        # Free delivery
                    "corporate_action_additional_quantity": 0,
                    "active_demat_transfer_quantity": 0
                },
                {
                    "isin": "INE467B01029",
                    "trading_symbol": "TCS",
                    "quantity": 40.0,
                    "average_price": 4100.00,
                    "pledge_quantity": 0.0,
                    "demat_locked_quantity": 0.0,
                    "groww_locked_quantity": 0.0,
                    "repledge_quantity": 0.0,
                    "t1_quantity": 10.0,                # T1 Cash Delivery
                    "demat_free_quantity": 30.0,        # Free delivery
                    "corporate_action_additional_quantity": 0,
                    "active_demat_transfer_quantity": 0
                }
            ]
        if not self.client:
            raise RuntimeError(self.auth_error or "Client not authenticated")
        
        resp = self.client.get_holdings_for_user()
        if isinstance(resp, dict):
            return resp.get("holdings", [])
        return resp if isinstance(resp, list) else []

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open & carry-forward MTF/margin positions (bought with Groww's margin funding)."""
        if self.mock_mode:
            return [
                {
                    "trading_symbol": "TATAMOTORS",
                    "segment": "CASH",
                    "exchange": "NSE",
                    "symbol_isin": "INE155A01022",
                    "quantity": 300,
                    "product": "MTF",
                    "net_carry_forward_quantity": 300,
                    "net_price": 980.00,
                    "net_carry_forward_price": 980.00,
                    "realised_pnl": 0.0
                },
                {
                    "trading_symbol": "SBIN",
                    "segment": "CASH",
                    "exchange": "NSE",
                    "symbol_isin": "INE062A01020",
                    "quantity": 500,
                    "product": "MTF",
                    "net_carry_forward_quantity": 500,
                    "net_price": 790.00,
                    "net_carry_forward_price": 790.00,
                    "realised_pnl": 0.0
                }
            ]
        if not self.client:
            raise RuntimeError(self.auth_error or "Client not authenticated")
        
        try:
            from growwapi import GrowwAPI
            resp = self.client.get_positions_for_user(segment=GrowwAPI.SEGMENT_CASH)
        except Exception:
            resp = self.client.get_positions_for_user()

        if isinstance(resp, dict):
            positions = resp.get("positions", [])
        elif isinstance(resp, list):
            positions = resp
        else:
            positions = []

        # Defensive filter: drop any non-equity (FNO) entries that may have slipped through
        # if the SDK ignored the segment filter above - FNO notional values would otherwise
        # massively inflate the equity portfolio totals.
        return [p for p in positions if str(p.get("segment", "CASH")).upper() == "CASH"]

    def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch LTP for a list of trading symbols.
        Groww SDK takes exchange_trading_symbols as single string or tuple of strings e.g. ("NSE_RELIANCE", "NSE_INFY")
        """
        if self.mock_mode:
            mock_prices = {
                "RELIANCE": 3020.50,
                "INFY": 1890.00,
                "HDFCBANK": 1645.20,
                "TATAMOTORS": 1055.00,
                "SBIN": 845.50,
                "TCS": 4320.00
            }
            return {sym: mock_prices.get(sym, 1000.00) for sym in symbols}

        if not self.client:
            raise RuntimeError(self.auth_error or "Client not authenticated")

        if not symbols:
            return {}

        from growwapi import GrowwAPI
        # Format symbols as NSE_<SYMBOL>
        formatted_symbols = tuple(f"NSE_{s.strip()}" if not s.startswith("NSE_") else s.strip() for s in symbols)
        
        try:
            # get_ltp supports up to 50 instruments per batch
            result = {}
            for i in range(0, len(formatted_symbols), 50):
                batch = formatted_symbols[i:i+50]
                resp = self.client.get_ltp(
                    segment=GrowwAPI.SEGMENT_CASH,
                    exchange_trading_symbols=batch if len(batch) > 1 else batch[0]
                )
                if isinstance(resp, dict):
                    for k, v in resp.items():
                        clean_sym = k.replace("NSE_", "").replace("BSE_", "")
                        result[clean_sym] = float(v)
            return result
        except Exception as e:
            logger.warning("Error fetching live LTP: %s", e)
            return {}

    def get_processed_portfolio(self) -> Dict[str, Any]:
        """
        Accurately structures portfolio into:
        1. Actual Delivery Holdings (100% Owned by User with their Cash Capital):
           - Free Demat Delivery (Unencumbered)
           - Collateral Pledged Delivery (Pledged to acquire margin limits)
        2. MTF (Pay Later) Positions:
           - Leveraged open positions financed via broker loan
           - Actual user margin blocked vs Groww loan outstanding
           - Daily and Annualized interest liability (~16.5% p.a.)
        """
        holdings_raw = self.get_holdings()
        positions_raw = self.get_positions()
        margins_raw = self.get_margins()

        # Gather all unique symbols for batch LTP quote
        all_symbols = list({
            h.get("trading_symbol") for h in holdings_raw if h.get("trading_symbol")
        }.union({
            p.get("trading_symbol") for p in positions_raw if p.get("trading_symbol")
        }))

        ltp_map = self.get_ltp(all_symbols)

        ANNUAL_INTEREST_RATE = 0.165  # Groww MTF interest ~16.5% p.a.
        DAILY_INTEREST_RATE = ANNUAL_INTEREST_RATE / 365.0

        # -------------------------------------------------------------
        # 1. PROCESS ACTUAL DELIVERY HOLDINGS (USER'S CASH ASSETS)
        # -------------------------------------------------------------
        delivery_holdings_items = []
        delivery_invested_total = 0.0
        delivery_current_total = 0.0
        delivery_free_value_total = 0.0
        delivery_pledged_value_total = 0.0

        for h in holdings_raw:
            sym = h.get("trading_symbol", "UNKNOWN")
            qty = float(h.get("quantity", 0.0))
            avg_price = float(h.get("average_price", 0.0))
            ltp = float(ltp_map.get(sym, avg_price))

            free_qty = float(h.get("demat_free_quantity", 0.0))
            t1_qty = float(h.get("t1_quantity", 0.0))
            pledge_qty = float(h.get("pledge_quantity", 0.0))
            repledge_qty = float(h.get("repledge_quantity", 0.0))
            locked_qty = float(h.get("demat_locked_quantity", 0.0))

            total_pledged_qty = pledge_qty + repledge_qty
            total_free_qty = free_qty + t1_qty
            if total_free_qty + total_pledged_qty < qty and total_pledged_qty == 0:
                # If broker didn't split free vs locked explicitly
                total_free_qty = qty

            invested = qty * avg_price
            current_val = qty * ltp
            pnl = current_val - invested
            pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0

            free_val = total_free_qty * ltp
            pledged_val = total_pledged_qty * ltp

            delivery_invested_total += invested
            delivery_current_total += current_val
            delivery_free_value_total += free_val
            delivery_pledged_value_total += pledged_val

            delivery_holdings_items.append({
                "symbol": sym,
                "isin": h.get("isin", ""),
                "total_quantity": qty,
                "free_quantity": total_free_qty,
                "pledged_quantity": total_pledged_qty,
                "avg_price": avg_price,
                "ltp": ltp,
                "invested_value": round(invested, 2),
                "current_value": round(current_val, 2),
                "free_current_value": round(free_val, 2),
                "pledged_current_value": round(pledged_val, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "pledge_status": "Pledged for Collateral" if total_pledged_qty > 0 else "Free Unencumbered"
            })

        # -------------------------------------------------------------
        # 2. PROCESS MTF (PAY LATER) POSITIONS (LEVERAGED EXPOSURE)
        #    Positions = shares bought using Groww's margin (get_positions_for_user).
        #    Cost basis / current value come straight from real quantity x price data,
        #    no assumed leverage ratio is applied here.
        # -------------------------------------------------------------
        mtf_items = []
        mtf_gross_value_total = 0.0
        mtf_cost_basis_total = 0.0

        for pos in positions_raw:
            product = str(pos.get("product", "")).upper()
            # MIS is intraday (squared off same day) - not a real overnight MTF holding
            if product == "MIS":
                continue

            pos_qty = float(pos.get("quantity", 0.0) or pos.get("net_carry_forward_quantity", 0.0))
            if pos_qty <= 0:
                continue

            sym = pos.get("trading_symbol", "UNKNOWN")
            buy_price = float(pos.get("net_price", 0.0) or pos.get("net_carry_forward_price", 0.0) or pos.get("credit_price", 0.0))
            ltp = float(ltp_map.get(sym, buy_price))

            pos_cost = pos_qty * buy_price
            pos_current = pos_qty * ltp
            pos_pnl = pos_current - pos_cost
            pos_pnl_pct = (pos_pnl / pos_cost * 100.0) if pos_cost > 0 else 0.0

            mtf_gross_value_total += pos_current
            mtf_cost_basis_total += pos_cost

            mtf_items.append({
                "symbol": sym,
                "isin": pos.get("symbol_isin", ""),
                "mtf_quantity": pos_qty,
                "buy_price": buy_price,
                "ltp": ltp,
                "total_position_value": round(pos_current, 2),
                "total_cost_basis": round(pos_cost, 2),
                "unrealized_pnl": round(pos_pnl, 2),
                "unrealized_pnl_pct": round(pos_pnl_pct, 2),
                "product": product or "MTF"
            })

        # -------------------------------------------------------------
        # Derive the REAL "your cash used for MTF" figure from Groww's margin API
        # instead of assuming a fixed leverage/margin percentage. net_margin_used
        # covers both equity + F&O margin, so we subtract the F&O portion to
        # isolate the cash you (not Groww) put in for MTF positions.
        # -------------------------------------------------------------
        net_margin_used = float(margins_raw.get("net_margin_used", 0.0))
        clear_cash = float(margins_raw.get("clear_cash", 0.0))
        collateral_available = float(margins_raw.get("collateral_available", 0.0))
        collateral_used = float(margins_raw.get("collateral_used", 0.0))

        fno_margin_details = margins_raw.get("fno_margin_details", {}) or {}
        net_fno_margin_used = float(fno_margin_details.get("net_fno_margin_used", 0.0))

        equity_margin_details = margins_raw.get("equity_margin_details", {}) or {}
        raw_equity_margin_used = float(equity_margin_details.get("net_equity_margin_used", 0.0))

        your_mtf_cash_used = abs(raw_equity_margin_used) if raw_equity_margin_used else max(0.0, net_margin_used - net_fno_margin_used)
        # Can never exceed the actual MTF cost basis - clamp to keep the numbers sane
        your_mtf_cash_used = min(your_mtf_cash_used, mtf_cost_basis_total) if mtf_cost_basis_total > 0 else 0.0

        mtf_broker_loan_total = max(0.0, mtf_cost_basis_total - your_mtf_cash_used)
        mtf_daily_interest_total = mtf_broker_loan_total * DAILY_INTEREST_RATE

        # Distribute the real aggregate cash-used proportionally across positions - for
        # display only, since Groww does not expose a per-stock MTF margin breakdown.
        for item in mtf_items:
            weight = (item["total_cost_basis"] / mtf_cost_basis_total) if mtf_cost_basis_total > 0 else 0.0
            item_user_cash = round(your_mtf_cash_used * weight, 2)
            item_broker_loan = round(item["total_cost_basis"] - item_user_cash, 2)
            item["est_your_cash_used"] = item_user_cash
            item["est_broker_funded_loan"] = item_broker_loan
            item["est_daily_interest_drag"] = round(item_broker_loan * DAILY_INTEREST_RATE, 2)
            item["est_annual_interest_drag"] = round(item_broker_loan * ANNUAL_INTEREST_RATE, 2)

        # -------------------------------------------------------------
        # Derive the REAL haircut (₹) applied by the exchange/Groww on your pledged
        # stocks. Groww doesn't expose a per-stock haircut %, but collateral_used +
        # collateral_available IS the total usable margin AFTER haircut, so:
        #   haircut (₹) = gross pledged stock value - post-haircut usable collateral
        # This is a real derived figure, not a summed/assumed percentage.
        # -------------------------------------------------------------
        total_collateral_margin = collateral_used + collateral_available
        pledged_haircut_value = max(0.0, delivery_pledged_value_total - total_collateral_margin) if delivery_pledged_value_total > 0 else 0.0
        pledged_haircut_pct = round((pledged_haircut_value / delivery_pledged_value_total * 100.0), 2) if delivery_pledged_value_total > 0 else 0.0

        # Distribute the real aggregate haircut proportionally across pledged stocks - for
        # display only, since Groww does not expose a per-stock haircut %.
        for item in delivery_holdings_items:
            if item["pledged_current_value"] > 0 and delivery_pledged_value_total > 0:
                weight = item["pledged_current_value"] / delivery_pledged_value_total
                item["est_haircut_value"] = round(pledged_haircut_value * weight, 2)
                item["est_collateral_value"] = round(item["pledged_current_value"] - item["est_haircut_value"], 2)
            else:
                item["est_haircut_value"] = 0.0
                item["est_collateral_value"] = 0.0

        # -------------------------------------------------------------
        # 3. EXECUTIVE SUMMARY METRICS
        # -------------------------------------------------------------
        # get_holdings_for_user() already mixes real delivery/CNC AND MTF/intraday
        # positions in one list (per Groww glossary), so delivery_current_total is
        # the true total portfolio value - adding mtf_gross_value_total on top would
        # double-count MTF stocks that already appear in holdings.
        total_portfolio_value = delivery_current_total
        total_pnl = delivery_current_total - delivery_invested_total
        # Total Actual Cash Deployed = capital currently tied up as pledged collateral
        # + cash still free in your wallet (clear_cash)
        total_actual_cash_deployed = delivery_pledged_value_total + clear_cash

        summary = {
            # Executive Level
            "total_actual_cash_deployed": round(total_actual_cash_deployed, 2),
            "total_portfolio_value": round(total_portfolio_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / delivery_invested_total * 100.0) if delivery_invested_total > 0 else 0.0, 2),

            # Pledged Stocks & Haircut (get_holdings_for_user pledge_quantity + margin API collateral)
            "pledged_value_gross": round(delivery_pledged_value_total, 2),
            "collateral_margin_total": round(total_collateral_margin, 2),
            "pledged_haircut_value": round(pledged_haircut_value, 2),
            "pledged_haircut_pct": pledged_haircut_pct,

            # Delivery / CNC Holdings (100% your own cash - get_holdings_for_user)
            "delivery_invested": round(delivery_invested_total, 2),
            "delivery_current": round(delivery_current_total, 2),
            "delivery_free_value": round(delivery_free_value_total, 2),
            "delivery_pledged_value": round(delivery_pledged_value_total, 2),
            "delivery_pnl": round(delivery_current_total - delivery_invested_total, 2),
            "delivery_pnl_pct": round(((delivery_current_total - delivery_invested_total) / delivery_invested_total * 100.0) if delivery_invested_total > 0 else 0.0, 2),

            # MTF Positions (get_positions_for_user) - bought using Groww's margin
            "mtf_cost_basis": round(mtf_cost_basis_total, 2),
            "mtf_gross_value": round(mtf_gross_value_total, 2),
            "mtf_your_cash_used": round(your_mtf_cash_used, 2),
            "mtf_broker_loan": round(mtf_broker_loan_total, 2),
            "mtf_pnl": round(mtf_gross_value_total - mtf_cost_basis_total, 2),
            "mtf_pnl_pct": round(((mtf_gross_value_total - mtf_cost_basis_total) / mtf_cost_basis_total * 100.0) if mtf_cost_basis_total > 0 else 0.0, 2),
            "mtf_daily_interest": round(mtf_daily_interest_total, 2),
            "mtf_monthly_interest": round(mtf_daily_interest_total * 30, 2),
            "mtf_annual_interest": round(mtf_daily_interest_total * 365, 2),

            # Groww Wallet & Margins
            "clear_cash": clear_cash,
            "net_margin_used": net_margin_used,
            "collateral_available": collateral_available,
            "collateral_used": collateral_used
        }

        return {
            "summary": summary,
            "delivery_holdings": delivery_holdings_items,
            "mtf_positions": mtf_items,
            "raw_holdings": holdings_raw,
            "raw_positions": positions_raw,
            "raw_margins": margins_raw
        }
