# MCX commodity futures

A navbar page ("MCX Futures", in the **MCX** row) showing MCX commodity futures: one row per
commodity with last price, change against the previous close, the day's range, volume and open
interest, plus candle charts. Dhan serves it; Kite takes over automatically when Dhan fails, and
INDmoney (free) when both do.

Visualisation only: it places no orders and generates no signals.

```bash
streamlit run pulse_dashboard.py                                  # the "MCX Futures" page
streamlit run apps/mcx_futures_dashboard.py --server.port 8512    # on its own
python scripts/dhan.py --master                               # the contract list; run monthly
python scripts/indmoney.py --master                           # which of them INDmoney lists; run monthly
```

Code: [`apps/mcx_futures_dashboard.py`](../apps/mcx_futures_dashboard.py) (page),
[`market/mcx_futures.py`](../market/mcx_futures.py) (contracts, choice, fallback, parsing),
`get_quotes` / `get_candles` in [`market/providers/dhan.py`](../market/providers/dhan.py),
[`market/providers/kite.py`](../market/providers/kite.py) and
[`market/providers/indmoney.py`](../market/providers/indmoney.py), tests in `tests/test_mcx_futures.py`.

## Which provider, and why

| Broker | MCX? | Role |
| --- | --- | --- |
| **Dhan** | ✅ quotes, minute and daily candles, all with OI | **Primary.** Its token is minted from TOTP, so it works with no one at the machine, and it keeps the session's volume after the close |
| **Kite** | ✅ same prices, OHLC and OI as Dhan, to the paisa | **Fallback.** Needs `python scripts/kite_login.py` each morning (the token dies at 06:00 IST). After the close it reports volume as 0 |
| INDmoney | ⚠️ quotes only (since Oct 2026): same prices, OHLC and OI as Kite, free, TOTP login. 19 of 28 commodities, nearer expiries only; no candles, no last-trade time | **Last resort.** Serves the table when Dhan and Kite both fail; the chart then has no candles ([retest 2026-10-17](PROVIDER_GUIDE.md#mcx-on-indmoney-retested-2026-10-17)) |
| Groww | Positions only in this repo | Not used |

Dhan and Kite were measured live on 2026-10-03, INDmoney on 2026-10-17; the side-by-side tables are in
[PROVIDER_GUIDE.md](PROVIDER_GUIDE.md#mcx-on-dhan-and-kite-tested-2026-10-03).

### How the fallback works

`quotes_with_fallback` tries Dhan, then Kite, then INDmoney, and uses the first one that prices
anything. A broker that connects but returns no prices counts as failed, because Dhan's quote helper
logs an API error and returns an empty result rather than raising. A broker with no stored ids fails
with the script to run. Candles try the broker that served the quotes first, then the others.

- When Kite is serving, a yellow notice says so and gives Dhan's reason (for example
  "Showing Kite because Dhan: Dhan authentication failed").
- If all three fail, the page shows each broker's reason. With no Kite login today that reason is
  "No Kite session for today - run 'python scripts/kite_login.py'".
- When INDmoney is serving:
  - Only the contracts INDmoney lists are asked for: one id it does not list fails its whole call with
    HTTP 400. The caption names the commodities left out (agri, LEAD, STEELREBAR, ELECDMBL, SUNOIL).
  - It gives no last-trade time, so the "Last trade" column is blank and "Live" (and auto-refresh) is
    judged from MCX's weekday hours, 09:00 to 23:55 IST. Exchange holidays are not known, so on a
    weekday holiday the page counts as live and refreshes every 30 s.
  - The chart asks INDmoney for candles first; it returns none for MCX, so Dhan and then Kite are tried.
- Each refresh (every 30 s while trading, or "Refresh now") tries Dhan first again, so the page
  returns to Dhan as soon as Dhan recovers.

## The page

| Part | What it shows |
| --- | --- |
| Badge | **Live** if any contract traded in the last 5 minutes, else **Last trade: Thu 01 Oct, 23:29**. Judged from the data, so MCX holidays need no calendar |
| Cards | Gold, silver, crude oil, natural gas and copper (most active contract): last price and change % |
| Table | One contract per commodity, grouped Bullion → Energy → Base metals → Agri. Change % is shaded green/red, darkest for the biggest move. Click a row to chart it (gold by default) |
| Chart | Candles (green up, red down) with open interest underneath. 5 min (4 days), 15 min (10 days), 1 hour (30 days) or Daily (1 year) |

Sidebar:

- **Contract**: *Most active* (default), *Near*, *Next* or *Far*.
  - *Most active* is the contract with the highest open interest, then volume. MCX liquidity doesn't follow
    the calendar: on 1 Oct 2026, GOLD OCT (expiring 5 Oct) had 169 lots of OI and GOLD DEC had 15,955.
  - Near/Next/Far are the 1st/2nd/3rd unexpired contracts. A commodity with fewer live expiries is left out.
- **Groups**: show or hide Bullion, Energy, Base metals and Agri.
- **Show mini contracts**: off by default. GOLDM, GOLDGUINEA, GOLDPETAL, GOLDTEN, SILVERM, SILVERMIC, SILVER100,
  CRUDEOILM, NATGASMINI, ALUMINI, ZINCMINI and LEADMINI move with their main contract.
- **Auto-refresh**: every 30 s, only while the badge says Live.
- **Refresh now**: clears the caches and reconnects both brokers.

The contract-month choice and the chart interval are bound to the URL (`?mcx_pick=Near&mcx_interval=Daily`).

Cost per refresh: one quote call (all ~160 live contracts fit in one call on either broker), plus one
candle call when the chart's contract or interval changes (candles are cached for 60 s).

## The contract list

`scripts/dhan.py --master` stores every MCX commodity future in the `mcx_futures` set of
`data/market.db`:

- **Dhan:** every `FUTCOM` row of Dhan's public instrument master, the same 35 MB CSV that
  `scripts/dhan.py --master` reads (`--use-cached` reuses today's saved copy). Options (`OPTFUT`) and
  MCX index futures (`FUTIDX`) are left out.
- **Kite:** each contract's `instrument_token` and `tradingsymbol` (`CRUDEOIL26OCTFUT`), from Kite's public
  `/instruments/MCX` list (1.3 MB), matched on commodity and expiry.
  - If Kite's list can't be fetched, the contracts are stored without Kite ids and there is no fallback
    until the next run.
- **What was stored on 2026-10-03:** 164 contracts across 28 commodities, all with Kite ids. The last expiry
  is March 2028.
- **INDmoney:** `scripts/indmoney.py --master` stores which of these INDmoney lists (`indmoney_mcx`), from its
  `/market/instruments?source=mcx`. INDmoney's `SECURITY_ID` is MCX's token, the same id as Dhan's, so the two
  sets join on it. 93 contracts across 19 commodities on 2026-10-17.

The page never downloads either list. Re-run the script about monthly, since new expiries are listed as old
ones lapse. The page shows a warning once the stored list runs out within 45 days, and says which script to
run if nothing is stored.

## Quirks worth knowing

- **`ohlc.close` is the previous session's close**, on all three brokers, and it stays that way after the
  session and at the weekend. Change is measured against it.
  - Except on Kite, not always: on Saturday 17 Oct Kite gave NATURALGAS OCT Friday's own close (298.6) as
    `ohlc.close`, so its change read ~0%, while for GOLD DEC it still gave Thursday's. INDmoney gave Thursday's
    for both (306, matching Kite's daily candle), the -2.45% Friday really moved.
- **Daily candles are a continuous series.**
  - Dhan returns a year of daily candles even for a contract listed months ago. Open interest drops at each
    monthly roll.
  - Kite does the same only with `continuous=1`, which the page sends for daily candles so both brokers draw
    the same chart.
- **The daily close is MCX's close, not the last trade.** CRUDEOIL OCT closed at 8,916 on 1 Oct on both
  brokers' daily candles, against a last trade of 9,008.
- **Untraded contracts**, mostly in agri, show no volume or OI, and their last trade is blank.
  - Dhan sends `01/01/1980` as the last trade time and Kite sends `1970-01-01 05:30:00`. Both are treated as
    "never traded".
  - Their change is 0.00% because the last price equals the previous close.
- **Lot size and tick size are not shown.** Dhan's master lists lot size 1 and tick size 100 for every MCX
  future, which isn't credible.
- **MCX hours:** 09:00 to 23:30 IST, or 23:55 while the US is on summer time. Some agri contracts close
  earlier: MENTHAOIL's last trade on 1 Oct was at 16:59.
