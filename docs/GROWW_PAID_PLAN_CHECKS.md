# Groww: checks to run once the paid data plan is active

On 2026-10-17 the account was on Groww's **free API plan**. Login, account, positions, orders and the instrument
list worked; every market-data call answered `Access forbidden for this request.`
([api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md)). The code was corrected that day so nothing depends on
the unknowns below, but each one needs a live answer before building on Groww's prices.

## How to run them

```bash
python scripts/debug/probe_groww.py               # read-only; prints [OK]/[ERR] per call and a CHECK line per question
python scripts/debug/probe_groww.py --socket 20   # adds 20 s on the live socket (run during market hours)
```

Run it **during market hours** (NSE 09:15-15:30, MCX until 23:30/23:55) for checks 3 and 7, and once with an
option and an MTF position open for checks 5 and 6. Then open the F&O page (`streamlit run apps/fno_dashboard.py`)
and the Portfolio page (`streamlit run apps/app.py`): the "no live price" warnings should be gone.

## The checks

| # | Question | Why it matters | Where the answer goes |
|---|---|---|---|
| 0 | Do the market-data calls now answer (quotes, LTP, OHLC, candles, option chain, Greeks)? | The whole point of the plan | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) top section, [PROVIDER_GUIDE.md](PROVIDER_GUIDE.md) Groww section, README Setup note |
| 1 | Does batched `get_ltp` work for MCX (`MCX_<symbol>`, segment `COMMODITY`)? | The repo prices MCX positions with one `get_quote` per contract (`GrowwAPIService.get_ltp_for_mcx`); a batch of 50 would be one call | If yes, switch `get_ltp_for_mcx` to batches of 50 |
| 2 | Do daily candles still have `open = None`? | Measured in Sept 2026; rules Groww out for gap calculations | PROVIDER_GUIDE "Weaknesses" |
| 3 | Is `get_ohlc`'s `close` the previous session's close, during the session and after it? | `get_previous_close_nse_cash` (heatmap's Groww provider) assumes it is | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md); fix the provider if it is today's close after hours |
| 4 | Does `get_quote` return `market_cap`, `week_52_high`, `week_52_low` with real values? | Documented, never seen | [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 5 | Is the `get_greeks` answer `{"greeks": {delta, gamma, theta, vega, rho, iv}}`, and does it work for **MCX** options? | The F&O page's Greeks tab reads exactly that shape (`GrowwAPIService.get_greeks`) | Greeks tab; [api/GROWW_API_LIVE_DATA.md](api/GROWW_API_LIVE_DATA.md) |
| 6 | Do MTF stocks appear in `get_holdings_for_user` as well as in positions? | The Portfolio page (`groww_client.py`) assumes holdings include them and values the portfolio from holdings only ([api/glossary.md](api/glossary.md)) | [api/GROWW_API_PORTFOLIO.md](api/GROWW_API_PORTFOLIO.md); fix `get_processed_portfolio` if not |
| 7 | Does the socket stream ticks, and is the handshake still slow? | The heatmap's Groww feed; [api/GROWW_API_FEED.md](api/GROWW_API_FEED.md) | GROWW_API_FEED.md observed section |
| 8 | Is an **OCO smart order with `GTC`** accepted for an F&O and an MCX carry-forward position? | The morning stop-loss + target automation; if OCO lasts across days, no daily job is needed for Groww | [api/GROWW_API_ORDERS.md](api/GROWW_API_ORDERS.md) |

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
