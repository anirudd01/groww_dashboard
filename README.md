# Pulse Tester: Groww Portfolio, FnO & Market Dashboards

Three Streamlit dashboards for a Groww trading account, sharing a common API client architecture:

- **[`fno_dashboard.py`](fno_dashboard.py)** — Futures & Options (NSE FnO + MCX Commodity) position tracker: real-time LTP, P&L, sentiment analytics, and a Quick Exit action for profitable positions.
- **[`app.py`](app.py)** — Portfolio & MTF Decoupler: separates actual (cash-owned) delivery holdings from MTF (margin/leveraged) positions, with a margin health simulator.
- **[`sector_heatmap_dashboard.py`](sector_heatmap_dashboard.py)** — Live Nifty 50 sector heatmap: a Plotly treemap of sector performance driven by a background live-market-data service, with drill-down into each sector's constituents. Visualisation only — it places no orders and generates no signals. See [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).

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
├── market/                       # Live market-data domain layer (sector heatmap)
│   ├── providers/                # Broker-agnostic market data providers
│   │   ├── base.py               # MarketDataProvider / FeedHandle interfaces
│   │   ├── dhan.py               # DhanHQ v2 REST + binary websocket (preferred)
│   │   ├── groww.py              # Adapter over the existing Groww stack
│   │   └── registry.py           # Name -> provider, preference order (Kite: planned)
│   ├── config.py                 # HeatmapConfig - all tunables, env-overridable
│   ├── universe.py               # Universe registry (NIFTY50; NIFTYNEXT50 ready)
│   ├── sector_mapping.py         # symbol -> sector classification (edit here)
│   ├── models.py                 # StockMarketData / SectorMarketData / FeedStatus
│   ├── live_feed.py              # LiveMarketDataService (background GrowwFeed worker)
│   ├── sector_aggregation.py     # % change + sector aggregation strategies
│   └── market_hours.py           # NSE session classification
│
├── ui/                           # Heatmap presentation layer
│   ├── sector_tiles.py           # Clickable coloured sector tiles (default)
│   ├── sector_heatmap.py         # Plotly treemap (display-only alternative)
│   ├── colours.py                # Shared diverging colour scale
│   └── sector_detail.py          # Constituent table + colour grading
│
├── tests/                        # Unit tests for the calculation layer
│   └── test_sector_heatmap.py
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
│   └── check_heatmap_universe.py # Verifies tokens, previous closes & the live feed
│
├── docs/                         # Reference docs, API notes, and dated project history
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

Fill in one of:

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

### 4. (Optional) Verify connectivity from the CLI

```bash
python scripts/test_api.py                   # groww_client.py connectivity
python scripts/check_heatmap_universe.py     # heatmap data pipeline + live feed
```

### 5. (Optional) Run the tests

```bash
python -m unittest discover -s tests -t .
```

---

## Architecture Notes

- **Two separate API client layers exist on purpose:** `groww_client.py` (`GrowwClient`) backs `app.py`, while the `groww_api/` package (`GrowwAPIClient` + `GrowwAPIService` + `PositionProcessor`) backs `fno_dashboard.py`. The `groww_api/` package uses a singleton auth pattern so the app authenticates once per session instead of on every cache refresh.
- **Shared formatting/sentiment logic** lives in `utils/` and is imported by both `fno_dashboard.py` and `groww_client.py` (for `format_inr`/`format_inr_full`) to avoid duplicated implementations.
- **Quick Exit** (in `fno_dashboard.py`) places a LIMIT SELL order at LTP − 0.5% for profitable positions, sorted highest P&L% first, and reads back the order status via `GrowwAPIService.get_order_status`.
- **The sector heatmap is broker-agnostic.** `market/providers/` defines a `MarketDataProvider` + `FeedHandle` interface with two implementations today — **Dhan** (DhanHQ v2, preferred) and **Groww** (an adapter over the existing stack). `PULSE_MARKET_PROVIDERS` sets the preference order (default `dhan,groww`); the service adopts the first broker that authenticates and fails over if its websocket cannot deliver. Kite/Zerodha is a registry placeholder for later.
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
```

---

## Troubleshooting

- **"Client not authenticated"** — verify `.env` credentials and `GROWW_AUTH_MODE`. Direct access tokens are short-lived; regenerate one when it expires.
- **Restarting after a credential change** — `GrowwAPIClient`/`GrowwClient` authenticate once per running process. The sidebar's "Refresh Data" button only clears the Streamlit data cache; after changing `.env` credentials, fully restart the Streamlit process to re-authenticate.
- **Dashboard won't start** — confirm the venv is activated and Streamlit is installed (`python -m streamlit run fno_dashboard.py`).

- **Clicking a heatmap tile does nothing** — you are on the Treemap view. Streamlit cannot receive Plotly treemap clicks (it listens for `plotly_click`; treemaps emit `plotly_treemapclick`). Switch the sidebar to **Tiles (clickable)**, which is the default.
- **Sector heatmap shows "LIVE (REST polling)"** — Groww's socket gateway never completes its NATS handshake (it neither authorises nor rejects the connection), so `GrowwFeed` cannot connect and the dashboard falls back to batched REST snapshots, labelled as such. The SDK usage matches Groww's docs exactly and the docs' own example fails the same way, so this is not a code fault. See "Known limitations" in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the full diagnosis to send to Groww support.

See [`docs/`](docs/) for deeper API reference and historical design notes, and [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the sector heatmap.
