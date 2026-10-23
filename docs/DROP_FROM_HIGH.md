# Drop from high

How far each stock trades below its highest price over a window. The page shows it as a treemap: each tile is a stock, sized by free-float market cap and coloured from green (at the high) to dark red (40% or more below it). Tiles can be boxed by sector. The outer box is the whole universe, so the stock, sector and index levels all read off one picture. It is visualisation only: no orders, no signals.

```bash
streamlit run pulse_dashboard.py                                # "Drop from High" link in the Insights group
streamlit run apps/drawdown_dashboard.py --server.port 8511     # or the page on its own
```

| File | Role |
|---|---|
| [`apps/drawdown_dashboard.py`](../apps/drawdown_dashboard.py) | The page: sidebar controls, KPI row, treemap, stock and sector tables, CSV download |
| [`market/drawdown.py`](../market/drawdown.py) | Windows, the SQL, corporate-action resets, summaries. Pure: no Streamlit, no network |
| [`ui/drawdown_treemap.py`](../ui/drawdown_treemap.py) | Plotly treemap and the two tables |
| [`tests/test_drawdown.py`](../tests/test_drawdown.py) | 25 tests: the SQL against a throwaway database with known numbers, and a headless run of the page |

## Controls

| Control | Options |
|---|---|
| **Stocks** | Nifty 50, Nifty 100, Nifty Next 50, All F&O |
| **High over** | 52 weeks, Year to date, 2 years, 5 years, or **Since a date** (any start, such as the day the Nifty last peaked) |
| **As of** | The close compared with the high. It defaults to the last stored day. Pick an earlier day to see the board as it stood then |
| **Show stocks whose drop is between** | A range filter. −100 to −20 keeps the stocks down 20% or more; −5 to 0 keeps those within 5% of their high |
| **Group by sector** | On: tiles are boxed by sector. Off: one flat sheet of stocks |
| **Tile size** | Market cap (free-float) or Equal |
| **Measure from after a suspected split/demerger** | On by default. See [Corporate actions](#corporate-actions) |

The KPI row always covers the whole universe, whatever the filter shows. It gives the median drop, the cap-weighted drop, how many stocks are within 5% of their high and how many are down 20% or more. Each sector box and the outer box are coloured by their stocks' cap-weighted drop.

## Definitions

- **High** is the highest daily `high` in the window. That is the intraday high, the same definition NSE and every broker use for the 52-week high.
- **Drop** is the as-of close against that high: `(close / high − 1) × 100`. It is 0 at the high and negative below it.
- **52 weeks** means 364 days back from the as-of day. **2 years** and **5 years** are the same date that many years earlier, and **Year to date** starts on 1 January.
- **Sessions since high** counts the stored trading days after the one that set the high.
- **Partial window** (`*` on the tile, "partial window" in the table): the stock's first bar is more than 7 days after the window starts. It listed later (for example SWIGGY, HYUNDAI, TMCV), so it is measured from its first day.

## Data

Everything comes from the `daily_bars` table in `data/market.db`. There are no live prices and no API call, so the page needs no broker login. The close is the last stored one, and today's appears after the 16:00 IST run of `python scripts/kite.py history`.

**History stored: 19 Oct 2021 to today, 217 stocks** (backfilled 2026-10-23):

```bash
python scripts/kite.py history --full --history-days 1830   # 5 years, ~216 requests, ~140 s
```

- **Cost.** Kite's daily candles cost one request per stock whatever the range, up to 2000 days per request. A longer range returns HTTP 400 "interval exceeds max limit: 2000 days", so the script refuses `--history-days` of 2000 or more.
- **Nifty 100 names without futures** (TATACAP, TMCV, VAML on 2026-10-23) are fetched too. They are not added to `fno_universe`, so the F&O pages never list them.
- **Size.** About 257,000 rows. The existing F&O pages hold their rows in memory, so they read only the last 400 calendar days (`DASHBOARD_LOOKBACK_DAYS` in `market/fno_movers.py`). Only this page reads further back, and it does so in SQL.

**Sectors** are NSE's industry labels with banks split out, the same labels the sector heatmap uses. They come from NSE's Nifty 500 list plus the universes, stored as the `sectors` section of the `index_constituents` set by `python scripts/kite.py --master` (or `dhan.py` / `indmoney.py`). A stock outside the Nifty 500 (UJJIVANSFB on 2026-10-23) shows as **Other**. **Tile sizes** are the free-float market caps in `index_weights` (`python scripts/dhan.py --master`); a stock without one gets the median size.

## How it is computed

The page holds one row per stock, never the history. `market.drawdown.drawdowns` is one SQLite query:

1. One aggregate pass per stock over its `(symbol, date)` primary-key range gives the high, the low, the first and last day, and the bar count.
2. Primary-key lookups give the day of the high, the bars since then, and the last close.

Measured on 2026-10-23 for 216 stocks: **52 weeks 52 ms, 2 years 95 ms, 5 years 200 ms**, and the page caches each result. Two earlier versions were 5–20× slower: one joined a CTE several times (SQLite recomputes a CTE each time it is referenced), and one used window functions (sorting every bar).

## Corporate actions

Kite adjusts its history for splits, bonuses and large dividends, **but not for demergers**. A demerged stock's old high stays in the history, so most of its "drop" is the part that was split off.

`suspected_actions` finds one-day falls of 25% or more in SQL, then keeps those whose ratio matches a split (the same `split_ratio` rule the F&O pages use). With the toggle on, such a stock is measured from the day of the fall, and the page names it. On 2026-10-23 this found:

- **VEDL, 30 Apr 2026, −32.9%:** the demerger. Without the reset, VEDL reads about −44% from its 52-week high; with it, about −35%.
- **IEX, 24 Jul 2025, −29.6%:** looks like the real fall after the CERC market-coupling order, not a corporate action. Confirming it as real stops the reset: `python scripts/confirm_fno_move.py add IEX 2025-07-24 "why"`. The reset then stops and IEX is measured over the whole window.

## Checked against Dhan (2026-10-23)

| Check | Result |
|---|---|
| 52-week high and low against Dhan `companyinfo` `FIFTY_TWO_WEEK_HIGH`/`LOW`, 6 Nifty 50 stocks | 4 match exactly. The low matches on all 6 |
| 52-week drop against Dhan's own daily candles, all 50 Nifty 50 stocks | **45 match exactly.** The median is −22.4% on both |

The 5 stocks that differ are where Kite adjusted for a large dividend and Dhan did not:

| Stock | Dhan (raw) | This page | Gap |
|---|---|---|---|
| ITC | −39.3% | −36.3% | 3.0 pts |
| ULTRACEMCO | −16.4% | −14.7% | 1.7 pts |
| INFY | −33.3% | −31.8% | 1.4 pts |
| TECHM | −1.3% | −0.8% | 0.5 pts |
| HINDUNILVR | −30.3% | −30.1% | 0.2 pts |

For example, INFY's high on 3 Feb 2026 is 1728.0 in Dhan's candles and 1691.4 in Kite's. NSE and the screeners (Tickertape, 5paisa) quote the raw traded high, so for these stocks this page reads a few points milder than they do.

## On 2026-10-22 (Nifty 50, 52 weeks)

The median Nifty 50 stock was 22.4% below its 52-week high, and 30 of the 50 were down 20% or more. Only KOTAKBANK (−3.6%) and TECHM (−0.8%) were within 5% of their high.

## Not covered

- **The index itself.** The outer box is the stocks' cap-weighted drop, not the Nifty 50 index's own drop from its high. Index bars aren't stored.
- **Today's live price.** The close is the last stored day.
- **Raw (dividend-unadjusted) prices.** See the Dhan check above. A raw-price option would mean storing Dhan's daily candles alongside Kite's: [ROADMAP](ROADMAP.md).
