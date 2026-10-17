# Groww live feed (websocket)

**Source:** https://groww.in/trade-api/docs/python-sdk/feed

> The first half of this file is **observed behaviour**, not documentation. The second half
> describes the SDK's feed interface as its source code defines it (Groww's own feed page is wrong
> in several places).
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
python scripts/debug/check_heatmap_universe.py --provider groww --seconds 40
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

## The SDK's feed interface (read from the source, `growwapi` 1.5.0, 2026-10-17)

This replaces a copy of Groww's feed page that used to sit here. Its examples could not run
(`subscribe_ltp(["RELIANCE", "INFY"])` raises `TypeError`), and its sample response (`feed_type`, `change`,
`change_pct`) and use cases (`data['pnl_change']`) matched nothing the SDK produces.

### Connecting

```python
from growwapi import GrowwAPI, GrowwFeed

groww = GrowwAPI(access_token)
feed = GrowwFeed(groww)  # mints a socket token over REST and completes the NATS handshake here
```

### Market data: instruments are dicts, never symbol strings

```python
instruments = [{"exchange": "NSE", "segment": "CASH", "exchange_token": "2885"}]   # RELIANCE
feed.subscribe_ltp(instruments, on_data_received=None)      # also: subscribe_market_depth, subscribe_index_value
feed.get_ltp()            # {"NSE": {"CASH": {"2885": {"tsInMillis": ..., "ltp": ..., ...}}}}
feed.unsubscribe_ltp(instruments)
```

- `instrument_list` must be a non-empty list of dicts with `exchange`, `segment` and `exchange_token`
  (from the instrument list, [GROWW_API_INSTRUMENTS.md](GROWW_API_INSTRUMENTS.md)). Anything else raises
  `TypeError` or `ValueError`.
- **`subscribe_ltp` and `subscribe_market_depth` accept segment `CASH` or `FNO` only.** Any other segment,
  MCX's `COMMODITY` included, raises `ValueError`. **There is no MCX stream** in the SDK.
- **Indices use `subscribe_index_value`**, a separate topic, with exchange `NSE` or `BSE`; read them with
  `get_index_value()`.
- `get_ltp()`, `get_market_depth()` and `get_index_value()` return the last message per topic, nested
  `{exchange: {segment: {exchange_token: data}}}`.
  - LTP data: `tsInMillis`, `ltp`, `open`, `high`, `low`, `close`, `volume`, `value`, `bidQty`,
    `offerQty`, `avgPrice`, `openInterest`, `highPriceRange`, `lowPriceRange`, `highTradeRange`,
    `lowTradeRange`. Only `ltp` and `tsInMillis` are filled on this topic (see above).
  - Depth data: `tsInMillis`, `buyBook`, `sellBook`.
  - Index data: `tsInMillis`, `value`.
- `on_data_received` is called with the topic's metadata (exchange, segment, feed type, key), not the
  data; read the data with the getters. `feed.consume()` blocks and processes messages.
- Groww's docs give a limit of 1,000 subscriptions.

### Order and position updates

```python
feed.subscribe_fno_order_updates(callback)      # F&O orders
feed.subscribe_equity_order_updates(callback)   # CASH orders
feed.subscribe_fno_position_updates(callback)   # F&O positions; there is no equity position stream
feed.get_fno_order_update(); feed.get_equity_order_update(); feed.get_fno_position_update()
```

- Order update fields: `qty`, `price`, `triggerPrice`, `filledQty`, `remainingQty`, `avgFillPrice`,
  `growwOrderId`, `exchangeOrderId`, `orderStatus`, `duration`, `exchange`, `segment`, `product`,
  `orderType` (`MARKET`/`LIMIT`, translated from `MKT`/`L`), `transactionType` (`BUY`/`SELL`, from `B`/`S`),
  `remark`, `contractId`.
- Position update: `{"symbolIsin": ..., "exchangePosition": {"NSE": {...}, "BSE": {...}}}`.
- Whether MCX orders arrive on the F&O order stream is not documented; untested.

None of the order or position streams is used by this repo yet.
