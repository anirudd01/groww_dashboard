# Dhan API explorer

The **Tools → Dhan API Explorer** page of `pulse_dashboard.py` sends one Dhan market-movers
request (`POST https://api.dhan.co/v2/data/marketmovers`) and shows the reply exactly as it
comes back. Nothing is stored, and nothing is sent until a button is pressed.

```bash
streamlit run pulse_dashboard.py                               # Tools -> Dhan API Explorer
streamlit run apps/dhan_api_explorer.py --server.port 8506     # or just this page
```

| File | Role |
|---|---|
| [`apps/dhan_api_explorer.py`](../apps/dhan_api_explorer.py) | The page |
| [`market/dhan_movers.py`](../market/dhan_movers.py) | `build_request` (the body), `universe_members` (gainers + losers -> members) |
| [`tests/test_dhan_api_explorer.py`](../tests/test_dhan_api_explorer.py) | Page and helper tests, Dhan faked |

## Request screen

Pick the instruments (stocks, stock/index futures, stock/index options), the ranking, a limit
(1-100) and a universe (stocks) or expiry (derivatives). The request body is shown as JSON and
can be edited by hand before **Send**: it is sent exactly as written, so any universe key Dhan
accepts can be tried. The reply shows as status, time taken and row count, then a table of
every field, the raw JSON (downloadable) and the body that was sent.

A stock row carries: `securityId`, `exchangeSegment`, `tradingSymbol`, `displayName`,
`instrument`, `expiry`, `strikePrice`, `tickSize`, `lotSize`, `ltp`, `change`, `changePercent`,
`volume`, `tradedValue`, `underlyingSecurityId`, `underlyingLtp`, `premiumDiscount(Percent)`,
`openInterest`, `openInterestChange(Percent)`, `putCallRatio`. **There is no sector or industry
field.**

## Members screen: can the rankings replace the NSE lists?

The question this screen answers: since the Dhan Movers page shows sector universes and the
stocks in them, could one call give each stock's sector and spare the `--master` download of
NSE's constituent lists? Choose a stored NSE index (Nifty 50 or Next 50) and some Dhan
universes; for each universe the page fetches gainers and losers (100 each) and ticks the
members it finds, next to the NSE sector from the stored list.

Measured on 2026-10-15, Nifty 50 against the 12 NSE sector universes:

| Finding | Detail |
|---|---|
| Membership of a broad list: yes | `NIFTY_50` gainers (42) + losers (8) were exactly the 50 stocks in NSE's list. Caveats: a side of 100 rows may be cut short, and a stock that has not traded yet today appears in neither |
| Sectors: no | Rows have no sector field, and the sector *universes* are NSE's sector *indices*, a different thing from a classification |
| 12 Nifty 50 stocks are in no sector universe | ASIANPAINT, BAJAJFINSV, BAJFINANCE, BEL, BSE, ETERNAL, HDFCLIFE, JIOFIN, SBILIFE, SHRIRAMFIN, TITAN, TRENT. No universe exists for Financial Services, Capital Goods, Consumer Durables or Consumer Services |
| 9 are in two or more | The private banks are in both `NIFTY_BANK` and `NIFTY_PRIVATE_BANK`; NTPC, ONGC, POWERGRID and RELIANCE in both `NIFTY_ENERGY` and `NIFTY_INFRA` |
| Sector indices are wider than the Nifty 50 | e.g. `NIFTY_ENERGY` has 40 members, 5 of them in the Nifty 50; `NIFTY_REALTY` and `NIFTY_MEDIA` have none |

So the stored NSE lists (`index_constituents`, from `--master`; see
[SECTOR_HEATMAP.md](SECTOR_HEATMAP.md#instrument-universe-and-sector-mapping)) stay the source
of membership and sectors. The marketmovers call would also tie the heatmap's universe to a
live call that Dhan only answers during and after a session, which the "generated offline,
read at runtime" rule exists to avoid.
