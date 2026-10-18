# Groww: paid data plan checks

On 2026-10-17 the account was on Groww's **free API plan**: login, account, positions, orders and the instrument
list worked, and every market-data call answered `Access forbidden for this request.` The paid data plan has been
active since **2026-10-18**. This page lists what had to be confirmed live once it was, the answers so far, and the
checks still open (⏳).

## How to run them

```bash
python scripts/debug/probe_groww.py               # read-only; prints [OK]/[ERR] per call and a CHECK line per question
python scripts/debug/probe_groww.py --socket 20   # adds 20 s on the live socket (run during market hours)
```

Still to do: run it **during market hours** (NSE 09:15-15:30, MCX until 23:30/23:55) for checks 3, 7 and 9, and
once with an MTF position open for check 6. On 2026-10-18 both pages (`streamlit run apps/fno_dashboard.py`,
`streamlit run apps/app.py`) loaded the live account with every position priced and no warnings.

## The checks

First run on the paid plan: **Sunday 2026-10-18**, after hours. ✅ = answered, ⏳ = still open.

| # | Question | Answer | Where it went |
|---|---|---|---|
| 0 | Do the market-data calls answer now? | ✅ Yes, about 0.35 s each: quotes, LTP, OHLC, NSE candles, expiries, NSE option chain, NSE Greeks. **MCX: prices only**, no candles (empty answer), no option chain ("Underlying not found"), no Greeks ("Internal error occurred") | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md), [PROVIDER_GUIDE.md](PROVIDER_GUIDE.md), README |
| 1 | Does batched `get_ltp` work for MCX? | ✅ Yes. `get_ltp_for_mcx` now batches 50 per call (`batched_ltp`). Found on the way: one unknown symbol fails the whole batch, so that batch is retried symbol by symbol | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 2 | Do daily candles still have `open = None`? | ✅ Yes, for stocks and NSE futures, and for some intraday candles too. Groww stays out of gap work | PROVIDER_GUIDE "Weaknesses" |
| 3 | Is `get_ohlc`'s `close` the previous session's close? | ✅ After hours, yes: on Sunday RELIANCE `close` was Thursday's 1215.0 and the last price Friday's 1211.2. ⏳ Confirm once during a session | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 4 | Does `get_quote` return `market_cap` and the 52-week range? | ✅ 52-week high/low yes; **`market_cap` is `None`** | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 5 | Is `get_greeks` `{"greeks": {delta, gamma, theta, vega, rho, iv}}`, and does it work for MCX? | ✅ Shape confirmed for NSE. **MCX: no**, so MCX options are no longer asked for and the Greeks tab says why | Greeks tab; [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 6 | Do MTF stocks appear in `get_holdings_for_user` as well as in positions? | ⏳ The account held no stocks and no MTF positions on 2026-10-18. Run the probe with one open | [api/GROWW_API_PORTFOLIO.md](api/GROWW_API_PORTFOLIO.md); fix `get_processed_portfolio` if not |
| 7 | Does the socket stream ticks, and is the handshake still slow? | ⏳ Needs market hours: `--socket 20` | [api/GROWW_API_FEED.md](api/GROWW_API_FEED.md) |
| 8 | Is an **OCO smart order with `GTC`** accepted for an F&O and an MCX carry-forward position? | ⏳ Needs one real order, with you present | [api/GROWW_API_ORDERS.md](api/GROWW_API_ORDERS.md) |
| 9 | For a **carry-forward** position, does the F&O page's P&L match the Groww app? | ⏳ New (2026-10-18). The page now derives the open quantity's cost from the fills and `realised_pnl` because `net_price` is wrong after a partial exit (GOLD showed −24,080 instead of −40,000). Unknown: whether `carry_forward_*_price` is the original price or the last settlement price, and whether `realised_pnl` covers earlier days. On a trading day with GOLD still held from Friday, compare the page's entry and P&L to the app's, and print the raw position (`probe_groww.py` shows it) | [api/GROWW_API_PORTFOLIO.md](api/GROWW_API_PORTFOLIO.md); `open_entry_price` in `groww_api/position_processor.py` |

**Check 8 places a real order.** It is not in the probe. Do it by hand, with the account holder present: one OCO
far from the market on a one-lot position, read it back with `get_smart_order_list`, then cancel it with
`cancel_smart_order`.

## Already settled (no need to re-check)

- No API returns order history beyond today, a P&L report, tradebook, ledger or contract notes: use the Excel
  exports ([api/GROWW_API_ORDERS.md](api/GROWW_API_ORDERS.md)).
- Instrument list units: MCX `tick_size` in paise, `lot_size` in position units (GOLD 100, GOLDM 10, CRUDEOIL 100,
  CRUDEOILM 10, NIFTY 65) ([api/GROWW_API_INSTRUMENTS.md](api/GROWW_API_INSTRUMENTS.md)).
- Margins: per-segment "used" figures negative, commodity margins in paise ([api/GROWW_API_PORTFOLIO.md](api/GROWW_API_PORTFOLIO.md#margins)).
- The socket has no MCX topic; the SDK accepts CASH and FNO only.

When a check is answered, record the result with its date in the doc named in the table and tick it off here.
