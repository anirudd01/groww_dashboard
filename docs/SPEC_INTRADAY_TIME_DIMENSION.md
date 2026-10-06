# Spec: intraday time dimension (Phase 5)

**Status:** draft for review. **Owner:** you. **Roadmap:** [`ROADMAP.md`](ROADMAP.md#phase-5--intraday-time-dimension)

How to review: edit this file. Put comments on a line starting `> COMMENT:` and
fill in the "Your call" column in section 9. Everything marked **(unverified)**
has not been tested against a live broker from this repo.

---

## 1. Problem

Every number on the heatmaps is measured against **yesterday's close**. By
mid-afternoon a sector that rallied 2% in the morning and has been falling for
two hours still shows green, so the board describes the whole day, not the
present. You can't see rotation, which is what the heatmap is for.

## 2. Goals and non-goals

**Goals**
- Let the user choose what the change is measured against: previous close (today's
  behaviour), the last 5 / 15 / 30 / 60 minutes, or the day's open.
- Show a small trend line next to each stock or index in the tables.
- Work on both boards (Nifty 50 sectors, NSE indices) and both treemaps.

**Non-goals (this phase)**
- No database and no files. History lives in memory and dies with the process
  (already decided in the roadmap). Section 5 covers how to cope with restarts.
- No alerts, signals or predictions. Display only, like the rest of the app.
- Not the F&O movers pages. They are built on daily closes and a 30 s quote.
- No tick-level or sub-second history.

## 3. What the user sees

1. A **"Change over"** control in the sidebar of the four live-heatmap pages:
   `Since prev close` (default) · `5 min` · `15 min` · `30 min` · `1 hour` · `Since open`.
2. Tile colours, tile percentages, leading/lagging tables and the breadth figures
   all switch to that basis together. The basis is named on screen ("Change over
   last 15 min"), as the weighting already is.
3. A **Trend** sparkline column in the constituent table, the index tables and the
   leading/lagging tables (today's prices, one point a minute).
4. While there is not enough history for a window (first minutes after the app
   starts), tiles show **"warming up"** in neutral grey, never 0.00%.

```
Change over: [Since prev close] [5 min] [15 min*] [30 min] [1 hour] [Since open]

 Stock       Change % (15 min)   LTP      Trend
 HDFCBANK    +0.42%              1,712.3  ▁▂▂▃▅▆▆▇
 INFY        -0.31%              1,498.0  ▇▆▅▅▃▃▂▁
```

## 4. Definitions

| Basis | Formula | Notes |
|---|---|---|
| Since prev close | `ltp / previous_close − 1` | Unchanged |
| Last N minutes | `ltp / price_at(now − N) − 1` | `price_at(t)` = the last stored price at or before `t` |
| Since open | `ltp / day_open − 1` | `day_open` is the exchange's official open from the quote packet, **not** the first tick we happened to see |

A window change is computed per stock first, then aggregated to the sector the
same way as today (equal- or market-cap-weighted). A stock with no reference
price is excluded and counted as unpriced, never treated as 0%.

## 5. Where the history comes from

The ring buffer fills from live ticks, so it starts empty at process start. A
restart at 14:00 means no 30-minute or 1-hour window until 14:30 or 15:00. Options:

| | A. Ticks only | B. Seed from minute bars at start |
|---|---|---|
| Startup | Empty; windows "warm up" | One REST call per instrument, once, at startup |
| Extra dependency | None | A broker's intraday-candle endpoint |
| Accuracy of the seeded part | n/a | Broker-specific; see below |
| Complexity | Low | Medium |

For B: Kite's minute bars are the most faithful to official prices (measured), but
Kite needs the daily login. Dhan's `/v2/charts/intraday` is the feed's own broker
but its minute prices differ from Kite's on 20-40% of bars (measured, see the
[comparison log](PROVIDER_COMPARISON_LOG.md)). INDmoney's are unusable. Whether
Dhan's or Kite's endpoint returns *today's partial day* is **(unverified)** for
Dhan; it is verified for Kite.

**Recommendation:** ship A first (phase 5a). It is small, and "warming up" is honest.
Add B afterwards only if restarts mid-session are common enough to hurt.

## 6. Design

**One new pure module, `market/price_history.py`** (no Streamlit, no network):

- `PriceHistory`: per symbol, a `deque` of `(timestamp, price)`. One point per
  **10 s** (a newer tick inside the same 10 s replaces the point, so busy stocks
  don't cost more). A session is 6.25 h ≈ 2,250 points per symbol; 67 symbols ≈
  150 k tuples, a few MB.
- `price_at(symbol, t)`: binary search (`bisect`), returns `None` if the buffer
  starts after `t` or the nearest point is older than a tolerance (see 7).
- `sparkline(symbol, points=60)`: downsample to about one point a minute.
- Cleared at the start of each trading session.

**Wiring**
- `live_feed.py` `_apply_prices` appends to the history under the existing lock.
  It already receives every price, so no new thread and no new network call.
- `MarketSnapshot` carries **precomputed reference prices** for the chosen basis
  (one float per stock), not the buffers. The UI thread stays cheap at a 1 s
  refresh and never copies history.
- `sector_aggregation.py` gains a `basis` argument; `compute_change_pct` itself
  does not change. The Streamlit pages pass the sidebar choice.
- `ui/`: basis selector in the shared `sidebar_controls`; sparkline column via
  `st.column_config.LineChartColumn` (Streamlit can't draw charts inside the
  clickable tile buttons, so tiles stay text-only).

## 7. Edge cases

| Case | Behaviour |
|---|---|
| App restarted mid-session | Windows longer than the history show "warming up" (option A) |
| Feed silent for longer than the tolerance (say 2× the window, max 60 s) | That window is "n/a", not a stale number |
| Failover to another broker | History continues; prices differ by a few hundredths of a percent between brokers (measured 0.035% max). A discontinuity is logged, not hidden |
| Market closed / weekend | Windows freeze at the last tick, measured against the session's own history; default stays `Since prev close` |
| Pre-open (09:00-09:15) | No window change; `day_open` isn't set until the open. Shows "warming up" |
| Day roll | Buffers cleared when the session starts; `Since open` waits for the official open |
| Index board | Own buffers (separate service). Same rules |
| Stock with one odd tick | Not filtered in 5a. Flag as a risk below |

## 8. Testing

All in the pure module, offline, like the existing suite:
- window lookup at, before and after the edges of the buffer; gaps; tolerance
- replace-within-10-s and downsampling counts
- `Since open` with and without a `day_open`
- aggregation under each basis, including "excluded, not 0%" and cap-weighting
- session roll clears history

Manual: run during a session, compare a 15-minute change against the same stock
on a broker chart.

## 9. Decisions needed

| # | Decision | Recommendation | Your call |
|---|---|---|---|
| 1 | History source: ticks only (A) or seed from minute bars (B) | A now, B later if needed | |
| 2 | Windows offered | 5, 15, 30, 60 min + since open | |
| 3 | Sampling interval | 10 s | |
| 4 | Default basis | Since prev close (today's behaviour) | |
| 5 | Sparkline in tables only (not tiles) | Yes | |
| 6 | Apply to the two treemaps too | Yes, same selector | |
| 7 | Extend to the F&O pages | No, separate feature | |

## 10. Phasing

- **5a** `price_history.py`, window changes, sidebar selector, "warming up". Tests.
- **5b** Sparkline columns.
- **5c** Since-open basis (needs `day_open` from the quote packet, which Dhan and
  INDmoney already send; Kite's socket is **(unverified)**).
- **5d** Optional seeding from minute bars (decision 1).

## 11. Risks

- **A bad tick** can swing a 5-minute window visibly. If it shows up, filter
  points that move more than a stated percentage from both neighbours.
- **Short windows are noisy.** 5-minute changes on illiquid names will jump
  around; that is the data, but the UI should not imply more precision than it has.
- **Restart behaviour** is the main usability cost of "no files"; decision 1 is
  the lever.
