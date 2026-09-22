# Feed API Documentation - Real-Time Streaming

**Source:** https://groww.in/trade-api/docs/python-sdk/feed

> Everything from here to the `---` before "Overview" is **observed behaviour**,
> not documentation. The rest of this file is Groww's own docs.
> See [Websocket behaviour in practice](#websocket-behaviour-in-practice-observed)
> before debugging anything socket-related — the docs describe none of it.

---

## Websocket behaviour in practice (observed)

*Verified 2026-09-21, NSE session open, `growwapi` 1.5.0 / `nats-py` 2.15.0.*

**The feed works.** The total failure recorded on 2026-09-18 — gateway accepts
`CONNECT`, then ignores all client input forever — is fixed on Groww's side.
Live LTP ticks arrive for all 50 Nifty constituents. The old diagnosis is kept
in `docs/SECTOR_HEATMAP.md` as history only.

It is, however, **not a drop-in match for a normal websocket**. Four things
differ from Dhan's socket, and code that assumes "a websocket is a websocket"
gets each of them wrong. The adapter in
[`market/providers/groww.py`](../../market/providers/groww.py) handles all four.

### 1. The connect is slow, retries internally, and logs nothing useful

`GrowwFeed(...)` does the whole handshake **in its constructor**: it mints a
socket token over REST, then opens the NATS-over-WebSocket connection. Groww's
gateway frequently lets that handshake time out. `nats-py` defaults to
`connect_timeout=2` and retries roughly every 4.2 s, so the constructor simply
blocks until an attempt lands.

Measured constructor times in a single session:

| Attempt | Wall time | Internal retries |
|---|---|---|
| best case | 1.3 s | 0 |
| typical | 5–10 s | 1–2 |
| bad | 43 s | 10 |
| worst seen | 145 s | 20 |

Each retry surfaces as this log line, and **only** this line:

```
ERROR growwapi.groww.nats_client: Error:
```

The message is empty because the SDK's `error_cb` does `logger.error("Error: %s", e)`
and the exception is a bare `TimeoutError()`, whose `str()` is `""`. Recovering
the type takes a monkeypatch of `NatsClient._on_error_cb`. **A run of empty
`Error:` lines followed by `Socket connection successful` is normal Groww
behaviour, not a fault** — this is the "websocket throws an error, then starts
working" symptom.

Raising `connect_timeout` does **not** fix it: a connect that is going to
succeed succeeds in ~1.3 s, and one that is going to fail stalls past any
timeout. Latency is not the variable; the gateway's willingness to authorise is.

What does correlate is **recent connection churn on the same account** — the
more connections opened in a short window, the more retries the next one takes.
So the practical rule is *do not churn connections*, which is why `close()`
below matters.

### 2. `get_ltp()` is a buffer, not a stream

The SDK stores the last message per subscribed topic and `get_ltp()` returns
that whole buffer on every call. It never empties and never errors. A feed that
died an hour ago still answers, with an hour-old price.

So **"got a price back" does not mean "the feed is alive."** `GrowwFeedHandle`
compares each entry's `tsInMillis` against the previous read and reports only
what actually moved. Without that the service would refresh its "last tick"
clock on every drain and the board would read `LIVE (websocket)` forever with
frozen prices, never falling back to REST.

Dhan needs no such treatment: its handle is fed by a real push socket whose
thread dies when the connection does.

### 3. Nothing reports a dropped connection

No SDK call raises, returns an error, or flips a flag when the socket drops.
The only honest signal is the NATS client underneath:

```python
socket = feed._nats_client._socket      # nats.aio.client.Client
socket.is_connected / is_reconnecting / is_closed
```

All private. `is_alive` reads them defensively and treats `is_reconnecting` as
alive, because `nats-py` recovers on its own and forcing a fresh Groww
handshake is the expensive part (see the table above).

### 4. There is no `close()`, and connections leak

`GrowwFeed` has **no teardown method at all**, and it memoises every NATS
client it builds in a class-level dict:

```python
GrowwFeed._nats_clients: dict[tuple[str, str], NatsClient]
```

keyed by `(socket_jwt, nkey_seed)` — both **re-minted per instance**, so the
cache never hits and every `GrowwFeed(...)` adds one more entry. Nothing is
ever removed. Each stranded entry is a live websocket, a daemon thread and a
running event loop that survive for the life of the process, and (per §1) make
the next connect slower.

`GrowwFeedHandle.close()` therefore closes the socket on its own loop, stops
the loop so the SDK's `run_forever` thread can exit, and pops the cache entry.
It deliberately **skips** `unsubscribe_ltp` first: that queues one
fire-and-forget coroutine per instrument onto a loop that is about to stop, so
all 50 get destroyed pending and flood the log with
`Task was destroyed but it is pending!`. Closing the connection discards the
subscriptions anyway.

### Timings worth knowing

- **Subscribe is asynchronous.** `subscribe_ltp()` only queues the SUBs onto
  the event loop and returns in ~0 ms. Ticks then trickle in: ~5/50 symbols
  priced at +0.5 s, ~40/50 at +5 s, 49/50 at +11 s. A partially-priced board in
  the first few seconds is expected.
- **REST first, socket second, by design.** The dashboard polls batched REST
  snapshots while the handshake runs and switches to `LIVE (websocket)` on its
  own. End to end that is typically 10–20 s from launch.

### What the LTP feed does *not* carry

The `stockLivePrice` proto has `open`/`high`/`low`/`close`/`volume` fields, but
on the LTP topic **they are always `0.0`** — only `ltp` and `tsInMillis` are
populated. So `day_bars()` and `previous_closes()` stay unimplemented for Groww
and both come from REST. Do not read `close` here as a previous close; it is
zero, not yesterday's price.

### Diagnosing it

```bash
python scripts/check_heatmap_universe.py --provider groww --seconds 40
```

Exits `OK` only if the **websocket** delivered ticks, and says so explicitly
when the prices came from REST instead.

| Symptom | Meaning |
|---|---|
| Repeated empty `ERROR ... nats_client: Error:` then success | Normal. Gateway retries. Wait. |
| `Groww socket handshake completed in 43.1s` | Normal but slow; check for leaked connections. |
| Board sits on `REST snapshots` past ~60 s | Handshake genuinely not landing. |
| `Task was destroyed but it is pending!` on teardown | An unsubscribe was queued before a loop stop. |
| `Extra data: line 1 column 5` from REST calls | Groww returned a non-JSON body — REST throttling. Back off. |
| `Authentication failed: The requested resource was not found` | Auth endpoint throttled by repeated re-auth. Wait it out. |

The last two are **REST**, not socket, and are easy to trigger by restarting
the dashboard repeatedly while debugging. They clear on their own.

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
