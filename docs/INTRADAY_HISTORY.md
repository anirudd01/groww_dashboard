# Intraday history store (1-minute bars + daily gaps)

1-minute OHLCV and daily open/close for every NSE F&O **stock** (the 210 in
the `fno_universe` set in `data/market.db`), kept in one SQLite file for analysis such as
gap-ups. Built and topped up by one script; the **Gap Fills** page
([FNO_INSIGHTS.md](FNO_INSIGHTS.md)) reads it, read-only.

| | |
|---|---|
| File | `data/market.db` (git-ignored, 227 MB for 60 days). The Kite tables below can be rebuilt any time, **but the file also holds the Dhan gainers/losers history ([DHAN_MOVERS.md](DHAN_MOVERS.md)), which cannot: back it up before deleting it** |
| Built by | `python scripts/kite.py intraday` |
| Schema | `market/intraday_store.py` |
| Provider | Kite. Why: [PROVIDER_COMPARISON_LOG.md](PROVIDER_COMPARISON_LOG.md) (2026-09-27) |
| Tests | `tests/test_intraday_store.py` |

## Running it

```bash
python scripts/kite_login.py                 # once a day, before 06:00 expiry
python scripts/kite.py intraday          # 60 days, all 210 stocks, ~5 min
python scripts/kite.py intraday --symbols RELIANCE,TCS
python scripts/kite.py intraday --intraday-days 120   # older history: 2 minute calls per stock
python scripts/kite.py intraday --full --intraday-days 60   # re-fetch stored days (after a split)
```

- **Cost.** Kite gives at most 60 days of 1-minute bars per call and one stock per call. A 61-day window returns `400` (tested 2026-09-27). So each stock costs one minute call per 60 days, plus one daily call. For 60 days that's 420 requests. The first full run on 2026-09-27 took 355 s with no failures. It stored 3,106,665 minute bars and 8,610 daily bars, 30 Jul to 25 Sep 2026 (41 trading days).
- **Incremental.** Each stock restarts from the start of its last stored day. A daily or weekly re-run costs the same 420 requests and fills every missing day.
- **Safe to interrupt.** Each stock is committed as it finishes, and every write is an upsert. If a run stops, run it again.
- **Today's daily bar** is stored only after 16:00 IST, the same rule as `scripts/kite.py history`. Before then its "close" is only the live price. Today's minute bars are stored as far as they go, and the next run completes the day.

## Schema

```sql
minute_bars(symbol, ts, open, high, low, close, volume, oi)   -- PK (symbol, ts)
daily_bars (symbol, date, open, high, low, close, volume)     -- PK (symbol, date)
daily_gaps (symbol, date, open, close, prev_close, gap_pct)   -- view
```

- **Formats.** `ts` is IST wall-clock text, `YYYY-MM-DD HH:MM`, stamped with the minute the bar **starts**. `date` is `YYYY-MM-DD`. Both sort and compare as text.
- **`oi`** is NULL: cash stocks have no open interest.
- **`daily_gaps`** takes each day's `open` against the previous stored `close` for the same symbol: `gap_pct = (open / prev_close − 1) × 100`. "Previous" means the previous row, so weekends and holidays are skipped without a calendar.

**Gaps come from daily bars, never from minute bars.** NSE's official close
is a volume-weighted average over the end of the session. It isn't the last
minute bar's close, so a gap computed from minute bars would be wrong.
Kite's first minute bar *does* open at the official open: it matched on
25 of 25 stock-days tested.

## Useful queries

```sql
-- Top 10 gap-ups on a day
SELECT symbol, prev_close, open, gap_pct FROM daily_gaps
WHERE date = '2026-09-25' ORDER BY gap_pct DESC LIMIT 10;

-- Every gap of 2% or more, either way, in September
SELECT * FROM daily_gaps WHERE date LIKE '2026-09-%' AND ABS(gap_pct) >= 2 ORDER BY date, gap_pct DESC;

-- One stock's first 15 minutes after each gap-up of 1% or more
SELECT m.* FROM minute_bars m JOIN daily_gaps g
  ON g.symbol = m.symbol AND m.ts BETWEEN g.date || ' 09:15' AND g.date || ' 09:29'
WHERE g.symbol = 'RELIANCE' AND g.gap_pct >= 1;
```

From Python: `pandas.read_sql(query, market.intraday_store.connect())`.

## What the data looks like (seen 2026-09-27)

- **Continuous trading ends at 15:15; 15:15–15:30 is SEBI's closing auction session (CAS).** CAS prices aren't continuous trades, so Kite and Dhan publish no minute bars for it. Before the switch Kite has 375 bars a day (09:15–15:29); after it, **360** (09:15–15:14). In this data the switch was phased:
  - 207 of the 210 stocks switched on **3 Aug 2026**.
  - ATHERENERG, MAHABANK and SAGILITY switched on **26 Aug**.
  - No stock returned to 15:29 afterwards.

  Groww shows it too: a near-empty 15:15 bar, then nothing until its post-close bars. (The CAS explanation is from the user, 2026-09-28; the dates are measured. It hasn't been checked against the SEBI or NSE circular.) Storing Groww's pre-open, CAS and post-close bars is on the [roadmap](ROADMAP.md#other-candidates). Don't assume a fixed number of bars per day. `market/market_hours.py` still says the session closes at 15:30.
- **Minute volumes usually add up to 91–99% of the daily volume.** The rest is traded outside the minute bars: the pre-open auction and the session close.
  - Two days are very different. On **31 Aug 2026** the average stock's minute bars held only 74% of the day's volume, and some held as little as 22% (ASTRAL, LAURUSLABS, RELIANCE). On **18 Sep** the average was 78%.
  - On those days most of the volume traded after 15:15, which fits index-rebalancing trades in the closing session.
  - So **use `daily_bars.volume` for a day's volume**, not the sum of its minute bars.
- **One daily history.** `scripts/kite.py history` writes this same `daily_bars` table from the same Kite daily candles, so the two scripts agree on every day they share. That script reaches back further: since 2026-10-23 `daily_bars` holds 5 years (from 19 Oct 2021) for the [Drop from High](DROP_FROM_HIGH.md) page, while `minute_bars` still starts on 30 Jul 2026.
- **Adjustment for corporate actions.** Kite adjusts past prices after a split or large dividend, which is why `--full` exists. A day stored before an ex-date keeps its raw price until you re-fetch it.

## Not covered

- **No sub-minute history.** No broker tested offers historical bars under 1 minute. Seconds data can only be recorded going forward from a live socket.
- **Futures and options** aren't included; this store is stocks only. Kite's NFO instrument list (`/instruments/NFO`) has the contract tokens if that changes.
- **Index minute bars** aren't included either, since the universe is F&O *stocks*.
