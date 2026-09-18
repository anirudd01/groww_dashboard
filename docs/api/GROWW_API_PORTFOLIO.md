# Portfolio API Documentation

**Source:** https://groww.in/trade-api/docs/python-sdk/portfolio

---

## Overview

The Portfolio section provides methods to retrieve detailed information about holdings and positions through the Groww Python SDK.

## Get Holdings

### Method: `get_holdings_for_user()`

Retrieves current holdings representing long-term equity delivery stocks stored in a user's DEMAT account.

**Usage Example:**
```python
from growwapi import GrowwAPI

API_AUTH_TOKEN = "your_token"
groww = GrowwAPI(API_AUTH_TOKEN)

holdings_response = groww.get_holdings_for_user(timeout=5)
print(holdings_response)
```

**Response Fields:**
- `isin` (string): International Securities Identification number
- `trading_symbol` (string): Symbol identifier
- `quantity` (float): Net holding quantity
- `average_price` (int): Average purchase price in rupees
- `pledge_quantity` (float): Pledged shares
- `demat_locked_quantity` (float): Locked in DEMAT
- `groww_locked_quantity` (float): Locked by Groww
- `t1_quantity` (float): T1 settlement quantity
- `demat_free_quantity` (float): Available for trading

## Get Positions for User

### Method: `get_positions_for_user(segment=None)`

Retrieves all trading positions across equity (CASH) and derivatives (FNO) segments.

**Parameters:**
- `segment` (string, optional): Filter by SEGMENT_CASH or SEGMENT_FNO

**Usage Example:**
```python
# All positions
positions = groww.get_positions_for_user()

# Specific segment
cash_positions = groww.get_positions_for_user(segment=groww.SEGMENT_CASH)
```

**Key Response Fields:**
- `trading_symbol` (string): Instrument symbol
- `segment` (string): CASH or FNO
- `quantity` (int): Net position quantity
- `net_price` (int): Average price in rupees
- `realised_pnl` (int): Realized profit/loss
- `product` (string): Product type (CNC, etc.)

## Get Position for Symbol

### Method: `get_position_for_trading_symbol(trading_symbol, segment)`

Retrieves detailed position data for a specific symbol.

**Required Parameters:**
- `trading_symbol` (string): Symbol to query
- `segment` (string): CASH or FNO segment

**Usage Example:**
```python
position = groww.get_position_for_trading_symbol(
    trading_symbol="RELIANCE", 
    segment=groww.SEGMENT_CASH
)
```

**Response Structure:** Returns position object with credit/debit quantities, carry-forward balances, and realized P&L metrics.

---

## Summary

These portfolio APIs give you complete access to:
- ✅ Delivery holdings (DEMAT)
- ✅ Trading positions (CASH & FNO)
- ✅ Detailed position metadata
- ✅ Pledge and lock information
