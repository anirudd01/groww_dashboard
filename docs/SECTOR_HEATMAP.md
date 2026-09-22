# Live Sector Heatmap Dashboard

**Entry point:** [`sector_heatmap_dashboard.py`](../sector_heatmap_dashboard.py)
**Status:** Phases 1-4 complete - live on the **Dhan** websocket, with
Dhan REST, Groww websocket and Groww REST behind it as fallbacks.
**Next:** see [`ROADMAP.md`](ROADMAP.md).

---

## What it does

A live market-visualisation tool for observing short-term sector rotation across
the Nifty 50. It has two screens:

1. **Sector heatmap** — one clickable tile per sector, coloured by the sector's
   percentage change vs the previous trading day's close. No individual stocks
   appear here. Clicking a tile opens that sector's table.
2. **Sector constituents** - a drill-down table of every Nifty 50 stock in the
   selected sector, sorted by live percentage change, highest first.

Beneath the heatmap sit a breadth summary and two tables: every advancing
sector with its strongest stock, and every declining sector with its weakest.

A second board, chosen in the sidebar, shows the **real NSE sectoral
indices** instead of an aggregate of the Nifty 50. See
"The sectoral index board" below.

### What it deliberately does not do

It places no orders, calls no order APIs, generates no signals, labels nothing
BUY/SELL/LONG/SHORT, runs no backtests and makes no predictions. It only
displays objectively calculated market data.

---

## Running it

```bash
pip install -r requirements.txt          # adds `websockets` for the Dhan feed
streamlit run sector_heatmap_dashboard.py
```

Or use the Windows launchers, which pin port 8502 so it can run alongside the
other dashboards:

```
run_sector_heatmap.bat
.\run_sector_heatmap.ps1
```

Verify the data pipeline and live feed without starting Streamlit:

```bash
python scripts/check_heatmap_universe.py --seconds 20
python scripts/check_heatmap_universe.py --provider dhan --seconds 20   # one broker
```

It exits `OK` only when the **websocket** delivered ticks, and warns explicitly
when prices came from the REST fallback instead:

```
state=LIVE  provider=Dhan  source=websocket  priced=50/50
OK    Dhan websocket is delivering live ticks
```

---

## Brokers (providers)

The dashboard is broker-agnostic. Brokers sit behind a small interface in
[`market/providers/base.py`](../market/providers/base.py) and are listed in
[`market/providers/registry.py`](../market/providers/registry.py):

| Provider | Status | Credentials |
|---|---|---|
| **Dhan** (DhanHQ v2) | Implemented, **preferred** — websocket verified live | `DHAN_ACCESS_TOKEN` only |
| **Groww** | Implemented, fallback — REST and websocket both work; the socket has its own quirks, see [`api/GROWW_API_FEED.md`](api/GROWW_API_FEED.md#websocket-behaviour-in-practice-observed) | existing `GROWW_*` vars |
| Kite (Zerodha) | Planned — named in config, skipped with a log line | — |

Preference order comes from `PULSE_MARKET_PROVIDERS` (default `dhan,groww`).
The service walks the list and adopts the **first broker that authenticates and
resolves instruments**.

### Recovery before failover

A broker that stumbles gets its socket back before the board changes hands.
That ordering matters: the preferred broker carries data the fallbacks do not
— day bars for the breadth column, and on the index board, any data at all —
so conceding the session over one hiccup costs more than the hiccup did.

**How a socket is noticed as gone**

| | Detected | Then |
|---|---|---|
| **Connection dropped** | immediately, on the next 0.5 s drain | reconnect the same broker at once |
| **Connected but silent** | no tick for `feed_silence_seconds` (10 s) during market hours | drop it and reconnect the same broker |
| **Never connects** | the attempt returns an error | reconnect the same broker |

The silence timer runs from the **last tick**, not from the connection, so it
catches a healthy feed that goes quiet mid-session just as well as one that
never started. Measuring from the connection instead would mark every
long-lived feed dead the moment it passed the window.

**Then, and only then, the next broker**

All three failures feed one counter, because the remedy for all three is the
same. Retries are `feed_reconnect_seconds` (1 s) apart; after
`feed_recovery_attempts` (2) the socket goes to the next broker in the list.
The counter is cleared by the first real tick, not by a successful connect —
a socket that opens and then stays mute would otherwise retry forever.

In practice a dropped Dhan socket is back in **~2 s**, on Dhan, with REST
covering the gap so nothing changes on screen. A broker that genuinely cannot
deliver hands over at ~20 s instead of holding the board all session.

One counter covers the never-connects case too, which is easy to miss: that
path has no feed object to drain, so without it nothing in the loop would ever
notice, and the board would sit on a dead broker's REST polling for the rest of
the session with a working broker unused behind it.

Two ordering details exist for real reasons. The failover decision runs
*before* the connect attempt, so a doomed attempt is never started against a
broker about to be dropped. And every connect result carries the provider that
made it: Groww's handshake can take minutes, easily outliving the failover that
abandoned it, and adopting that socket would stream one broker's prices under
another broker's name.

Failover is announced in the UI. The effective chain today is:

```
Dhan websocket  →  Dhan REST polling  →  Groww websocket  →  Groww REST polling
```

Within one broker, REST polling covers the websocket; across brokers, the next
provider in the list takes over. Every step is labelled in the status bar, so
the screen always states which of the four is actually feeding it.

```bash
PULSE_MARKET_PROVIDERS=dhan,groww     # default: Dhan first, Groww as fallback
PULSE_MARKET_PROVIDERS=groww          # force Groww only
```

Adding a broker is two files: implement `MarketDataProvider` + `FeedHandle`, add
one line to `PROVIDER_FACTORIES`. Nothing above the provider layer changes —
aggregation and UI only ever see canonical NSE symbols and floats.

### Credentials

Groww reuses the project's existing `GrowwAPIClient` singleton in
[`groww_api/client.py`](../groww_api/client.py) — there is no second auth path
for it.

**Dhan needs only `DHAN_ACCESS_TOKEN`.** Dhan embeds `dhanClientId` in the
access token, so the provider decodes it and `DHAN_CLIENT_ID` is an optional
override. A non-numeric value (such as a leftover `your_dhan_client_id`
placeholder) is ignored with a warning — otherwise it would mask the real error
behind a confusing "808 Client ID invalid".

Dhan access tokens last ~24h. TOTP is only needed to *mint* tokens
programmatically; a token generated from the Dhan web console works on its own,
so the dashboard never prompts for an authenticator code. The provider logs how
long the token remains valid and fails with a clear message once it expires.

**Dhan requires the paid Data API plan.** Market quotes *and* the live feed both
need it; without it every market-data call returns `806 Data APIs not
Subscribed` while trading/profile endpoints keep working. The provider checks
`/v2/profile` first and reports `dataPlan` explicitly rather than surfacing a
bare HTTP 401.

No credential is logged or stored by any module added for this dashboard.

---

## Architecture

```
    provider REST  ───────►  instrument ids + previous closes   (startup, once)
                                          │
    provider websocket ───────────────────┼──►  LiveMarketDataService
                                          │      (background daemon thread,
    provider REST (fallback) ─────────────┘       thread-safe in-memory state)
                                                          │
                                                   snapshot()
                                                          │
                                          sector aggregation (pure functions)
                                                          │
                                                   Streamlit + Plotly
```

| Layer | Module | Responsibility |
|---|---|---|
| Providers | `market/providers/` | Broker interface + Dhan and Groww implementations |
| Auth (Groww) | `groww_api/client.py` *(existing, unchanged)* | One authentication per process |
| API (Groww) | `groww_api/api_calls.py` *(extended)* | Instrument resolution, previous close, batched LTP |
| Config | `market/config.py` | All tunables, env-overridable |
| Universe | `market/universe.py`, `market/sector_mapping.py` | Constituents and sector classification |
| Indices | `market/index_mapping.py` | Which NSE indices the index board shows |
| Models | `market/models.py` | `StockMarketData`, `SectorMarketData`, `FeedStatus` |
| Feed | `market/live_feed.py` | `LiveMarketDataService` — the background worker |
| Calc | `market/sector_aggregation.py` | Percentage change, aggregation, ranking, highlights |
| Weights | `market/weights.py` | Loads the offline weights file (never fetches) |
| Session | `market/market_hours.py` | NSE session classification |
| UI | `ui/sector_tiles.py` | Clickable coloured tile grid (default heatmap) |
| UI | `ui/sector_heatmap.py` | Plotly treemap (display-only alternative) |
| UI | `ui/colours.py` | Shared diverging colour scale (tiles + table) |
| UI | `ui/sector_detail.py` | Constituent table construction + styling |
| UI | `ui/sector_highlights.py` | Leading / lagging sector tables |
| UI | `ui/index_board.py` | Index tiles tooltip, summary line and index table |
| App | `sector_heatmap_dashboard.py` | Streamlit wiring only |

The Groww API is never called from rendering code, and no sector maths happens
inside Streamlit callbacks.

### Why the feed lives outside Streamlit

Streamlit reruns the whole script constantly. A websocket owned by the script
would be torn down and rebuilt on every rerun. Instead the service is created
once via `@st.cache_resource` and owns a daemon thread; Streamlit only ever
calls `snapshot()`, which returns a locked, copied view of the state. Navigating
between the two screens does not touch the feed.

### Update frequency

- **Websocket:** continuous; the tick callback only bumps a counter and a
  timestamp (no parsing, no logging — logging every tick would make the console
  unusable at 50 instruments).
- **Worker:** drains the feed's in-memory buffer every 0.5 s. This is local work
  and makes no network calls.
- **UI:** an `st.fragment(run_every="1s")` re-renders roughly once per second and
  always draws the latest available state.

There is no requirement for exactly one tick per second in either direction.

---

## How previous close is obtained

There are two sources, and which one is correct depends on whether the market
is open. The service picks between them; the UI says which one it used.

### During the session — the OHLC endpoint

Each provider supplies it from its own OHLC endpoint, reading the `close`
field, which on both brokers is the **previous trading day's** close *while
trading is live*. One batched call covers the whole universe.

Verified against live data on both:

- **Groww** — `RELIANCE` `last_price` 1240.10 with `day_change` −3.80, and
  `ohlc.close` 1243.90. Consistent, so `close` is the prior session's close.
- **Dhan** — `/v2/marketfeed/ohlc` returned `close` 1243.90 for `RELIANCE` at
  the same time: an independent broker agreeing to the paisa.

Dhan additionally pushes an explicit previous-close packet (response code 6) on
subscribe. That is exchange-published reference data, not a tick, and it is used
only to fill symbols REST could not supply.

The previous close is **never** inferred from the first websocket tick. It is
fetched once at startup (and refreshed every 15 minutes so a new trading day is
picked up without a restart). A stock whose previous close is missing or zero is
excluded from its sector's average, counted as unpriced, and listed in the
dashboard's "Data gaps" panel — it never silently contributes 0%.

### Outside the session — daily candles

The OHLC `close` field stops meaning "previous trading day" the moment trading
stops: brokers repoint it at *today's* close (measured on Dhan, see limitation
4 below). Starting the dashboard after 15:30 would therefore measure today
against itself and read +0.00% on every tile.

So when the session is `CLOSED` or `WEEKEND`, the previous close comes from
daily candles instead — `POST /v2/charts/historical` on Dhan, behind the
optional `get_prior_session_close` on the provider interface. Daily candles do
not move when the session ends.

**Which candle.** The one immediately before the session the *current price*
belongs to, which is not simply "the second-to-last":

| When you start it | Latest price is | Previous close is |
|---|---|---|
| Friday 16:00 | Friday's close | the last candle before Friday |
| Friday 16:00, before Dhan publishes Friday's candle | Friday's close | still the last candle before Friday |
| Saturday, or Monday 07:00 | Friday's close | the candle before the most recent one |

`market_hours.todays_session_date()` draws that distinction: it returns today's
date once today's session has begun, and `None` when the latest price comes
from an earlier session. `prior_close_from_candles()` in the Dhan provider
applies it.

**No silent fallback.** A symbol the candles cannot cover is left unresolved
and appears in "Data gaps". It is never backfilled from the OHLC endpoint,
because that endpoint is known to be wrong at precisely the moment this path
runs — a gap is honest, a +0.00% tile is not. If nothing resolves at all, the
status bar says so rather than showing a flat board.

**Cost.** The historical endpoint takes one security per request, not a batch,
so this is ~50 throttled calls at startup and only when the market is closed.
Dhan publishes 1 req/s for quote endpoints and 5/s for the wider "Data APIs"
bucket without stating which bucket this endpoint is in, so it gets its own
gate at 4/s — about 13 s for 50 symbols, paid once at startup. The lookup
abandons the universe after 5 consecutive empty responses, since that pattern
means a missing entitlement or a dead token rather than a thin instrument. Set
`PULSE_HEATMAP_HISTORICAL_PREV_CLOSE=false` to skip it entirely.

The periodic refresh still never runs outside market hours, for the reason in
limitation 4: it exists to pick up a new trading day, and re-running it after
the close could only make things worse.

---

## Instrument universe and sector mapping

Constituents live in [`market/sector_mapping.py`](../market/sector_mapping.py)
as a plain `symbol -> sector` dict; [`market/universe.py`](../market/universe.py)
turns it into a `Universe`. All Nifty 50 members are `exchange=NSE`,
`segment=CASH`.

**Exchange tokens are never hardcoded.** Each provider resolves its own
instrument ids from that broker's instrument master — for Dhan via the
generated file described below, for Groww via `get_all_instruments()`. Nothing
above the provider layer ever sees a broker-specific id; aggregation and the UI
work only in canonical NSE symbols.

To update after an NSE reshuffle, edit the dict — nothing else changes. Run
`python scripts/check_heatmap_universe.py` afterwards; it reports any symbol
that no longer resolves.

### Instrument ids come from a generated file, not a download

Dhan publishes ids only as `api-scrip-master-detailed.csv`: **35 MB, 206,659
rows, served uncompressed**, containing every F&O contract on every exchange.
Verified 2026-09-18: there is no zip or gzip variant (`.zip`, `.gz` return 403),
and the CDN ignores `Accept-Encoding: gzip` because it serves the file as
`application/octet-stream`. Dhan's docs also list an authenticated
`GET /v2/instrument/{exchangeSegment}` which would return one segment rather
than the whole file — **untested here**, as it needs a live token, and worth
trying if the download ever becomes a nuisance again.

Of those rows the dashboard uses about sixty, and two fields from each. So the
download is a **script**, not a startup step:

```bash
python scripts/fetch_instrument_master.py              # writes data/dhan_instruments.json
python scripts/fetch_instrument_master.py --verbose    # log every symbol
python scripts/fetch_instrument_master.py --keep-raw   # also keep Dhan's CSV
python scripts/fetch_instrument_master.py --use-cached # reuse today's CSV
```

It streams the CSV with `csv.DictReader`, keeps only the symbols in the
configured universes, and writes a **12 KB** JSON that the dashboard reads at
startup in under a millisecond. Same contract as the weights file: generated
offline, committed, never fetched live.

**When to re-run it:**

| Trigger | Why |
|---|---|
| After an NSE index reconstitution | Effective end of March and end of September; the constituent set changes |
| After editing `market/sector_mapping.py`, or adding a universe | New symbols have no id until they are resolved |
| When the "Data gaps" panel reports unresolved symbols | A symbol was renamed, delisted or demerged |
| Roughly monthly otherwise | Cheap insurance; the loader warns past 90 days |

Security ids of *existing* instruments are stable, so a file that is a few
weeks old is not a risk — what changes is which symbols exist. A stale file
fails loudly and specifically: the symbol is listed as unresolved in the UI and
the log names the script to run. It is never papered over with a guessed id or
a silent 35 MB download during market hours.

Five fields are kept per instrument. Only `security_id` is used; the rest make
the file diagnosable by eye:

```json
"RELIANCE": {
  "isin": "INE002A01018", "lot_size": "1.0",
  "name": "RELIANCE INDUSTRIES LTD", "security_id": "2885", "series": "EQ"
}
```

`isin` is how you confirm a demerged entity is the continuing one — `TMPV` kept
Tata Motors' original ISIN (limitation 6) — and `series`/`name` confirm the row
is the tradable equity rather than a lookalike. The file is small enough that a
reconstitution shows up as a handful of changed lines in a commit.

With `--keep-raw`, Dhan's unedited response is saved under `data/instruments/`
(git-ignored) so a re-run the same day can skip the download.

### Configurable universe (Phase 3 readiness)

`PULSE_HEATMAP_UNIVERSE` selects the universe (default `NIFTY50`). A
`NIFTYNEXT50` slot already exists with an empty mapping; fill in
`NIFTY_NEXT_50_SECTORS` and it becomes selectable with no code changes. An
unpopulated universe raises a clear error rather than rendering an empty board.

---

## How sector percentage change is calculated

Per stock:

```
change_pct = ((ltp - previous_close) / previous_close) * 100
```

Per sector — an **equal-weighted average of the constituent percentage changes**:

```
sector_change_pct = mean(change_pct for priced stocks in sector)
```

This is explicit and deliberate. Market-cap weighting is **not** used, and NSE
sector-index values are **not** used. The displayed number is the average
performance of the constituent stocks.

Constituents without a usable change (no tick yet, missing previous close) are
counted in `constituent_count` but excluded from the mean, so one broken
instrument cannot distort its sector. A sector with no usable prices reports
"no data", never 0%.

## Market-cap weighting

Selectable in the sidebar under **Sector maths**, alongside equal weighting. The
screen always states which definition produced the number on it.

```
sector_change_pct = sum(change_pct * weight) / sum(weight)   # within the sector
```

**What the number means.** It is a cap-weighted basket of *our own
constituents* - "how did this sector's big names do". It is deliberately **not**
an attempt to reproduce an NSE sector index, whose constituent list is wider
than the Nifty 50 members tracked here. Reproducing the real indices is a
separate, planned feature; see [`ROADMAP.md`](ROADMAP.md).

### Where the weights come from

Neither broker supplies them. This was checked rather than assumed: Dhan's
detailed scrip master (32 columns) and Groww's instrument master (21 columns)
both carry ISIN, lot size, margins and circuit limits, but **no market
capitalisation and no share count**. The one "market cap" reference in Dhan's
docs describes its ScanX screener, not a data endpoint.

So weights come from a file, generated offline:

```bash
python scripts/fetch_index_weights.py            # writes data/index_weights.json
python scripts/fetch_index_weights.py --verbose  # one line per symbol
```

| | |
|---|---|
| Source | Yahoo Finance `quoteSummary` - public, no API key, no account |
| Basis | **Free-float market cap** (`floatShares x price`), the basis NSE itself uses |
| NSE contact | None. NSE is never called. |
| When to run | Manually, weekly or monthly. Share counts move slowly. |
| Runtime behaviour | The dashboard **reads the file only**. It never fetches weights while running. |

The dashboard reading a static file rather than a live source is deliberate: a
weight that changed mid-session would make two refreshes of the same screen
disagree, and a fundamentals lookup that stalls during market hours would stall
the dashboard.

The file is plain JSON, so it can equally be filled in **by hand** from NSE's
published index factsheet if the automated source ever breaks. Only ratios
within a sector matter, so any consistent unit works. Format is documented in
[`market/weights.py`](../market/weights.py).

### When weights are missing

Never silently. A weighted number that is secretly unweighted would be a lie, so:

- **No file at all** - the sidebar says so and names the script to run; selecting
  market-cap weighting shows a warning and falls back to equal weighting.
- **A sector with no weighted constituent** - falls back to an equal-weighted
  mean for that sector and sets `fell_back_to_equal_weight`.
- **Partial coverage** - the weighted mean is computed from the constituents that
  do have weights, and `weight_coverage` records the fraction. A missing weight
  shrinks the basket; it never contributes zero.
- **Weights older than 45 days** - flagged in the sidebar with the age.

### Adding another method

`market/sector_aggregation.py` exposes a strategy registry:

```python
AGGREGATION_STRATEGIES = {
    "equal_weight": _equal_weight_strategy,
    "market_cap":   weighted_change_pct,
}
```

Each strategy takes `(changes, weights)` and returns the sector change. Adding
`index_weight` means adding one entry plus a label in `AGGREGATION_LABELS`. The
UI takes `SectorMarketData` objects and does not care how `change_pct` was
produced, so no rendering code changes.

---

## Breadth

Answering "is this sector moving broadly, or is one stock carrying it".

| Figure | Meaning |
|---|---|
| Stocks advancing / declining | Constituents up or down vs the previous close, out of those with a live price |
| Sectors up / down | How many sectors have a positive vs negative aggregate |
| Avg day-range position | Where prices sit between the day's low (0%) and high (100%), averaged over constituents whose range is known. Above 50% means most stocks are nearer their highs. |

Per sector, `SectorMarketData` also carries `positive_count`, `negative_count`,
`advancing_pct` and `avg_range_position_pct`; the first two appear in each
tile's tooltip.

**Where the day range comes from.** Dhan's **quote** packets (response code 4,
50 bytes, `RequestCode 17`) carry today's open, high, low and volume alongside
the LTP, so breadth costs no extra requests - the feed simply subscribes to
quote instead of ticker. On the REST fallback the same OHLC endpoint that
supplies the previous close also supplies today's open/high/low.

Providers that publish none of this are a supported case, not an error:
`FeedHandle.day_bars()` and `MarketDataProvider.get_day_bars()` default to
empty, and the UI drops the day-range column rather than inventing values. The
Groww fallback is in exactly that position today: its `stockLivePrice` proto
*has* `open`/`high`/`low`/`volume` fields, but on the LTP topic they are always
`0.0`, so reading them would be worse than reporting nothing.

A zero from the feed (a field the exchange has not populated before the
session's first trade) is kept as **unknown**, never as a price - a 0.00 low
would otherwise place every stock at the top of its range.

---

## Leading and lagging sectors

Two tables beneath the heatmap, one row per sector:

| Table | Contains |
|---|---|
| **Leading sectors** | Every sector that is *up*, strongest first, each with its own best-performing constituent |
| **Lagging sectors** | Every sector that is *down*, weakest first, each with its own worst-performing constituent |

A sector appears in exactly one table or neither. A flat sector, or one with no
priced constituents, appears in neither - calling a sector that has not moved a
"top performer" would be misleading.

Both tables share one colour scale, so a -2% cell in the laggards table is
exactly as dark as a +2% cell in the leaders table.

These describe what has moved and what drove it. They are **not**
recommendations, and nothing ranks a stock as something to buy or sell.

Turn them off with `PULSE_HEATMAP_HIGHLIGHT_TABLES=false`; cap the rows with
`PULSE_HEATMAP_HIGHLIGHT_LIMIT` (0 = every qualifying sector).

---

## The sectoral index board

A separate page (sidebar: **NSE Sectoral Indices**) showing real NSE index
values. Nothing on it is aggregated: each tile is one index measured against its
own previous close.

### Why it exists alongside the Nifty 50 board

    Nifty 50 board  ->  "how are the Nifty 50's IT names doing"
    Index board     ->  "how is the IT sector doing"

The index's constituent list is wider than the Nifty 50 members we track, so the
two boards **are expected to disagree** - and that gap is the point. It shows
where the large caps are moving differently from the sector as a whole. Measured
live on 2026-09-18, Nifty IT was -1.58% as a real index while the equal-weighted
Nifty 50 IT aggregate read -1.95%.

### What it shows

14 NSE sectoral indices (Auto, Bank, Consumer Durables, Financial Services,
FMCG, Healthcare, IT, Media, Metal, Oil & Gas, Pharma, Private Bank, PSU Bank,
Realty) plus Nifty 50, Nifty Next 50 and Nifty 500 as broad benchmarks. Nifty
Bank is a sectoral tile and is deliberately not repeated as a benchmark.

The list lives in [`market/index_mapping.py`](../market/index_mapping.py), one
row per tile. Adding an index is one row; security ids are resolved from the
instrument master at startup and are never hardcoded. Verify with:

```bash
python scripts/check_heatmap_universe.py --board indices --provider dhan
```

Below the tiles, a table lists every index with LTP, change, previous close,
open and the day's range.

### Where the data comes from

Dhan addresses index values as their own exchange segment, `IDX_I`:

| | |
|---|---|
| Instrument master | `EXCH_ID=NSE, SEGMENT=I, INSTRUMENT=INDEX` (119 NSE indices) |
| Previous close | `/v2/marketfeed/ohlc` with `IDX_I` - the same REST rule as equities, never a tick |
| Live values | The websocket, subscribed with `IDX_I` |

One finding worth recording: **Dhan does not send the documented index packet
(response code `1`) for `IDX_I` subscriptions.** It sends the ordinary ticker
(`2`), quote (`4`) and previous-close (`6`) packets, exactly as for equities, so
the existing parser handles indices with no changes. Index quote packets carry
open/high/low (verified matching REST to the paisa) with volume and traded
quantity zero, which the `_positive()` guard keeps as "unknown" rather than
turning into a fake zero.

Security ids are unique *within* a segment but not across them - index id 13 and
an equity id 13 both exist - so each board runs its own service with its own
universe, and refs from different segments are never mixed in one request.

### Drill-down

Clicking an index tile shows **the Nifty 50 members of the matching sector**,
with the index's own value, change, previous close and day range above them.

This is labelled explicitly in the UI, because it is *not* the index's real
constituent list: neither broker publishes that. A table headed "Nifty Auto"
listing six Nifty 50 car makers would otherwise be read as the index's contents.

Indices with no honest link show a message instead of a misleading table:

- **Nifty Media** and **Nifty Realty** - no Nifty 50 constituent is classified
  under either sector.
- **The three benchmarks** - broad market indices, not sectors.

Nifty Pharma and Nifty Healthcare both drill into our `Healthcare` bucket,
because the Nifty 50 sector mapping does not separate them; the drill-down names
the sector it is actually showing.

### Providers

The index board is Dhan-only today. The Groww adapter reports index symbols as
**unresolved** rather than raising, so the service fails over to a broker that
does serve them instead of the whole board erroring out. If Dhan is unavailable,
the index board reports no usable provider while the Nifty 50 board keeps
working on Groww.

### Two boards, two feeds

Each board runs its own `LiveMarketDataService` with its own websocket. Dhan
allows 5 concurrent connections per client id, so two is comfortable, and the
feed for a board you have not opened is never started.

Dhan's quote rate limit (1 request/second) applies **per client id, not per
connection**, so the throttle is process-wide rather than per provider
instance - two boards starting together would otherwise collide and trip error
`805`. Provider activation also retries rather than failing permanently, so a
transient rate limit no longer leaves a board dead until restart.

---

## Colour scale (tiles and table)

Both the heatmap tiles and the `Change %` column of the constituent table use
one implementation, [`ui/colours.py`](../ui/colours.py), so a sector tile and
its rows read the same way.

- **Diverging red → neutral → green**, centred on zero.
- **Intensity tracks the size of the move.** The strongest mover on screen is
  the darkest shade; small moves stay pale. In the constituent table this means
  the biggest gainer is dark green, milder gains progressively lighter green,
  and losses the same in red.
- The scale is symmetric: +1.0% is exactly as saturated as −1.0%.
- The limit is `max(|change|)` across what is displayed, floored at 0.75%
  (`PULSE_HEATMAP_MIN_COLOUR_SCALE_PCT`), so a flat day still shows contrast.
- No data renders neutral grey with muted text — never as a flat 0%.
- Text flips to white on dark backgrounds for contrast.

### Treemap colour scale

- A **diverging red → neutral → green** scale, defined in
  `ui/sector_heatmap.py` as `DIVERGING_COLOURSCALE`.
- `cmid=0` with symmetric `cmin=-limit` / `cmax=+limit`, so **zero is always the
  neutral colour** (`#f2f2f2`) and +1.0% is exactly as saturated as −1.0%.
- `limit = max(|sector change|)` across the board, floored at 0.75% (configurable
  via `PULSE_HEATMAP_MIN_COLOUR_SCALE_PCT`). Intensity is therefore *relative to
  the other sectors* today, while a flat day still shows contrast instead of an
  all-grey board.
- Colour is driven **only** by percentage change. No sector is ever assigned a
  fixed colour.
- A sector with no computable change renders at the neutral midpoint and is
  labelled "no data", so it is not mistaken for a flat sector.

### Tile size

Every tile has `value=1`. **Tile area carries no meaning in Phase 1** and in
particular does not encode percentage change. A regression test
(`test_tile_area_is_constant`) enforces this.

---

## Sector ordering — and the Plotly limitation

Two modes, switchable in the sidebar (default from
`PULSE_HEATMAP_SECTOR_ORDER`):

1. **Strongest first** (default) — sectors are sorted by descending
   `change_pct` before the treemap is built, and the trace sets `sort=False` so
   Plotly lays tiles out in the supplied order rather than re-sorting by
   `values` (which are all equal). The strongest sector lands top-left.
2. **Alphabetical** — a deterministic order in which a tile never moves.

**The limitation:** Plotly's squarify layout positions tiles from the input
order, so as ranks change intraday the tiles *physically swap places*. This is
correct behaviour, but on a fast-moving day it can look unstable — tiles jump
around once per second and are harder to track by eye. Rather than fight the
layout engine, the alphabetical mode is offered as a stable fallback.

In **both** modes the sector name, percentage and colour update every second.
The dashboard remains fully useful even if you never let the tiles move.

Ties (and sectors with no data) break alphabetically, so equal values do not
cause tiles to shuffle randomly between refreshes.

---

## Interaction — why the heatmap is buttons, not a treemap

**Streamlit cannot receive a click on a Plotly treemap tile.** Its Plotly
component listens for `plotly_click`, `plotly_selected` and `plotly_deselect`
(confirmed by inspecting the shipped frontend bundle). Plotly.js treemap traces
do not emit `plotly_click` — they emit `plotly_treemapclick`, which Streamlit
never wires up. No `on_select` / `selection_mode` combination can fix this; it
would need a custom component.

So the heatmap is drawn as a grid of real `st.button` widgets
([`ui/sector_tiles.py`](../ui/sector_tiles.py)). Each tile is wrapped in
`st.container(key=...)`, which Streamlit renders with a `st-key-<key>` CSS
class, letting one injected `<style>` block colour every tile from its own
percentage change. Clicks are ordinary widget events, so drilling into a sector
always works — one click, straight to the table.

The tiles keep everything the treemap provided:

| Requirement | How |
|---|---|
| One tile per sector, no stocks | One button per aggregated sector |
| Colour = percentage change | Per-tile CSS from the shared diverging scale |
| Equal tile area | Fixed height, equal grid columns |
| Sector name + change on the tile | Two-line button label |
| Dynamic ordering | Tiles render in the order passed in |
| Constituent counts | Tooltip on hover |

The Plotly treemap is still available from the sidebar as **Treemap (display
only)**, with the selectbox fallback for navigation. Grid width is configurable
via `PULSE_HEATMAP_COLUMNS` (default 4).

Returning uses "← Back to Sector Heatmap". **The live feed keeps running
throughout; navigation never reconnects it.**

## Connection status

The status bar always states the true source and freshness:

| Indicator | Meaning |
|---|---|
| `● LIVE (Dhan websocket)` | Receiving websocket ticks from the named broker |
| `● LIVE (Dhan REST polling)` | That broker's websocket is unavailable; prices are REST snapshots |
| `● STALE — last update Ns ago` | Market open but no update for > 10 s |
| `● MARKET CLOSED / PRE-MARKET / WEEKEND` | Outside the session; last known values shown, explicitly not live |
| `● DISCONNECTED` | No price source available |
| `● ERROR` | Authentication or reference-data failure, with the reason |

Stale data is never presented as live. Outside market hours the last known
values are shown but labelled as closed, and no prices are ever fabricated.

The broker is always named, so a silent failover from Dhan to Groww is visible
rather than implicit.

The bar also shows the last update time and an `N/50 priced` count, plus a
collapsible "Data gaps" panel listing any symbol missing an exchange token or a
previous close.

When the previous close came from daily candles rather than the OHLC endpoint
— which is the case whenever the dashboard is started outside market hours —
the bar says so beneath the pill, because it changes what the percentages are
measured against. If no previous close could be resolved at all, it says that
too, instead of leaving a board of unexplained blanks.

---

## Known limitations

### 1. ~~Groww's websocket feed never completes its handshake~~ — fixed on Groww's side

> **Resolved 2026-09-21.** Groww's socket gateway now completes the handshake
> and streams live LTP ticks; `check_heatmap_universe.py --provider groww`
> exits `OK` on the websocket. The investigation below is kept only as the
> record of what was wrong on 2026-09-18 and how it was proved.
>
> Groww's feed is still **not** interchangeable with Dhan's — the handshake is
> slow and retries silently, the SDK buffers instead of pushing, it never
> reports a drop, and it has no `close()`. Those are live concerns, not
> history, and they are documented in
> [`docs/api/GROWW_API_FEED.md`](api/GROWW_API_FEED.md#websocket-behaviour-in-practice-observed).
> Read that before touching the Groww feed path.

<details>
<summary>Historical diagnosis (2026-09-18) — the gateway went silent after CONNECT</summary>

The SDK usage in this dashboard was checked line by line against the official
docs (`python-sdk/feed`, `live-data`, `annexures`, `exceptions`) and **matches
them exactly**: instrument dicts use the required `exchange` / `segment` /
`exchange_token` keys, exchange tokens come from the instruments CSV,
`subscribe_ltp(list, on_data_received=...)` and `feed.get_ltp()` are used as
documented, and `consume()` is correctly *not* called (the docs' own
synchronous-polling example omits it, and `NatsClient` already starts its event
loop thread in its constructor).

The failure is below the SDK, in the NATS handshake. Diagnosed on 2026-09-18
during live market hours:

**Server INFO** (from `apex-nats-socket-gateway-server`, NATS 2.11.0-dev):

```json
{ "auth_required": true, "nonce": "...", "max_payload": 51200,
  "xkey": "XAWYKM2X6QOZFL4J3DMLW2BRTA5YS76QLOV4NZJ47M22KXFHOCEA64WM" }
```

The `xkey` field indicates the gateway uses **NATS auth callout** — an external
service decides whether a connection is authorised.

**Handshake behaviour observed** (raw NATS-over-WebSocket, bypassing the SDK):

*Before* `CONNECT` the protocol parser is fully alive:

| Client sends | Server response |
|---|---|
| `GARBAGE_OP` | `-ERR 'Authorization Violation'` @ 0.20 s, closes |
| `PING` | `-ERR 'Authorization Violation'` @ 0.17 s, closes |
| nothing | `-ERR 'Authentication Timeout'` @ 5.13 s, closes |
| `CONNECT` with no `jwt` | closes @ 0.14 s |

*After* a `CONNECT` carrying a valid socket JWT and nkey signature, the parser
goes completely silent:

| Client sends | Server response |
|---|---|
| `PING` | nothing, ever |
| `SUB /ld/eq/nse/price.2885 1` | no `+OK` (under `verbose`), no data |
| `GARBAGE_OP` | **nothing** — no `-ERR`, no close |
| malformed `SUB` | **nothing** |
| nothing | one server `PING` @ ~2.4 s, then silence; connection stays open 35 s+ |

The server-initiated `PING` at ~2.4 s appears exactly once and only after
`CONNECT`; our `PONG` is accepted (the connection is never closed for missed
pings).

**This is the core finding.** The gateway answers *every* malformed input before
`CONNECT` but ignores *all* input after it — including protocol violations that
any live NATS parser must reject with `-ERR 'Unknown Protocol Operation'`. The
connection is therefore not "authenticated and idle"; it is parked in a
pending-authorisation state where client input is no longer processed. Given the
`xkey` field in `INFO` (NATS **auth callout**), the most consistent explanation
is that the external authorisation service never returns a verdict, leaving the
connection in limbo. That accounts for the missing `PONG`, the ignored `SUB`,
and the total absence of market data.

A supporting control: a **deliberately corrupted** nkey signature produces
behaviour *identical* to a valid one. A server that had verified the signature
would reject it — this one never gets far enough to try.

**Ruled out:**

- *Our code* — the docs' example, reproduced verbatim in a fresh process with a
  fresh access token and a single instrument, fails identically.
- *SDK/dependency versions* — same failure with nats-py 2.9.0 (growwapi's pinned
  floor) and 2.15.0; growwapi 1.5.0 is the latest release.
- *Network/sandbox* — reproduced identically inside and outside the tool
  sandbox. The WebSocket upgrade, `INFO`, server `PING` and `-ERR` frames all
  arrive normally, and the server reacts to what we send, so both directions
  work.
- *A missing market-data entitlement* — an earlier draft of this document
  guessed this, on the incorrect assumption that the connection staying open
  proved authentication had succeeded. Two findings disprove it: the
  corrupted-signature control above, and the access token's own `role` claim,
  which contains **`live_data-basic`**. The account's Groww subscription is
  active and carries the live-data role.
- *Token staleness or the TOTP flow* — reproduced identically with a freshly
  minted access token whose `role` includes `live_data-basic` and whose
  `sourceIpAddress` claim matches this host's egress IP. REST calls made with
  that same token (`get_ltp`, `get_ohlc`, `generate_socket_token`) all succeed.

**This looks like a Groww-side problem with the socket gateway's auth callout,
not something fixable in this repository.** The reproduction above (especially
the corrupted-signature control) is what to send to Groww support.

Only the TOTP auth flow could be tested, since no `GROWW_API_SECRET` is
configured. If a key+secret is available, trying `GROWW_AUTH_MODE=API_KEY` is
worth one attempt in case the two flows mint tokens with different scopes.

The dashboard keeps retrying the websocket every 30 s in the background, on its
own thread so the retry never blocks the UI. If Groww's feed starts delivering,
the status flips to `LIVE (websocket)` automatically with no restart.

*Outcome: it did exactly that. The conclusion above — a Groww-side gateway
problem, not a code fault — held, and no code change was needed to pick the
feed up once Groww fixed it. The background retry did its job.*

</details>

### 2. REST fallback is a fallback, not the normal path

Each provider can poll instead of streaming: one **batched** quote call covering
all 50 symbols every 3 s (~20 requests/min, not 50 requests/second). It runs
only while that broker's websocket is not delivering, and is labelled
`LIVE (<broker> REST polling)` with a persistent warning banner — polled data is
never displayed as socket-live.

Disable it with `PULSE_HEATMAP_REST_FALLBACK=false` to run websocket-only.

Two broker quirks are handled here:

- **Dhan rate-limits quote endpoints to 1 request/second** across `ltp`, `ohlc`
  and `quote`. The provider throttles to stay under it and retries once on
  error `805`.
- **The Groww SDK defaults to no HTTP timeout.** An observed stall on a repeated
  `get_ltp` call froze the worker loop entirely, so every REST call made by this
  dashboard passes an explicit timeout.

### 3. Dhan access tokens expire daily

Dhan access tokens last ~24h. The provider logs remaining validity at startup
and fails with a clear message once expired; generate a fresh one from the Dhan
console and restart. TOTP is only needed to mint tokens programmatically — the
dashboard itself never prompts for an authenticator code.

Note that a token minted **before** the Data API plan was activated will not
work on the websocket even after the plan goes live: regenerate the token after
subscribing.

### 4. After the close, brokers repoint `close` at today's close

Measured on Dhan on 2026-09-18, minutes after the session ended:

| | during the session | after the close |
|---|---|---|
| Nifty 50 `last_price` | 23341.20 | 23346.40 |
| Nifty 50 `ohlc.close` | **23270.60** (yesterday) | **23346.40** (today) |

The OHLC `close` field stops meaning "previous trading day" the moment trading
stops and becomes today's close, identical to `last_price`.

**Consequence, and the guard against it.** The previous-close refresh exists to
pick up a new trading day without a restart, and it used to run every 15 minutes
regardless of session. Left running past 15:30, it would overwrite yesterday's
close with today's and collapse every percentage on the board to +0.00%,
silently erasing the day's move. The refresh is now **skipped outside market
hours** (`SESSION_OPEN` and `SESSION_PRE_MARKET` only), so a dashboard left open
keeps showing the day's closing move. `tests/test_weighting_and_breadth.py`
guards this.

**Starting the dashboard after the close.** The first fetch would get today's
close as the previous close and every tile would read +0.00%. That is why the
previous close comes from `/v2/charts/historical` outside the session instead —
see "How previous close is obtained" above. The status bar names the source,
and symbols the candles cannot cover stay unresolved rather than being filled
from the OHLC field.

**What remains.** The candle lookup is only as good as the session calendar
behind it, so on an exchange holiday it measures against the last real
session's close and reads +0.00% (limitation 5). Brokers other than Dhan have
no historical path yet: `get_prior_session_close` is optional and Groww's
provider does not implement it, so a Groww-only setup still shows the flat
board outside market hours.

### 5. Exchange holidays are not tracked

`market/market_hours.py` checks weekday and clock only. On a holiday the session
window looks open; the staleness detector surfaces the absence of ticks instead
of the dashboard implying prices are live.

It also costs one candle of accuracy in the previous-close lookup above: a
holiday is treated as a day that traded, so the lookup measures against the
last real session's close and reads +0.00% rather than that session's move.

### 6. Tata Motors demerger

`TATAMOTORS` no longer exists in Groww's instrument master. It has split into
`TMPV` (passenger vehicles, ISIN `INE155A01022` — the original Tata Motors ISIN)
and `TMCV` (commercial vehicles). The mapping uses **`TMPV`** as the continuing
index entity. If NSE also includes `TMCV` in the Nifty 50, add it to
`NIFTY_50_SECTORS`.

### 7. Constituent list drift

The Nifty 50 list is a point-in-time snapshot and NSE reconstitutes the Nifty
indices twice a year — effective end of March and end of September — plus
ad-hoc changes for mergers, demergers and suspensions.

After a reshuffle, two things need updating and neither happens on its own:

1. `NIFTY_50_SECTORS` in `market/sector_mapping.py` — which symbols exist and
   what sector each belongs to.
2. `python scripts/fetch_instrument_master.py` — the broker ids for the new
   symbols.

A symbol present in step 1 but missing from step 2 is unresolved, not wrong: it
appears in the "Data gaps" panel and is excluded from its sector's average.

---

## Configuration reference

All optional; every one has a working default. Put them in `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DHAN_ACCESS_TOKEN` | — | Dhan access token (client id is read from it) |
| `DHAN_CLIENT_ID` | from token | Optional override; normally leave unset |
| `PULSE_MARKET_PROVIDERS` | `dhan,groww` | Broker preference order |
| `PULSE_HEATMAP_UNIVERSE` | `NIFTY50` | Which universe to track |
| `PULSE_HEATMAP_UI_REFRESH_SECONDS` | `1.0` | UI fragment refresh interval |
| `PULSE_HEATMAP_SECTOR_ORDER` | `performance` | `performance` or `alphabetical` |
| `PULSE_HEATMAP_COLUMNS` | `4` | Tiles per row |
| `PULSE_HEATMAP_AGGREGATION` | `equal_weight` | `equal_weight` or `market_cap` |
| `PULSE_HEATMAP_WEIGHTS_FILE` | `data/index_weights.json` | Where weights are read from |
| `PULSE_HEATMAP_HIGHLIGHT_TABLES` | `true` | Show the leaders/laggards tables |
| `PULSE_HEATMAP_HIGHLIGHT_LIMIT` | `0` | Max rows per table (0 = all) |
| `PULSE_HEATMAP_MIN_COLOUR_SCALE_PCT` | `0.75` | Colour-scale floor |
| `PULSE_HEATMAP_FEED_DRAIN_SECONDS` | `0.5` | Feed-buffer drain interval |
| `PULSE_HEATMAP_STALE_AFTER_SECONDS` | `10.0` | Staleness threshold |
| `PULSE_HEATMAP_FEED_SILENCE_SECONDS` | `10.0` | Seconds without a tick before a connected websocket is dropped and reconnected |
| `PULSE_HEATMAP_FEED_RECONNECT_SECONDS` | `1.0` | Gap between quick reconnects to the broker that just failed |
| `PULSE_HEATMAP_FEED_RECOVERY_ATTEMPTS` | `2` | Reconnects to try before handing the socket to the next broker |
| `PULSE_HEATMAP_FEED_RETRY_SECONDS` | `30.0` | Backoff once every broker has been tried and none works |
| `PULSE_HEATMAP_REST_FALLBACK` | `true` | Enable the REST fallback |
| `PULSE_HEATMAP_REST_POLL_SECONDS` | `3.0` | Fallback poll interval |
| `PULSE_HEATMAP_REST_TIMEOUT_SECONDS` | `10` | HTTP timeout for price calls |
| `PULSE_HEATMAP_PREV_CLOSE_REFRESH_SECONDS` | `900` | Previous-close refresh interval |
| `PULSE_HEATMAP_HISTORICAL_PREV_CLOSE` | `true` | Outside market hours, take the previous close from daily candles instead of the OHLC field |
| `PULSE_INSTRUMENTS_FILE` | `data/dhan_instruments.json` | Generated instrument-id file the dashboard reads at startup |
| `PULSE_LOG_LEVEL` | `INFO` | Log level |

---

## Verifying that live data is actually updating

1. **`python scripts/check_heatmap_universe.py --seconds 20`** — prints the
   session, auth result, token/previous-close resolution, then a status line
   every 2 s. It exits `OK` only if the **websocket** delivered ticks, and warns
   explicitly when prices came from the REST fallback instead.
2. **In the dashboard** — the "Last update" clock must advance every second or
   two, and the source in the status pill tells you which path is live.
3. **Cross-check** a number: open the same symbol on groww.in and compare LTP
   and change %. The drill-down table shows LTP, previous close and the derived
   percentage so the arithmetic is auditable.
4. **Logs** — startup logs report instruments resolved, previous closes
   resolved, feed connection attempts and the first tick per symbol. Individual
   ticks are not logged by design.

---

## Testing

```bash
python -m unittest discover -s tests -t .     # 273 tests, no extra dependencies
pytest tests                                   # also works if pytest is installed
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_sector_heatmap.py` | 54 | Percentage change (positive, negative, zero, missing, zero previous close, non-numeric), equal-weight aggregation, partial/missing data, sector and constituent ranking, stale-feed detection, market-hours classification, **which session the latest price belongs to** (mid-session, after the close, pre-market, weekend, other timezones), universe configuration, treemap construction (constant tile area, colour driven by change, input ordering, no-data sectors) |
| `tests/test_providers.py` | 67 | Provider interface and registry (unknown/planned names skipped, not fatal), Dhan JWT client-id extraction and placeholder rejection, Dhan binary packet decoding against handcrafted frames (ticker, **quote**, previous close, OI, disconnect, concatenated and truncated packets), error-payload shapes, instrument resolution from the generated id file (segment isolation, a missing file, and that resolution never touches the network), **daily-candle previous-close selection** (stepping over today's candle, an unpublished candle, weekends, holiday gaps, short series, zero closes, unreadable or mismatched timestamps) and segment/instrument codes |
| `tests/test_ui_colours.py` | 29 | Colour ramp ordering (stronger move = darker shade), symmetry around zero, no-data staying neutral, clamping, text contrast, tile keys/labels/CSS, and the styled constituent table |
| `tests/test_index_board.py` | 35 | Index mapping integrity (unique symbols and labels, every drill-down link resolving to a real sector, benchmarks carrying no sector), the index universe being one group per index so nothing is averaged together, segment-code mapping, tooltips, the summary line and the index table |
| `tests/test_instruments.py` | 25 | The generated instrument-id file: loader behaviour on a missing, unparseable, empty or partly broken file, blank and `nan` ids, unknown segments, staleness against the reshuffle calendar, that the checked-in file resolves every tracked symbol with a numeric id, and the generator's filtering (the futures row not shadowing the equity, the BSE listing not being used, an index not resolving in the cash segment, unresolved symbols reported rather than invented, and a round trip back through the loader) |
| `tests/test_weighting_and_breadth.py` | 63 | Weighted means, fallback and coverage reporting when weights are missing, day-range position (including degenerate and zero-filled ranges), breadth counts, leader/laggard selection and ordering, highlight-table rendering, the weights file loader, the previous-close refresh window, and **which source supplies the previous close** (OHLC in session, daily candles outside it, never a silent fallback between them) |

The tests are deliberately confined to non-UI logic — no Streamlit, no network,
no broker credentials — so the suite runs in under a second offline.

Streamlit interaction is verified separately with `AppTest` against the live
app: tile render, click-through to a sector, back navigation, and a second
drill-down all run without exceptions. Note that `AppTest` exposes the
underlying DataFrame rather than the pandas `Styler`, so `Change %` appears
there as a raw float (`-1.406662`); the browser renders it as `-1.41%` with its
background colour. The column is kept numeric precisely so it can be both
formatted and colour-graded.

---

## What is next

See [`ROADMAP.md`](ROADMAP.md). Phases 1-4 are done: the two boards, weighting
and breadth, the sectoral index board, and the previous close outside market
hours. The largest planned item is now the **intraday time dimension** — every
number on both boards is measured against yesterday's close, so by mid-
afternoon the board describes the whole day rather than the present. A rolling
in-memory history would add change over the last 5/15/30 minutes and since the
open, plus sparklines.

Seams that already exist for later work:

| Later capability | Seam |
|---|---|
| Another weighting scheme | `AGGREGATION_STRATEGIES` in `market/sector_aggregation.py` |
| Kite (Zerodha) as a third broker | `PROVIDER_FACTORIES` + `PLANNED_PROVIDERS` in `market/providers/registry.py` |
| Nifty Next 50 and other universes | `NIFTY_NEXT_50_SECTORS` in `market/sector_mapping.py`, selected by `PULSE_HEATMAP_UNIVERSE` |
| A different price source per screen | `MarketDataProvider` / `FeedHandle` in `market/providers/base.py` |
| Historical previous close on another broker | `get_prior_session_close` in `market/providers/base.py` — optional, so a broker without one degrades rather than breaks |

None of these require rewriting the UI.
