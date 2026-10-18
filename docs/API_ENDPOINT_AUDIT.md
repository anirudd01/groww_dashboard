# API endpoint audit (2026-10-01)

Did the brokers publish endpoints that our local docs or code do not cover? Checked
against each broker's own published spec or docs site. Read-only: nothing here
places orders.

| Broker | Spec source | Result |
|---|---|---|
| **Dhan** | Swagger/OpenAPI at `https://api.dhan.co/v2/v3/api-docs` (47 paths). Saved as [`api/dhan-openapi-2026-10-01.json`](api/dhan-openapi-2026-10-01.json) | **3 endpoints missing from our export**, one of them important (below). All four `/data/*` analytics endpoints are in the Dhan docs export of 2026-10-09 |
| **INDmoney** | No OpenAPI. `https://api-docs.indstocks.com` publishes an "Export for LLMs" file (`/llms-full.txt`) | Same 28 endpoints as our copy. The only differences are our own `[pulse_tester]` corrections. **Do not overwrite** [`indstocks-api-docs.md`](indstocks-api-docs.md) with a fresh download |
| **Kite** | No OpenAPI. Docs at `kite.trade/docs/connect/v3/` (13 pages) | Every endpoint we do not document is trading or account related (orders, GTT, alerts, margins, mutual funds, holdings auctions). We have everything for market data |
| **Groww** | No OpenAPI. The `growwapi` 1.5.0 SDK source (33 endpoints) and the Python SDK docs pages, 2026-10-17 | Every endpoint is now documented in [`api/GROWW_API_*.md`](api/GROWW_API_ORDERS.md). Unused here: order/position update streams, GTT/OCO smart orders, the margin calculator, option chain. No report, tradebook-history or ledger endpoint exists |

## Dhan: three endpoints our export lacked

The public release notes stop at v2.5 (Feb 2026) and mention none of these. On 2026-10-01 they
existed only in the Swagger spec. All are `POST`, under `/v2/data/`, part of the Data API.

**Update 2026-10-18:** the Dhan docs export of 2026-10-09 now documents all four (these three plus
`/data/technical`) as **Market Analytics**, with request parameters and an Annexure of enums. It
has no response schema for `marketmovers` or `newsheadline`. The release notes still stop at v2.5.

| Endpoint | What it does |
|---|---|
| `/data/marketmovers` | **Server-side top gainers / losers.** Categories `PRICE_GAINERS`, `PRICE_LOSERS` (stocks); `TOP_VOLUME`, `OI_GAINERS`, `OI_LOSERS` (futures and options); `HIGHEST_OI` (options only, per the docs' Annexure). Stocks take a `universe`: `FNO_STOCKS`, `NIFTY_50`, `NIFTY_500`, every Nifty and BSE sector index, `SENSEX` and more. `limit` 1-100. Returns ltp, change, `changePercent`, volume, traded value (and OI for derivatives) |
| `/data/companyinfo` | Market cap, industry/sector, valuation and profitability ratios, shareholding pattern, for one stock |
| `/data/newsheadline` | Latest news headlines, filterable by category, with a sentiment label. Max 50 |

`/data/technical` (RSI, MACD, SMA/EMA, pivots and more, computed server-side) is also
in the spec. The 2026-10-09 export documents it: `NSE_EQ` or `IDX_I`, `EQUITY` or `INDEX`,
timeframe `1`, `5`, `15` or `D`, values as of the latest closed candle. Not tried live.

**Tried live 2026-10-01, mid-session:** `marketmovers` with `NSE_EQ`, `EQUITY`,
`PRICE_GAINERS`, universe `FNO_STOCKS`, limit 5 answered in 0.4 s with 200 OK and
correct-looking data (COFORGE +3.73% on top). `PRICE_LOSERS` took 0.7 s. `NIFTY_IT`
also worked. **This corrects [`FNO_MOVERS.md`](FNO_MOVERS.md), which said no broker
had a top-movers API.**

**Adopted 2026-10-02** as the Dhan Movers page ([`DHAN_MOVERS.md`](DHAN_MOVERS.md)), which records what the
endpoint does in practice: `DH-907` is an empty ranking, derivative `expiry` snaps to the monthly
contract, and it returns the last session after the close.

What it does *not* replace: it ranks **today against the previous close only**, so the
3 / 5 / 10 / 20 / 30 / 50 / 100-day views still come from stored closes. It is in the API reference since the 2026-10-09 export but still absent from the release
notes, so treat it as something that may change. Outside market hours it returns the last session's moves with no date: on the holiday of
Fri 2 Oct 2026 it answered with Thu 1 Oct's. The date has to come from `last_trade_time` in the quote
endpoint. It has no paging (`limit` is capped at 100; `offset`/`page` are ignored), and 58 universes
are listed in the Swagger spec, 31 of them working on `NSE_EQ` ([`DHAN_MOVERS.md`](DHAN_MOVERS.md)). The
2026-10-09 docs export lists only 33, NSE only, three spelled differently from the ones tested. Still untested:
before the open.

## Kite: what exists that we do not use

Alerts (`/alerts`), GTT (`/gtt/triggers`), order and basket margin (`/margins/orders`,
`/margins/basket`, `/charges/orders`), mutual funds (`/mf/*`), holdings auctions.
"Auction" in Kite's docs is the **holdings trade-in auction** order variety, not the
closing auction session (CAS). Nothing in Kite's docs covers pre-open, CAS or
post-close market data.

## Dhan, in the other direction

The Swagger spec has **no** market-quote, option-chain, live-feed or instrument-list
paths (those come from the docs pages in our export), so neither source alone is
complete. Global stocks (`/globalstocks/*`), conditional orders, super/forever orders,
EDIS and static-IP endpoints are in both; none is used here.
