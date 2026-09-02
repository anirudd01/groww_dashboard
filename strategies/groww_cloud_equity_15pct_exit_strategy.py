"""
==========================================
15% Profit Exit Strategy - EQUITY OPTIONS (NSE)
==========================================
Groww Cloud Strategy
- Processes EQUITY options (NSE) only
- Places limit exit orders at 15% markup from entry price (premium)
- Full quantity exit for each position
- Verbose logging of all actions and failures
"""

from growwapi import GrowwAPI
import time

# =====================
# STEP 1: Setup
# =====================
groww = GrowwAPI("api_key")

# =====================
# STEP 2: Fetch All Positions
# =====================

print("\n" + "=" * 70)
print("FETCHING EQUITY FNO POSITIONS")
print("=" * 70)

try:
    all_positions_response = groww.get_positions_for_user()
    print(f"✅ Successfully fetched positions")
except Exception as e:
    print(f"❌ Failed to fetch positions: {e}")
    exit(1)

# Handle dict response - extract positions list
all_positions = []
if isinstance(all_positions_response, dict):
    for key in ["data", "positions", "positionsList", "open_positions", "fno"]:
        if key in all_positions_response:
            positions_data = all_positions_response[key]
            if isinstance(positions_data, list):
                all_positions = positions_data
                break
            elif isinstance(positions_data, dict):
                all_positions = list(positions_data.values()) if positions_data else []
                break
else:
    all_positions = (
        all_positions_response if isinstance(all_positions_response, list) else []
    )

print(f"   Total positions extracted: {len(all_positions)}")

# Filter for FnO positions only
fno_positions = [
    p for p in all_positions if isinstance(p, dict) and p.get("segment") == "FNO"
]
print(f"✅ FnO positions found: {len(fno_positions)}")

# =====================
# STEP 3: Process EQUITY OPTIONS (NSE)
# =====================

print("\n" + "=" * 70)
print("PROCESSING EQUITY OPTIONS (NSE)")
print("=" * 70)

equity_failed = []
equity_processed = 0

for idx, pos in enumerate(fno_positions):
    symbol = pos.get("trading_symbol", "UNKNOWN")
    entry_price = float(pos.get("net_price", 0.0))
    quantity = int(pos.get("quantity", 0))

    # Skip if no valid data
    if entry_price <= 0 or quantity <= 0:
        print(
            f"⚠️  {symbol}: Skipped (invalid entry_price={entry_price} or quantity={quantity})"
        )
        continue

    # Calculate 15% markup target price
    target_price = round(entry_price * 1.15)

    print(f"\n📊 {symbol}")
    print(f"   Entry Price: ₹{entry_price:.2f}")
    print(f"   Quantity: {quantity}")
    print(f"   Target Price (15% markup): ₹{target_price:.2f}")

    try:
        time.sleep(1)
        order_id = groww.place_order(
            trading_symbol=symbol,
            quantity=quantity,
            price=target_price,
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_NRML,
            order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
        )
        print(
            f"   ✅ SELL order placed | Order ID: {order_id.get('groww_order_id', 'N/A')}"
        )
        equity_processed += 1
    except Exception as e:
        print(f"   ❌ FAILED to place order: {str(e)}")
        equity_failed.append(
            {
                "symbol": symbol,
                "entry_price": entry_price,
                "target_price": target_price,
                "quantity": quantity,
                "error": str(e),
            }
        )

# =====================
# STEP 4: Final Report
# =====================

print("\n" + "=" * 70)
print("EQUITY STRATEGY EXECUTION SUMMARY")
print("=" * 70)

print(f"\n✅ Total Equity Orders Placed: {equity_processed}")

if equity_failed:
    print(f"\n❌ Total Equity Orders Failed: {len(equity_failed)}")
    print(f"\n   📈 EQUITY FAILURES ({len(equity_failed)}):")
    for fail in equity_failed:
        print(f"      • {fail['symbol']}")
        print(
            f"        Entry: ₹{fail['entry_price']:.2f} | Target: ₹{fail['target_price']:.2f} | Qty: {fail['quantity']}"
        )
        print(f"        Error: {fail['error']}")
else:
    print(f"\n✅ All equity orders placed successfully! No failures.")

print("\n" + "=" * 70)
print("EQUITY STRATEGY EXECUTION COMPLETED")
print("=" * 70)
