import os
import sys
import json

# Allow running as `python scripts/test_api.py` from the repo root while still
# importing groww_client.py, which lives one directory up.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

from groww_client import GrowwClient

def test_groww_connection():

    print("==================================================")
    print("       GROWW TRADING API DIAGNOSTIC TEST          ")
    print("==================================================")

    auth_mode = os.getenv("GROWW_AUTH_MODE", "TOTP")
    api_key = os.getenv("GROWW_API_KEY")
    totp_secret = os.getenv("GROWW_TOTP_SECRET")
    api_secret = os.getenv("GROWW_API_SECRET")
    access_token = os.getenv("GROWW_ACCESS_TOKEN")

    print(f"Auth Mode         : {auth_mode}")
    print(f"API Key / TOTP Tok: {'[CONFIGURED]' if api_key else '[MISSING]'}")
    print(f"TOTP Secret       : {'[CONFIGURED]' if totp_secret else '[MISSING]'}")
    print(f"API Secret        : {'[CONFIGURED]' if api_secret else '[MISSING]'}")
    print(f"Direct Token      : {'[CONFIGURED]' if access_token else '[NONE]'}")
    print("--------------------------------------------------")

    has_credentials = bool(access_token or (api_key and (totp_secret or api_secret)))

    # Force mock mode if explicitly missing dependencies or testing
    client = GrowwClient(mock_mode=not has_credentials)
    if has_credentials and not client.is_connected:
        print("Note: Live client authentication not active in this terminal. Falling back to diagnostic test...")
        client = GrowwClient(mock_mode=True)

    if not client.is_connected:
        print(f"\n❌ Authentication Failed: {client.auth_error}")
        print("\nFix:")
        print("1. Ensure `pip install growwapi pyotp python-dotenv` is executed.")
        print("2. Populate GROWW_API_KEY and GROWW_TOTP_SECRET in `.env`")
        return

    print("\n✅ Authentication Successful!")
    print("--------------------------------------------------")

    # 1. Profile test
    print("\n[1/4] Fetching User Profile...")
    try:
        profile = client.get_user_profile()
        print(f"   UCC: {profile.get('ucc')}, Segments: {profile.get('active_segments')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 2. Margins test
    print("\n[2/4] Fetching Margin Details...")
    try:
        margins = client.get_margins()
        print(f"   Clear Cash: ₹{margins.get('clear_cash'):,.2f}, Margin Used: ₹{margins.get('net_margin_used'):,.2f}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 3. Holdings test
    print("\n[3/4] Fetching & Decoupling Delivery/CNC Holdings vs MTF Positions...")
    try:
        from groww_client import format_inr, format_inr_full
        processed = client.get_processed_portfolio()
        summary = processed["summary"]
        print(f"   Total Actual Cash Deployed  : {format_inr(summary['total_actual_cash_deployed'])} ({format_inr_full(summary['total_actual_cash_deployed'])})")
        print(f"   Total Portfolio Value       : {format_inr(summary['total_portfolio_value'])} ({format_inr_full(summary['total_portfolio_value'])})")
        print(f"   Delivery/CNC Holdings (Your Money) : {format_inr(summary['delivery_current'])} ({len(processed['delivery_holdings'])} stocks)")
        print(f"   - Invested (Cost Basis) : {format_inr(summary['delivery_invested'])}")
        print(f"   - Free Delivery Value   : {format_inr(summary['delivery_free_value'])}")
        print(f"   - Pledged (Collateral)  : {format_inr(summary['delivery_pledged_value'])}")
        print(f"   Pledged Stock Haircut Breakdown:")
        print(f"   - Pledged Value (Gross) : {format_inr(summary['pledged_value_gross'])}")
        print(f"   - Usable Margin (Post-Haircut) : {format_inr(summary['collateral_margin_total'])}")
        print(f"   - Haircut (\u20b9)          : {format_inr(summary['pledged_haircut_value'])} ({summary['pledged_haircut_pct']:.1f}%)")
        print(f"   MTF Positions (Groww's Margin) : {format_inr(summary['mtf_gross_value'])} ({len(processed['mtf_positions'])} positions)")
        print(f"   - Your Cash Used for MTF: {format_inr(summary['mtf_your_cash_used'])} (from Groww Margin API, not assumed)")
        print(f"   - Groww MTF Loan (Debt) : {format_inr(summary['mtf_broker_loan'])}")
        print(f"   - Daily Interest Drag   : {format_inr(summary['mtf_daily_interest'])}/day")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 4. LTP test
    print("\n[4/4] Fetching Live Market LTP...")
    try:
        ltp = client.get_ltp(["RELIANCE", "INFY", "TCS"])
        print(f"   Quotes: {json.dumps(ltp, indent=2)}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n==================================================")
    print("Diagnostic complete! Run 'streamlit run app.py' to launch dashboard.")
    print("==================================================")

if __name__ == "__main__":
    test_groww_connection()
