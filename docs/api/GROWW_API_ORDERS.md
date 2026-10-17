# Groww orders, smart orders, margins and reports

**Sources:** https://groww.in/trade-api/docs/python-sdk/orders, `/smart-orders`, `/margin`, the SDK source
(`growwapi` 1.5.0), and a read-only live run on 2026-10-17 on the **free API plan**. Nothing was placed,
modified or cancelled.

## What the free plan allows (tested 2026-10-17)

Everything on this page answered on the free plan. Only market data (quotes, prices, candles, option chain,
Greeks) is refused; see [GROWW_API_LIVE_DATA.md](GROWW_API_LIVE_DATA.md).

| Call | Free plan | Notes |
|---|---|---|
| `get_access_token` (TOTP) | ✅ 1.7 s | Rate limit 150 tokens per 24 h |
| `get_user_profile` | ✅ | `active_segments` e.g. `["CASH", "FNO", "COMMODITY"]` |
| `get_available_margin_details` | ✅ | Signs and units: [GROWW_API_PORTFOLIO.md](GROWW_API_PORTFOLIO.md#margins) |
| `get_order_list(segment=...)` | ✅ | Today's orders only, see below |
| `get_smart_order_list(GTT/OCO, CASH/FNO)` | ✅ | |
| `get_order_margin_details` | ✅ | Margin and charges for an order before placing it |
| `place_order`, `modify_order`, `cancel_order` | not tried | |
| `create_smart_order` (GTT, OCO) | not tried | |

## Orders

- **`get_order_list` covers today only.** Groww's docs describe it as orders "placed during the day". On
  Saturday 2026-10-17 it returned nothing for every segment although Friday's MCX trades were still in the
  positions.
- **SDK quirk:** `get_order_list(page, page_size, segment)` never sends `page_size` (Groww's default is 25),
  and sends `page` only when `segment` is given. Pass a segment and walk `page` to see more than 25.
- `get_order_status` / `get_order_detail` / `get_trade_list_for_order` take one `groww_order_id`;
  `get_order_status_by_reference` takes your own `order_reference_id`.
- **Prices are in rupees** in orders and responses. Order prices must sit on the contract's tick grid, and
  the instrument list's MCX ticks are in paise ([GROWW_API_INSTRUMENTS.md](GROWW_API_INSTRUMENTS.md)).
- **Quantity** is in the same unit as positions and `lot_size` (GOLD: 100 per lot), and is an `int`.

Where this repo places orders, and how it guards them:

| Code | What it places |
|---|---|
| [`apps/fno_dashboard.py`](../../apps/fno_dashboard.py) Quick Exit, built by [`groww_api/orders.py`](../../groww_api/orders.py) | A DAY limit order that flattens one position: longs sold at LTP − 0.5% rounded down to the tick, shorts bought back at LTP + 0.5% rounded up, in the position's own product. Refused with a reason when there is no live price, no tick size, the quantity is not whole lots, or the price would round to 0 (a long trading at one tick). Sent with a 15 s timeout; on a timeout the page says to check the order book before retrying, since the order may have gone through. The price is the page's cached LTP, up to 60 s old |
| [`strategies/`](../../strategies/) (Groww Cloud scripts) | A DAY limit SELL at entry + 15%, rounded up to the tick, for each long F&O (or MCX) position, in its own product. Shorts, and contracts whose tick size is blank or zero, are skipped and reported |

## Smart orders (GTT and OCO)

`create_smart_order(smart_order_type, segment, trading_symbol, quantity, product_type, exchange, duration, ...)`
with duration `DAY` or `GTC`:

- **GTT:** `trigger_price`, `trigger_direction` (`UP`/`DOWN`) and an `order` (`order_type`, `price`,
  `transaction_type`), optionally `child_legs`.
- **OCO:** `net_position_quantity` (your current position), a `target` and a `stop_loss` leg (each
  `trigger_price`, `order_type`, optional `price`) and `transaction_type`. One fills, the other is cancelled.

That is a stop-loss and a target on an existing position that can last more than a day (`GTC`), which is
the use case behind a morning "place SL and target" job. **Untested:** whether OCO with `GTC` is accepted for
FNO and COMMODITY carry-forward positions. Groww's docs show CASH and FNO examples only. Checking needs one
real order placed and cancelled.

## Reports: not available through the API

There is **no API for a P&L report, tradebook history, ledger, contract notes or tax/capital-gains
reports**. All 33 SDK endpoints were read and none of Groww's doc pages mention one. The nearest things are:

| Need | Closest API | Limit |
|---|---|---|
| Orders over a period | `get_order_list` | Today only |
| Fills | `get_trade_list_for_order` | One order id at a time |
| P&L | `realised_pnl` on each position | Current positions only (`get_positions_for_user`) |
| Charges | `brokerage_and_charges` in margins | A running total, no breakdown |

So a financial year of orders and P&L has to come from the **Excel exports in the Groww app or website**.
The API can only add today's orders on top.

## Rate limits (Groww docs)

Applied per type, not per call.

| Type | Calls | Per second | Per minute |
|---|---|---|---|
| Orders | create, modify, cancel | 10 | 250 |
| Live data | quote, LTP, OHLC | 10 | 300 |
| Non-trading | order status/list, trade list, positions, holdings, margin | 20 | 500 |

Tokens: 5/s and 30/min, and at most 150 per 24 hours. Live feed: up to 1,000 subscriptions.
