# F&O movers dashboard

Top gainers and losers, day by day. There are two views: the Nifty 50 (all
50 trade in F&O) and every NSE F&O stock (210 as of 2026-09-25).
Visualisation only; it places no orders.

```bash
python scripts/kite_login.py                 # once per trading day
python scripts/kite.py history         # backfill, then daily after 16:00 IST (or weekly)
streamlit run pulse_dashboard.py            # F&O Nifty 50 and F&O All Stocks are pages in the top navbar
streamlit run apps/fno_movers_dashboard.py --server.port 8503   # or just those two pages
```

The run ends with `N candles fetched -> A new, R revised, S already stored`.
Each stock is re-fetched from its last stored day, so "already stored" is normally not
zero. `scripts/kite.py intraday` writes the same `daily_bars` rows, so after
a recent backfill a run can correctly report 0 new. When that happens it prints
the date the history already ran to.

| File | Role |
|---|---|
| [`apps/fno_movers_dashboard.py`](../apps/fno_movers_dashboard.py) | Streamlit page: days (1/3/5/7), rows per table, one page each for Nifty 50 and All F&O, CSV downloads |
| [`market/fno_movers.py`](../market/fno_movers.py) | Universe building, the stored closes, move computation. Pure, no network |
| [`scripts/kite.py history`](../scripts/kite.py) | The only writer of the F&O universe and the daily closes |
| the `fno_universe` set in `data/market.db` | F&O stocks + Kite instrument tokens, from Kite's public NFO and NSE dumps |
| [`scripts/confirm_fno_move.py`](../scripts/confirm_fno_move.py) | Lists the suspected splits and records one as a real move (or takes that back) |
| the `fno_confirmed_moves` set in `data/market.db` | Falls checked and confirmed real, so they are not flagged as splits |
| the `daily_bars` table in `data/market.db` | `symbol, date, open, high, low, close, volume`, one row per stock per day. The 1-minute backfill fills the same table |
| [`tests/test_fno_movers.py`](../tests/test_fno_movers.py) | 22 tests |

For *consistent* movers rather than the biggest ones, meaning stocks that rose
or fell day after day, see the **F&O Heatmap** page: [FNO_HEATMAP.md](FNO_HEATMAP.md).

## Over a period

Both pages have a **By day / Over a period** switch. "Over a period" ranks stocks
by the change between the latest close (today's live price when it is showing)
and the close 3, 5, 10, 20, 30, 50 or 100 **trading days** earlier in the stored file, so
weekends and holidays need no calendar. A stock missing a row on either end day
is left out. 30D, 50D and 100D need that many stored days: backfill with
`python scripts/kite.py history --full --history-days 200` (about 135 trading days, ~2 minutes;
the 2026-10-01 backfill stored 2026-03-16 onward; since 2026-10-23 the table holds 5 years for the
[Drop from High](DROP_FROM_HIGH.md) page). Without enough history the page says so. Each table also shows up days (days that closed above the day
before) and a trend sparkline of the closes.

## Suspected splits and bonuses

Kite adjusts past prices after a split or bonus, but rows already stored keep
the old prices, so the ex-date shows as a huge one-day fall. `suspected_corporate_actions`
flags a fall of 25% or more whose prior/new close ratio is within 6% of 3:2, 2, 2.5,
3, 4, 5 or 10. It only *suspects*: a demerger, buyback or real crash can match.

- Flagged stocks are **hidden from the rankings** (sidebar switch, on by default)
  and listed in an expander on each page. A period ranking drops a stock whose
  window contains the flagged day.
- `python scripts/kite.py history --fix-splits` re-fetches just those stocks
  over the whole stored range and reports each as **adjusted** (Kite's candles now
  show the corporate action, so the jump is gone) or **still a fall** (a real move).
- **Confirmed real moves** are kept with `python scripts/confirm_fno_move.py`: `suspected` shows what is flagged,
  `add SYMBOL YYYY-MM-DD "why"` confirms one, `remove` takes it back, `list` shows them. A confirmed pair is
  never flagged. POLICYBZR on 2026-09-24 (1886 to 1207, about 40% in 20 days) is confirmed: it was checked and
  is a real fall, and it survived a full re-fetch of Kite's adjusted candles.
- Reverse splits (price rises) are not detected.

## Change % colouring

In every gainers/losers table the Change % cell is green for a gain and red
for a loss. The shade scales with the move's size relative to the largest move
in that table: the top row (biggest move) is darkest, the smallest is lightest.
Gainers and losers are shaded independently, so each table uses its full range.
See `shade_change` in `apps/fno_movers_dashboard.py`.

## Where each number comes from

The F&O pages use **Kite only**. They ignore the heatmap pages' provider setting, and a caption on each page says so.

- **Past days:** from the stored closes, with no API call. A day's move is its close
  against the same stock's close on the previous trading day stored. If
  the stock has no row that day, no move is shown, so a two-day move is never
  presented as one day's.
- **Today, while the market is open:** one `GET /quote/ohlc` for all 210
  stocks, cached for 30 s. `ohlc.close` is used as the previous close; it
  matched the daily candles on 50/50 stocks on 2026-09-25.
- **Today, after 15:30:** the live price is measured against the last *stored*
  close, because what `ohlc.close` means after the session has not been
  verified. Once the updater runs after 16:00, today comes from the file like
  any other day.

## Is there a gainers/losers API?

**Only Dhan has one**, found in its Swagger spec on 2026-10-01 (then not in the vendor
docs export; the 2026-10-09 export documents it, the release notes still do not): `POST /v2/data/marketmovers`, with `PRICE_GAINERS` /
`PRICE_LOSERS` over a universe such as `FNO_STOCKS` or `NIFTY_50`. Tried live: 0.4 s,
correct-looking. See [`API_ENDPOINT_AUDIT.md`](API_ENDPOINT_AUDIT.md); the "Dhan Movers" page ([`DHAN_MOVERS.md`](DHAN_MOVERS.md)) is built on it. It ranks *today against the
previous close* only, so it could serve the "By day" card for today, but not the multi-day
views, which still need stored closes. Kite, Groww and INDmoney have no such endpoint, so for
them every mover is computed from closes. The brokers differ only in how cheaply they deliver
the closes. The page does not use Dhan's endpoint yet (see the roadmap).

## Which provider (measured 2026-09-25)

| | Kite | Dhan | Groww | INDmoney |
|---|---|---|---|---|
| Live quote, instruments per call | **1000** | 1000 | 50 | 1000 |
| Calls for today, 210 stocks | **1** | 1 | 5 | 1 |
| Daily candles | 1 instrument/call, any range | 1/call | 1/call | 5/call |
| Candle rate limit | 3/s | 5/s | not published; ~0.4 s/call measured | 5/s |
| F&O stock list | **public dump, no login** | public 35 MB CSV | SDK instrument list | needs token |
| Past closes | verified | – | **identical to Kite on every past day checked** (5 stocks x 5 days) | – |
| Login | daily browser login | token lasts ~24h | TOTP, automatic | token lasts 24h |

Kite was chosen because it needs the fewest calls and the least setup: one bulk
call for today, a public F&O list, and an adapter already verified in this
repo. Its one cost is the morning login. Groww's candles are just as
good (open is `None` in its daily candles, close is correct), but today costs
five calls instead of one.

**The websocket does not help here.** It streams live ticks, so it could keep
*today* updating tick by tick, but it carries no history. A single bulk REST
call every 30 s is simpler and plenty for a ranking.

**Candles cost one request per stock no matter how many days they cover**, on
every broker. That is why the history is stored: a 7-day catch-up and a 1-year
backfill both cost ~210 requests (about 75-110 s on Kite), and the dashboard
then needs none for past days.

## Where the closes are stored

In the `daily_bars` table of the shared SQLite database `data/market.db`: one row per stock per day (symbol,
date, open, high, low, close, volume). The 1-minute backfill ([`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md))
fills the same table from the same Kite daily candles, so there is one daily history, and both scripts upsert, so
the days they share agree. A year of about 210 stocks is roughly 50,000 rows.

Since 2026-10-23 the table holds 5 years (about 257,000 rows), for the [Drop from High](DROP_FROM_HIGH.md) page,
which reads it with SQL. This page and the other in-memory pages (F&O Heatmap, the Insights pages) load only
the last 400 calendar days: `load_closes(since=dashboard_since())`, `DASHBOARD_LOOKBACK_DAYS` in
`market/fno_movers.py`. Their longest window is 100 trading days, and loading all 5 years took 1.0 s against
0.3 s for 400 days. The table also holds the Nifty 100 members without futures (TATACAP, TMCV, VAML); every
F&O page filters by `fno_universe`, so they never appear here.

The table stores **closes, not rankings**. Tables for any number of days, a weekly or monthly change, or a
different universe are all derived at read time, so none of them needs new storage. The dashboard's download
buttons export both the shown tables and the full history as CSV.

## Known limitations

- The list of F&O stocks is today's. A stock that left F&O last month is not
  in the history, and one that joined is backfilled over the full window.
- Exchange holidays need no special handling. The file only has rows for days
  that traded, and each move is measured against the previous day in the file.
- Corporate actions (splits, bonuses) are not detected. Kite adjusts its
  candles retroactively, but rows already stored keep the old prices, so the
  ex-date shows a large false move. `python scripts/kite.py history
  --full --days 60` re-fetches the window and overwrites the stored rows.
