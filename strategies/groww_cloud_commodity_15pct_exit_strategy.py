"""
==========================================
15% Profit Exit Strategy - COMMODITY OPTIONS (MCX)
==========================================
Groww Cloud Strategy
- Processes COMMODITY options (MCX) only
- Places limit exit orders at 15% markup from entry price (premium)
- Full quantity exit for each long position, in the position's own product (NRML/MIS)
- Target rounded up to the contract's tick size (from Groww's instrument list)
- Short positions are skipped and reported
- Verbose logging of all actions and failures
"""

from decimal import ROUND_CEILING, Decimal

from growwapi import GrowwAPI
import time

# =====================
# STEP 1: Setup
# =====================
groww = GrowwAPI("api_key")


def tick_in_rupees(exchange, trading_symbol):
    """The contract's price step in rupees, from Groww's instrument list.

    The list's ``tick_size`` is in paise for MCX (GOLD 100.0 = Rs 1, NATURALGAS 10.0 = Rs 0.10)
    and in rupees for NSE (options 0.05). An order price off this grid is rejected.
    """
    row = groww.get_instrument_by_exchange_and_trading_symbol(exchange, trading_symbol)
    tick = Decimal(str(row["tick_size"]))
    # A blank cell arrives as NaN and would become a NaN price; zero would divide by zero.
    if not tick.is_finite() or tick <= 0:
        raise ValueError(f"unusable tick_size {row['tick_size']!r}")
    return tick / 100 if exchange == "MCX" else tick


def round_up_to_tick(price, tick):
    """``price`` raised onto the tick grid, so the target is never below +15%."""
    return float((Decimal(str(price)) / tick).to_integral_value(ROUND_CEILING) * tick)


EXCHANGE = groww.EXCHANGE_MCX

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

# Filter for MCX positions only: Groww marks them segment COMMODITY, exchange MCX
commodity_positions = [
    p for p in all_positions
    if isinstance(p, dict) and p.get("segment") == "COMMODITY" and p.get("exchange") == "MCX"
]

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
    product = pos.get("product") or groww.PRODUCT_NRML  # exit in the position's own product

    # Longs only: a SELL at +15% is the profit target of a bought contract. A short (negative
    # quantity) would need a BUY below its entry instead, which this strategy does not place.
    if quantity < 0:
        print(f"⚠️  {symbol}: Skipped (short position, quantity={quantity}; not handled here)")
        continue
    if entry_price <= 0 or quantity == 0:
        print(
            f"⚠️  {symbol}: Skipped (closed or no entry price: entry_price={entry_price}, quantity={quantity})"
        )
        continue

    try:
        tick = tick_in_rupees(EXCHANGE, symbol)
    except Exception as e:
        print(f"⚠️  {symbol}: Skipped (tick size not found in Groww's instrument list: {e})")
        continue

    # Calculate 15% markup target price
    target_price = round_up_to_tick(entry_price * 1.15, tick)

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
            exchange=EXCHANGE,
            segment=groww.SEGMENT_COMMODITY,
            product=product,
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
