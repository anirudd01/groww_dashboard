"""
==========================================
15% Profit Exit Strategy - COMMODITY OPTIONS (MCX)
==========================================
Groww Cloud Strategy
- Processes COMMODITY options (MCX) only
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
print("FETCHING COMMODITY FNO POSITIONS")
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

# Filter for COMMODITY positions only
commodity_keywords = [
    "GOLD",
    "SILVER",
    "COPPER",
    "ZINC",
    "LEAD",
    "ALUMINUM",
    "NICKEL",
    "CRUDEOIL",
    "CRUDE",
]

commodity_positions = []
for p in all_positions:
    if isinstance(p, dict):
        symbol = p.get("trading_symbol", "").upper()
        if any(kw in symbol for kw in commodity_keywords):
            commodity_positions.append(p)

print(f"✅ Commodity positions found: {len(commodity_positions)}")

# =====================
# STEP 3: Process COMMODITY OPTIONS (MCX)
# =====================

print("\n" + "=" * 70)
print("PROCESSING COMMODITY OPTIONS (MCX)")
print("=" * 70)

commodity_failed = []
commodity_processed = 0

for idx, pos in enumerate(commodity_positions):
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
    target_price = round(entry_price * 1.15, 1)

    print(f"\n📊 {symbol}")
    print(f"   Entry Price: ₹{entry_price:.2f}")
    print(f"   Quantity: {quantity}")
    print(f"   Target Price (15% markup): ₹{target_price:.2f}")
    time.sleep(0.5)

    try:
        order_id = groww.place_order(
            trading_symbol=symbol,
            quantity=quantity,
            price=target_price,
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_MCX,
            segment=groww.SEGMENT_COMMODITY,
            product=groww.PRODUCT_NRML,
            order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
        )
        print(
            f"   ✅ SELL order placed | Order ID: {order_id.get('groww_order_id', 'N/A')}"
        )
        commodity_processed += 1
    except Exception as e:
        print(f"   ❌ FAILED to place order: {str(e)}")
        commodity_failed.append(
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
print("COMMODITY STRATEGY EXECUTION SUMMARY")
print("=" * 70)

print(f"\n✅ Total Commodity Orders Placed: {commodity_processed}")

if commodity_failed:
    print(f"\n❌ Total Commodity Orders Failed: {len(commodity_failed)}")
    print(f"\n   🏆 COMMODITY FAILURES ({len(commodity_failed)}):")
    for fail in commodity_failed:
        print(f"      • {fail['symbol']}")
        print(
            f"        Entry: ₹{fail['entry_price']:.2f} | Target: ₹{fail['target_price']:.2f} | Qty: {fail['quantity']}"
        )
        print(f"        Error: {fail['error']}")
else:
    print(f"\n✅ All commodity orders placed successfully! No failures.")

print("\n" + "=" * 70)
print("COMMODITY STRATEGY EXECUTION COMPLETED")
print("=" * 70)
