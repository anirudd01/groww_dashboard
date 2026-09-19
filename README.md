# Pulse Tester: Groww Portfolio, FnO & Market Dashboards

Three Streamlit dashboards for a Groww trading account, sharing a common API client architecture:

- **[`fno_dashboard.py`](fno_dashboard.py)** — Futures & Options (NSE FnO + MCX Commodity) position tracker: real-time LTP, P&L, sentiment analytics, and a Quick Exit action for profitable positions.
- **[`app.py`](app.py)** — Portfolio & MTF Decoupler: separates actual (cash-owned) delivery holdings from MTF (margin/leveraged) positions, with a margin health simulator.
- **[`sector_heatmap_dashboard.py`](sector_heatmap_dashboard.py)** — Live sector heatmaps, two boards in one app: the **Nifty 50 board** aggregates the 50 constituents into sectors (equal- or market-cap weighted), and the **NSE Sectoral Indices board** shows the real index values. Both are grids of clickable tiles coloured by live percentage change, with one-click drill-down. Broker-agnostic, with **Dhan** as the default live feed and Groww as fallback. Visualisation only — it places no orders and generates no signals. See [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).

---

## Project Structure

```
pulse_tester/
│
├── fno_dashboard.py              # FnO dashboard (NSE + MCX), Quick Exit
├── app.py                        # Portfolio / MTF Decoupler dashboard
├── sector_heatmap_dashboard.py   # Live Nifty 50 sector heatmap (Streamlit entry point)
├── groww_client.py               # Groww API wrapper used by app.py (delivery/MTF/margins)
│
├── groww_api/                    # Groww API client package used by fno_dashboard.py
│   ├── client.py                 # Singleton auth (one authentication per session)
│   ├── api_calls.py              # API wrappers (positions, LTP, orders, margins)
│   ├── position_processor.py     # FnO business logic & P&L calculations
│   └── __init__.py
│
├── data/                         # Generated reference data (checked in)
│   └── index_weights.json         # Free-float market caps for sector weighting
│
├── market/                       # Live market-data domain layer (sector heatmap)
│   ├── providers/                # Broker-agnostic market data providers
│   │   ├── base.py               # MarketDataProvider / FeedHandle interfaces
│   │   ├── dhan.py               # DhanHQ v2 REST + binary websocket (preferred)
│   │   ├── groww.py              # Adapter over the existing Groww stack
│   │   └── registry.py           # Name -> provider, preference order (Kite: planned)
│   ├── config.py                 # HeatmapConfig - all tunables, env-overridable
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
├── tests/                        # Unit tests for the non-UI logic (212 tests)
│   ├── test_sector_heatmap.py     # % change, aggregation, ranking, staleness, universe
│   ├── test_providers.py          # Provider interface, registry, Dhan packet decoding
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
│   └── fetch_index_weights.py    # Regenerates data/index_weights.json (run manually)
│
├── docs/                         # Reference docs, API notes, and dated project history
│   ├── SECTOR_HEATMAP.md          # Sector heatmap design notes
│   ├── ROADMAP.md                 # What is done and what is planned next
│   ├── API_REFERENCE.md
│   ├── ARCHITECTURE.md
│   ├── QUICK_START.md
│   ├── api/                      # Groww API endpoint notes
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
```

The first two open at `http://localhost:8501`; the launcher scripts put the
sector heatmap on `http://localhost:8502` so it can run alongside them.

### 4. Maintenance scripts (not run by the dashboard)

Two files the dashboard *reads* but never *fetches*, so that no third-party
source can fail or stall while the market is open. Both are committed, and both
are regenerated by hand:

```bash
python scripts/fetch_instrument_master.py    # -> data/dhan_instruments.json
python scripts/fetch_index_weights.py        # -> data/index_weights.json
```

| Script | What it writes | Re-run it |
|---|---|---|
| `fetch_instrument_master.py` | Broker security ids for every tracked symbol (12 KB). Dhan publishes these only as a 35 MB uncompressed CSV of every F&O contract; this pulls out the sixty rows that matter | After an NSE index reconstitution (end of March / end of September), after editing `market/sector_mapping.py`, or when the dashboard reports unresolved symbols. Monthly otherwise |
| `fetch_index_weights.py` | Free-float market caps for cap-weighted sector aggregation | Weekly or monthly; share counts move slowly |

If either file is stale the dashboard says so rather than guessing: unresolved
symbols appear in the "Data gaps" panel with the script named in the logs, and
missing weights fall back to equal weighting with a visible note.

### 5. (Optional) Verify connectivity from the CLI

```bash
python scripts/test_api.py                   # groww_client.py connectivity
python scripts/check_heatmap_universe.py     # heatmap data pipeline + live feed
python scripts/check_heatmap_universe.py --provider dhan --seconds 20
python scripts/check_heatmap_universe.py --board indices --provider dhan
```

`check_heatmap_universe.py` exits `OK` only if the **websocket** delivered
ticks, and says so explicitly when prices came from the REST fallback instead.

### 6. (Optional) Run the tests

```bash
python -m unittest discover -s tests -t .    # 273 tests, no extra dependencies
```

---

## Architecture Notes

- **Two separate API client layers exist on purpose:** `groww_client.py` (`GrowwClient`) backs `app.py`, while the `groww_api/` package (`GrowwAPIClient` + `GrowwAPIService` + `PositionProcessor`) backs `fno_dashboard.py`. The `groww_api/` package uses a singleton auth pattern so the app authenticates once per session instead of on every cache refresh.
- **Shared formatting/sentiment logic** lives in `utils/` and is imported by both `fno_dashboard.py` and `groww_client.py` (for `format_inr`/`format_inr_full`) to avoid duplicated implementations.
- **Quick Exit** (in `fno_dashboard.py`) places a LIMIT SELL order at LTP − 0.5% for profitable positions, sorted highest P&L% first, and reads back the order status via `GrowwAPIService.get_order_status`.
- **The sector heatmap is broker-agnostic.** `market/providers/` defines a `MarketDataProvider` + `FeedHandle` interface with two implementations today — **Dhan** (DhanHQ v2, preferred) and **Groww** (an adapter over the existing stack). `PULSE_MARKET_PROVIDERS` sets the preference order (default `dhan,groww`); the service adopts the first broker that authenticates and fails over if its websocket cannot deliver. Kite/Zerodha is a registry placeholder for later.
- **Two boards share one engine.** The Nifty 50 board aggregates constituents into sectors; the NSE Sectoral Indices board shows real index values from Dhan's `IDX_I` segment, where each tile is one index and nothing is averaged. Each board runs its own feed (Dhan allows 5 connections per client id) and a board you have not opened is never started. The index drill-down shows the Nifty 50 members of the matching sector, labelled explicitly as *not* the index's real constituent list — neither broker publishes that.
- **Sector percentages are equal-weighted by default, market-cap weighted on request.** Equal weighting answers "how did the average stock in this sector do"; cap weighting answers "how did its big names do". Neither broker exposes market cap, so free-float weights are generated offline by `scripts/fetch_index_weights.py` into `data/index_weights.json` and only *read* at runtime — the dashboard never fetches fundamentals while the market is open. If weights are missing it falls back to equal weighting and says so rather than presenting an unweighted number as weighted.
- **It reuses, rather than duplicates, the existing Groww stack:** it authenticates through the same `GrowwAPIClient` singleton and extends `GrowwAPIService` with NSE-CASH helpers (instrument resolution, previous close via `get_ohlc`, batched LTP). Its live feed runs on a background daemon thread owned by `LiveMarketDataService`, deliberately outside Streamlit's rerun lifecycle, so reruns and view changes never rebuild the websocket. Full design notes, including the current Groww websocket limitation and the REST fallback, are in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).

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

- **Clicking a heatmap tile does nothing** — you are on the Treemap view. Streamlit cannot receive Plotly treemap clicks (it listens for `plotly_click`; treemaps emit `plotly_treemapclick`). Switch the sidebar to **Tiles (clickable)**, which is the default.
- **Sector heatmap shows "LIVE (Dhan REST polling)"** — the websocket is not delivering, so prices are batched REST snapshots (labelled as such, never shown as socket-live). Most common cause: the Dhan access token was minted **before** the Data API plan was activated — regenerate it after subscribing. Diagnose with `python scripts/check_heatmap_universe.py --provider dhan`, which reports `dataPlan` explicitly.
- **Sector heatmap shows "LIVE (Groww REST polling)"** — Dhan was unavailable and Groww's socket gateway never completes its NATS handshake (it neither authorises nor rejects the connection), so `GrowwFeed` cannot connect. The SDK usage matches Groww's docs exactly and the docs' own example fails the same way, so this is not a code fault. See "Known limitations" in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the full diagnosis to send to Groww support.

See [`docs/`](docs/) for deeper API reference and historical design notes, [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the sector heatmap, and [`docs/ROADMAP.md`](docs/ROADMAP.md) for what is planned next.
