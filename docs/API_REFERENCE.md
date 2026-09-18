# API Reference

**Status:** ✅ Complete & Verified

Complete Groww Trading API documentation for integrating FnO position tracking.

---

## 📖 Official API Documentation

Located in `docs/api/`:

### **Portfolio Operations**
📄 **[GROWW_API_PORTFOLIO.md](./api/GROWW_API_PORTFOLIO.md)**
- `get_holdings()` - Equity delivery holdings
- `get_positions_for_user()` - Open positions (MTF, FnO)
- `get_available_margin_details()` - Margin & fund balance
- Response structure & field mappings

### **Live Market Data**
📄 **[GROWW_API_LIVE_DATA.md](./api/GROWW_API_LIVE_DATA.md)**
- `get_ltp()` - Last Traded Price (batched calls)
- `get_quote()` - Detailed quotes with OHLC
- Greeks data (Delta, Gamma, Theta, Vega)
- Supported segments: FNO, COMMODITY, CASH
- Field explanations & example responses

### **Real-Time Streaming**
📄 **[GROWW_API_FEED.md](./api/GROWW_API_FEED.md)**
- `subscribe()` - Real-time price subscriptions
- `get_feed_data()` - Streaming updates
- Feed message structure
- Implementation notes & examples

### **Glossary**
📄 **[glossary.md](./api/glossary.md)**
- Term definitions
- Acronym reference
- Financial concepts

---

## 🔧 Implementation in Pulse Tester

### **How We Use the APIs**

#### **Get All Positions (with LTP)**
```python
from groww_api import GrowwAPIClient, GrowwAPIService, PositionProcessor

# Singleton auth (ONE per session)
client = GrowwAPIClient.get_instance()

# Service layer
api = GrowwAPIService(client)

# Business logic
processor = PositionProcessor(api)
positions = processor.get_fno_positions()
```

**Behind the Scenes:**
1. `get_positions()` - Fetches all open positions
2. Separates NSE vs MCX symbols
3. `get_ltp_for_nse_fno()` - Calls `get_ltp()` with NSE_ prefix
4. `get_ltp_for_mcx()` - Calls `get_quote()` for MCX symbols
5. Calculates P&L = (LTP - entry_price) * quantity

#### **Fetch User Profile**
```python
profile = api.get_user_profile()
# Returns: vendor_user_id, ucc, enabled_segments, etc.
```

#### **Get Available Margin**
```python
margins = api.get_margins()
# Returns: clear_cash, net_margin_used, collateral_used, etc.
```

#### **Get Holdings**
```python
holdings = api.get_holdings()
# Returns: List of delivery holdings (ISIN, quantity, average_price, etc.)
```

---

## 📊 Key API Parameters

### **NSE FnO (Equity Futures & Options)**
```python
client.get_ltp(
    segment=GrowwAPI.SEGMENT_FNO,
    exchange_trading_symbols="NSE_NIFTY26SEP24200CE"  # or tuple of symbols
)
```
- Max 50 symbols per call
- Returns: Dict of {symbol: ltp_value}

### **MCX Commodity (Futures & Options)**
```python
client.get_quote(
    exchange=GrowwAPI.EXCHANGE_MCX,
    segment=GrowwAPI.SEGMENT_COMMODITY,
    trading_symbol="GOLD25SEP26150000CE"
)
```
- One symbol per call (MCX limitation)
- Returns: Dict with ltp, lastPrice, bid, ask, etc.

### **Cash/Equity Holdings**
```python
client.get_ltp(
    segment=GrowwAPI.SEGMENT_CASH,
    exchange_trading_symbols="NSE_RELIANCE"
)
```
- For equity stock prices
- Same batching as NSE FnO

---

## ✅ Verified Working

| API Call | Symbols | Status | Notes |
|----------|---------|--------|-------|
| `get_positions_for_user()` | All | ✅ Working | Returns 63 positions |
| `get_ltp()` NSE FnO | 46 | ✅ Working | All symbols fetching |
| `get_quote()` MCX | 13 | ✅ Working | Individual calls working |
| `get_holdings()` | N/A | ✅ Working | Delivery holdings |
| `get_available_margin_details()` | N/A | ✅ Working | Margin info |
| `get_user_profile()` | N/A | ✅ Working | User details |

---

## 🔗 Response Examples

### **Position Object**
```json
{
  "trading_symbol": "NIFTY26SEP24200CE",
  "segment": "FNO",
  "exchange": "NSE",
  "quantity": 75,
  "net_price": 175.65,
  "credit_price": 175.65,
  "debit_price": 0.0,
  "delta": 0.65,
  "gamma": 0.008,
  "theta": -3.20,
  "vega": 15.50
}
```

### **LTP Response (NSE FnO)**
```json
{
  "NIFTY26SEP24200CE": 173.25,
  "RELIANCE26SEP1290CE": 40.6,
  "HEROMOTOCO26SEP5400CE": 88.7
}
```

### **Quote Response (MCX)**
```json
{
  "ltp": 4353.5,
  "lastPrice": 4353.5,
  "bid": 4350.0,
  "ask": 4357.0,
  "volume": 5000,
  "openInterest": 150000
}
```

---

## ⚠️ Known Limitations

1. **MCX Individual Calls** - No batch API for MCX commodities
   - Solution: Loop with batching on our end

2. **Greeks Data Availability** - `get_quote()` may not return all Greeks
   - Solution: Call separately if needed

3. **Feed API Not Yet Used** - Real-time streaming available but not integrated
   - Future: Can be added for live price updates

4. **Auth Token Expiry** - Tokens expire after ~24 hours
   - Solution: Implement refresh mechanism for long-running services

---

## 🚀 Advanced Usage

### **Bulk LTP Fetch with Fallback**
```python
from groww_api import GrowwAPIService

api = GrowwAPIService(client)

# Automatic separation by exchange
nse_ltp = api.get_ltp_for_nse_fno(symbols)
mcx_ltp = api.get_ltp_for_mcx(symbols)

combined = {**nse_ltp, **mcx_ltp}
```

### **Error Handling**
```python
try:
    positions = processor.get_fno_positions()
except Exception as e:
    logger.error(f"Failed to fetch positions: {e}")
    # Fallback to cached data or mock mode
```

### **Testing with Mock Data**
```python
# Legacy API supports mock mode
from groww_client import GrowwClient

client = GrowwClient(mock_mode=True)
positions = client.get_fno_positions()  # Returns sample data
```

---

## 📞 Troubleshooting

**"Auth failed" error**
- Check `.env` file has correct credentials
- Verify GROWW_AUTH_MODE matches your auth type
- Try TOKEN auth as fallback

**"LTP not found"**
- Verify market is open for the segment
- Run `python debug_api_calls.py` to test
- Check symbol spelling (case-sensitive on MCX)

**"Rate limit exceeded"**
- Implement exponential backoff
- Use batching (max 50 symbols per call)
- Add delay between calls

---

## 📚 Additional Resources

- `README.md` - Project overview
- `ARCHITECTURE.md` - System design
- `QUICK_START.md` - Setup instructions
- `debug_api_calls.py` - Live API testing script

---

**Last Updated:** 2026-09-02 | **API Version:** Groww SDK 1.5.0
