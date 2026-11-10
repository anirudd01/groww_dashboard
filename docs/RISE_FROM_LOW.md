# Rise from low

The mirror of [Drop from high](DROP_FROM_HIGH.md): how far each stock trades above its lowest price over a window. The page shows it as a treemap: each tile is a stock, sized by free-float market cap and coloured from red (still at the low) to dark green (50% or more above it). Tiles can be boxed by sector, and the outer box is the whole universe. It is visualisation only: no orders, no signals.

```bash
streamlit run pulse_dashboard.py                              # "Rise from Low" link in the Insights group
streamlit run apps/rally_dashboard.py --server.port 8513      # or the page on its own
```

| File | Role |
|---|---|
| [`apps/rally_dashboard.py`](../apps/rally_dashboard.py) | The page: sidebar controls, KPI row, treemap, stock and sector tables, CSV download |
| [`market/rally.py`](../market/rally.py) | The SQL and the summaries. Windows, corporate-action detection and resets come from `market/drawdown.py` |
| [`ui/rally_treemap.py`](../ui/rally_treemap.py) | Plotly treemap and the two tables |
| [`tests/test_rally.py`](../tests/test_rally.py) | The SQL against a throwaway database with known numbers, and a headless run of the page |

The Drop from High files are unchanged; this page imports from them.

## Controls

The same as Drop from High (stocks, window, as-of day, group by sector, tile size, the split/demerger reset), plus:

| Control | Options |
|---|---|
| **Show stocks whose rise is between** | 0 to 100%. The top value means 100% or more, so long windows still show every stock. 0 to 5 keeps the stocks still within 5% of their low; 20 to 100 keeps those up 20% or more |
| **Low came** | Any; **Low after high** (the stock fell and is bouncing off the bottom); **Low before high** (it set the low early and has climbed since) |

The KPI row covers the whole universe, whatever the filters show: the median and cap-weighted rise, how many stocks are within 5% of their low, how many are up 20% or more, and how many set their low after their high.

## Definitions

- **Low** is the lowest daily `low` in the window: the intraday low, NSE's definition of the 52-week low. If the low was touched twice, the later day counts.
- **Rise** is the as-of close against that low: `(close / low − 1) × 100`. It is 0 at the low.
- **From high** is the same close against the window's high, exactly the Drop from High figure.
- **Fall won back** (only when the low came after the high): `(close − low) / (high − low) × 100`. 0% is still at the low, 100% is back at the high.
- Windows, partial windows (`*`) and sessions are counted as on Drop from High.

## Corporate actions

A demerger left unadjusted in Kite's history lowers the price for good, so the days after it would set a fake low. The reset toggle measures such a stock from the day of the fall, using the same detection as Drop from High.

## Checked (2026-11-04)

For the Nifty 50 and all 218 F&O stocks, over 52 weeks, the year to date and 5 years, the rise from the low and the drop from the high match the Drop from High page's "Above low %" and "From high %" for every stock. All F&O over 5 years takes about 250 ms.
