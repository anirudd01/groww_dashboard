# Feed API Documentation - Real-Time Streaming

**Source:** https://groww.in/trade-api/docs/python-sdk/feed

---

## Overview

The Groww Feed provides real-time data streaming capabilities through the `GrowwFeed` client. Users can subscribe to live market data and receive updates either synchronously or asynchronously via callbacks.

## Key Features

### Connection & Initialization
To begin using the feed service, developers initialize the client with their API authentication token:

```python
from growwapi import GrowwFeed, GrowwAPI

groww = GrowwAPI(API_AUTH_TOKEN)
feed = GrowwFeed(groww)
```

### Subscription Modes

The SDK supports two operational patterns:

#### 1. **Asynchronous with Callbacks**
Define callback functions to trigger when data arrives, then call `feed.consume()` for blocking event processing

```python
def on_ltp_update(data):
    print(f"LTP Update: {data}")

feed.subscribe_ltp(["RELIANCE", "INFY"], on_ltp_update)
feed.consume()  # Blocking call - processes incoming data
```

#### 2. **Synchronous Polling**
Subscribe to data streams and manually poll using getter methods at intervals

```python
feed.subscribe_ltp(["RELIANCE"])
while True:
    ltp_data = feed.get_ltp()
    print(ltp_data)
    time.sleep(1)
```

---

## Live Data Streams

The API supports real-time subscriptions for:

### LTP (Last Traded Price) Updates
**Method:** `subscribe_ltp()` and `get_ltp()`

Real-time updates for the last price at which instruments were traded.

```python
feed.subscribe_ltp(
    exchange_trading_symbols=["NSE_RELIANCE", "NSE_INFY"]
)
```

### Index Value Data
**Method:** `subscribe_index_value()` and `get_index_value()`

Real-time index level updates for NIFTY, SENSEX, BANKNIFTY, etc.

```python
feed.subscribe_index_value(
    indices=["NIFTY", "BANKNIFTY"]
)
```

### Market Depth
**Method:** `subscribe_market_depth()` and `get_market_depth()`

Buy/sell order book information showing bids, asks, and quantities.

```python
feed.subscribe_market_depth(
    exchange_trading_symbols=["NSE_RELIANCE"]
)
```

**Capacity:** Up to 1,000 instruments can be subscribed simultaneously.

---

## Order & Position Tracking

Real-time notifications for:

### Derivative Order Updates
**Method:** `subscribe_fno_order_updates()`

Receive real-time notifications when FnO orders are executed, cancelled, or modified.

```python
def on_fno_order(data):
    print(f"FnO Order Update: {data}")

feed.subscribe_fno_order_updates(on_fno_order)
```

### Equity Order Updates
**Method:** `subscribe_equity_order_updates()`

Real-time updates for equity (CASH segment) order executions.

```python
def on_equity_order(data):
    print(f"Equity Order Update: {data}")

feed.subscribe_equity_order_updates(on_equity_order)
```

### Derivative Position Changes
**Method:** `subscribe_fno_position_updates()`

Real-time notifications when FnO positions are opened, modified, or closed.

```python
def on_position_change(data):
    print(f"Position Update: {data}")

feed.subscribe_fno_position_updates(on_position_change)
```

---

## Data Format

Responses are structured JSON objects containing:

**Standard Fields:**
- `timestamp` - Time in milliseconds
- `exchange` - Stock exchange (NSE, BSE, etc.)
- `segment` - Market segment (CASH, FNO, COMMODITY, CURRENCY)
- `feed_type` - Type of data (LTP, DEPTH, ORDER, etc.)
- `feed_key` - Unique identifier for routing

**Instrument-Specific Fields:**
- Prices (LTP, bid, ask, OHLC)
- Quantities (volume, bid size, ask size)
- Status (execution status, order status)
- Metadata (instrument ID, symbol)

**Example Response:**
```json
{
  "timestamp": 1694521200000,
  "exchange": "NSE",
  "segment": "CASH",
  "feed_type": "LTP",
  "feed_key": "NSE_RELIANCE",
  "ltp": 2850.50,
  "change": 25.50,
  "change_pct": 0.90,
  "volume": 5000000
}
```

---

## Metadata

Callback functions receive metadata containing:
- Exchange information
- Segment classification
- Feed type identifier
- Unique feed keys for filtering and routing data appropriately

---

## Use Cases

### 1. Live Dashboard Updates
```python
def update_dashboard(data):
    # Update UI with latest prices
    dashboard.update_price(data['feed_key'], data['ltp'])

feed.subscribe_ltp(symbols, update_dashboard)
feed.consume()
```

### 2. Position Monitoring
```python
def monitor_positions(data):
    if data['pnl_change'] > threshold:
        alert_user(data)

feed.subscribe_fno_position_updates(monitor_positions)
```

### 3. Order Tracking
```python
def track_order(data):
    if data['status'] == 'EXECUTED':
        log_execution(data)
        update_portfolio()

feed.subscribe_fno_order_updates(track_order)
```

---

## Performance Tips

1. **Subscribe strategically** - Only subscribe to instruments you need
2. **Use callbacks for efficiency** - Better than polling
3. **Handle disconnections** - Implement reconnection logic
4. **Filter subscriptions** - Process only relevant data types
5. **Limit concurrent subscriptions** - Max 1,000 instruments

---

## Summary

The Feed API provides:
- ✅ Real-time LTP streaming
- ✅ Index value updates
- ✅ Market depth data
- ✅ Order notifications
- ✅ Position change alerts
- ✅ Up to 1,000 simultaneous subscriptions
- ✅ Both async (callback) and sync (polling) modes

**Perfect for:** Live dashboards, real-time alerts, position monitoring, order tracking, market surveillance.
