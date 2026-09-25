# Pulse Tester: Groww Portfolio, FnO & Market Dashboards

Four Streamlit dashboards for a Groww trading account, sharing a common API client architecture:

- **[`fno_dashboard.py`](fno_dashboard.py)** — Futures & Options (NSE FnO + MCX Commodity) position tracker: real-time LTP, P&L, sentiment analytics, and a Quick Exit action for profitable positions.
- **[`app.py`](app.py)** — Portfolio & MTF Decoupler: separates actual (cash-owned) delivery holdings from MTF (margin/leveraged) positions, with a margin health simulator.
- **[`sector_heatmap_dashboard.py`](sector_heatmap_dashboard.py)** — Live sector heatmaps, two boards in one app: the **Nifty 50 board** aggregates the 50 constituents into sectors (equal- or market-cap weighted), and the **NSE Sectoral Indices board** shows the real index values. Both are grids of clickable tiles coloured by live percentage change, with one-click drill-down. Broker-agnostic and switchable from the sidebar: **Dhan** is the default live feed with **INDmoney** as the first fallback, **Groww** and **Zerodha Kite** as further options, or pin any one broker to compare them. Visualisation only — it places no orders and generates no signals. See [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).
- **[`fno_movers_dashboard.py`](fno_movers_dashboard.py)** — F&O top gainers and losers, one card per day (last 1/3/5/7 days), with separate tabs for the **Nifty 50** and **all ~210 NSE F&O stocks**. Past days come from a stored close history, and today from one bulk Kite quote. Visualisation only. See [`docs/FNO_MOVERS.md`](docs/FNO_MOVERS.md).

---

## Project Structure

```
pulse_tester/
│
├── fno_dashboard.py              # FnO dashboard (NSE + MCX), Quick Exit
├── app.py                        # Portfolio / MTF Decoupler dashboard
├── sector_heatmap_dashboard.py   # Live Nifty 50 sector heatmap (Streamlit entry point)
├── fno_movers_dashboard.py       # F&O top gainers/losers by day (Streamlit entry point)
├── groww_client.py               # Groww API wrapper used by app.py (delivery/MTF/margins)
│
├── groww_api/                    # Groww API client package used by fno_dashboard.py
│   ├── client.py                 # Singleton auth (one authentication per session)
│   ├── api_calls.py              # API wrappers (positions, LTP, orders, margins)
│   ├── position_processor.py     # FnO business logic & P&L calculations
│   └── __init__.py
│
├── data/                         # Generated reference data (checked in)
│   ├── index_weights.json         # Free-float market caps for sector weighting
│   ├── fno_universe.json          # NSE F&O stocks + Kite tokens (update_fno_history.py)
│   ├── fno_daily_closes.csv       # Daily OHLCV per F&O stock (update_fno_history.py)
│   ├── dhan_instruments.json      # Dhan security ids for tracked symbols
│   ├── indmoney_instruments.json  # INDmoney security ids for tracked symbols
│   └── kite_instruments.json      # Kite instrument tokens + tradingsymbols
│
├── market/                       # Live market-data domain layer (sector heatmap)
│   ├── providers/                # Broker-agnostic market data providers
│   │   ├── base.py               # MarketDataProvider / FeedHandle interfaces
│   │   ├── dhan.py               # DhanHQ v2 REST + binary websocket (preferred)
│   │   ├── indmoney.py           # INDmoney (INDstocks) REST + JSON websocket
│   │   ├── groww.py              # Adapter over the existing Groww stack
│   │   ├── kite.py               # Zerodha Kite Connect REST + binary websocket (read-only)
│   │   ├── kite_session.py       # Kite login flow + the saved daily session
│   │   ├── candles.py            # Shared daily-candle previous-close logic
│   │   └── registry.py           # Name -> provider, preference order
│   ├── config.py                 # HeatmapConfig - all tunables, env-overridable
│   ├── fno_movers.py             # F&O universe, close history, daily movers (pure)
│   ├── universe.py               # Universe registry (NIFTY50; NIFTYNEXT50 ready)
│   ├── sector_mapping.py         # symbol -> sector classification (edit here)
│   ├── index_mapping.py          # which NSE indices the index board shows
│   ├── models.py                 # StockMarketData / SectorMarketData / FeedStatus
│   ├── live_feed.py              # LiveMarketDataService (background feed worker + failover)
│   ├── sector_aggregation.py     # % change, aggregation strategies, highlights
│   ├── weights.py                # Reads the offline weights file (never fetches)
│   └── market_hours.py           # NSE session classification
│
├── ui/                           # Heatmap presentation layer
│   ├── sector_tiles.py           # Clickable coloured sector tiles (default)
│   ├── sector_heatmap.py         # Plotly treemap (display-only alternative)
│   ├── colours.py                # Shared diverging colour scale
│   ├── sector_detail.py          # Constituent table + colour grading
│   ├── sector_highlights.py      # Leading / lagging sector tables
│   └── index_board.py            # NSE sectoral index board
│
├── tests/                        # Unit tests for the non-UI logic (403 tests)
│   ├── test_sector_heatmap.py     # % change, aggregation, ranking, staleness, universe
│   ├── test_providers.py          # Provider interface, registry, Dhan packet decoding
│   ├── test_indmoney.py           # INDmoney frames, REST mapping, index-name table
│   ├── test_kite.py               # Kite login/session expiry, packets, REST mapping, read-only guard
│   ├── test_fno_movers.py         # F&O universe, close file upserts, gap-safe daily moves
│   ├── test_ui_colours.py         # Colour ramp, tile keys/labels/CSS, styled table
│   ├── test_weighting_and_breadth.py  # Weighting, breadth, leader/laggard tables
│   └── test_index_board.py        # Index mapping, universe, tooltips, index table
│
├── utils/                        # Shared formatting, sentiment & constants
│   ├── formatting.py             # format_inr, format_expiry_date/_short, sentiment helpers
│   ├── constants.py               # Segments, exchanges, keyword lists, month maps
│   └── __init__.py
│
├── strategies/                   # Standalone Groww Cloud exit strategy scripts
│   ├── groww_cloud_equity_15pct_exit_strategy.py
│   └── groww_cloud_commodity_15pct_exit_strategy.py
│
├── scripts/
│   ├── test_api.py               # CLI connectivity/diagnostic check for groww_client.py
│   ├── check_heatmap_universe.py # Verifies tokens, previous closes & the live feed
│   ├── fetch_instrument_master.py # Generates data/dhan_instruments.json (run monthly)
│   ├── fetch_indmoney_instruments.py # Generates data/indmoney_instruments.json
│   ├── fetch_kite_instruments.py # Generates data/kite_instruments.json (public, no login)
│   ├── kite_login.py             # Daily Zerodha login -> .kite_session.json
│   ├── fetch_index_weights.py    # Regenerates data/index_weights.json (run manually)
│   └── update_fno_history.py     # Extends data/fno_daily_closes.csv (daily/weekly, needs Kite login)
│
├── docs/                         # Reference docs, API notes, and dated project history
│   ├── PROVIDER_GUIDE.md          # Which broker API (Kite/Dhan/INDmoney/Groww) for which job — read first
│   ├── PROVIDER_COMPARISON_LOG.md # Dated, measured broker comparisons (the evidence behind the guide)
│   ├── SECTOR_HEATMAP.md          # Sector heatmap design notes
│   ├── FNO_MOVERS.md              # F&O movers: provider comparison, storage choice
│   ├── ROADMAP.md                 # What is done and what is planned next
│   ├── API_REFERENCE.md
│   ├── ARCHITECTURE.md
│   ├── QUICK_START.md
│   ├── api/                      # Groww, INDmoney and Kite API notes (INDMONEY_API.md: Dhan comparison)
│   └── _archived/                # Superseded design/status docs, kept for history
│
├── run_fno_dashboard.bat / .ps1  # Windows launchers for fno_dashboard.py
├── run_sector_heatmap.bat / .ps1 # Windows launchers for the sector heatmap (port 8502)
├── requirements.txt
└── .env.example                  # Credentials template
```

---

## Getting Started

### 1. Set up the environment

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

**For the sector heatmap (Dhan — the default provider), one variable is enough:**

```bash
DHAN_ACCESS_TOKEN=your_dhan_access_token
```

Dhan embeds the client id in the token, so `DHAN_CLIENT_ID` is not needed. The
token lasts ~24h and requires Dhan's paid **Data API** plan for quotes and the
live feed; generate the token *after* subscribing.

**For INDmoney (free market data), also one variable:**

```bash
IND_MONEY_ACCESS_TOKEN=your_indmoney_access_token
```

Generate it at indstocks.com → API Trading → Access Tokens; it lasts 24 hours.
Choose the broker in the heatmap's sidebar (**Data provider**): *Auto* walks
`PULSE_MARKET_PROVIDERS` with failover, and picking one broker pins the boards
to it. How INDmoney compares with Dhan, and what it does not serve (Nifty Oil &
Gas), is in [`docs/api/INDMONEY_API.md`](docs/api/INDMONEY_API.md).

**For Zerodha Kite (paid Kite Connect plan), two variables plus a daily login:**

```bash
KITE_API_KEY=your_kite_api_key       # KITE_APIKEY is accepted too
KITE_API_SECRET=your_kite_api_secret
```

Both come from your app at developers.kite.trade. Kite tokens cannot be pasted
in: they come from a browser login and expire at **06:00 IST every day**. So
each trading morning, run:

```bash
python scripts/kite_login.py          # opens Zerodha's login page, then asks you to paste the redirect URL
python scripts/kite_login.py --status # is today's session still accepted?
```

This saves the day's token to `.kite_session.json`, which is git-ignored. The
dashboard picks it up the next time a board connects to Kite, with no restart
needed. Kite comes last in *Auto*, so until you log in it is just skipped. The
Kite code is read-only: it calls no order endpoint. Details are in
[`docs/api/KITE_API.md`](docs/api/KITE_API.md).

**For the Groww dashboards (and the heatmap's Groww fallback)**, fill in one of:

```bash
# Option A: TOTP flow (recommended)
GROWW_AUTH_MODE=TOTP
GROWW_API_KEY=your_api_key
GROWW_TOTP_SECRET=your_secret

# Option B: API Key + Secret
GROWW_AUTH_MODE=API_KEY
GROWW_API_KEY=your_key
GROWW_API_SECRET=your_secret

# Option C: Direct access token (short-lived)
GROWW_AUTH_MODE=TOKEN
GROWW_ACCESS_TOKEN=your_access_token
```

### 3. Run a dashboard

```bash
streamlit run fno_dashboard.py               # FnO tracker + Quick Exit
streamlit run app.py                         # Portfolio / MTF Decoupler
streamlit run sector_heatmap_dashboard.py    # Live Nifty 50 sector heatmap
streamlit run fno_movers_dashboard.py --server.port 8503   # F&O gainers/losers by day
```

The first two open at `http://localhost:8501`; the launcher scripts put the
sector heatmap on `http://localhost:8502` so it can run alongside them.

### 4. Maintenance scripts (not run by the dashboard)

Files the dashboard *reads* but never *fetches*, so that no third-party
source can fail or stall while the market is open. Both are committed, and both
are regenerated by hand:

```bash
python scripts/fetch_instrument_master.py    # -> data/dhan_instruments.json
python scripts/fetch_indmoney_instruments.py # -> data/indmoney_instruments.json (needs the token)
python scripts/fetch_kite_instruments.py     # -> data/kite_instruments.json (public, no login)
python scripts/fetch_index_weights.py        # -> data/index_weights.json
python scripts/update_fno_history.py         # -> data/fno_universe.json + fno_daily_closes.csv (needs kite_login.py)
```

| Script | What it writes | Re-run it |
|---|---|---|
| `fetch_instrument_master.py` | Broker security ids for every tracked symbol (12 KB). Dhan publishes these only as a 35 MB uncompressed CSV of every F&O contract; this pulls out the sixty rows that matter | After an NSE index reconstitution (end of March / end of September), after editing `market/sector_mapping.py`, or when the dashboard reports unresolved symbols. Monthly otherwise |
| `fetch_indmoney_instruments.py` | INDmoney's ids for the same symbols (11 KB). Equity ids equal Dhan's; index ids and names are INDmoney's own | Same triggers as Dhan's file |
| `fetch_kite_instruments.py` | Kite's `instrument_token` (websocket/candles) **and** `tradingsymbol` (REST quotes) for the same symbols (12 KB), from Kite's public 0.7 MB NSE dump | Same triggers as Dhan's file |
| `fetch_index_weights.py` | Free-float market caps for cap-weighted sector aggregation | Weekly or monthly; share counts move slowly |
| `update_fno_history.py` | The F&O stock list, plus each stock's daily OHLCV appended to one CSV. One Kite request per stock however many days are missing (~210 requests, 75-110 s) | Daily after 16:00 IST, or weekly: one run fills every missing day. The movers dashboard warns when the history is more than 4 days old |

If either file is stale the dashboard says so rather than guessing: unresolved
symbols appear in the "Data gaps" panel with the script named in the logs, and
missing weights fall back to equal weighting with a visible note.

### 5. (Optional) Verify connectivity from the CLI

```bash
python scripts/test_api.py                   # groww_client.py connectivity
python scripts/check_heatmap_universe.py     # heatmap data pipeline + live feed
python scripts/check_heatmap_universe.py --provider dhan --seconds 20
python scripts/check_heatmap_universe.py --board indices --provider dhan
python scripts/check_heatmap_universe.py --provider indmoney --seconds 20
python scripts/check_heatmap_universe.py --provider kite --seconds 20     # after kite_login.py
```

`check_heatmap_universe.py` exits `OK` only if the **websocket** delivered
ticks, and says so explicitly when prices came from the REST fallback instead.

### 6. (Optional) Run the tests

```bash
python -m unittest discover -s tests -t .    # 403 tests, no extra dependencies
```

---

## Architecture Notes

- **Two separate API client layers exist on purpose:** `groww_client.py` (`GrowwClient`) backs `app.py`, while the `groww_api/` package (`GrowwAPIClient` + `GrowwAPIService` + `PositionProcessor`) backs `fno_dashboard.py`. The `groww_api/` package uses a singleton auth pattern so the app authenticates once per session instead of on every cache refresh.
- **Shared formatting/sentiment logic** lives in `utils/` and is imported by both `fno_dashboard.py` and `groww_client.py` (for `format_inr`/`format_inr_full`) to avoid duplicated implementations.
- **Quick Exit** (in `fno_dashboard.py`) places a LIMIT SELL order at LTP − 0.5% for profitable positions, sorted highest P&L% first, and reads back the order status via `GrowwAPIService.get_order_status`.
- **The sector heatmap is broker-agnostic.** `market/providers/` defines a `MarketDataProvider` + `FeedHandle` interface, implemented by **Dhan** (DhanHQ v2, preferred), **INDmoney** (INDstocks API, free, first fallback), **Groww** (an adapter over the existing stack) and **Kite** (Zerodha Kite Connect, last in *Auto*). `PULSE_MARKET_PROVIDERS` sets the preference order for *Auto*; the service adopts the first broker that authenticates and fails over if its websocket cannot deliver. The sidebar's **Data provider** switch can instead pin one broker with no failover, for comparing them. Kite is called without the `kiteconnect` SDK: the SDK's ticker runs on Twisted, whose reactor cannot restart within a process, and this service reconnects feeds as a matter of course.
- **Two boards share one engine.** The Nifty 50 board aggregates constituents into sectors; the NSE Sectoral Indices board shows real index values (Dhan's `IDX_I` segment, or INDmoney's `NIDX`), where each tile is one index and nothing is averaged. Each board runs its own feed (Dhan allows 5 connections per client id, INDmoney 3 per user) and a board you have not opened is never started. The index drill-down shows the Nifty 50 members of the matching sector, labelled explicitly as *not* the index's real constituent list — neither broker publishes that.
- **Sector percentages are equal-weighted by default, market-cap weighted on request.** Equal weighting answers "how did the average stock in this sector do"; cap weighting answers "how did its big names do". Neither broker exposes market cap, so free-float weights are generated offline by `scripts/fetch_index_weights.py` into `data/index_weights.json` and only *read* at runtime — the dashboard never fetches fundamentals while the market is open. If weights are missing it falls back to equal weighting and says so rather than presenting an unweighted number as weighted.
- **It reuses, rather than duplicates, the existing Groww stack:** it authenticates through the same `GrowwAPIClient` singleton and extends `GrowwAPIService` with NSE-CASH helpers (instrument resolution, previous close via `get_ohlc`, batched LTP). Its live feed runs on a background daemon thread owned by `LiveMarketDataService`, deliberately outside Streamlit's rerun lifecycle, so reruns and view changes never rebuild the websocket. Full design notes and the REST fallback are in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md); how Groww's websocket differs from Dhan's, and what the adapter does about it, is in [`docs/api/GROWW_API_FEED.md`](docs/api/GROWW_API_FEED.md#websocket-behaviour-in-practice-observed).

---

## Requirements

```
Python >=3.9
streamlit >=1.35.0
pandas >=2.0.0
plotly >=5.20.0
growwapi >=0.1.0
pyotp >=2.9.0
python-dotenv >=1.0.0
requests >=2.31.0
websockets >=12.0
```

`websockets` backs the Dhan binary market feed. Dhan needs no SDK — its REST
and websocket APIs are called directly.

---

## Troubleshooting

- **"Client not authenticated"** — verify `.env` credentials and `GROWW_AUTH_MODE`. Direct access tokens are short-lived; regenerate one when it expires.
- **Restarting after a credential change** — `GrowwAPIClient`/`GrowwClient` authenticate once per running process. The sidebar's "Refresh Data" button only clears the Streamlit data cache; after changing `.env` credentials, fully restart the Streamlit process to re-authenticate.
- **Dashboard won't start** — confirm the venv is activated and Streamlit is installed (`python -m streamlit run fno_dashboard.py`).

- **INDmoney: "authentication failed ... TokenException"** — the 24h token has expired or was revoked. Generate a new one at indstocks.com → API Trading → Access Tokens and restart the dashboard.
- **INDmoney index board shows 16/17, with Nifty Oil & Gas missing** — expected. INDmoney lists that index but serves no data for it; see [`docs/api/INDMONEY_API.md`](docs/api/INDMONEY_API.md).
- **Kite shows "no credentials" in the provider list** — the API key is set but nobody has logged in today, or the session passed 06:00 IST. Run `python scripts/kite_login.py`.
- **Kite: "authentication failed (HTTP 403 ... TokenException)"** — the token was revoked, for example by logging out of all Kite sessions. Log in again with `scripts/kite_login.py`.
- **Kite: "market data unavailable (HTTP 403 ... PermissionException)"** — the app is on the free *Personal* plan, which has no quotes, historical data or websocket. The paid *Kite Connect* plan is needed.
- **Kite login: "Token is invalid or has expired"** — the `request_token` in the redirect URL is single-use and lasts a few minutes. Log in again and paste the new URL promptly.
- **INDmoney websocket won't connect while both boards are open** — INDmoney allows 3 sockets per user. Two boards plus a `check_heatmap_universe.py` run already use all three.

- **Clicking a heatmap tile does nothing** — you are on the Treemap view. Streamlit cannot receive Plotly treemap clicks (it listens for `plotly_click`; treemaps emit `plotly_treemapclick`). Switch the sidebar to **Tiles (clickable)**, which is the default.
- **Sector heatmap shows "LIVE (Dhan REST polling)"** — the websocket is not delivering, so prices are batched REST snapshots (labelled as such, never shown as socket-live). Most common cause: the Dhan access token was minted **before** the Data API plan was activated — regenerate it after subscribing. Diagnose with `python scripts/check_heatmap_universe.py --provider dhan`, which reports `dataPlan` explicitly.
- **Terminal says "Dhan websocket delivered nothing for 10.0s - reconnecting"** — the socket went quiet or dropped, and the service is getting it back. A dropped Dhan socket reconnects in ~2 s and the board stays on Dhan; REST covers the gap, which is why nothing changes on screen. Only if two reconnects in a row fail does the board move to the next broker. See "Recovery before failover" in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).

- **Sector heatmap shows "LIVE (Groww REST polling)" for the first few seconds** — normal. Groww's socket handshake is slow (1 s in the best case, tens of seconds routinely), so the board polls REST until it lands and then switches to `LIVE (websocket)` by itself, typically within 10–20 s. The banner says whether it is still negotiating or has actually failed.

- **Groww logs a run of empty `ERROR ... nats_client: Error:` lines, then works** — also normal, and the single most misleading thing this feed does. Each line is a `TimeoutError` from Groww's gateway with an empty message; `nats-py` retries every ~4 s until one lands. It is not a fault and needs no action. Groww's websocket behaves quite differently from Dhan's in several other ways too — buffered rather than pushed, no drop notification, no `close()` — all measured and explained in [`docs/api/GROWW_API_FEED.md`](docs/api/GROWW_API_FEED.md#websocket-behaviour-in-practice-observed). **Read that before assuming the two brokers' sockets behave alike.**

- **Groww REST starts failing with `Extra data: line 1 column 5` or `Authentication failed: The requested resource was not found`** — Groww throttles its REST and auth endpoints, and restarting the dashboard repeatedly while debugging will trip it. Neither is a socket problem; wait a few minutes.

See [`docs/`](docs/) for deeper API reference and historical design notes, [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the sector heatmap, and [`docs/ROADMAP.md`](docs/ROADMAP.md) for what is planned next.
