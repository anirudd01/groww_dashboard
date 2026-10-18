# Trade journal (Dhan)

The **Trade Journal** page (`pulse_dashboard.py` → Journal, or `streamlit run apps/dhan_journal_dashboard.py`)
turns your Dhan fills and ledger into round trips and measures them **after costs**. It answers whether the
trading makes money, where, and what it costs. Built 2026-10-18.

It reads account statements only and places no orders. Groww is not in it: Groww has no API for trade history
or P&L ([api/GROWW_API_ORDERS.md](api/GROWW_API_ORDERS.md)).

## Getting the data

```bash
python scripts/dhan.py --journal                      # from a few days before the newest stored fill to today
python scripts/dhan.py --journal --since 2026-04-01   # refetch from a date
```

The page's **Sync now** button runs the same code (`market.dhan_journal.sync`).

- **The first sync** starts at the beginning of the financial year (1 April).
- **Later syncs** refetch the last 5 days and replace them. Dhan can correct a day, and fills have no unique id
  (below), so replacing whole days is the only safe merge. Running a sync twice changes nothing.
- **Today's fills** come from the trade book, which has no charges. They show as "Charges pending" and stay out
  of the statistics until the next day's sync swaps in the history version.
- **Open positions** are priced at the last traded price at sync time (`/marketfeed/ltp`, needs the Data API
  plan). Without the plan the sync still works and says how many it could not price.
- About 10 calls for 200 fills, a few seconds. Needs the Dhan credentials in `.env`, like the other Dhan pages.

| Table (`data/market.db`) | Holds | Rebuildable? |
|---|---|---|
| `dhan_fills` | One row per fill: time, contract, side, quantity, price, the six charges | Yes: `--journal --since <date>` |
| `dhan_ledger` | Ledger entries (opening/closing balance rows dropped) | Yes, the same way |
| `runtime_state` row `dhan_journal_sync` | Last sync time, and the last prices of open positions | Yes: sync again |

Setup tags per round trip were built on 2026-10-18 and removed the same day at the account holder's request
(none had been saved). A `dhan_trip_tags` table may remain in an older `market.db`; nothing reads it.

## Dhan's statement APIs (checked live 2026-10-18)

| Call | What it gives | Found |
|---|---|---|
| `GET /v2/trades/{from}/{to}/{page}` | Every fill in the range, with brokerage, STT, exchange charges, SEBI fee, stamp duty and GST | **20 fills per page**; walk pages until one is empty. Ranges before the account opened return `[]` |
| `GET /v2/trades` | Today's fills | No charge fields |
| `GET /v2/ledger?from-date=&to-date=` | Every ledger entry | Newest first; amounts are strings; dates like `Oct 16, 2026`; includes `OPENING BALANCE` (dated 1970) and `CLOSING BALANCE` rows |

Both are account APIs and work without the Data API plan.

Quirks:

- **`exchangeTradeId` is always `"0"`** and **`orderType` is null** in the history, so a fill has no unique id.
- `exchangeTime` is `2026-10-16T20:32:15` in the history and `2026-10-16 20:32:15` in the trade book. `createTime`
  and `updateTime` are `"NA"`.
- `tradingSymbol` is null; `customSymbol` carries the name (`GOLD DEC FUT`, `NIFTY OCT FUT`, `HBL Engineering`).
- Cash-equity fills have `productType` null.
- **A day's STT (MCX: CTT) and stamp duty for a contract sit on one fill.** On 2026-10-16 one NIFTY sell carried
  Rs 60,042 STT, 0.05% of all four sells that day; GOLD's CTT likewise (0.01% of the day's sells). The day's
  total is right, the split is not. `spread_day_charges` spreads them by trade value over the side that pays:
  STT on sells (both sides for delivery equity), stamp duty on buys. Without it one round trip a day carried
  the whole day's tax (one NIFTY trip showed -82,567 instead of about -36,000).
- `/v2/positions` reports MCX quantity in **lots** (`buyQty: 2`, `multiplier: 100`), but its `unrealizedProfit`
  ignores the multiplier (−1,002 for a position that was −1,00,200). The journal does not use it.

## How the numbers are made

**Quantity × price change is the P&L, with no lot multiplier.** The history's `tradedQuantity` is in the unit
the price is quoted in (GOLD 200 = 2 lots of 100). Checked by reconciling 189 fills (MCX, NSE F&O, NSE cash) with
the ledger:

| Segment | Ledger | Journal (closed after charges, open at last price) | Difference |
|---|---|---|---|
| NSE F&O | −3,71,573.43 | −3,71,571.92 | 1.51 |
| NSE cash | 8,783.20 | 8,783.15 | 0.05 |
| MCX | 1,60,051.07 | Matches to 5.46 with the open GOLD at its settlement price | — |

The page's **Checks** view shows this table, live, for MCX and NSE F&O.

**A round trip** is one position on one contract and product, from flat to flat. Every fill that adds to it or
reduces it belongs to it. A fill that reverses the position (long 100, sell 300) is split: 100 closes the trip,
200 opens a short, and the fill's charges are shared by quantity. Prices are averaged within the trip, so a
closed trip's gross P&L is exactly money received minus money paid. Its id is
`<security id>:<product>:<first order id>`, stable across re-syncs.

**Left out of the statistics:**
- open trips;
- trips with today's uncharged fills;
- **"bought before the history"**: a delivery sale (CNC or MTF, or cash with no product) from a flat position,
  meaning the shares were bought before the first stored fill. Sync from an earlier date to include them.

**Statistics** (closed round trips, net of charges, in closing order):

| Statistic | How it is computed |
|---|---|
| Win rate | Share of trips with net > 0 |
| Expectancy | Average net per trip |
| Profit factor | Total won ÷ total lost |
| Win / loss size | Average win ÷ average loss |
| Max drawdown | Largest fall of cumulative net from a peak, trip by trip |
| Worst losing streak | Consecutive losing trips |

**Daily P&L** (the Daily P&L view and the loss-limit count):
- **MCX and NSE F&O** use the ledger's "Trades Executed for the Day" line. That line is Dhan's daily settlement,
  net of charges, with positions held overnight marked to market. So a day shows what it did to the account,
  even with nothing closed.
  - Proof: on days with nothing held overnight, it equals that day's closed P&L minus charges exactly
    (2026-10-12: 4,200 − 31,237.11 = −27,037.11).
- **NSE cash** uses the closed round trips on the day they closed. The cash ledger line is money paid and
  received for shares, not P&L.
- **Options:** none were in the history when this was built. For an option, the F&O ledger line will likely
  carry the premium paid or received rather than a mark-to-market, so a day with an open long option would show
  the premium as a loss. Check this the first time options are traded.

**The daily loss limit** defaults to ₹50,000 (`DAILY_LOSS_LIMIT`), the account holder's choice. The page lets you
change it for the session. A day counts when its total for the chosen segments is below minus the limit.

**Other costs** are ledger debits that belong to no trade: interest (margin, MTF), data API and DDPI fees,
pledge charges, square-off charges. They appear under Costs and are not part of any round trip's net.

## The page

- **Filters:**
  - **Period** buttons: Financial year, Month, Week, each with a count (1 = the current one, 2 = this one and
    the one before, and so on; weeks start on Monday). **Dates** opens a calendar for any range.
    The default is this financial year.
  - Segments, and the daily loss limit.
- **Headline:**
  - net P&L, charges, round trips, win rate, expectancy, profit factor;
  - average win and loss, win/loss size, max drawdown, worst losing streak, days over the limit.
- **Views:**
  - **Daily P&L:** bars against the limit line, the cumulative curve, and the days over the limit.
  - **Trades:** open positions at the sync price, then the closed round trips **grouped by contract, side and
    product**: trips, win rate, average size, average points captured, median time held, gross, charges, net
    and net per trip.
  - **Breakdown:** every split one after the other, each a chart and a table: underlying, side, holding time,
    product, entry weekday,
    entry hour or segment.
  - **Costs:** charges by kind (STT and MCX's CTT apart: Dhan reports both in one field, so fills on MCX are
    counted as CTT), charges as a share of gross P&L, by segment, and the other ledger costs.
  - **Checks:** the reconciliation above, and any trips left out of the statistics.

## What the first sync showed (2026-09-04 to 2026-10-16, 50 closed round trips)

| | |
|---|---|
| Net after charges | −85,349 |
| Charges | 2,78,020: **more than the 1,92,671 gross P&L** |
| Win rate | 58% |
| Average win / average loss | 36,248 / −54,122 (0.67) |
| Profit factor | 0.92 |
| By underlying | GOLD +7,31,975 (26 trips, 73% wins); NIFTY −3,71,572; ELECDMBL −3,23,506; GOLDM −1,56,521 |
| Charges per round trip | GOLD 2 lots about 5,150 (CTT 0.01% of the sell, stamp 0.002% of the buy, about 1,600 the rest); NIFTY 20 lots (1,300) about 17,000 (STT 0.05% of the sell is about 15,000) |
| By holding time | Overnight −3,27,988 over 11 trips; held under 5 minutes −1,33,238 over 2 trips |
| Days below −50,000 | 10 of 30 |

## Code

| File | Does |
|---|---|
| [`market/dhan_journal.py`](../market/dhan_journal.py) | Dhan calls, parsing, the tables, sync, round trips, statistics, daily P&L, reconciliation |
| [`scripts/jobs/dhan_journal.py`](../scripts/jobs/dhan_journal.py) | `scripts/dhan.py --journal` |
| [`apps/dhan_journal_dashboard.py`](../apps/dhan_journal_dashboard.py) | The page |
| `tests/test_dhan_journal.py` | Parsing, round trips (scaling, shorts, flips, products, delivery sales), statistics, daily P&L, sync, retries, the page |
