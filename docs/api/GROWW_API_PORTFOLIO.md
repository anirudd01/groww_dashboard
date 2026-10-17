# Groww holdings, positions and margins

**Sources:** https://groww.in/trade-api/docs/python-sdk/portfolio (and `#get-holdings`), `/margin`, the SDK
source (`growwapi` 1.5.0) and live responses on 2026-10-17 (free API plan; all of these work on it).
Notes marked **observed** come from the live account, not from Groww's docs.

## Holdings: `get_holdings_for_user(timeout=None)`

Long-term delivery holdings in the demat account. The response is `{"holdings": [...]}`, so read the
`holdings` key; the SDK method is `get_holdings_for_user` (there is no `get_holdings`; this repo called that
by mistake until 2026-10-17).

| Field | Type | Meaning |
|---|---|---|
| `isin`, `trading_symbol` | string | |
| `quantity` | float | Net quantity held |
| `average_price` | number | Average buy price, rupees |
| `pledge_quantity`, `repledge_quantity` | float | Pledged as collateral |
| `demat_locked_quantity`, `groww_locked_quantity` | float | Locked |
| `t1_quantity` | float | Bought, not yet settled (T+1) |
| `demat_free_quantity` | float | Free to sell |
| `corporate_action_additional_quantity`, `active_demat_transfer_quantity` | int | |

Whether MTF stocks also appear here (the [glossary](glossary.md) says they do) has not been checked: the
account held no stocks on 2026-10-17. [`groww_api/groww_client.py`](../../groww_api/groww_client.py) relies on it.

## Positions: `get_positions_for_user(segment=None, timeout=None)` and `get_position_for_trading_symbol(trading_symbol, segment, timeout=None)`

Both return `{"positions": [...]}`. `segment` filters to `CASH`, `FNO` or **`COMMODITY`** (MCX; Groww's
page names only CASH and FNO, but COMMODITY works, observed). Two live MCX rows from 2026-10-17:

```json
{"trading_symbol": "GOLD04DEC26FUT", "segment": "COMMODITY", "exchange": "MCX", "product": "NRML",
 "credit_quantity": 500, "credit_price": 148240.8, "debit_quantity": 400, "debit_price": 148349.5,
 "carry_forward_credit_quantity": 0, "carry_forward_credit_price": 0.0,
 "carry_forward_debit_quantity": 0, "carry_forward_debit_price": 0.0,
 "symbol_isin": "MCX_GOLD04DEC26FUT", "quantity": 100, "net_carry_forward_quantity": 0,
 "net_price": 148240.8, "net_carry_forward_price": 0.0, "realised_pnl": 59400.0}
{"trading_symbol": "CRUDEOIL19NOV26FUT", ..., "credit_quantity": 500, "credit_price": 9111.0,
 "debit_quantity": 500, "debit_price": 9168.4, "quantity": 0, "net_price": 9168.4, "realised_pnl": 28700.0}
```

| Field | Meaning (observed where Groww's docs are silent) |
|---|---|
| `quantity` | Net quantity, **negative for a short**, 0 once squared off. Same unit as `lot_size` (GOLD: 100 = 1 lot) |
| `credit_quantity` / `credit_price` | What was **bought** (GOLD: 500 bought, 400 sold, net +100) |
| `debit_quantity` / `debit_price` | What was **sold** |
| `carry_forward_*` | The same, for quantity brought in from earlier days |
| `net_price` | Average price of the open quantity, rupees |
| `realised_pnl` | Rupees. CRUDEOIL: 500 × (9168.4 − 9111.0) = 28,700, so P&L is quantity × price change, with no lot multiplier |
| `product` | `NRML`, `MIS`, `CNC`, `MTF` |

**Not in a position:** expiry, strike, lot size, tick size, last price or Greeks. The F&O dashboard takes
the contract facts from the instrument list ([GROWW_API_INSTRUMENTS.md](GROWW_API_INSTRUMENTS.md)), prices
from the quote calls and Greeks from `get_greeks` ([GROWW_API_LIVE_DATA.md](GROWW_API_LIVE_DATA.md)).
A position closed today keeps quantity 0 and its `realised_pnl`, and still shows on Saturday after a
Friday trade (observed).

## Margins: `get_available_margin_details(timeout=None)`

Live response, 2026-10-17, with one GOLD future open:

```json
{"clear_cash": 1810270.97, "net_margin_used": 1364900.0, "brokerage_and_charges": 0.0,
 "collateral_used": 0.0, "collateral_available": 0.0, "adhoc_margin": 0.0,
 "fno_margin_details": {"net_fno_margin_used": -1364900.0, "span_margin_used": -1179900.0,
   "exposure_margin_used": -185000.0, "future_balance_available": 445370.97,
   "option_buy_balance_available": 445370.97, "option_sell_balance_available": 445370.97},
 "equity_margin_details": {"net_equity_margin_used": 0.0, "cnc_margin_used": 0.0, "mis_margin_used": 0.0,
   "cnc_balance_available": 445370.97, "mis_balance_available": 445370.97},
 "commodity_margin_details": {"commodity_span_margin": -117990000.0, "commodity_exposure_margin": -18500000.0,
   "commodity_tender_margin": 0.0, "commodity_special_margin": 0.0, "commodity_additional_margin": 0.0,
   "commodity_unrealised_m2m": 0.0, "commodity_realised_m2m": 0.0}}
```

What it shows (observed; none of it is in Groww's docs):

- **Per-segment "used" margins are negative**, while `net_margin_used` is positive. Take magnitudes before
  combining them: `net_margin_used − net_fno_margin_used` is 1,364,900 − (−1,364,900) = 2,729,800, twice the
  real figure. The Portfolio page's MTF figures did exactly that until 2026-10-17.
- **`commodity_margin_details` is in paise**: span 117,990,000 is ₹11,79,900, exposure 18,500,000 is
  ₹1,85,000. The same amounts appear in rupees in `fno_margin_details`, so **F&O margins include MCX**.
- **`clear_cash` is not free margin.** It is the wallet cash (₹18.1L) before margin; what is free for a new
  F&O or MCX trade is `future_balance_available` (₹4.45L = 18.1L − 13.6L used). The F&O dashboard showed
  `clear_cash + collateral_available` as "Available Margin" until 2026-10-17.

## What else uses these

- [`apps/app.py`](../../apps/app.py) (Portfolio page) via `GrowwClient` in [`groww_api/groww_client.py`](../../groww_api/groww_client.py).
- [`apps/fno_dashboard.py`](../../apps/fno_dashboard.py) via [`groww_api/position_processor.py`](../../groww_api/position_processor.py).
- The [glossary](glossary.md) holds earlier notes on what each holdings and margin field means for MTF.
