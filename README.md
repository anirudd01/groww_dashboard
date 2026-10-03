# Pulse Tester: Groww Portfolio, FnO & Market Dashboards

Five Streamlit dashboards: four for a Groww trading account, sharing a common API client architecture, and one built only from TradingView widgets:

- **[`apps/fno_dashboard.py`](apps/fno_dashboard.py)** — Futures & Options (NSE FnO + MCX Commodity) position tracker: real-time LTP, P&L, sentiment analytics, and a Quick Exit action for profitable positions.
- **[`apps/app.py`](apps/app.py)** — Portfolio & MTF Decoupler: separates actual (cash-owned) delivery holdings from MTF (margin/leveraged) positions, with a margin health simulator.
- **[`pulse_dashboard.py`](pulse_dashboard.py)** — One app with an always-expanded top navbar ([`ui/navbar.py`](ui/navbar.py)): every page is a direct link, grouped as **Sectors** (Nifty 50 Sectors, Sectoral Indices, two treemaps), **F&O** (Nifty 50 Movers, All F&O Movers, F&O Heatmap, Dhan Movers) **Insights** (Breadth, Overnight vs Intraday, Rotation, Gap Fills, Gap Streaks) and **MCX** (MCX Futures). One row per group, with no dropdown or "more" menu to open first, and Streamlit's large top padding trimmed so the bar sits at the top of the page (from [`apps/sector_heatmap_dashboard.py`](apps/sector_heatmap_dashboard.py) and [`apps/fno_movers_dashboard.py`](apps/fno_movers_dashboard.py)). Live sector heatmaps, two boards: the **Nifty 50 board** aggregates the 50 constituents into sectors (equal- or market-cap weighted), and the **NSE Sectoral Indices board** shows the real index values. Both are grids of clickable tiles coloured by live percentage change, with one-click drill-down. Broker-agnostic and switchable from the sidebar: **Dhan** is the default live feed with **INDmoney** as the first fallback, **Groww** and **Zerodha Kite** as further options, or pin any one broker to compare them. Visualisation only — it places no orders and generates no signals. See [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).
- **[`apps/fno_movers_dashboard.py`](apps/fno_movers_dashboard.py)** — F&O top gainers and losers, one card per day (last 1/3/5/7 days), as two navbar pages: the **Nifty 50** and **all ~210 NSE F&O stocks**. Past days come from a stored close history, and today from one bulk Kite quote. Visualisation only. See [`docs/FNO_MOVERS.md`](docs/FNO_MOVERS.md).
- **[`apps/fno_heatmap_dashboard.py`](apps/fno_heatmap_dashboard.py)** — **F&O consistency heatmap** (the **F&O Heatmap** navbar page): which F&O stocks rose or fell *steadily* over the last 3–20 trading days, not just which moved most. Three stock × day heatmaps in tabs: the **Nifty 50**, the most consistent **gainers** among the other F&O stocks, and the most consistent **losers** among them. Each cell is one day's % change. Rows are ranked by a consistency score (net move ÷ total distance moved) or, from a radio button, by up days or plain net change. Reads only the stored daily closes, with no API call. See [`docs/FNO_HEATMAP.md`](docs/FNO_HEATMAP.md).
- **F&O insights**: five pages in the **Insights** group, built only from the stored history, with no API call. They are **[Market Breadth](apps/fno_breadth_dashboard.py)** (% of stocks above their 20/50-day averages, A/D line, new highs vs lows), **[Overnight vs Intraday](apps/fno_session_split_dashboard.py)** (whether each stock's move came from the gaps or the session), **[Relative Rotation](apps/fno_rotation_dashboard.py)** (RRG-style quadrants for Nifty 50 sectors and stocks against an equal-weight Nifty 50) and **[Gap Fills](apps/fno_gap_fills_dashboard.py)** (how often and how fast gaps trade back to the previous close, from 1-minute bars in `data/market.db`) and **[Gap Streaks](apps/fno_gap_streaks_dashboard.py)** (which stocks gapped up or down day after day: stock × day heatmaps of each day's gap, current streaks, and whether the session held the gaps). See [`docs/FNO_INSIGHTS.md`](docs/FNO_INSIGHTS.md).
- **[`apps/mcx_futures_dashboard.py`](apps/mcx_futures_dashboard.py)** — **MCX Futures**: one row per MCX commodity (bullion, energy, base metals, agri) with last price, change against the previous close, the day's range, volume and open interest, plus headline cards for gold, silver, crude, natural gas and copper. Shows the most active contract (highest open interest) by default, or the near/next/far month. Click a row for 5-minute, 15-minute, hourly or daily candles with open interest. **Dhan** serves it, and **Kite** takes over automatically when Dhan fails (after `kite_login.py`). The contract list comes from `scripts/fetch_mcx_futures.py`. Visualisation only. See [`docs/MCX_FUTURES.md`](docs/MCX_FUTURES.md).
- **[`apps/dhan_movers_dashboard.py`](apps/dhan_movers_dashboard.py)** — **Dhan Movers**: Dhan's own server-side rankings (`/v2/data/marketmovers`). Four screens: **Stocks** (top gainers/losers of F&O stocks, Nifty 50/500 or a sector index, set against money traded), **Futures** (price against open-interest build-up, and the most traded contracts with their basis) **Options** (open interest by strike, calls against puts) and **History** (the stored closes, read from the database: any past session, breadth over time, the stocks that keep topping the lists). The live screens rank today against the previous close only. Needs Dhan credentials. Visualisation only. See [`docs/DHAN_MOVERS.md`](docs/DHAN_MOVERS.md).
- **[`apps/tradingview_dashboard.py`](apps/tradingview_dashboard.py)** — **Market pulse**: crude oil (WTI, Brent), natural gas (Henry Hub), USD/INR and EUR/INR, and Indian markets, each category in its own section. There are two views: **ticker tags** (compact pills; hover one for its chart) and **mini charts with TradingView's Top Stories** news alongside. It needs no credentials and the app makes no network calls: TradingView's widgets fetch their own data in the browser. NSE, MCX and GIFT Nifty are **not licensed for TradingView widgets**, so Nifty is shown through its BSE-listed ETFs, crude and gas through the CFDs that track the benchmarks, and the rest as links to tradingview.com. See [`docs/TRADINGVIEW_WIDGETS.md`](docs/TRADINGVIEW_WIDGETS.md), the widget reference to read before touching any TradingView widget.

---

## Project Structure

```
pulse_tester/
│
├── pulse_dashboard.py            # Main entry point: always-expanded top navbar (Sectors / F&O / Insights / MCX links)
├── apps/                         # Every other Streamlit app (each also runs on its own)
│   ├── fno_dashboard.py          # FnO dashboard (NSE + MCX), Quick Exit
│   ├── app.py                    # Portfolio / MTF Decoupler dashboard
│   ├── sector_heatmap_dashboard.py  # Sector heatmap page functions (used by pulse_dashboard.py)
│   ├── fno_movers_dashboard.py   # F&O top gainers/losers (page functions + standalone entry point)
│   ├── dhan_movers_dashboard.py  # Dhan market movers: stocks, futures build-up, options OI (page + standalone)
│   ├── mcx_futures_dashboard.py  # MCX commodity futures: board + candles, Dhan with Kite fallback (page + standalone)
│   ├── fno_heatmap_dashboard.py  # F&O consistency heatmap: Nifty 50 / other F&O gainers / losers (stored closes only)
│   ├── fno_breadth_dashboard.py  # Insights: market breadth (stored closes only)
│   ├── fno_session_split_dashboard.py  # Insights: overnight vs intraday (stored closes only)
│   ├── fno_rotation_dashboard.py # Insights: relative rotation, RRG-style (stored closes only)
│   ├── fno_gap_fills_dashboard.py  # Insights: gap fills (data/market.db)
│   ├── fno_gap_streaks_dashboard.py  # Insights: consistent gap-ups / gap-downs (stored closes only)
│   ├── fno_common.py             # Shared loaders/widgets for the Insights pages
│   └── tradingview_dashboard.py  # Market pulse: TradingView widgets, no credentials
├── groww_api/                    # Groww API code (subscription ended, see the note below)
│   ├── groww_client.py           # GrowwClient: delivery/MTF/margins, used by apps/app.py
│   ├── client.py                 # Singleton auth (one authentication per session)
│   ├── api_calls.py              # API wrappers (positions, LTP, orders, margins)
│   ├── position_processor.py     # FnO business logic & P&L calculations
│   └── __init__.py
│
├── data/                         # Local data: one git-ignored SQLite database
│   └── market.db                  # F&O bars and closes, Dhan gainers/losers history, saved sessions, clock offset, generated reference data. See "What lives in data/market.db". Back it up
│
├── market/                       # Live market-data domain layer (sector heatmap)
│   ├── providers/                # Broker-agnostic market data providers
│   │   ├── base.py               # MarketDataProvider / FeedHandle interfaces
│   │   ├── dhan.py               # DhanHQ v2 REST + binary websocket (preferred)
│   │   ├── indmoney.py           # INDmoney (INDstocks) REST + JSON websocket
│   │   ├── groww.py              # Adapter over the existing Groww stack
│   │   ├── kite.py               # Zerodha Kite Connect REST + binary websocket (read-only)
│   │   ├── kite_session.py       # Kite login flow + the saved daily session
│   │   ├── dhan_session.py       # Dhan token minted from TOTP, shared via market.db (dhan_session)
│   │   ├── indmoney_session.py   # INDmoney token minted from TOTP, shared via market.db (indmoney_session)
│   │   ├── token_store.py        # Small helpers both of those share (JWT claims, env spellings); the storage and lock are in state_store.py
│   │   ├── candles.py            # Shared daily-candle previous-close logic
│   │   └── registry.py           # Name -> provider, preference order
│   ├── config.py                 # HeatmapConfig - all tunables, env-overridable
│   ├── fno_movers.py             # F&O universe, close history, daily movers (pure)
│   ├── dhan_movers.py            # Dhan marketmovers request/response parsing, build-up classifier, session_date (pure)
│   ├── dhan_movers_history.py    # Takes one capture of the gainers/losers and stores it (session dating, once-per-session)
│   ├── dhan_movers_store.py      # dhan_movers + dhan_movers_breadth tables in market.db: schema, one-transaction write, reads
│   ├── fno_consistency.py        # Consistency score + ranking over the last N days (pure)
│   ├── price_panel.py            # Date x symbol frames, equal-weight index, universe sets (pure)
│   ├── breadth.py                # Advances/declines, % above MAs, new highs/lows (pure)
│   ├── session_split.py          # Overnight vs intraday split per stock (pure)
│   ├── rotation.py               # RRG-style RS-Ratio / RS-Momentum and quadrants (pure)
│   ├── gap_fills.py              # Gap fills from daily_gaps + minute bars (read-only SQLite)
│   ├── gap_streaks.py            # Consistent gap-ups/downs, streaks, session follow-through (pure)
│   ├── clock_offset.py           # PC clock vs NTP, saved to market.db (clock_offset); all TOTP codes use it
│   ├── intraday_store.py         # The shared SQLite database: connection, F&O bars schema, upserts, read-only handle
│   ├── state_store.py            # Saved sessions + clock offset as rows in that database, and the cross-process lock
│   ├── reference_store.py        # Generated reference data (instrument ids, weights, F&O list) as rows in it
│   ├── tradingview_symbols.py    # Market pulse: categories, symbols, proxies, what widgets cannot show
│   ├── universe.py               # Universe registry (NIFTY50; NIFTYNEXT50 ready)
│   ├── sector_mapping.py         # symbol -> sector classification (edit here)
│   ├── index_mapping.py          # which NSE indices the index board shows
│   ├── models.py                 # StockMarketData / SectorMarketData / FeedStatus
│   ├── live_feed.py              # LiveMarketDataService (background feed worker + failover)
│   ├── sector_aggregation.py     # % change, aggregation strategies, highlights
│   ├── weights.py                # Reads the stored weights (never fetches)
│   └── market_hours.py           # NSE session classification
│
├── ui/                           # Heatmap presentation layer
│   ├── sector_tiles.py           # Clickable coloured sector tiles (default)
│   ├── sector_heatmap.py         # Plotly treemap (display-only alternative)
│   ├── colours.py                # Shared diverging colour scale
│   ├── sector_detail.py          # Constituent table + colour grading
│   ├── sector_highlights.py      # Leading / lagging sector tables
│   ├── shading.py                # Green/red cell shading for gainers/losers tables (F&O and Dhan movers)
│   ├── index_board.py            # NSE sectoral index board
│   ├── fno_heatmap.py            # Stock x day Plotly heatmap for the F&O consistency page
│   ├── insight_charts.py         # Plotly figures for the Insights pages
│   ├── navbar.py                 # Always-expanded top navbar: every page a direct link
│   └── tradingview.py            # TradingView widget HTML for st.iframe (+ in-browser theme detection)
│
├── tests/                        # Unit tests for the non-UI logic (721 tests). Git-ignored for now, see below
│   ├── test_sector_heatmap.py     # % change, aggregation, ranking, staleness, universe
│   ├── test_providers.py          # Provider interface, registry, Dhan packet decoding
│   ├── test_indmoney.py           # INDmoney frames, REST mapping, index-name table
│   ├── test_kite.py               # Kite login/session expiry, packets, REST mapping, read-only guard
│   ├── test_fno_movers.py         # F&O universe, stored closes, confirmed moves, gap-safe daily moves
│   ├── test_state_store.py        # Sessions/offset documents, the lease lock, and the suite's safety net
│   ├── test_reference_store.py    # Reference sets must come back exactly as stored
│   ├── test_confirm_fno_move.py   # The command that confirms a suspected split as a real move
│   ├── test_dhan_movers.py        # Dhan marketmovers request, parsing, provider call, dashboard
│   ├── test_dhan_movers_history.py  # Movers history: session dating, once-per-session close, stored rows
│   ├── test_dhan_movers_store.py  # Movers tables in the shared store: schema, atomic write, reads, read-only handle
│   ├── test_fno_consistency.py    # Consistency score, ranking, gaps, heatmap figure, page AppTest
│   ├── test_fno_insights.py       # Breadth, overnight/intraday, rotation, gap fills/streaks, navbar, page AppTests
│   ├── test_ui_colours.py         # Colour ramp, tile keys/labels/CSS, styled table
│   ├── test_weighting_and_breadth.py  # Weighting, breadth, leader/laggard tables
│   ├── test_index_board.py        # Index mapping, universe, tooltips, index table
│   ├── test_tradingview.py        # Market pulse symbols, widget HTML, feed choice, grid heights
│   └── test_tradingview_app.py    # Headless AppTest: both Market pulse views run
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
│   ├── test_api.py               # CLI connectivity/diagnostic check for groww_api/groww_client.py
│   ├── check_heatmap_universe.py # Verifies tokens, previous closes & the live feed
│   ├── fetch_instrument_master.py # Generates data/market.db (dhan_instruments) (run monthly)
│   ├── fetch_indmoney_instruments.py # Generates data/market.db (indmoney_instruments)
│   ├── fetch_kite_instruments.py # Generates data/market.db (kite_instruments) (public, no login)
│   ├── fetch_mcx_futures.py      # Generates data/market.db (mcx_futures): MCX contracts with Dhan + Kite ids (monthly)
│   ├── kite_login.py             # Daily Zerodha login -> market.db (kite_session)
│   ├── fetch_index_weights.py    # Regenerates data/market.db (index_weights) (run manually)
│   ├── update_fno_history.py     # Extends the F&O universe and daily closes in data/market.db (daily/weekly, needs Kite login)
│   ├── confirm_fno_move.py       # Lists suspected splits, confirms one as a real move (or takes it back)
│   ├── store_dhan_movers.py      # Stores the close of Dhan's gainers/losers in data/market.db
│   ├── backfill_intraday.py      # 1-minute + daily bars for F&O stocks -> data/market.db (needs Kite login)
│   ├── compare_indmoney_kite.py  # Measured INDmoney vs Kite daily-data comparison
│   ├── compare_intraday_providers.py # Measured 1-minute history comparison, all four brokers
│   └── tradingview_symbol_probe.py # Opens a page of widgets to check which symbols stream (stdlib only)
│
├── docs/                         # Reference docs, API notes, and dated project history
│   ├── PROVIDER_GUIDE.md          # Which broker API (Kite/Dhan/INDmoney/Groww) for which job — read first
│   ├── PROVIDER_COMPARISON_LOG.md # Dated, measured broker comparisons (the evidence behind the guide)
│   ├── INTRADAY_HISTORY.md        # SQLite store of 1-minute bars + daily gaps (data/market.db)
│   ├── SECTOR_HEATMAP.md          # Sector heatmap design notes
│   ├── FNO_MOVERS.md              # F&O movers: provider comparison, storage choice
│   ├── DHAN_MOVERS.md             # Dhan Movers page: what marketmovers returns, quirks, limits
│   ├── MCX_FUTURES.md             # MCX Futures page: provider choice, Dhan/Kite fallback, contract list, quirks
│   ├── FNO_HEATMAP.md             # F&O consistency heatmap: the score, the three heatmaps, controls
│   ├── FNO_INSIGHTS.md            # Breadth, overnight vs intraday, relative rotation, gap fills, gap streaks
│   ├── TRADINGVIEW_WIDGETS.md     # TradingView widget reference: formats, options, symbol availability, Streamlit notes
│   ├── ROADMAP.md                 # What is done and what is planned next
│   ├── QUICK_START.md
│   ├── api/                      # Groww, INDmoney and Kite API notes (INDMONEY_API.md: Dhan comparison)
│   └── _archived/                # Superseded docs (old architecture, status, Groww API index, changelog); git-ignored, local only
│
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

**For the sector heatmap (Dhan — the default provider), three variables:**

```bash
DHAN_CLIENT_ID=your_10_digit_client_id
DHAN_PIN=your_6_digit_dhan_pin
DHAN_TOTP_SECRET=base32_secret_from_setup_totp
```

There's no access token in `.env`. `market/providers/dhan_session.py` mints a
24-hour token from TOTP when there's no usable one. It saves the token to the shared database (`data/market.db`, git-ignored), and every dashboard and script shares it.
It's replaced an hour before expiry, or at once if Dhan rejects it. Get the
TOTP secret from Dhan Web → DhanHQ Trading APIs → **Setup TOTP**. Market data
needs Dhan's paid **Data API** plan. Details:
[Dhan token generation](docs/PROVIDER_GUIDE.md#dhan-token-generation-tested-2026-09-27).

**For INDmoney (free market data), the same idea:**

```bash
IND_MONEY_CLIENT_ID=client_id_shown_after_totp_setup   # sent as x-api-key
IND_MONEY_MPIN=your_mpin
IND_MONEY_TOTP_SECRET=base32_setup_key
```

There's no access token in `.env` here either. `market/providers/indmoney_session.py`
mints one (valid to 07:00 IST) and shares it through the `indmoney_session` row of `data/market.db`. A new INDmoney token **revokes** the previous one, so
it's only minted when none is usable or INDmoney rejects the saved one. Set up
TOTP at indstocks.com → API Trading → Access Tokens.
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

This saves the day's token to the `kite_session` row of `data/market.db`, which is git-ignored. The
dashboard picks it up the next time a board connects to Kite, with no restart
needed. Kite comes last in *Auto*, so until you log in it is just skipped. The
Kite code is read-only: it calls no order endpoint. Details are in
[`docs/api/KITE_API.md`](docs/api/KITE_API.md).

> **Groww is currently inactive (checked 2026-09-30).** The Groww API
> subscription has ended, so every Groww login fails with `Authorisation failed.
> Your API token does not have the required permissions`. This is an account
> state, not a code fault, so there is no point retrying. The `GROWW_*` values
> are removed from `.env`. Until the subscription is renewed, `apps/app.py`,
> `apps/fno_dashboard.py` and the heatmap's Groww provider will not authenticate; the
> heatmap skips Groww (it is unconfigured) and uses the other brokers. To bring
> it back, renew the subscription, regenerate the key on Groww's Cloud API Keys
> page, and put the values below back in `.env`.

**For the Groww dashboards (and the heatmap's Groww fallback)**, once the subscription is active, fill in one of:

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
streamlit run apps/fno_dashboard.py               # FnO tracker + Quick Exit
streamlit run apps/app.py                         # Portfolio / MTF Decoupler
streamlit run pulse_dashboard.py             # Everything, one always-expanded top navbar
streamlit run apps/fno_movers_dashboard.py --server.port 8503   # F&O movers pages on their own
streamlit run apps/fno_heatmap_dashboard.py --server.port 8510  # F&O consistency heatmap on its own (stored closes only, no login)
streamlit run apps/fno_breadth_dashboard.py --server.port 8506  # Insights pages on their own (8506-8509, 8511; no login)
streamlit run apps/tradingview_dashboard.py --server.port 8504  # Market pulse (TradingView widgets, no .env needed)
streamlit run apps/dhan_movers_dashboard.py --server.port 8505  # Dhan market movers on their own (needs Dhan credentials)
streamlit run apps/mcx_futures_dashboard.py --server.port 8512  # MCX commodity futures on their own (Dhan, or Kite as fallback)
```

The first one opens at `http://localhost:8501`; start others with `--server.port` (for example
`streamlit run pulse_dashboard.py --server.port 8502`) to run them alongside it.

### 4. Maintenance scripts (not run by the dashboard)

Data the dashboard *reads* but never *fetches*, so that no third-party
source can fail or stall while the market is open. Each script stores its result
in the shared database (see "What lives in `data/market.db`" below) and is run by hand:

```bash
python scripts/fetch_instrument_master.py    # -> data/market.db (dhan_instruments)
python scripts/fetch_indmoney_instruments.py # -> data/market.db (indmoney_instruments) (needs the token)
python scripts/fetch_kite_instruments.py     # -> data/market.db (kite_instruments) (public, no login)
python scripts/fetch_mcx_futures.py          # -> data/market.db (mcx_futures) (public, no login)
python scripts/fetch_index_weights.py        # -> data/market.db (index_weights)
python scripts/update_fno_history.py         # -> data/market.db: fno_universe + daily_bars (needs kite_login.py)
python scripts/confirm_fno_move.py suspected # which falls the F&O pages flag as possible splits (add / remove / list too)
python scripts/backfill_intraday.py          # -> data/market.db, 60 days of 1-minute bars (needs kite_login.py)
python scripts/store_dhan_movers.py          # -> data/market.db tables dhan_movers + dhan_movers_breadth (needs Dhan credentials)
```

| Script | What it writes | Re-run it |
|---|---|---|
| `fetch_instrument_master.py` | Broker security ids for every tracked symbol (12 KB). Dhan publishes these only as a 35 MB uncompressed CSV of every F&O contract; this pulls out the sixty rows that matter | After an NSE index reconstitution (end of March / end of September), after editing `market/sector_mapping.py`, or when the dashboard reports unresolved symbols. Monthly otherwise |
| `fetch_indmoney_instruments.py` | INDmoney's ids for the same symbols (11 KB). Equity ids equal Dhan's; index ids and names are INDmoney's own | Same triggers as Dhan's ids |
| `fetch_kite_instruments.py` | Kite's `instrument_token` (websocket/candles) **and** `tradingsymbol` (REST quotes) for the same symbols (12 KB), from Kite's public 0.7 MB NSE dump | Same triggers as Dhan's ids |
| `fetch_mcx_futures.py` | Every MCX commodity future (164 contracts, 28 commodities on 2026-10-03) with Dhan's security id and Kite's `instrument_token` + `tradingsymbol`, matched on commodity and expiry. From Dhan's 35 MB master and Kite's public 1.3 MB MCX list | Monthly, as new expiries are listed. The MCX page warns when the stored list runs out within 45 days |
| `fetch_index_weights.py` | Free-float market caps for cap-weighted sector aggregation | Weekly or monthly; share counts move slowly |
| `backfill_intraday.py` | 1-minute bars and daily open/close for the 210 F&O stocks into SQLite (`data/market.db`), plus a `daily_gaps` view. One 60-day minute call + one daily call per stock (~420 requests, ~5 min). See [`docs/INTRADAY_HISTORY.md`](docs/INTRADAY_HISTORY.md) | Whenever you want fresher bars; one run fills every missing day |
| `confirm_fno_move.py` | Nothing from Kite. `suspected` lists the falls the F&O pages flag as a possible split or bonus; `add SYMBOL YYYY-MM-DD "why"` records one as a real move so it stops being flagged; `remove` takes that back; `list` shows what is confirmed | When you have checked a flagged fall |
| `store_dhan_movers.py` | The close of Dhan's gainers and losers (price and % change only; up to 100 per side) for 21 universes, into the `dhan_movers` and `dhan_movers_breadth` tables of the shared `data/market.db` (git-ignored), in one transaction. Rows are filed under the session the prices belong to (read from Dhan's last trade time), so a weekend or holiday run files the last trading day. Once per session date; no intraday unless `--intraday`. About 50 s. The Dhan Movers page's History screen reads it. **Dhan only ever returns the current session, so this history cannot be rebuilt: back `market.db` up** | Any time after 16:00 on a trading day, or the next day |
| `update_fno_history.py` | The F&O stock list, plus each stock's daily OHLCV in the `daily_bars` table (the one the backfill fills too). One Kite request per stock however many days are missing (~210 requests, 75-110 s). `--fix-splits` re-fetches the stocks whose history shows a split-like fall | Daily after 16:00 IST, or weekly: one run fills every missing day. The movers dashboard warns when the history is more than 4 days old |

If stored data is stale or missing the dashboard says so rather than guessing: unresolved
symbols appear in the "Data gaps" panel with the script named in the logs, and
missing weights fall back to equal weighting with a visible note.

### 5. (Optional) Verify connectivity from the CLI

```bash
python scripts/test_api.py                   # Groww connectivity (groww_api/groww_client.py)
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
python -m unittest discover -s tests -t .    # 721 tests, no extra dependencies
```

---

## Tests are not committed yet

`tests/` is in `.gitignore`: the suite stays on this machine for now and will be committed later. Run it with `.venv\Scripts\python.exe -m unittest discover -s tests`. `tests/__init__.py` and `tests/support.py` were committed earlier and stay tracked (ignore rules do not untrack files); every other test file is untracked.

## What lives in `data/market.db`

One SQLite file, `data/market.db` (git-ignored), holds the project's local data. Its code is
[`market/intraday_store.py`](market/intraday_store.py) (the connection and the F&O tables) and one small
module per feature that adds its own tables to the same file. `.env` (credentials) is the only other file.

| Tables | What | Written by | Can be rebuilt? |
|---|---|---|---|
| `daily_bars`, `minute_bars` | F&O daily bars (the closes behind every F&O page) and 1-minute bars, plus the `daily_gaps` view | `scripts/update_fno_history.py` (daily), `scripts/backfill_intraday.py` (both) | Yes, from Kite |
| `dhan_movers`, `dhan_movers_breadth` | Dhan's gainers/losers, one close per session | `scripts/store_dhan_movers.py` | **No**: Dhan only returns the current session |
| `runtime_state`, `state_locks` | The saved Dhan, INDmoney and Kite sessions (**live tokens**), the clock offset, and the lock that stops two processes minting one token | The providers, `scripts/kite_login.py` | Yes: log in again |
| `reference_sets`, `reference_rows` | Generated reference data: each broker's instrument ids (`dhan_instruments`, `indmoney_instruments`, `kite_instruments`), the MCX contracts (`mcx_futures`), `index_weights`, `fno_universe`, and `fno_confirmed_moves` (falls confirmed as real moves) | The `scripts/fetch_*.py` scripts, `update_fno_history.py`, and `confirm_fno_move.py` | Yes: run the script. The confirmed moves are a person's decisions, so they are re-added with `confirm_fno_move.py` |

- **Back it up.** The Dhan history cannot be re-fetched, and the confirmed moves are your own notes. The file also
  holds live tokens, which all expire within a day (Kite at 06:00 IST, Dhan after 24 hours, INDmoney at 07:00), so an
  old backup holds nothing usable, but do not share it.
- **A fresh checkout starts empty**, and the dashboards say which script to run: `fetch_instrument_master.py`,
  `fetch_indmoney_instruments.py`, `fetch_kite_instruments.py`, `fetch_mcx_futures.py`, `fetch_index_weights.py`,
  `update_fno_history.py`, and `kite_login.py` (the Dhan and INDmoney sessions mint themselves).
- **`PULSE_STATE_DB`** points the sessions, offset, reference data and daily closes at another database file. The
  test suite sets it to a throwaway file, so tests never touch the real one.
- Two processes can use it at once (the file runs in WAL mode). A token is minted by one process under a
  short lease row, so a dashboard and a script starting together make one token, not two.

## Dhan market movers: universes

Reference for the Dhan Movers page and `scripts/store_dhan_movers.py`. Full detail is in
[`docs/DHAN_MOVERS.md`](docs/DHAN_MOVERS.md).

**Scope: NSE only. BSE universes are out of scope.** Nothing here is meant to use the BSE segment
or any BSE universe (`SENSEX` and the `BSE_*` ones). Do not add them unless that changes.

Dhan's `/v2/data/marketmovers` takes a `universe`, the list of stocks to rank. Its schema lists 58;
each was tried on 2026-10-02 (a Dhan token and the Data API plan are needed):

| Result | Count | Which |
|---|---|---|
| **Used** (NSE, in `market/dhan_movers.py` `UNIVERSES`) | 21 | `FNO_STOCKS`, `NIFTY_50`, `NIFTY_NEXT_50`, `NIFTY_100`, `NIFTY_200`, `NIFTY_500`, `NIFTY_MIDCAP_100`, `NIFTY_SMALLCAP_100`, `NIFTY_BANK`, `NIFTY_PRIVATE_BANK`, `NIFTY_PSU_BANK`, `NIFTY_IT`, `NIFTY_AUTO`, `NIFTY_PHARMA`, `NIFTY_FMCG`, `NIFTY_METAL`, `NIFTY_ENERGY`, `NIFTY_REALTY`, `NIFTY_INFRA`, `NIFTY_MEDIA`, `ALL` (all NSE stocks) |
| NSE, works, **not used yet** | 10 | `FINNIFTY`, `NIFTY_MIDCAP`, `NIFTY_SMALLCAP_50`, `NIFTY_MID_CAP_50`, `NIFTY_MIDCAP_150`, `NIFTY_SMALLCAP_250`, `NIFTY_MICROCAP_250`, `NIFTY_MNC`, `NIFTY_SERVICE_SECTOR`, `NIFTY_CUNSUMPTION` (Dhan's own spelling) |
| BSE, **out of scope** | 25 | `SENSEX` and the 24 `BSE_*` universes. They answer only on the `BSE_EQ` segment (the NSE segment returns `DH-907`) |
| Return nothing | 2 | `INDIA_VIX`, `GIFT_NIFTY` |

To use one of the 10 spare NSE universes, add it to `UNIVERSES` in `market/dhan_movers.py`
(label to Dhan key); the page's dropdown and the history script's default pick it up.

Things to know before building on this:

- **At most 100 rows per ranking, and no paging.** `limit=101` is rejected, and `offset`/`page` are
  ignored. A universe with more than 100 gainers or losers (Nifty 500, `ALL`, the larger F&O side)
  shows only its best 100 and worst 100.
- **A gainers list holds only stocks that are up**, so for a universe of 100 stocks or fewer the gainers
  plus the losers are every stock that moved, and the counts are exact breadth (Nifty 50 always
  sums to 50).
- **`DH-907` means an empty ranking** (Nifty Auto and Media had no gainers on a day they were all
  down), not an error.
- **A universe is a list of stocks.** There is no index open/high/low/close in this endpoint; those
  come from Dhan's quote endpoint (`IDX_I`), which the NSE Sectoral Indices page already uses.
- **Responses carry no date.** Outside market hours and on holidays they show the last session,
  so the session date is read from the quote endpoint's `last_trade_time`.

## Architecture Notes

- **Two separate API client layers exist on purpose:** `groww_api/groww_client.py` (`GrowwClient`) backs `apps/app.py`, while the `groww_api/` package (`GrowwAPIClient` + `GrowwAPIService` + `PositionProcessor`) backs `apps/fno_dashboard.py`. The `groww_api/` package uses a singleton auth pattern so the app authenticates once per session instead of on every cache refresh.
- **Shared formatting/sentiment logic** lives in `utils/` and is imported by both `apps/fno_dashboard.py` and `groww_api/groww_client.py` (for `format_inr`/`format_inr_full`) to avoid duplicated implementations.
- **Quick Exit** (in `apps/fno_dashboard.py`) places a LIMIT SELL order at LTP − 0.5% for profitable positions, sorted highest P&L% first, and reads back the order status via `GrowwAPIService.get_order_status`.
- **The sector heatmap is broker-agnostic.** `market/providers/` defines a `MarketDataProvider` + `FeedHandle` interface, implemented by **Dhan** (DhanHQ v2, preferred), **INDmoney** (INDstocks API, free, first fallback), **Groww** (an adapter over the existing stack) and **Kite** (Zerodha Kite Connect, last in *Auto*). `PULSE_MARKET_PROVIDERS` sets the preference order for *Auto*; the service adopts the first broker that authenticates and fails over if its websocket cannot deliver. The sidebar's **Data provider** switch can instead pin one broker with no failover, for comparing them. Kite is called without the `kiteconnect` SDK: the SDK's ticker runs on Twisted, whose reactor cannot restart within a process, and this service reconnects feeds as a matter of course.
- **Two boards share one engine.** The Nifty 50 board aggregates constituents into sectors; the NSE Sectoral Indices board shows real index values (Dhan's `IDX_I` segment, or INDmoney's `NIDX`), where each tile is one index and nothing is averaged. Each board runs its own feed (Dhan allows 5 connections per client id, INDmoney 3 per user) and a board you have not opened is never started. The index drill-down shows the Nifty 50 members of the matching sector, labelled explicitly as *not* the index's real constituent list — neither broker publishes that.
- **Sector percentages are equal-weighted by default, market-cap weighted on request.** Equal weighting answers "how did the average stock in this sector do"; cap weighting answers "how did its big names do". Neither broker exposes market cap, so free-float weights are generated offline by `scripts/fetch_index_weights.py` into the `index_weights` set in `data/market.db` and only *read* at runtime — the dashboard never fetches fundamentals while the market is open. If weights are missing it falls back to equal weighting and says so rather than presenting an unweighted number as weighted.
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

- **Groww: "Your API token does not have the required permissions"** — the Groww API subscription has ended (2026-09-30). Renew it and regenerate the key; retrying or changing the code will not help. See the note in Setup.
- **"Client not authenticated"** — verify `.env` credentials and `GROWW_AUTH_MODE`. Direct access tokens are short-lived; regenerate one when it expires.
- **Restarting after a credential change** — `GrowwAPIClient`/`GrowwClient` authenticate once per running process. The sidebar's "Refresh Data" button only clears the Streamlit data cache; after changing `.env` credentials, fully restart the Streamlit process to re-authenticate.
- **Dashboard won't start** — confirm the venv is activated and Streamlit is installed (`python -m streamlit run apps/fno_dashboard.py`).

- **INDmoney: "authentication failed ... TokenException"** — the 24h token has expired or was revoked. Generate a new one at indstocks.com → API Trading → Access Tokens and restart the dashboard.
- **INDmoney index board shows 16/17, with Nifty Oil & Gas missing** — expected. INDmoney lists that index but serves no data for it; see [`docs/api/INDMONEY_API.md`](docs/api/INDMONEY_API.md).
- **Kite shows "no credentials" in the provider list** — the API key is set but nobody has logged in today, or the session passed 06:00 IST. Run `python scripts/kite_login.py`.
- **Kite: "authentication failed (HTTP 403 ... TokenException)"** — the token was revoked, for example by logging out of all Kite sessions. Log in again with `scripts/kite_login.py`.
- **Kite: "market data unavailable (HTTP 403 ... PermissionException)"** — the app is on the free *Personal* plan, which has no quotes, historical data or websocket. The paid *Kite Connect* plan is needed.
- **Kite login: "Token is invalid or has expired"** — the `request_token` in the redirect URL is single-use and lasts a few minutes. Log in again and paste the new URL promptly.
- **INDmoney websocket won't connect while both boards are open** — INDmoney allows 3 sockets per user. Two boards plus a `check_heatmap_universe.py` run already use all three.

- **Market pulse shows "Permission denied – This symbol is only available on TradingView"** — that exchange is not licensed for TradingView widgets (NSE, MCX, NSEIX/GIFT Nifty, NYMEX and ICE all are not). No setting fixes it. Use a proxy symbol, or list it as a link in `market/tradingview_symbols.py`. Check a symbol with `python scripts/tradingview_symbol_probe.py EXCHANGE:TICKER`.
- **Market pulse: Indian charts ignore a 1-day range** — deliberate. BSE data in widgets is end of day, which rejects intraday ranges, so those charts use 3 months as a minimum.
- **Market pulse widgets are blank** — the widgets load from `widgets.tradingview-widget.com` and `s3.tradingview.com` in *your browser*, so an ad blocker or a corporate proxy blocking those hosts blanks them. The Streamlit server needs no internet access at all.

- **Clicking a heatmap tile does nothing** — you are on the Treemap view. Streamlit cannot receive Plotly treemap clicks (it listens for `plotly_click`; treemaps emit `plotly_treemapclick`). Switch the sidebar to **Tiles (clickable)**, which is the default.
- **Sector heatmap shows "LIVE (Dhan REST polling)"** — the websocket is not delivering, so prices are batched REST snapshots (labelled as such, never shown as socket-live). Most common cause: the Dhan access token was minted **before** the Data API plan was activated — regenerate it after subscribing. Diagnose with `python scripts/check_heatmap_universe.py --provider dhan`, which reports `dataPlan` explicitly.
- **Terminal says "Dhan websocket delivered nothing for 10.0s - reconnecting"** — the socket went quiet or dropped, and the service is getting it back. A dropped Dhan socket reconnects in ~2 s and the board stays on Dhan; REST covers the gap, which is why nothing changes on screen. Only if two reconnects in a row fail does the board move to the next broker. See "Recovery before failover" in [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md).

- **Sector heatmap shows "LIVE (Groww REST polling)" for the first few seconds** — normal. Groww's socket handshake is slow (1 s in the best case, tens of seconds routinely), so the board polls REST until it lands and then switches to `LIVE (websocket)` by itself, typically within 10–20 s. The banner says whether it is still negotiating or has actually failed.

- **Groww logs a run of empty `ERROR ... nats_client: Error:` lines, then works** — also normal, and the single most misleading thing this feed does. Each line is a `TimeoutError` from Groww's gateway with an empty message; `nats-py` retries every ~4 s until one lands. It is not a fault and needs no action. Groww's websocket behaves quite differently from Dhan's in several other ways too — buffered rather than pushed, no drop notification, no `close()` — all measured and explained in [`docs/api/GROWW_API_FEED.md`](docs/api/GROWW_API_FEED.md#websocket-behaviour-in-practice-observed). **Read that before assuming the two brokers' sockets behave alike.**

- **Groww REST starts failing with `Extra data: line 1 column 5` or `Authentication failed: The requested resource was not found`** — Groww throttles its REST and auth endpoints, and restarting the dashboard repeatedly while debugging will trip it. Neither is a socket problem; wait a few minutes.

See [`docs/`](docs/) for deeper API reference and historical design notes, [`docs/SECTOR_HEATMAP.md`](docs/SECTOR_HEATMAP.md) for the sector heatmap, and [`docs/ROADMAP.md`](docs/ROADMAP.md) for what is planned next.
