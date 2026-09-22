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
| Aggregation | Equal-weighted mean of constituent percentage changes |

## Phase 2 — complete

Breadth and weighting.

| | |
|---|---|
| Market-cap weighting | Free-float cap weights from `data/index_weights.json`, switchable in the sidebar against equal weighting |
| Weights pipeline | `scripts/fetch_index_weights.py` — run manually, writes the JSON, never called at runtime |
| Breadth | Advancing/declining counts, sectors up vs down, average day-range position |
| Day range | Open/high/low/volume from Dhan quote packets, with the OHLC endpoint as the REST fallback |
| Leaders / laggards | Two tables under the heatmap: each advancing sector with its best stock, each declining sector with its worst |

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
| Fix | Moved out of the runtime entirely. `scripts/fetch_instrument_master.py` downloads it offline and writes a 12 KB `data/dhan_instruments.json`; the dashboard reads that at startup and never fetches an instrument master |
| Effect | Instrument resolution is now instant and offline. No pandas, no network, on the boot path |
| Cadence | Re-run after an NSE reconstitution (end of March / end of September), after editing the sector mapping, or when a symbol stops resolving. The loader warns past 90 days |
| Precedent | Same contract as the weights file: generated offline, committed, never fetched live |

---

## Planned

### Phase 5 — intraday time dimension

Deliberately deferred. Every number on both boards is currently measured
against *yesterday's close*, so by mid-afternoon the board describes the whole
day rather than the present. A rolling in-memory history would add sector change
over the last 5/15/30 minutes and since the open, plus sparklines.

Decided: history stays **in memory only** — no database, no files; it dies with
the process.

### Other candidates

Ordered roughly by value, not commitment:

| Idea | Note |
|---|---|
| Holdings overlay | Mark which sectors the account is actually exposed to, reusing the existing portfolio/FnO clients. Informational only. |
| Universe expansion | Nifty Next 50 / Nifty 500 on the aggregate board. The blocker is sector classification: a hand-maintained dict does not scale past 50 rows. |
| Exchange holiday calendar | `market/market_hours.py` checks weekday and clock only, so a holiday looks like an open session with no ticks. Now also the last inaccuracy in the Phase 4 lookup: on a holiday it measures against the last real session and reads +0.00% rather than that session's move. |
| Token expiry countdown | The Dhan token lasts ~24h; today you discover it has expired when the feed stops. |
| Kite (Zerodha) provider | Registry placeholder exists (`PLANNED_PROVIDERS`); deliberately not implemented while Dhan is working. |
| More index boards | The index board is list-driven, so Nifty Midcap/Smallcap or thematic indices are rows in `index_mapping.py`, not new code. |

---

See [`SECTOR_HEATMAP.md`](SECTOR_HEATMAP.md) for how the current system works.
