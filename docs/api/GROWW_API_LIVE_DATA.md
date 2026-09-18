# Live Data API Documentation

**Source:** https://groww.in/trade-api/docs/python-sdk/live-data

---

## Overview
The Groww API provides several methods for retrieving real-time market data through its Python SDK.

## Get Quote

**Purpose:** Retrieve real-time quote for a single instrument.

**Method:** `get_quote()`

**Required Parameters:**
- `exchange` - Stock exchange (e.g., `EXCHANGE_NSE`)
- `segment` - Market segment like CASH or FNO
- `trading_symbol` - Symbol identifier from exchange

**Example:**
```python
quote_response = groww.get_quote(
    exchange=groww.EXCHANGE_NSE,
    segment=groww.SEGMENT_CASH,
    trading_symbol="NIFTY"
)
```

**Response includes:** 
- Average price
- Bid/offer quantities and prices
- Day changes
- Circuit limits
- OHLC data
- Market depth
- Volatility
- Volume
- 52-week highs/lows
- Open interest metrics

---

## Get LTP

**Purpose:** Fetch last traded prices for multiple instruments (up to 50 per call).

**Method:** `get_ltp()`

**Required Parameters:**
- `segment` - Market segment
- `exchange_trading_symbols` - String or tuple of symbol identifiers

**Example:**
```python
ltp_response = groww.get_ltp(
    segment=groww.SEGMENT_CASH,
    exchange_trading_symbols=("NSE_NIFTY", "NSE_RELIANCE")
)
```

**Response Format:**
Returns dictionary mapping symbols to their last traded prices in rupees.

---

## Get OHLC

**Purpose:** Retrieve opening, high, low, and closing prices for instruments.

**Method:** `get_ohlc()`

**Required Parameters:**
- `segment` - Market segment
- `exchange_trading_symbols` - Symbol identifier(s)

**Note:** This returns real-time snapshots; for interval-based candle data, use Historical Data methods.

**Example:**
```python
ohlc_response = groww.get_ohlc(
    segment=groww.SEGMENT_CASH,
    exchange_trading_symbols=("NSE_NIFTY", "NSE_RELIANCE")
)
```

---

## Get Option Chain

**Purpose:** Retrieve complete option chain data including Greeks for derivatives.

**Method:** `get_option_chain()`

**Required Parameters:**
- `exchange` - NSE or BSE
- `underlying` - Underlying symbol (NIFTY, BANKNIFTY, etc.)
- `expiry_date` - Expiry in YYYY-MM-DD format

**Response includes:** 
- Underlying LTP
- Strike-wise data for both Call (CE) and Put (PE) options
- Greeks data
- Trading symbols
- LTP
- Open interest
- Volume

---

## Get Greeks

**Purpose:** Fetch Greeks data for derivative contracts supporting risk assessment.

**Method:** `get_greeks()`

**Required Parameters:**
- `exchange` - Stock exchange
- `underlying` - Underlying symbol
- `trading_symbol` - FNO contract symbol
- `expiry` - Contract expiry in YYYY-MM-DD format

**Greeks Returned:** 
- Delta
- Gamma
- Theta
- Vega
- Rho
- Implied Volatility (IV)

---

## Summary

These live data APIs provide:
- ✅ Real-time quotes (`get_quote()`)
- ✅ Last traded prices in bulk (`get_ltp()`)
- ✅ OHLC data (`get_ohlc()`)
- ✅ Option chain data (`get_option_chain()`)
- ✅ Greeks for options (`get_greeks()`)

**Perfect for:** Building live dashboards, calculating P&L, displaying Greeks, monitoring option chains.
