# Groww live data, history, option chain and Greeks

**Sources:** https://groww.in/trade-api/docs/python-sdk/live-data, `/historical-data`, the SDK source
(`growwapi` 1.5.0) and a live run on 2026-10-17.

## Needs the paid data plan (tested 2026-10-17)

On Groww's **free API plan every call on this page is refused** with
`GrowwAPIException: Access forbidden for this request.` (`get_option_chain`: "Access Forbidden. Your API
token does not have the required roles or is invalid."). Each refusal took about 0.55 s. Refused:
`get_quote`, `get_ltp`, `get_ohlc` (CASH, FNO and COMMODITY, stocks and indices), `get_historical_candles`
and the deprecated `get_historical_candle_data` (every interval and segment), `get_expiries`,
`get_contracts`, `get_option_chain` and `get_greeks`.

What the repo does then:

| Code | Without the data plan |
|---|---|
| F&O dashboard ([`groww_api/position_processor.py`](../../groww_api/position_processor.py)) | Positions listed with no price or P&L and a warning; no quick exit for them; Greeks tab says why |
| Portfolio page ([`apps/app.py`](../../apps/app.py)) | Stocks valued at their buy price, with a warning naming them |
| Heatmap's Groww provider ([`market/providers/groww.py`](../../market/providers/groww.py)) | Finds the symbols, then gets no prices, so another broker serves the board |

The live socket ([GROWW_API_FEED.md](GROWW_API_FEED.md)) connected on the free plan, but on a Saturday no
tick could arrive either way, so whether it streams without the data plan is unknown.

## `get_quote(trading_symbol, exchange, segment, timeout=None)`

One instrument per call, e.g. `get_quote("NIFTY", "NSE", "CASH")` or
`get_quote("GOLD04DEC26FUT", "MCX", "COMMODITY")`. Documented response fields:

`average_price`, `bid_quantity`, `bid_price`, `day_change`, `day_change_perc`, `upper_circuit_limit`,
`lower_circuit_limit`, `ohlc` (`open`, `high`, `low`, `close`), `depth` (`buy`/`sell` price and quantity),
`high_trade_range`, `low_trade_range`, `implied_volatility`, `last_trade_quantity`, `last_trade_time`,
**`last_price`**, **`market_cap`**, `offer_price`, `offer_quantity`, `oi_day_change`,
`oi_day_change_percentage`, `open_interest`, `previous_open_interest`, `total_buy_quantity`,
`total_sell_quantity`, `volume`, **`week_52_high`**, **`week_52_low`**.

So market cap and the 52-week range come from here, one stock at a time; the instrument list has no price
data. The repo prices MCX positions with this call (`GrowwAPIService.get_ltp_for_mcx`).

## `get_ltp(exchange_trading_symbols, segment, timeout=None)` and `get_ohlc(...)`

Up to **50 instruments per call**, as `"<EXCHANGE>_<trading_symbol>"`: `("NSE_RELIANCE", "NSE_NIFTY")`,
`"NSE_NIFTY26OCTFUT"` with segment FNO. The response keys are the same strings: `get_ltp` maps each to a
price, `get_ohlc` to `{open, high, low, close}`.

- The SDK docstring for `get_ohlc` shows `"NSE:RELIANCE"`; that is wrong. The heatmap used `NSE_RELIANCE`
  successfully when Groww's data was paid for (2026-09).
- Groww's docs name CASH and FNO for these two calls. Whether `MCX_<symbol>` with segment COMMODITY works is
  unverified, so MCX stays on `get_quote`.
- **What `close` means is not documented** ("Closing price"). This repo reads it as the previous session's
  close, which held during the session when it was last tested. To re-check with the data plan.
- Rate limit: 10 per second, 300 per minute, shared by quote, LTP and OHLC.

## `get_historical_candles(exchange, segment, groww_symbol, start_time, end_time, candle_interval, timeout=None)`

`groww_symbol` from the instrument list (`NSE-RELIANCE`, `NSE-NIFTY-27Oct26-FUT`,
`MCX-CRUDEOIL-19Oct26-FUT`); times as `yyyy-MM-dd HH:mm:ss`; interval one of `1minute`, `2minute`,
`3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `1hour`, `4hour`, `1day`, `1week`, `1month`.
Response `{"candles": [[timestamp, open, high, low, close, volume, ...], ...]}`. Earlier findings (paid plan,
2026-09): daily candles had `open = None`, 1-minute history is limited to 30 days per call, and pre-open
minutes carry volume only ([PROVIDER_GUIDE.md](../PROVIDER_GUIDE.md)). `get_historical_candle_data` is
deprecated by the SDK.

## Option chain and Greeks

- `get_expiries(exchange, underlying_symbol, year=None, month=None)`, `get_contracts(exchange, underlying_symbol, expiry_date)`.
- `get_option_chain(exchange, underlying, expiry_date)`: `{"underlying_ltp": ..., "strikes": {"23400": {"CE": {...}, "PE": {...}}}}`;
  each CE/PE has `trading_symbol`, `ltp`, `open_interest`, `volume` and `greeks`.
- `get_greeks(exchange, underlying, trading_symbol, expiry)`: `{"greeks": {"delta", "gamma", "theta", "vega", "rho", "iv"}}`,
  e.g. `get_greeks("NSE", "NIFTY", "NIFTY25O1425100CE", "2025-10-14")`.
  - **It is the only SDK call without a `timeout` argument** (its request has no timeout at all), so
    `GrowwAPIService.get_greeks` runs it on a worker thread and gives up after 10 s.
  - The F&O dashboard's Greeks tab uses it for each open option position. Groww positions carry no Greeks.
    The tab showed zeros before 2026-10-17: it read Greek fields that positions don't have, and filtered on
    a position type that never occurs.
