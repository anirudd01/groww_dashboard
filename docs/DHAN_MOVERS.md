# Dhan market movers

A navbar page ("Dhan Movers") built on Dhan's own server-side ranking endpoint,
`POST https://api.dhan.co/v2/data/marketmovers`. Dhan ranks the instruments, so each
screen is one or two calls and no history is stored. It is separate from the
[F&O movers pages](FNO_MOVERS.md), which are Kite-based and cover multi-day moves.

Visualisation only: it places no orders and generates no signals. The futures
"build-up" labels describe what open interest and price did today; they predict nothing.

```bash
streamlit run pulse_dashboard.py                              # the "Dhan Movers" page
streamlit run apps/dhan_movers_dashboard.py --server.port 8505   # on its own
```

It needs Dhan credentials (`DHAN_CLIENT_ID`, `DHAN_PIN`, `DHAN_TOTP_SECRET`) and the Dhan
Data API plan, like the other Dhan features. Without them the page says so instead of failing.

## Screens

Pick one with the control under the title. Every selector is bound to the URL, so a view is a
link: `?dhan_view=Futures&dhan_futures_show=Most+traded`.

| Screen | What it shows | Calls |
|---|---|---|
| **Stocks** | Top gainers and losers of a universe (F&O stocks, Nifty 50/100/200/500, midcap/smallcap, 12 NSE sector indices, all NSE), with advancing/declining counts, and a scatter of each move against the money traded behind it | 2 (gainers, losers; 100 each) |
| **Futures, build-up** | Stock or index futures sorted into four quadrants from today's price change and open-interest change: long build-up, short build-up, short covering, long unwinding. Scatter plus a table of the largest OI changes, filterable by quadrant | 2 (OI gainers, OI losers) |
| **Futures, most traded** | The highest-volume contracts with their basis (futures price over the underlying), and a basis bar chart | 1 |
| **Options** | Open interest by strike with calls beside puts, call/put OI totals and a ratio, and a contract table. Rankings: highest OI, most traded, OI gainers, OI losers; index or stock options; one underlying at a time | 1 |

The badge under the title says **Live**, or **Last session: Thu 01 Oct 2026**: it is dated from Dhan's last
trade time, so a holiday shows the last trading day even though the clock says the market is open (and
auto-refresh is off then).

The side controls choose rows per table (5 to 50), auto-refresh (every 30 s while the market is
open; off after the close), and "Refresh now", which also reconnects to Dhan.

## What the endpoint does (checked live 2026-10-02, after the close)

The request is `{exchangeSegment, instrument[], category, limit, universe | expiry}`; the schema
is in [`api/dhan-openapi-2026-10-01.json`](api/dhan-openapi-2026-10-01.json).

- **Stocks**: `NSE_EQ` / `EQUITY`, category `PRICE_GAINERS` or `PRICE_LOSERS`, and a `universe`.
- **Derivatives**: `NSE_FNO` with `FUTSTK`, `FUTIDX`, `OPTSTK` or `OPTIDX`; categories
  `TOP_VOLUME`, `OI_GAINERS`, `OI_LOSERS`, and `HIGHEST_OI` (options only).
- **`limit` is 1 to 100, and that is a hard cap.** `limit=101` is rejected (HTTP 400), and an
  `offset` or `page` field is silently ignored: asking for page 2 returns the same 100 rows. The
  request schema has no paging field. So a universe with more than 100 gainers or losers (Nifty 500,
  all NSE) shows only its best 100 and worst 100; the middle is not reachable.
- **A gainers list holds only stocks that are up.** Nifty 50 gave 13 gainers and 37 losers;
  Nifty Metal gave 1 gainer. So a count under 100 is the exact number advancing or declining.
  A full list is shown as "100+" because the true figure is unknown.
- **`DH-907` ("incorrect parameters or no data present") means an empty ranking.** Nifty Auto and
  Nifty Media returned it for gainers on a day nothing in them was up, while their losers
  returned rows. Index-futures `OI_LOSERS` did the same. The code reads it as empty.
- **`expiry` is required for derivatives and is snapped to the monthly contract.** 06-Oct, 13-Oct
  and 29-Oct all returned 27-Oct contracts, so weekly contracts cannot be ranked. The code sends
  the last Tuesday of the month and shows the expiry that comes back.
- **Outside market hours it returns the last session, and says nothing about which.** The response
  has no date. On Friday 2 Oct 2026, a market holiday, every call answered with Thursday 1 Oct's
  moves (the page and the first version of the history script both took that for "today"). The only
  date in Dhan's data is `last_trade_time` in the quote endpoint (`01/10/2026 15:59:03`, IST), which
  is what `session_date()` reads. Index quotes carry it too.
- Latency was 0.3 to 0.7 s per call. The calls go through the shared Dhan quote throttle
  (1 per 1.1 s per client id), because Dhan does not say which rate-limit bucket this endpoint is in.

### Universes

The request schema lists **58** `universe` values. Tried each one on 2026-10-02:

| Result | Count | Which |
|---|---|---|
| Works with `NSE_EQ` | 31 | `ALL`, `FNO_STOCKS`, `NIFTY_50`, `NIFTY_NEXT_50`, `NIFTY_100`, `NIFTY_200`, `NIFTY_500`, `NIFTY_BANK`, `FINNIFTY`, `NIFTY_MIDCAP`, `NIFTY_MID_CAP_50`, `NIFTY_MIDCAP_100`, `NIFTY_MIDCAP_150`, `NIFTY_SMALLCAP_50`, `NIFTY_SMALLCAP_100`, `NIFTY_SMALLCAP_250`, `NIFTY_MICROCAP_250`, and the sectors `AUTO`, `PRIVATE_BANK`, `PSU_BANK`, `FMCG`, `ENERGY`, `INFRA`, `IT`, `MEDIA`, `METAL`, `MNC`, `PHARMA`, `REALTY`, `SERVICE_SECTOR`, `CUNSUMPTION` (Dhan's spelling) |
| Works only with `BSE_EQ` | 25 | `SENSEX` and the 24 `BSE_*` universes (BSE 100/200/500, mid/small caps, Bankex, and sectors). The `NSE_EQ` segment answers `DH-907` for them |
| Returns nothing | 2 | `INDIA_VIX` and `GIFT_NIFTY`: empty on both segments |

**Scope: NSE only. BSE universes are out of scope** (decided 2026-10-02): the 25 BSE ones below are
not used and not planned.

The page and the history use 21 of the 31 NSE ones (`dhan_movers.UNIVERSES`); the other 10 work and
are simply not listed (`FINNIFTY`, `NIFTY_MIDCAP`, `NIFTY_SMALLCAP_50`, `NIFTY_MID_CAP_50`,
`NIFTY_MIDCAP_150`, `NIFTY_SMALLCAP_250`, `NIFTY_MICROCAP_250`, `NIFTY_MNC`,
`NIFTY_SERVICE_SECTOR`, `NIFTY_CUNSUMPTION`). The 25 BSE ones would need the code to send
`exchangeSegment: BSE_EQ` for them, which it deliberately does not.

A universe is a list of **stocks**. There is no index level (the Nifty Bank value, its open or
close) in this endpoint. Those come from the quote endpoint, see below.

### Fields

Per row: `tradingSymbol`, `displayName`, `securityId`, `instrument`, `lotSize`, `ltp`, `change`,
`changePercent`, `volume`, `tradedValue` (rupees), and for derivatives `expiry`, `strikePrice`,
`openInterest`, `openInterestChange`, `openInterestChangePercent`, `underlyingLtp`, and
`premiumDiscountPercent` (futures) or `putCallRatio` (options).

Things to know when reading them:

- Fields that do not apply are not always null: stocks carry `0` for open interest, futures carry
  a strike of `-0.01`, and options carry a meaningless `premiumDiscountPercent` (about -99%).
  `parse_movers` blanks these.
- Open interest looks like **units, not lots** (HDFCBANK Oct future: 366 million with a lot size
  of 650). That is inferred from magnitude, not documented.
- `putCallRatio` varies by strike (0.64 at 23500, 3.67 at 22000), so it is a per-contract figure.
  Dhan does not say how it is computed; the page labels it as Dhan's.

## History: `scripts/store_dhan_movers.py`

The endpoint only answers "today against the previous close", so a history exists only if it is
saved as it happens. The script stores **the close of each session** in two tables of the shared
SQLite database `data/market.db` (the file the F&O 1-minute history lives in), and leaves out volume
and open interest.

```bash
python scripts/store_dhan_movers.py --dry-run     # fetch and print, write nothing, any time of day
python scripts/store_dhan_movers.py               # store the latest finished session's close (about 50 s)
python scripts/store_dhan_movers.py --top 20 --universes "Nifty 50,Nifty Bank"
python scripts/store_dhan_movers.py --intraday --every 15   # optional snapshots while open; off by default
```

| Table | One row per | Columns |
|---|---|---|
| `dhan_movers` | ranked stock | `trading_date, kind, captured_at, universe, side, rank, symbol, name, ltp, change_pct` |
| `dhan_movers_breadth` | universe, per capture | `trading_date, kind, captured_at, universe, advancing, declining, advancing_capped, declining_capped` |

- **`trading_date` is the session the prices belong to, not the day the script ran.** It is read from
  the feed (see above), so running on a Saturday files Friday, and running on a holiday files the day
  before. `captured_at` is when it actually ran. The first version filed Thursday's close under
  Friday 2 Oct, a holiday; that was wrong and the files were regenerated.
- **Run it whenever.** One run stores the latest finished session, so after 16:00, the next
  morning, or at the weekend all work, and a missed day can be caught up as long as Dhan still
  shows that session. It is stored **once per session date**; a second run says it is already stored
  and fetches nothing.
- **Not before 16:00 on a trading day**, because the closing figures settle after 15:30. While the
  market is open it stores nothing (unless `--intraday`), and says why.
- `side` is `gainer` or `loser`; `rank` starts at 1 for the biggest move.
- **`--top` defaults to 100, which is everything Dhan returns** (see the cap above). Lower it to
  keep only the extremes. Breadth does not depend on it: it is counted from everything fetched.
- Breadth is the index-level picture: each Nifty sector index is a universe, so it says how many of
  Nifty Bank's stocks were up and down. A count under 100 is exact (Nifty 50 always sums to 50);
  `*_capped` is true where the 100-row limit cut it short (Nifty 500, all NSE, the larger F&O side).
- A close that could not fetch every universe is not stored at all, so a rerun completes it. Each
  universe is retried once on a timeout (Dhan did time out on Nifty Smallcap 100 and the all-NSE
  universe the first time this ran). A reply with no `data` field is treated as an error, never as
  "nothing is up".
- **Intraday is off.** `--intraday` (with `--every N`) adds snapshots while the market is open, kind
  `intraday`; not recommended for now, see the roadmap note.
- Size: a close at `--top 100` is about 1,300 rows and 134 KB (measured on 2026-10-01's), so a year
  of closes is about 34 MB. At `--top 20` it is about 535 rows and 55 KB.

Primary keys are `(trading_date, kind, captured_at, universe, side, rank)` and the same without `side, rank`
for breadth, so a capture cannot be stored twice, and a capture is written in **one transaction**: both
tables or neither. Dates are `YYYY-MM-DD` text and `captured_at` is IST ISO text, as in the rest of the
store.

**Back up `data/market.db`.** It is git-ignored, and everything else in it can be rebuilt (the F&O tables
from Kite, the reference data by running its script, the sessions by logging in), but these two tables
cannot: Dhan only ever returns the current session, so a lost day is gone. See the README's "What lives in
`data/market.db`". First capture: the
Thursday 1 Oct 2026 close.

Reading it yourself (the file is plain SQLite):

```bash
sqlite3 data/market.db "SELECT trading_date, universe, advancing, declining FROM dhan_movers_breadth ORDER BY trading_date DESC, universe"
sqlite3 data/market.db "SELECT symbol, change_pct FROM dhan_movers WHERE universe='NIFTY_50' AND side='gainer' AND trading_date='2026-10-01' ORDER BY rank"
```

```python
from market import dhan_movers_store as store
conn = store.connect_readonly()          # None if there is no database yet; never writes
store.session_dates(conn)                # ['2026-10-01', ...] newest first
store.movers_on(conn, "2026-10-01", "NIFTY_BANK")      # {'gainer': [...], 'loser': [...]}
store.breadth_history(conn, "NIFTY_50")                # advancing/declining per session
store.repeat_movers(conn, "NIFTY_50", "gainer", top=10)  # who keeps topping the list
```

### The History screen

The fourth screen of the Dhan Movers page reads these tables, read-only, and **never calls Dhan**. Pick
a stored session and universe, and it shows that day's gainers and losers with the advancing and
declining counts, a breadth-over-time chart (from two stored sessions), and the stocks that most
often appeared among the top 10 gainers or losers over every stored session. Reads are cached against
the database file's modification time, so a new capture shows on the next reload. With no database, or
one holding only the F&O tables, it says how to fill it.

### Sector and index heat-map data

The rankings give each *stock's* move, so the sector story can be rebuilt from them: for a universe
of at most 100 stocks, the gainers plus the losers are every stock that moved, so the breadth and
the average move are exact (an equal-weighted average, not the index's own cap-weighted return). That
is end-of-day history, not a replacement for the live heat map, which values the stocks from the
websocket and weights them.

An index's own open, high, low and close are not in this endpoint. Dhan's **quote** endpoint
(`POST /v2/marketfeed/quote`, segment `IDX_I`, the one the NSE Sectoral Indices page already uses)
returns them for each index: `ohlc{open,high,low,close}`, `last_price`, `net_change`,
`last_trade_time`. After the close its `close` equals the last price and `net_change` is 0, so the
previous close has to come from elsewhere (the daily candles).

### REST or websocket?

REST. `marketmovers` is one HTTPS `POST` and one JSON response: a snapshot, nothing streams, and it
is polled. Dhan's websocket (`wss://api-feed.dhan.co`) is a separate live-tick feed, and that is
what the live heat map reads.

## What this does not do

- **No multi-day moves from the page.** Every change is today against the previous close. The F&O
  pages cover 3 to 100 trading days from Kite's stored closes; the history above is what lets this
  data build up its own.
- **Not a full option chain.** An options ranking holds at most 100 contracts, so a strike missing
  from the OI chart is outside the ranking, not zero. The page says so, and its call/put totals
  and ratio cover only the contracts shown.
- **Not in Dhan's published docs.** The endpoint is in its Swagger spec only, so it may change.
  See [`API_ENDPOINT_AUDIT.md`](API_ENDPOINT_AUDIT.md).

## Code

| File | Role |
|---|---|
| `apps/dhan_movers_dashboard.py` | The page: `page_dhan_movers()` for the navbar, and a standalone entry point |
| `market/dhan_movers.py` | Request building, parsing into `Mover`, the monthly-expiry helper, the build-up classifier, `session_date()`. No Streamlit |
| `market/providers/dhan.py` | `DhanProvider.market_movers(body)`: the throttled POST, one retry on a rate limit (`805`, `DH-904`), and `DhanDataError` carrying Dhan's error code; `get_last_trade_times()` for dating the session |
| `market/dhan_movers_history.py` | The history: which session a capture belongs to, fetching with a retry, the rows, and the once-per-session guard |
| `market/dhan_movers_store.py` | The two tables in the shared store: schema, the one-transaction write, and the reads the History screen uses |
| `market/intraday_store.py` | The shared SQLite store (path, WAL, connection). `connect(extra_schema=...)` and `connect_readonly()` were added so other features share it |
| `scripts/store_dhan_movers.py` | Command line for the history (single capture, or a loop) |
| `ui/shading.py` | Green/red cell shading, shared with the F&O movers page |
| `tests/test_dhan_movers.py`, `tests/test_dhan_movers_history.py`, `tests/test_dhan_movers_store.py` | Request, parsing, provider call, dashboard and history tests; nothing reaches Dhan |

The provider is cached for an hour (`st.cache_resource`), rankings for 20 s (`st.cache_data`). A
failed connection is not cached, so fixing `.env` and pressing "Refresh now" is enough.
