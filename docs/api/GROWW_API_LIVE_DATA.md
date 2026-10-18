# Groww live data, history, option chain and Greeks

**Sources:** https://groww.in/trade-api/docs/python-sdk/live-data, `/historical-data`, the SDK source
(`growwapi` 1.5.0), a live run on the free plan on 2026-10-17 and on the paid plan on 2026-10-18.

## Needs the paid data plan

**Paid plan, 2026-10-18 (Sunday, so after hours):** every call on this page answers, each in about 0.35 s,
except where the table says otherwise. Run `python scripts/debug/probe_groww.py` to repeat it.

| Call | Result on the paid plan |
|---|---|
| `get_ltp`, `get_ohlc`, `get_quote` | ✅ CASH, FNO and **COMMODITY (MCX)**, including batched `get_ltp` with `MCX_<symbol>` keys |
| `get_historical_candles` | ✅ NSE cash and NSE F&O, every interval tried. **MCX: an empty answer for every interval** (`{"candles": []}`, no error), so Groww has no MCX candle history |
| `get_expiries`, `get_option_chain`, `get_greeks` | ✅ NSE. **MCX: no.** `get_option_chain("MCX", "CRUDEOIL", ...)` answers "Underlying not found", and `get_greeks` answers "Internal error occurred" for every MCX option tried (CRUDEOIL, GOLD, NATURALGAS) |

On the **free plan** (2026-10-17) every call on this page was refused with
`GrowwAPIException: Access forbidden for this request.` (`get_option_chain`: "Access Forbidden. Your API
token does not have the required roles or is invalid."). What the repo does when prices are refused or missing:

| Code | Without a price |
|---|---|
| F&O dashboard ([`groww_api/position_processor.py`](../../groww_api/position_processor.py)) | Positions listed with no price or P&L and a warning; no quick exit for them; Greeks tab says why. MCX options never get Greeks |
| Portfolio page ([`apps/app.py`](../../apps/app.py)) | Stocks valued at their buy price, with a warning naming them |
| Heatmap's Groww provider ([`market/providers/groww.py`](../../market/providers/groww.py)) | Finds the symbols, then gets no prices, so another broker serves the board |

## `get_quote(trading_symbol, exchange, segment, timeout=None)`

One instrument per call, e.g. `get_quote("NIFTY", "NSE", "CASH")` or
`get_quote("GOLD04DEC26FUT", "MCX", "COMMODITY")`. Documented response fields:

`average_price`, `bid_quantity`, `bid_price`, `day_change`, `day_change_perc`, `upper_circuit_limit`,
`lower_circuit_limit`, `ohlc` (`open`, `high`, `low`, `close`), `depth` (`buy`/`sell` price and quantity),
`high_trade_range`, `low_trade_range`, `implied_volatility`, `last_trade_quantity`, `last_trade_time`,
**`last_price`**, **`market_cap`**, `offer_price`, `offer_quantity`, `oi_day_change`,
`oi_day_change_percentage`, `open_interest`, `previous_open_interest`, `total_buy_quantity`,
`total_sell_quantity`, `volume`, **`week_52_high`**, **`week_52_low`**.

The 52-week range comes from here, one stock at a time; the instrument list has no price data.
**`market_cap` is documented but comes back `None`** (RELIANCE, 2026-10-18), so Groww is no source for
market cap. `week_52_high` and `week_52_low` have real values.

## `get_ltp(exchange_trading_symbols, segment, timeout=None)` and `get_ohlc(...)`

Up to **50 instruments per call**, as `"<EXCHANGE>_<trading_symbol>"`: `("NSE_RELIANCE", "NSE_NIFTY")`,
`"NSE_NIFTY26OCTFUT"` with segment FNO. The response keys are the same strings: `get_ltp` maps each to a
price, `get_ohlc` to `{open, high, low, close}`.

- The SDK docstring for `get_ohlc` shows `"NSE:RELIANCE"`; that is wrong. The heatmap used `NSE_RELIANCE`
  successfully when Groww's data was paid for (2026-09).
- Groww's docs name CASH and FNO for these two calls, but **`MCX_<symbol>` with segment COMMODITY works**
  (2026-10-18). The repo prices F&O and MCX positions in batches of 50
  (`batched_ltp` in [`groww_api/api_calls.py`](../../groww_api/api_calls.py)).
- **One unknown symbol fails the whole batch** ("Invalid trading symbol: ..."), so `batched_ltp` retries
  that batch one symbol at a time. A price of `None` or 0 is treated as no price.
- **`close` is the previous session's close.** On Sunday 2026-10-18 RELIANCE's `close` was 1215.0, Thursday's
  daily close, while the last price was Friday's 1211.2; MCX GOLD's `day_change` (511) was likewise last
  price minus `close`. That is what the heatmap's previous close needs. Not yet seen during a session.
- Rate limit: 10 per second, 300 per minute, shared by quote, LTP and OHLC.

## `get_historical_candles(exchange, segment, groww_symbol, start_time, end_time, candle_interval, timeout=None)`

`groww_symbol` from the instrument list (`NSE-RELIANCE`, `NSE-NIFTY-27Oct26-FUT`,
`MCX-CRUDEOIL-19Oct26-FUT`); times as `yyyy-MM-dd HH:mm:ss`; interval one of `1minute`, `2minute`,
`3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `1hour`, `4hour`, `1day`, `1week`, `1month`.
Response `{"candles": [[timestamp, open, high, low, close, volume, open_interest], ...]}`.

- **Daily candles have `open = None`**, still on 2026-10-18, for stocks and NSE futures alike. Some
  intraday candles do too (RELIANCE 5-minute, 09:05 and the first candles after it). Don't use Groww for
  gaps or anything that needs the open.
- **MCX returns no candles at all** (above).
- 1-minute history is limited to 30 days per call, and pre-open minutes carry volume only (2026-09,
  [PROVIDER_GUIDE.md](../PROVIDER_GUIDE.md)). `get_historical_candle_data` is
deprecated by the SDK.

## Option chain and Greeks

- `get_expiries(exchange, underlying_symbol, year=None, month=None)`, `get_contracts(exchange, underlying_symbol, expiry_date)`.
- `get_option_chain(exchange, underlying, expiry_date)`: `{"underlying_ltp": ..., "strikes": {"23400": {"CE": {...}, "PE": {...}}}}`;
  each CE/PE has `trading_symbol`, `ltp`, `open_interest`, `volume` and `greeks`.
- `get_greeks(exchange, underlying, trading_symbol, expiry)`: `{"greeks": {"delta", "gamma", "theta", "vega", "rho", "iv"}}`,
  e.g. `get_greeks("NSE", "NIFTY", "NIFTY25O1425100CE", "2025-10-14")`.
  - **It is the only SDK call without a `timeout` argument** (its request has no timeout at all), so
    `GrowwAPIService.get_greeks` runs it on a worker thread and gives up after 10 s.
  - **NSE only.** For MCX options it answers "Internal error occurred" (2026-10-18), so the repo does not
    ask for them and the Greeks tab says so.
  - The option chain's per-strike `greeks` are all 0 for strikes with no trades (deep in the money).
  - The F&O dashboard's Greeks tab uses it for each open option position. Groww positions carry no Greeks.
    The tab showed zeros before 2026-10-17: it read Greek fields that positions don't have, and filtered on
    a position type that never occurs.
