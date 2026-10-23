# Sector Heatmap Roadmap

Where the live sector heatmap is, and what is planned next. The design
constraint below applies to every phase, without exception.

> **This is a visualisation and research tool.** No phase will add order
> placement, automated trading, buy/sell signals, or BUY/SELL/LONG/SHORT
> labels. Features describe what the market *did*; they never recommend what to
> do about it.

---

## Phase 1 — complete

The live board and the drill-down.

| | |
|---|---|
| Live feed | Dhan websocket (quote packets), with Dhan REST → Groww websocket → Groww REST behind it |
| Screen 1 | Clickable sector tiles, coloured by percentage change |
| Screen 2 | Constituent table, sorted by live change, colour graded |
| Previous close | From each broker's OHLC endpoint — never inferred from a tick |
| Aggregation | Equal-weighted mean of constituent percentage changes (Phase 1; market-cap weighted only since 2026-10-18, see Phase 2) |

## Phase 2 — complete

Breadth and weighting.

| | |
|---|---|
| Market-cap weighting | Free-float cap weights from the `index_weights` set in `data/market.db`. The only sector % method since 2026-10-18: the sidebar's Equal / Market-cap switch was removed at the user's request, with its code, config and tests; a sector with no weighted member still falls back to a plain mean and says so |
| Weights pipeline | `scripts/dhan.py --master` (Dhan `companyinfo`: market cap x (1 - promoter holding)) — run manually, stores `index_weights`, never called at runtime |
| Breadth | Advancing/declining counts, sectors up vs down, average day-range position |
| Day range | Open/high/low/volume from Dhan quote packets, with the OHLC endpoint as the REST fallback |
| Leaders / laggards | Two tables under the heatmap: each advancing sector with its best stock, each declining sector with its worst |
| Tile weight and order | Every tile shows its weight in the index and its impact on it; tiles ordered by biggest impact (default), largest sector or biggest move, on all four boards (`market/sector_impact.py`). Replaced the alphabetical order (2026-10-18) |

## Phase 3 — complete

The **sectoral index board**: a second page showing the real NSE indices rather
than an aggregate of the Nifty 50 members we track.

| | |
|---|---|
| Page | Separate board, chosen in the sidebar. Its own feed, universe and drill-down |
| Tiles | 14 NSE sectoral indices plus Nifty 50, Nifty Next 50 and Nifty 500 as benchmarks |
| Data | Dhan `IDX_I` segment — REST for previous close, websocket for live values |
| Drill-down | The Nifty 50 members of the matching sector, explicitly labelled as *not* the index's real constituent list |
| Index list | `market/index_mapping.py` — one row per tile, ids resolved from the instrument master |

Why both boards exist: the Nifty 50 board answers *"how are the Nifty 50's IT
names doing"*, the index board answers *"how is the IT sector doing"*. They are
expected to disagree, and the gap is the information — it shows large caps
moving differently from the wider sector.

## Phase 4 — complete

Previous close outside market hours.

| | |
|---|---|
| The problem | Brokers repoint the OHLC `close` field at *today's* close once trading stops, so a dashboard started after 15:30 read +0.00% on every tile |
| Fix | Outside the session the previous close comes from daily candles (`POST /v2/charts/historical`) instead, via the new optional `get_prior_session_close` on the provider interface |
| Candle selection | The last candle strictly before the session the current price belongs to — correct whether or not today's own candle has been published yet |
| No silent fallback | A symbol the candles cannot cover stays unresolved and shows as a data gap; it is never filled from the OHLC field, which is known to be wrong at exactly that moment |
| Switch | `PULSE_HEATMAP_HISTORICAL_PREV_CLOSE=false` skips the lookup and accepts the flat board |

## Phase 4b — complete

Boot time.

| | |
|---|---|
| The problem | Dhan's 35 MB scrip master, served uncompressed with no zip or gzip variant, was downloaded on every boot — and once per board, since the cache was a per-instance attribute. 15-40 s to obtain sixty numbers |
| Fix | Moved out of the runtime entirely. `scripts/dhan.py --master` downloads it offline and writes a 12 KB the `dhan_instruments` set in `data/market.db`; the dashboard reads that at startup and never fetches an instrument master |
| Effect | Instrument resolution is now instant and offline. No pandas, no network, on the boot path |
| Cadence | Re-run after an NSE reconstitution (end of March / end of September), after editing the sector mapping, or when a symbol stops resolving. The loader warns past 90 days |
| Precedent | Same contract as the weights: generated offline, stored, never fetched live |

## Phase 4c — complete

A second live broker, switchable, so brokers can be compared.

| | |
|---|---|
| INDmoney provider | `market/providers/indmoney.py` over the INDstocks REST + websocket APIs. Free; token minted from TOTP (see below). Live on both boards (16/17 indices — Nifty Oil & Gas is not served by INDmoney) |
| Instrument ids | `scripts/indmoney.py --master` → the `indmoney_instruments` set in `data/market.db`, same offline contract as Dhan's |
| Provider switch | Sidebar **Data provider**: Auto (configured order with failover) or one broker pinned, no failover |
| Default chain | `dhan,indmoney,groww` — INDmoney ahead of Groww because it also serves the index board |
| Shared candle logic | Previous-close selection moved to `market/providers/candles.py`, so the next broker only converts its candle format |
| Comparison | [`api/INDMONEY_API.md`](api/INDMONEY_API.md) — Dhan vs INDmoney capability table and the live behaviours the vendor docs get wrong |

## Phase 4d — complete (verified live 2026-09-25)

Zerodha Kite as the fourth broker, read-only.

| | |
|---|---|
| Kite provider | `market/providers/kite.py`: REST quotes (`/quote`, `/quote/ohlc`, `/quote/ltp`), daily candles for the previous close outside market hours, and the binary `wss://ws.kite.trade` feed in `quote` mode. No `kiteconnect` SDK, because its Twisted-based ticker cannot reconnect within a process |
| Login | `market/providers/kite_session.py` + `scripts/kite_login.py`: browser login, `request_token` → `access_token`, saved to the shared database (`data/market.db`, git-ignored) with its **06:00 IST** expiry. The API secret is never stored |
| Instrument ids | `scripts/kite.py --master` → the `kite_instruments` set in `data/market.db` (instrument token + tradingsymbol), from Kite's public NSE dump. 67/67 symbols resolved on 2026-09-25 |
| Default chain | `dhan,indmoney,groww,kite`: Kite is last, because it needs a login every morning |
| Read-only | No order, GTT or alert endpoint is referenced; `tests/test_kite.py` asserts it |

## F&O movers dashboard — complete (2026-09-25)

A separate page, not part of the heatmap: [`FNO_MOVERS.md`](FNO_MOVERS.md).

| | |
|---|---|
| Page | `apps/fno_movers_dashboard.py`: top gainers/losers per day, for the last 1/3/5/7 days, in Nifty 50 and All F&O (210) tabs |
| History | `scripts/kite.py history` → the `daily_bars` table in `data/market.db` (one row per stock per day). One Kite request per stock per run, whatever the range |
| Today | One bulk `/quote/ohlc` for all 210 stocks, cached 30 s |
| Provider | Kite: one call for today, public F&O list. Groww's past closes matched Kite's exactly, but it needs five calls for today. No broker offers a movers endpoint |

## Intraday history, Dhan TOTP login, clock correction — complete (2026-09-28)

| | |
|---|---|
| 1-minute store | `scripts/kite.py intraday` → git-ignored SQLite `data/market.db`: `minute_bars`, `daily_bars` and a `daily_gaps` view for the 210 F&O stocks. One 60-day Kite call per stock. See [`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md) |
| Provider pick | All four brokers measured: Kite is the only one whose minute bars reproduce the official daily open. [Log](PROVIDER_COMPARISON_LOG.md) |
| Dhan login | `market/providers/dhan_session.py` mints the 24 h token from TOTP (`DHAN_CLIENT_ID`, `DHAN_PIN`, `DHAN_TOTP_SECRET`). It shares the token through the shared database (`data/market.db`, git-ignored) under a lease-row lock. `.env` no longer holds a Dhan access token |
| INDmoney login | `market/providers/indmoney_session.py` mints the token (valid to 07:00 IST) from `IND_MONEY_CLIENT_ID`, `IND_MONEY_MPIN`, `IND_MONEY_TOTP_SECRET` and shares it through the `indmoney_session` row of `data/market.db`. Minted only when needed, because each one revokes the last. Both session modules share `token_store.py`. The provider and all three INDmoney scripts use it; no script reads a token from `.env` or a session file by hand any more (`auth_headers()` on the Kite, Dhan and INDmoney providers) |
| Clock correction | `market/clock_offset.py` measures this PC's clock against NTP (21.0 s slow on 2026-09-28) once per process and saves it to the `clock_offset` row of `data/market.db`. Dhan's and both Groww clients' TOTP codes use it. A fresh Dhan token now takes ~1.6 s instead of ~17.5 s, because nothing waits out a window "to be safe" |

---

## F&O movers: multi-day change and split detection — built (2026-09-30)

| | |
|---|---|
| Multi-day change | "Over a period" view on both F&O pages: 3/5/10/20/30/50/100 trading days (30D+ added 2026-10-01 after a 135-day backfill), with up-days and a trend sparkline. `period_changes` in `market/fno_movers.py` |
| Split detection | `suspected_corporate_actions` flags a fall of 25% or more that matches a split or bonus ratio (within 6%). Flagged stocks are hidden from the rankings by default, and listed in a panel |
| Settling a suspect | `python scripts/kite.py history --fix-splits` re-fetches only the flagged stocks; Kite's adjusted candles remove a real corporate action, while a real move stays. **Not yet run against live Kite** |
| First real hit | POLICYBZR on 2026-09-24 (-36%, about 1/1.56 of the prior close). **Confirmed a real fall, not a split** (2026-10-01), so it is confirmed with `scripts/confirm_fno_move.py` and no longer flagged. VEDL on 2026-04-30 (-33%) is still flagged and unchecked |

## F&O consistency heatmap — built (2026-10-02)

A navbar page beside the F&O movers pages: [`FNO_HEATMAP.md`](FNO_HEATMAP.md).

| | |
|---|---|
| Page | `apps/fno_heatmap_dashboard.py` ("F&O Heatmap"): three stock x day heatmaps in tabs. Nifty 50 (all 50), plus the most consistent gainers and losers among F&O stocks outside the Nifty 50 (top 10–30). Window 3/5/7/10/15/20 trading days |
| Ranking | Radio button: **Consistency** (directional efficiency = net log move ÷ total absolute log move, −100..+100), **Up days**, or **Net change**. `market/fno_consistency.py` |
| Data | The stored daily closes only. No live column, no API call, no login. Stocks missing a day in the window, or with a suspected split in it, are left out and listed |

## Dhan market movers — built (2026-10-02)

A navbar page, "Dhan Movers": [`DHAN_MOVERS.md`](DHAN_MOVERS.md). It adopts the `/data/marketmovers`
endpoint found in the Swagger audit ([`API_ENDPOINT_AUDIT.md`](API_ENDPOINT_AUDIT.md)).

| Piece | What was built |
|---|---|
| Page | `apps/dhan_movers_dashboard.py`: **Stocks** (gainers/losers of 21 universes, move against money traded), **Futures** (build-up quadrants from price and OI change; most traded with basis), **Options** (OI by strike, calls against puts) |
| Data layer | `market/dhan_movers.py` (request, parsing, monthly expiry, build-up classifier) and `DhanProvider.market_movers` with a typed `DhanDataError` |
| Found while building | `DH-907` means an empty ranking; derivative `expiry` snaps to the monthly contract; a gainers list holds only stocks that are up, so under 100 rows is exact breadth; Dhan returns the last session after the close |
| Shared | Cell shading moved to `ui/shading.py`; every selector is bound to the URL so a view is a link |
| History | `scripts/dhan.py` stores the close of the gainers/losers (price and % change, no volume or OI, up to 100 per side) and per-universe breadth in the `dhan_movers` / `dhan_movers_breadth` tables of the shared `data/market.db`, in one transaction. Each row carries the session it belongs to, read from Dhan's last trade time, so weekend and holiday runs are filed correctly; one close per session date. First capture: Thu 1 Oct 2026. The Dhan Movers page's **History** screen reads it. Intraday snapshots exist behind `--intraday` and are off: ranks churn within a day and a Kite 1-minute store already covers intraday. The tables cannot be rebuilt (Dhan only returns the current session), so back up `market.db` |
| Not yet checked | Behaviour before the open (pre-open session); whether weekly option expiries can be ranked another way |

## F&O insights: breadth, overnight vs intraday, rotation, gap fills — built (2026-10-02)

Four pages in a new **Insights** group (the dropdown menus first used for it were replaced the same day by an always-expanded navbar, below), with every URL unchanged. All four pages read stored history only. See [`FNO_INSIGHTS.md`](FNO_INSIGHTS.md).

| | |
|---|---|
| Market Breadth | `apps/fno_breadth_dashboard.py`: % of stocks above their 20/50-day averages, A/D line, new 20/50-day closing highs vs lows, a plain-words breadth label. `market/breadth.py` |
| Overnight vs Intraday | `apps/fno_session_split_dashboard.py`: each stock's move split into gap and session as log returns, the average stock's cumulative lines, a scatter, pattern tables. `market/session_split.py` |
| Relative Rotation | `apps/fno_rotation_dashboard.py`: RRG-style RS-Ratio/RS-Momentum against an equal-weight Nifty 50, for 16 Nifty 50 sectors, Nifty 50 stocks or other F&O stocks, with trails and quadrant changes. Open approximation, not JdK. `market/rotation.py` |
| Gap Fills | `apps/fno_gap_fills_dashboard.py`: same-day fill rate by gap size and direction, fill curve by time of day, per-stock fill / gap-and-go rates, from `data/market.db`. Closing-auction fills counted at 15:15. `market/gap_fills.py` |
| Data refresh | `scripts/kite.py history` and `scripts/kite.py intraday` run on 2026-10-02: closes to 1 Oct (136 days), 1-minute bars to 1 Oct, and the partial 30 Sep (stopped at 13:13) completed |
| Next | Sector map for the ~160 non-Nifty F&O stocks (would give Rotation and Breadth sector views for all F&O). Optionally a cap-weighted benchmark |

## Always-expanded navbar and Gap Streaks — built (2026-10-02)

| | |
|---|---|
| Navbar | `ui/navbar.py`: Streamlit's top navigation has no hover mode, its sections open on click, and a flat bar folds overflow into "N more". So `pulse_dashboard.py` now routes with `st.navigation(..., position="hidden")` and draws every page as a direct `st.page_link`, one row per group (Sectors / F&O / Insights) with the labels in a fixed column. One click per page. Small cosmetic CSS trims Streamlit's ~6rem top padding to 1.25rem, makes the header strip transparent, and lets clicks pass through it except on its own buttons. That was checked in a browser at 1900 and 1280 px: every link and the Deploy/menu buttons stay clickable. Replaces the earlier dropdown menus. `nav_spec()` in `pulse_dashboard.py` is the one page list |
| Gap Streaks | `apps/fno_gap_streaks_dashboard.py`: consistent gap-ups/gap-downs over 5–30 days as stock × day gap heatmaps (Nifty 50, other F&O gap-ups, other F&O gap-downs), current streaks, and whether the same days' sessions held the gaps. `market/gap_streaks.py`; `ConsistencyRow` generalised to any daily log-return series |

## MCX Futures page — built (2026-10-03)

A navbar page in a new **MCX** row: [`MCX_FUTURES.md`](MCX_FUTURES.md).

| | |
|---|---|
| Provider | Dhan primary, Kite automatic fallback. Both were tested live and returned identical MCX prices, OHLC and OI. Dhan leads because it needs no morning login and keeps volume after the close. INDmoney is the third choice since 2026-10-17 (quotes only, no candles, 19 of 28 commodities; [retest](PROVIDER_GUIDE.md#mcx-on-indmoney-retested-2026-10-17)); Groww is positions-only here. Results in [`PROVIDER_GUIDE.md`](PROVIDER_GUIDE.md#mcx-on-dhan-and-kite-tested-2026-10-03) |
| Page | `apps/mcx_futures_dashboard.py`: headline cards (gold, silver, crude, natural gas, copper), a one-contract-per-commodity table, and candles (5 min to daily) with OI for the clicked row. Most active contract (highest OI) by default, because MCX liquidity often sits beyond the nearest expiry |
| Data | `scripts/dhan.py --master` stores 164 contracts (28 commodities) with Dhan and Kite ids in the `mcx_futures` set; run monthly. `market/mcx_futures.py` holds the logic and the fallback; `get_quotes` / `get_candles` were added to both providers |
| Next | Optional: stream MCX ticks over Dhan's socket instead of 30 s polling; store MCX daily closes for multi-day views |

## One local database — built (2026-10-02)

Everything the project stores locally is in the shared `data/market.db`; `.env` is the only other file.

| Piece | What it is |
|---|---|
| Runtime state | `market/state_store.py`: the Dhan, INDmoney and Kite sessions and the clock offset in `runtime_state`, and a lease row in `state_locks` that stops two processes minting one token (taken atomically, and not holding the database while a token is minted) |
| Reference data | `market/reference_store.py`: each broker's instrument ids, the index weights, the F&O universe and the confirmed moves, in `reference_sets` / `reference_rows`. A set loads back as one dictionary, so each loader parses what it always did |
| Daily closes | The F&O closes are the `daily_bars` table, the one the 1-minute backfill fills, so there is a single daily history. `scripts/kite.py history` writes it, and the pages read it, cached against `intraday_store.store_stamp()` |
| Confirmed moves | `scripts/confirm_fno_move.py suspected / list / add / remove` |
| Shared code | `intraday_store.connect(extra_schema=, timeout=)`, `connect_readonly()` and `store_stamp()` are the one way in; the state, reference and Dhan movers modules and `gap_fills` all use them |
| Safety | `tests/__init__.py` points `PULSE_STATE_DB` at a throwaway file, so no test touches the real database. Tests that check the stored data open it read-only, or copy the closes out of it into a temporary one |
| Consequence | A fresh checkout has an empty database and runs the fetch scripts (and `kite_login.py`) once. The file holds live tokens, the Dhan history and the confirmed moves: back it up, never share it |

## Trade journal (Dhan) — built (2026-10-18)

- `market/dhan_journal.py`, `scripts/dhan.py --journal` and the **Trade Journal** page: Dhan's trade history and
  ledger into `data/market.db`, round trips after charges, statistics, daily P&L against a loss limit, splits by contract, side, product and time.
- Checked against the ledger: NSE F&O to Rs 1.51, MCX to Rs 5.46 ([`DHAN_JOURNAL.md`](DHAN_JOURNAL.md)).
- Next candidates:
  - the morning protective-order job, dry run first;
  - checking what the F&O ledger line does for options, the first time one is traded;
  - an import of Groww's Excel exports, if Groww trades should join the journal.

## Drop from High — built (2026-10-23)

- `market/drawdown.py`, `ui/drawdown_treemap.py`, `apps/drawdown_dashboard.py`: each stock's drop from its high over 52 weeks, YTD, 2 or 5 years or since a date, as a treemap (stock tiles, optional sector boxes) for the Nifty 50 / 100 / Next 50 / all F&O, with a drop-range filter. All in SQLite, one row per stock. See [`DROP_FROM_HIGH.md`](DROP_FROM_HIGH.md).
- `daily_bars` backfilled to 5 years, plus the Nifty 100 names without futures. The in-memory F&O pages now load only the last 400 days.
- NSE sector labels for every Nifty 500 stock (`sectors` section of `index_constituents`).
- Next candidates:
  - a raw-price option (Dhan daily candles stored beside Kite's), so ITC, INFY and other large-dividend payers match the screeners' 52-week high;
  - the Nifty 50 index's own drop from its high (store index daily bars);
  - today's live price in place of the last stored close during the session;
  - drop from high against days since the high, as a scatter.

## Planned

### Phase 5 — intraday time dimension

Draft spec for review: [`SPEC_INTRADAY_TIME_DIMENSION.md`](SPEC_INTRADAY_TIME_DIMENSION.md).

Deliberately deferred. Every number on both boards is currently measured
against *yesterday's close*, so by mid-afternoon the board describes the whole
day rather than the present. A rolling in-memory history would add sector change
over the last 5/15/30 minutes and since the open, plus sparklines.

Decided: history stays **in memory only** — no database, no files; it dies with
the process.

### Instant NSE Sectoral Indices page

Opening **NSE Sectoral Indices** shows grey tiles / 0.00% for a few seconds.
The index board's feed is only created on the first visit (`get_service`), so
that visit pays for fetching previous closes over REST and opening a
websocket, throttled by Dhan's process-wide 1 req/s quote limit. (Instrument
ids are not part of it: they are read from the local `data/*_instruments.json`
files, never downloaded at runtime.) The Nifty 50 board's data can't fill in, because it is a different
universe, segment and feed. Measured 2026-09-30 with
`scripts/debug/compare_heatmap_startup.py`: Dhan needs ~2.9 s to a full board from
REST (two ~1.1 s calls), INDmoney ~1.4 s, Kite ~2.8 s; see
[`PROVIDER_COMPARISON_LOG.md`](PROVIDER_COMPARISON_LOG.md).

Proposal: start the index service in the background when the app opens, not on
first visit. The websocket is cheap and the quote call is one request for ~17
indices, but the two services' requests must be staggered to stay under the
rate limit and the INDmoney 3-socket cap. Also persist the last snapshot (LTP,
previous close, change %) to a small git-ignored file, and have the page draw
that immediately, labelled "as of HH:MM" until the first live tick replaces it.
No tile should show 0.00% for "no data": show the cached value or a loading
state. Outside market hours the cached file is already the right answer.

### Other candidates

Ordered roughly by value, not commitment:

| Idea | Note |
|---|---|
| Dhan `/data/companyinfo`, `/data/newsheadline`, `/data/technical` | Fundamentals, sentiment-tagged headlines and server-side indicators, found in the Swagger audit and published in Dhan's docs since the 2026-10-09 export. `companyinfo` now feeds the index weights; the other two are unused. `/data/marketmovers` is now the Dhan Movers page |
| Holdings overlay | Mark which sectors the account is actually exposed to, reusing the existing portfolio/FnO clients. Informational only. |
| Universe expansion | Nifty Next 50 / Nifty 500 on the aggregate board. The blocker is sector classification: a hand-maintained dict does not scale past 50 rows. |
| Exchange holiday calendar | `market/market_hours.py` checks weekday and clock only, so a holiday looks like an open session with no ticks. Now also the last inaccuracy in the Phase 4 lookup: on a holiday it measures against the last real session and reads +0.00% rather than that session's move. |
| Token expiry countdown | Dhan and INDmoney tokens both last ~24h, and Kite's die at 06:00 IST; the providers log the hours left at startup, but the UI does not show it, so you discover expiry when the feed stops. |
| Kite login without the paste | `scripts/kite_login.py` asks you to paste the redirect URL. If the app's redirect URL is `http://127.0.0.1:<port>/...`, a tiny local listener could catch the `request_token` itself. |
| Extended-session minute bars (pre-open, closing auction, post-close) | **Blocked until Groww's paid data plan is active** (its free API plan refuses candles, checked 2026-10-17). Checked 2026-09-30: none of Kite, Dhan or INDmoney documents pre-open, CAS or post-close data (since the 2026-10-09 export Dhan documents a **CAS Live Feed** websocket, Pro Traders Plan only: per-stock indicative equilibrium price, quantities, 5-level depth and imbalance, plus indicative index closes; no minute bars, not tried), and their minute bars stop at 15:14 (Kite, Dhan) or are invented flat bars to 15:30 (INDmoney). The open test is a live socket probe: `python scripts/debug/probe_extended_session.py --until 09:16` (start before 09:00) and `--until 16:05` (start before 15:15) log what Dhan, INDmoney and Kite send in those windows to `data/extended_session_probe.csv`. Built 2026-10-01 and checked mid-session; the two windows have not been run yet. The windows that matter are pre-open (09:00-09:15) and CAS, the closing auction session (15:15-15:30); after 15:30 is settlement and of less interest. The summary reports CAS separately. For strategy research, not day-to-day use. Groww returns bars outside 09:15–15:15 that Kite and Dhan omit: pre-open 09:00–09:08 (volume only; prices are `None`), the closing auction session (CAS) 15:15–15:30 (a near-empty 15:15 bar was seen, so check what else it carries), and post-close bars to 15:59. Plan: an `extended_bars` table in `data/market.db` (or a `session` column on `minute_bars`) filled from Groww, 30 days per call. That's two calls per stock for 60 days, so ~420 requests. Also confirm how the CAS price relates to the official close. Groww's opens differ from Kite's on ~half the regular-session bars, so keep Kite for 09:15–15:15. |
| Debug INDmoney's 1-minute data | Its bars don't look wrong so much as belonging to some other series. Volumes match Kite's on 0.2% of bars, O/H/L/C agreement is ~61/82/76/71% (almost exactly Dhan's), and there are flat bars 15:16–15:30 during the CAS. Worth checking: is it BSE, or NSE+BSE consolidated (compare against the BSE scrip code)? Are the bars stamped at the end of the minute rather than the start, or cut from ticks differently? Why does every request return only 7 days? Re-run `scripts/debug/compare_intraday_providers.py` as the harness. |
| More index boards | The index board is list-driven, so Nifty Midcap/Smallcap or thematic indices are rows in `index_mapping.py`, not new code. |

---

See [`SECTOR_HEATMAP.md`](SECTOR_HEATMAP.md) for how the current system works.
