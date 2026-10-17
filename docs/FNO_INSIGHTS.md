# F&O insights: breadth, overnight vs intraday, relative rotation, gap fills, gap streaks

Five pages in the **Insights** group of `pulse_dashboard.py`'s top navbar. All five read
only the stored history, with no live prices, no API call and no broker login.
They describe what happened; none of them is a signal. Visualisation only.

```bash
streamlit run pulse_dashboard.py                                         # Insights links in the top navbar
streamlit run apps/fno_breadth_dashboard.py --server.port 8506           # or any page on its own
streamlit run apps/fno_session_split_dashboard.py --server.port 8507
streamlit run apps/fno_rotation_dashboard.py --server.port 8508
streamlit run apps/fno_gap_fills_dashboard.py --server.port 8509
streamlit run apps/fno_gap_streaks_dashboard.py --server.port 8511
```

| Page | Question it answers | Data | Logic | Page |
|---|---|---|---|---|
| **Market Breadth** | How many stocks take part in the market's moves? | Stored closes (`daily_bars`) | [`market/breadth.py`](../market/breadth.py) | [`apps/fno_breadth_dashboard.py`](../apps/fno_breadth_dashboard.py) |
| **Overnight vs Intraday** | Is a stock's move made in the gaps or during the session? | Stored closes (`daily_bars`) | [`market/session_split.py`](../market/session_split.py) | [`apps/fno_session_split_dashboard.py`](../apps/fno_session_split_dashboard.py) |
| **Relative Rotation** | Which sectors/stocks lead the market, and which are turning? | Stored closes (`daily_bars`) | [`market/rotation.py`](../market/rotation.py) | [`apps/fno_rotation_dashboard.py`](../apps/fno_rotation_dashboard.py) |
| **Gap Fills** | After a gap, does the stock trade back to yesterday's close the same day? | Stored 1-minute bars and `daily_gaps` (`data/market.db`) | [`market/gap_fills.py`](../market/gap_fills.py) | [`apps/fno_gap_fills_dashboard.py`](../apps/fno_gap_fills_dashboard.py) |
| **Gap Streaks** | Which stocks gapped up (or down) day after day, and did the gaps hold? | Stored closes (`daily_bars`) | [`market/gap_streaks.py`](../market/gap_streaks.py) | [`apps/fno_gap_streaks_dashboard.py`](../apps/fno_gap_streaks_dashboard.py) |

Shared pieces:
- [`market/price_panel.py`](../market/price_panel.py) turns the stored closes into date × symbol frames, builds the equal-weight index and defines the universe sets.
- [`apps/fno_common.py`](../apps/fno_common.py) holds the cached loaders, the universe picker, the split toggle and the staleness warning.
- [`ui/insight_charts.py`](../ui/insight_charts.py) builds every figure.
- [`tests/test_fno_insights.py`](../tests/test_fno_insights.py) has 32 tests, including a headless AppTest for each page and for the navbar.

## Keeping the data current

```bash
python scripts/kite_login.py           # once per trading day
python scripts/kite.py history   # daily closes -> data/market.db (~85 s)
python scripts/kite.py intraday    # 1-minute + daily bars -> data/market.db (~4 min); Gap Fills only
```

Both scripts run after 16:00 IST and fill every missing day in one run. Each
page warns when its data is more than 4 calendar days old. As of 2026-10-02 the
stored closes run from 16 Mar to 1 Oct (136 days) and the 1-minute bars from 30 Jul to 1 Oct.

**Common rules.** Every page offers **Nifty 50 / All F&O / F&O outside Nifty 50**
(Rotation has its own views). Every page except Gap Fills has **Hide suspected splits/bonuses**,
on by default: it blanks the flagged day (same detector as the movers pages), so a
price adjustment is never read as a market move. Days a stock has no row stay
empty and are never forward-filled.

**There is no index series.** The repo stores no Nifty close, so "the market"
is an **equal-weight index** built from the members: the average daily return of
every stock that traded both days, chained. It answers "how did the average
stock do", the same default as the sector heatmap.

## Market Breadth

For each stored day:

| Measure | Definition |
|---|---|
| Advances / declines | Stocks that closed above / below their previous close (both days needed) |
| A/D line | Running total of advances − declines. It rises when more stocks go up than down, whatever the size |
| % above 20-day / 50-day avg | Share of stocks whose close is above their own simple moving average. Only stocks with a full window count |
| New highs / lows | Stocks closing above / below **every close** of the previous 20 (or 50) trading days. Closes, not intraday highs, as the file stores closes |
| Breadth label | % above the 50-day: **Broad strength** ≥ 60%, **Broad weakness** ≤ 40%, otherwise **Mixed** |

The averages are computed on the full history. **Show (1M / 3M / All)** only sets
how much the charts display. The 50-day measure needs 50 stored days, so it starts
in late May.

*On 2026-10-01 (all F&O):* only 10% of stocks were above their 50-day average and
7% above their 20-day. There was 1 new 20-day high against 102 new lows. The A/D
line had fallen from about +1000 in early August to below 0.

## Overnight vs Intraday

Each close-to-close move splits into **overnight** (previous close → open, the gap)
and **intraday** (open → close). The parts are summed as **log returns**, so
overnight and intraday together give the total exactly. The open is Kite's
daily-candle open, NSE's official pre-open auction price. A day counts only if the
stock has a row on the previous trading day too.

| Pattern | Meaning |
|---|---|
| Gap-driven up/down | ≥ 65% of the absolute movement came overnight |
| Session-driven up/down | ≤ 35% came overnight |
| Both, up/down | In between |
| Gaps up, sold in session / Gaps down, bought in session | The two parts pointed in opposite directions |

The page shows the average stock's cumulative overnight, intraday and total lines.
It also has a scatter of every stock (x = overnight, y = intraday, colour = total,
dotted diagonal = went nowhere), and tables for gap-driven stocks, session-driven
stocks and stocks where the two fought.

*On the 60 trading days to 2026-10-01 (all F&O):* the average stock fell 5.0%.
Its overnight gaps **added** 0.8%, and the whole loss (−5.8%) came during sessions.
125 of 213 stocks had the two parts pointing in opposite directions.

## Relative Rotation

An RRG-style chart against the equal-weight Nifty 50:

```text
RS           = price / benchmark
RS-Ratio     = 100 × RS / SMA(RS, lookback), then smoothed over 3 days     (x axis)
RS-Momentum  = 100 × RS-Ratio / RS-Ratio `momentum` days earlier          (y axis)
```

| Quadrant | x | y | Meaning |
|---|---|---|---|
| Leading | > 100 | > 100 | Beating the benchmark, edge growing |
| Weakening | > 100 | < 100 | Still beating it, edge shrinking |
| Lagging | < 100 | < 100 | Behind, falling further behind |
| Improving | < 100 | > 100 | Behind, catching up |

Names tend to move clockwise: Improving → Leading → Weakening → Lagging. A stock
outperforming at a **steady** rate keeps a constant RS-Ratio, so its momentum sits
on 100. Leading needs the edge to *grow*.

- **Views:** Nifty 50 sectors (16 equal-weight sector indices from
  NSE's lists stored by `--master`, with trails), Nifty 50 stocks, and the other F&O
  stocks. With more than 20 names the chart shows dots only. Pick names in
  **Highlight** to draw their trails and labels.
- **Controls:** trail length 2–20 days, lookback 10/20/40, momentum 3/5/10.
- **Tables:** every name with its quadrant and its quadrant 5 days ago, plus the
  names that changed quadrant.
- The formulas are an **open approximation**. The JdK RS-Ratio/RS-Momentum behind
  commercial RRG charts are proprietary, so values will not match those charts.
- Sectors exist only for the Nifty 50. The other ~160 F&O stocks have no sector
  in the repo, so they are plotted as stocks only.

## Gap Fills

- **Gap:** the official open against the previous official close, from the
  `daily_gaps` view (daily candles; [INTRADAY_HISTORY.md](INTRADAY_HISTORY.md)
  explains why never from minute bars).
- **Filled:** a gap-up fills when a minute bar's low reaches the previous close,
  a gap-down when a high does. The time is counted from 09:15, and 0 means within
  the first minute.
- **Closing auction:** continuous trading ends at 15:15 (since August 2026), and
  the 15:15–15:30 auction has no minute bars. If no bar reached the previous close
  but the official close got back through it, the gap filled in the auction and is
  counted as filled at 15:15.
- **Outcomes:** **Filled**; **Held, faded** (never filled, closed back inside the
  gap); **Gap and go** (never filled, closed beyond the open).
- **Complete days only:** a day needs at least 350 minute bars (360 since August,
  375 before). A backfill that stopped mid-session cannot pass for a gap that
  never filled.
- **Controls:** smallest gap 0.25/0.5/1/2%, direction, universe, and a minimum
  gap count for the per-stock table.
- **Charts:** fill rate by gap size (n shown on each bar) and the cumulative
  fill curve by time of day.
- **Tables:** stocks that fill most often, stocks that gap and go most often,
  and every gap.

One SQL query reads every gap of at least 0.25% with its first fill minute: 5,117
gaps over 3.46 million bars in about 2.6 s. The result is cached until
`market.db` changes. The page opens the store read-only.

*30 Jul to 1 Oct 2026, gaps ≥ 0.5%, all F&O:* 2,834 gaps; 54% filled the same day
(gap-ups 61%, gap-downs 47%); median time to fill 8 minutes; 36% gap and go.
Fill rates fall with size: 68% of 0.5–1% gap-ups filled against 9% of 3%+.

## Gap Streaks

The Gap Fills page asks what happens *after* one gap. Gap Streaks asks which stocks
gap the **same way day after day**. A run of opens above the previous close means
persistent overnight demand (news, global cues, flows outside market hours); a run
below it means persistent overnight supply.

- **Layout:** the same as the [F&O Heatmap](FNO_HEATMAP.md). It has a stock × day
  heatmap where each cell is that day's **gap** (open vs previous close), and three
  tabs: **Nifty 50** (all 50), **Other F&O: consistent gap-ups** and **Other F&O:
  consistent gap-downs** (top 10–30). The heatmap scoring code is shared:
  `ConsistencyRow` now also takes per-day log returns (`steps`).
- **Rank by:** **Consistency** (net gap ÷ total gap distance, −100..+100; +100 =
  opened above the previous close every day), **Gap-up days** (minus gap-down days),
  or **Net gap** (all the window's gaps compounded).
- **Ignore gaps smaller than** 0 / 0.1 (default) / 0.25 / 0.5%: such a day counts
  as neither a gap-up nor a gap-down for the day counts and streaks. The heatmap
  still shows it.
- **Streaks and follow-through tab:** every F&O stock with its **current streak**
  (consecutive gap-ups +, gap-downs −, up to the last day), gap-up/down days, net
  and average gap, and **Session, same days**, the open-to-close moves over the same
  window compounded. An opposite sign to the net gap means the gaps were faded during
  the day. The KPI **Gaps held by the session** is the share of stocks where the
  session moved the same way as the net gap.
- **Window:** 5/10/15/20/30 trading days. A stock missing a day in the window is
  left out and listed, the same rule as the F&O Heatmap.

*10 trading days to 2026-10-01:* no F&O stock gapped up or down on all 10 days.
The longest current gap-down streak was 7 days and the longest gap-up streak 4.
Only 44% of stocks had sessions moving the same way as their net gap: the gaps
were mostly faded, matching the Overnight vs Intraday reading.

## Known limitations

- Equal-weight benchmark only. A cap-weighted one would need free-float weights for
  all F&O stocks; the `index_weights` set in `data/market.db` has the Nifty 50 only.
- The F&O list and the Nifty 50 membership are today's, applied to the whole
  history.
- Gap Fills covers only what `scripts/kite.py intraday` stored (about 60 days). Older
  history needs `--days 120` (two minute calls per stock).
- Every page reads `data/market.db`, which is not checked in. On another machine each page says which script
  builds what it needs: `scripts/kite.py history` for the closes, and `scripts/kite.py intraday` as well for Gap Fills.
