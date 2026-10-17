# F&O consistency heatmap

Which F&O stocks have moved **steadily** in one direction over the last N
trading days. The [F&O movers](FNO_MOVERS.md) pages answer a different question:
they rank by the biggest change from one close to another, so one huge day can
put a stock on top. Here each stock is a row of N daily moves, and a steady
performer shows as a solid green (or red) row. Visualisation only; it places no
orders and generates no signals.

```bash
streamlit run pulse_dashboard.py                                   # "F&O Heatmap" link in the top navbar
streamlit run apps/fno_heatmap_dashboard.py --server.port 8510     # or the page on its own
```

**Data comes only from the stored daily closes** (`daily_bars` in `data/market.db`). There are no live prices
and no API call, so the page needs no broker login. Keep them current
with `python scripts/kite.py history` (see [FNO_MOVERS.md](FNO_MOVERS.md)).
The page warns when the history is more than 4 days old.

| File | Role |
|---|---|
| [`apps/fno_heatmap_dashboard.py`](../apps/fno_heatmap_dashboard.py) | The page: sidebar controls, KPI row, three tabs, CSV download |
| [`market/fno_consistency.py`](../market/fno_consistency.py) | Window, per-stock rows, scores, ranking. Pure, no Streamlit, no network |
| [`ui/fno_heatmap.py`](../ui/fno_heatmap.py) | Plotly stock x day heatmap, colour limit, table export |
| [`tests/test_fno_consistency.py`](../tests/test_fno_consistency.py) | 20 tests, including a headless AppTest of the page |

## The three heatmaps

The page has three tabs. Each one is a full-width heatmap.

| Tab | Stocks | Order |
|---|---|---|
| **Nifty 50** | All 50 | Strongest at the top, weakest at the bottom |
| **Other F&O: consistent gainers** | F&O stocks **outside** the Nifty 50 that **rose** over the window, top 10–30 | Strongest first |
| **Other F&O: consistent losers** | F&O stocks outside the Nifty 50 that **fell** over the window, top 10–30 | Weakest first |

The gainers list only includes stocks that rose over the window, and the losers
list only stocks that fell. When the whole market falls, the gainers tab is
short or empty rather than padded with stocks that merely fell less. On
2026-09-30 (a falling week) it held 6 stocks.

A cell is that day's close-to-close % change. The colour scale is shared by all
three heatmaps, so a shade means the same move on every tab. It is symmetric
around 0 and capped at the 95th percentile of all the daily moves shown (at least
±1%), so one crash day does not wash out everything else. Cells show their value
up to 10 days; above that, hover for it. Each row label reads
`SYMBOL  up-days/N↑  net%`, so the reason for a stock's rank is visible.

## Ranking: the radio button

| Rank by | What it measures | Ties broken by |
|---|---|---|
| **Consistency** (default) | Directional efficiency, −100 to +100 (below) | Net change |
| **Up days** | Up days minus down days | Net change |
| **Net change** | First close to last close: the plain biggest-move ranking | Symbol |

### Consistency score

```text
efficiency = ln(last close / first close) / Σ |ln(close_i / close_i-1)|
score      = efficiency × 100
```

It is the net move divided by the total distance travelled:

- **+100**: closed higher every day, however small each step was.
- **near 0**: choppy. It went up and down and got nowhere, even if one day was huge.
- **−100**: closed lower every day.

Log returns make the numerator exactly the sum of the daily steps, so the ratio
is exact. Example, 20 trading days to 2026-09-30, other F&O stocks: ATHERENERG
fell 17.4%, the third-largest fall, but scores only −43, because it fell in bursts
with up days in between. TATAELXSI fell less (15.1%) but more steadily, and scores
−66. **Net change** puts ATHERENERG near the top of the losers and leaves TATAELXSI
off it. **Consistency** puts TATAELXSI first and ATHERENERG well down the list.

Why this and not something else:

- **Up-day count alone** takes only N+1 values (0..5 for 5 days), so most stocks
  tie and the heatmap order is arbitrary. It is offered as a ranking, with net
  change breaking ties.
- **Mean ÷ standard deviation of returns** (a Sharpe-like t-stat) is unstable
  over 3–5 days. A stock with five near-identical +0.1% days gets a huge score.
- **Efficiency** is continuous, bounded, scale-free (a ₹100 and a ₹10,000 stock are
  comparable), and easy to explain.

Efficiency deliberately ignores size. A stock up 0.1% a day for 5 days scores
+100, the same as one up 3% a day. Net change breaks ties, and the row label
shows the net %, so you can tell the two apart. Switch to **Net change** to rank
by size.

## Controls

| Sidebar | Options | Default |
|---|---|---|
| Trading days | 3, 5, 7, 10, 15, 20 | 5 |
| Rank by | Consistency, Up days, Net change | Consistency |
| Stocks per Other F&O heatmap | 10, 15, 20, 25, 30 | 15 |
| Hide suspected splits/bonuses | on/off | on |
| Download all ranked stocks (CSV) | Every ranked F&O stock, one column per day, with a Nifty 50 flag | |

Trading days are counted in the file, not on a calendar, so weekends and
holidays need no handling.

## Gaps and splits

- **A stock missing a close on any day of the window is left out**, and listed
  under the KPI row. Its row would either hide the gap or show two days' move in
  one cell. A gap before the window does not matter.
- **Suspected splits/bonuses** use the same detector as the movers pages
  (`suspected_corporate_actions`, honouring the confirmed moves kept by `scripts/confirm_fno_move.py`). With
  the switch on, a stock with a flagged day inside the window is left out.
  POLICYBZR's −36% on 2026-09-24 is a confirmed real fall, so it is shown.

## Known limitations

- No live "today" column. The window ends on the last stored day. Run the updater
  after 16:00 IST to include today.
- The F&O list is today's (same as the movers pages).
- Nifty 50 membership comes from `market/universe.py`, which is the current list.
  It is not dated, so a reconstitution changes which tab a stock appears in for
  past windows too.
