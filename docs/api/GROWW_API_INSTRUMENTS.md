# Groww instrument list

**Source:** https://groww.in/trade-api/docs/python-sdk/instruments, plus the SDK source (`growwapi` 1.5.0)
and the live file, checked 2026-10-17. Code: [`groww_api/instruments.py`](../../groww_api/instruments.py).

## What it is

One CSV of every tradable contract, at `https://growwapi-assets.groww.in/instruments/instrument.csv`.
It is public: no login and no paid plan needed. The SDK's `get_all_instruments()` downloads it into a
DataFrame, `get_instrument_by_groww_symbol()` / `get_instrument_by_exchange_and_trading_symbol()` /
`get_instrument_by_exchange_token()` look rows up in it.

On 2026-10-17 it had **141,201 rows**: NSE 112,846 (CASH 4,328, FNO 85,957, COMMODITY 22,561), MCX 15,532,
BSE 12,823. By type: CE 63,690, PE 63,702, EQ 12,794, FUT 984, IDX 31.

## Columns

| Column | Example | Notes |
|---|---|---|
| `exchange` | `NSE`, `MCX`, `BSE` | |
| `exchange_token` | `2885` | The exchange's id. For MCX it equals Dhan's and INDmoney's id |
| `trading_symbol` | `NIFTY26OCTFUT` | What orders, positions, `get_quote` and `get_ltp` use |
| `groww_symbol` | `NSE-NIFTY-27Oct26-FUT` | What `get_historical_candles` uses |
| `name` | `Reliance Industries` | |
| `instrument_type` | `EQ`, `IDX`, `FUT`, `CE`, `PE` | |
| `segment` | `CASH`, `FNO`, `COMMODITY` | |
| `series` | `EQ` | |
| `isin` | `INE002A01018` | |
| `underlying_symbol` | `NIFTY`, `GOLD` | Blank for stocks and indices |
| `underlying_exchange_token` | | |
| `expiry_date` | `2026-10-27` | Derivatives only |
| `strike_price` | `18150` | Options only, in rupees (MCX too: `GOLD29JAN27166000CE` → 166000) |
| `lot_size` | `65`, `100` | Quantity of one lot, see below |
| `tick_size` | `0.05`, `100.0` | **Rupees on NSE/BSE, paise on MCX**, see below |
| `freeze_quantity` | `3511` | |
| `is_reserved`, `buy_allowed`, `sell_allowed` | `0`/`1` | |
| `internal_trading_symbol`, `is_intraday` | | In the file, not in Groww's docs |

**There is no price data at all**: no previous close, open, high, low, 52-week range or market cap.
The 52-week high/low are fields of `get_quote` (one instrument per call, paid data plan). So is
`market_cap` on paper, but it comes back `None` (2026-10-18; [GROWW_API_LIVE_DATA.md](GROWW_API_LIVE_DATA.md)).

## Things to get right (verified 2026-10-17)

- **Every column is text.** The SDK reads the CSV with `dtype="str"`, so `lot_size` is `"100"` and blank
  cells are `NaN` floats. Convert before comparing or doing arithmetic.
- **MCX `tick_size` is in paise.** NSE and BSE ticks are in rupees. Groww's docs don't say so, and their own
  examples disagree with each other (BANKNIFTY options 0.05, RELIANCE 5).

  | Contract | `tick_size` in the file | Real tick |
  |---|---|---|
  | GOLD, GOLDM, CRUDEOIL, CRUDEOILM, SILVER futures | 100.0 | ₹1 |
  | NATURALGAS, NATGASMINI, NICKEL | 10.0 | ₹0.10 |
  | COPPER, ZINC, LEAD, ALUMINIUM | 5.0 | ₹0.05 |
  | COTTON, STEELREBAR | 1000.0 | ₹10 |
  | GOLD options | 50.0 | ₹0.50 |
  | NIFTY options / NIFTY futures / RELIANCE | 0.05 / 0.1 / 0.1 | the same, in rupees |

  An order price off the tick grid is rejected, so [`groww_api/instruments.py`](../../groww_api/instruments.py)
  converts MCX ticks (`tick_in_rupees`) and rounds prices onto the grid (`round_to_tick`).
- **`lot_size` is in the same unit as position and order quantities.** NIFTY 65, GOLD 100, GOLDM 10,
  CRUDEOIL 100, CRUDEOILM 10, NATURALGAS 1250, SILVER 30 (matching what the Groww app shows). A GOLD
  position of quantity 100 is one lot, and its P&L is `quantity × price change` (checked against CRUDEOIL's
  `realised_pnl`: 500 × (9168.4 − 9111.0) = 28,700).
- **Never parse expiries from trading symbols.** Groww uses three layouts:

  | Symbol | Layout | Expiry |
  |---|---|---|
  | `NIFTY26OCTFUT` | NSE monthly: year, month | 27 Oct 2026 (the "26" is the year) |
  | `NIFTY26O1918150CE` | NSE weekly: year, one-letter month, day | 19 Oct 2026 |
  | `GOLD04DEC26FUT` | MCX: day, month, year | 4 Dec 2026 |

  `expiry_date` in this file is the answer. The F&O dashboard used to read "26" as the day of
  `NIFTY26OCTFUT` and showed weekly expiries as "N/A".
- **The SDK re-downloads the file in every new process** (`GrowwAPI.instruments` caches it only on that
  object) and writes it to `instruments.csv` inside its own package folder in `site-packages`. It takes
  about 2.7 s. One `GrowwAPIClient` session per process keeps that to once.
