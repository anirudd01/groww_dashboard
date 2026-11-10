# Provider comparison log

Dated, measured comparisons between broker APIs. Add new runs at the top and
never edit old ones. If a later run contradicts an earlier one, say so in the
new entry. Conclusions go into [`PROVIDER_GUIDE.md`](PROVIDER_GUIDE.md); this
file holds the evidence.

Re-run:

```bash
python scripts/kite_login.py                          # if today's Kite session is missing
python scripts/debug/compare_intraday_providers.py --out results.json    # 1-minute + daily, Kite, Groww and Dhan
python scripts/debug/compare_heatmap_startup.py --out results.json       # heatmap cold start, both boards
```

---

## 2026-11-07: Kite vs Groww vs Dhan, 1-minute and daily, all three logged in

Why: the 2026-09-27 Groww numbers predate the 2026-10-01 fix (session-only comparison, label
alignment), Groww was never re-run with it, and daily candles had only been compared Kite vs Dhan.
Question: can the daily jobs run unattended on Dhan and/or Groww instead of Kite, whose login is manual?

Setup: `python scripts/debug/compare_intraday_providers.py --end 2026-11-06`, run twice on Sat
2026-11-07 evening; both runs gave identical numbers. RELIANCE, TCS, HDFCBANK, INFY, SBIN. 1-minute:
the 6 sessions to 2026-11-06, compared by minute label inside 09:15-15:14 only. Groww's pre-open
(09:08 bar, volume only) and its 15:15-15:59 bars (closing auction session and after) are counted,
never compared. Daily: the 22 sessions to 2026-11-06 (new part 6 of the script). Kite is the
reference because its minute bars reproduce the official daily candle.

**Widest 1-minute window per call:** Kite 60 days, Groww 30 days (31 → `GA001`), Dhan 90 days.
Same as before.

**1-minute bars, % equal to Kite (10,800 bars; Dhan 10,795):**

| | O | H | L | C | V | Best label shift | Bars outside 09:15-15:14 |
|---|---|---|---|---|---|---|---|
| Groww | 55.9 | 89.8 | 89.9 | **92.7** | **99.8** | 0 | 312 (pre-open + CAS) |
| Dhan | 48.2 | 67.3 | 67.0 | 58.6 | 12.9 | 0 | 0 |

- Bars per day (RELIANCE): Kite and Dhan 360, 09:15-15:14 (Dhan once 359). Groww 363-373, 09:08-15:59.
- Against the official daily candle (30 stock-days): first bar = official open Kite 30, Dhan 24,
  Groww 0. Minute high reaches the day's high: Kite 25, Dhan 22, Groww 9. Low: Kite 30, Dhan 28, Groww 6.
- How often a bar's open equals the previous bar's close: Kite 40.4%, Dhan 33.2%, Groww **0.0%**.
  So Groww's opens are not a "previous close" convention; they are a different open price.

**Daily candles, % equal to Kite (110 stock-days):**

| | O | H | L | C | V |
|---|---|---|---|---|---|
| Dhan | 83.6 | 83.6 | 83.6 | 83.6 | **100** |
| Groww | 0.0 | 40.0 | 23.6 | 83.6 | 47.3 |

Every daily mismatch in O/H/L/C, for both, is **INFY on 18 days up to 2026-10-21**: Kite has
adjusted those days for a corporate action (closes ~2.2% lower) and Dhan and Groww show the raw
price, as the 2026-10-23 entry found. On the other four stocks Dhan's daily candle equals Kite's
exactly, field for field. Groww's daily open never matches and its high, low and volume mostly
don't: its daily candle is not the official one.

**Findings**
- **Dhan daily = Kite daily**, except that Kite adjusts history for corporate actions and Dhan
  doesn't. Dhan can take over `daily_bars` unattended, if the adjusted-vs-raw basis is handled.
- **Groww is the best unattended source of 1-minute bars**: volume equal on 99.8% of bars,
  close on 92.7%, same labels as Kite. Its opens differ, and its first bar never opens at the
  official open, so take a day's open from the daily candle, never from Groww's 09:15 bar. Its
  pre-open and closing-session bars must be dropped (or stored separately) when writing `minute_bars`.
- **Dhan's 1-minute bars got worse** than on 2026-09-27 (close 69.9% → 58.6%, volume 12.2% → 12.9%).
  Don't use them for history.

**Why they differ** (same evening: raw candles stored by `scripts/debug/capture_candles.py` in
`data/provider_compare.db`, run `20261107T175417Z`, measured by `scripts/debug/analyze_candle_diffs.py`):

- **Not a decimals or rounding issue.** No mismatch is under 1 paisa; outside INFY they are whole
  ticks (5-50 paise, median 0.05-0.5).
- **INFY is a corporate-action adjustment, in minute bars too.** Kite rescales all INFY prices before
  2026-11-03 by about 0.978 (2.29%, ~Rs 26); Dhan and Groww keep raw prices (e.g. 2026-11-02 close
  Kite 1135.0, Dhan/Groww 1161.0; from 2026-11-03 all three equal). That alone produced most "large"
  mismatches in the headline table.
- **Without INFY, Groww's 1-minute bars are nearly Kite's:** close 98.8-99.8%, high 95.6-97.0%, low
  95.1-97.7%, volume 99.6-100% equal, misses of 5-50 paise. Labels line up exactly: volume is equal on
  99.8% of bars at the same label and 0% at a one-minute shift either way. The open differences are
  two **conventions**, not bad data (rechecked the same night):
  - **09:15 bar - the pre-open price.** Kite's 09:15 open is the pre-open (call auction) price on 24/24
    stock-days. Groww puts that price in a separate pre-open bar (09:08) and starts its 09:15 bar at
    the first continuous trade, so its 09:15 open matched Kite's on 0/24. This is where the largest
    open gaps are (TCS 2026-10-30: Kite 2495.20 = Groww's pre-open price, Groww 09:15 open 2507.20).
    Example RELIANCE 2026-11-06: Groww 09:08 = 1295.00 = Kite's 09:15 open; Groww 09:15 opens 1295.60.
  - **Later bars - Kite repeats the previous close.** In 99% (3,353/3,379) of the open mismatches after
    09:15, Kite's open is its own previous minute's close; Groww's open is the minute's first trade and
    never the previous close. Kite does this on ~40% of all bars. Because Kite's range then includes
    that repeated price, about half of the high/low mismatches are Kite's high or low being its own
    open (173/335 highs, 145/289 lows). The rest of the high/low gaps (~2% of bars) are small, 5-15 paise.
  - Rebuilding Groww's bars "Kite-style" (open = previous close every minute) made the opens worse
    (39% equal), so Kite doesn't repeat the close on every minute - only on some. Which minutes is not
    worked out.
- **Dhan's 1-minute bars: boundary trades land in the wrong minute, both ways, with no net delay**
  (same checks as for Groww, rechecked the same night):
  - **09:15 open = the official (pre-open) open on 24/24 stock-days**, like Kite.
  - **Labels line up:** close equal to Kite's 62.5% at the same label, ~6% at a one-minute shift either way.
  - **No delay.** If Dhan's minute started δ seconds late, its volume would be the true volume minus δ
    seconds of this minute plus δ seconds of the next. Fitting that over 8,496 bars, with each day scaled to
    the same total, gives δ = **-0.3 s** overall (per stock-day -1.5 to +2.3 s). An earlier reading here,
    "a few seconds late", was wrong.
  - **Trades at the boundary are filed in a neighbouring minute.**
    - Each minute's volume error is strongly negatively correlated with the next minute's (**-0.50**):
      what one minute gains, the next loses.
    - Dhan is above Groww/Kite as often as below (3,732 vs 3,695 bars).
    - The error is small, a median of **0.40% of the minute's volume** (about 115 shares), and it does not
      build up: 128 shares per 5-minute block.
    - The prices follow: where Dhan's close differs from Groww's, it equals the next minute's first trade on
      38% of bars. Dhan's open is its own previous close on 24% of its open mismatches with Kite.
  - **Why only 13.7% of volumes are exactly equal:** any trade moved across a boundary breaks exact
    equality, though the bars are off by a fraction of a percent.
- **Groww's daily candle:** `open` is always null. High, low, close and volume are built from *all* its
  minute bars, including pre-open and 15:15-15:59 (closing auction session and after): high 30/30,
  low 30/30, close 30/30, volume 30/30 (vs 24/30, 28/30, -, 0/30 using 09:15-15:14 only). Its volume
  equals Kite's daily volume on 17/30.
- **Dhan's daily candle equals Kite's** on every field apart from the INFY adjustment.
- Groww's extra minute labels: 09:00-09:08 (volume only; 09:08 priced on half the days), 15:15, 15:28-15:29,
  15:50-15:59.
- None of this depends on an account setting: these are API responses, the same for any account.

**Pairwise tables, 4 stocks (INFY left out: its gap is Kite's adjustment, above).** "Equal" is exact
equality; the gaps are for the candles that differ. 1-minute: 8,640 bars in 09:15-15:14. Daily: 88 days.

Groww vs Kite:

| Field | 1-min equal | 1-min median gap | 1-min largest gap | Daily equal | Daily median gap |
|---|---|---|---|---|---|
| Open | 60.6% | Rs 0.10 (0.010%) | Rs 12.00 | no open in Groww's daily | - |
| High | 96.1% | Rs 0.10 (0.010%) | Rs 9.40 | 48.9% | Rs 0.30 (0.025%) |
| Low | 96.7% | Rs 0.15 (0.012%) | Rs 7.80 | 27.3% | Rs 0.30 (0.026%) |
| Close | 99.3% | Rs 0.20 (0.016%) | Rs 1.30 | 100% | - |
| Volume | 99.8% | 137 shares (0.50%) | 56,380 shares | 47.7% | 74,447 shares (0.82%) |

Dhan vs Kite:

| Field | 1-min equal | 1-min median gap | 1-min largest gap | Daily equal | Daily median gap |
|---|---|---|---|---|---|
| Open | 50.9% | Rs 0.15 (0.014%) | Rs 2.80 | 100% | - |
| High | 72.3% | Rs 0.10 (0.008%) | Rs 2.30 | 100% | - |
| Low | 71.2% | Rs 0.10 (0.008%) | Rs 2.60 | 100% | - |
| Close | 62.5% | Rs 0.15 (0.014%) | Rs 2.90 | 100% | - |
| Volume | 13.7% | 192 shares (0.63%) | 2,271,584 shares | 100% | - |

Dhan vs Groww:

| Field | 1-min equal | 1-min median gap | 1-min largest gap | Daily equal | Daily median gap |
|---|---|---|---|---|---|
| Open | 40.8% | Rs 0.15 (0.013%) | Rs 12.00 | no open in Groww's daily | - |
| High | 70.0% | Rs 0.10 (0.008%) | Rs 9.40 | 48.9% | Rs 0.30 (0.025%) |
| Low | 69.5% | Rs 0.10 (0.008%) | Rs 7.80 | 27.3% | Rs 0.30 (0.026%) |
| Close | 62.7% | Rs 0.15 (0.014%) | Rs 2.90 | 100% | - |
| Volume | 13.8% | 192 shares (0.63%) | 2,271,584 shares | 47.7% | 74,447 shares (0.82%) |

The large single gaps sit at the first bars of the day: for Groww's open (Rs 12) it is the pre-open
price, which Kite folds into its 09:15 bar and Groww keeps in its 09:08 bar (see above). Dhan's 2.27M
shares is its 09:15 volume.
Dhan vs Groww daily equals Groww vs Kite daily because Dhan's daily equals Kite's.

**Agrees with** the 2026-09-27 Groww row once INFY is left out (close 99.3% then 99.2%, high/low ~96%).
The headline table above is lower only because of INFY.

**Which provider for which data** (also in [`PROVIDER_GUIDE.md`](PROVIDER_GUIDE.md)):

| Data | Use | Not | Why |
|---|---|---|---|
| Daily candle (O/H/L/C/V) | **Dhan** (unattended) or Kite | Groww | Dhan = Kite exactly, raw prices. Groww has no open, and its high/low/volume include pre-open and closing-session trades |
| Adjusted daily history | Kite | Dhan, Groww | Only Kite adjusts for corporate actions |
| 1-minute close and volume | Kite, or **Groww** (unattended) | Dhan, where exact per-minute values matter | Groww close 99.3%, volume 99.8% equal to Kite. Dhan files boundary trades in the neighbouring minute (volume off by a median 0.4%, close equal 62.5%); fine for charts, not for exact minute data |
| 1-minute open/high/low | Kite; Groww if its convention is fine | Dhan | Groww's open is the minute's first trade; Kite's sometimes repeats the previous close. For the day's official open from Groww, use its pre-open (09:08) bar, not its 09:15 bar. Groww high/low ~96% equal. Dhan's open 51%, high/low ~72% |
| Pre-open and closing auction bars | Groww (only source) | - | Kite and Dhan send none |

**Not covered:** stocks beyond these five; weeks with a split or bonus; Groww's pre-open and
closing-session bars themselves (dropped, not checked).

---

## 2026-10-23: Kite daily range limit, and Kite vs Dhan 52-week highs

Question 1: how far back does one Kite day-candle call go? RELIANCE, to 2026-10-23:

| From | Result |
|---|---|
| 2021-10-20 (5 years) | `200`, 1,243 candles, the first already adjusted for the 2024 1:1 bonus (1307.2) |
| 2019-06-01 (~7.4 years) | `400` "interval exceeds max limit: 2000 days" |

So 5 years is still one request per stock. `scripts/kite.py history --full --history-days 1830` then
stored 217 stocks × 1,243 days (2021-10-19 .. 2026-10-22) in 138 s with no failures.

Question 2: do our 52-week highs (max of Kite's daily `high`) match the brokers'?

- **Dhan `companyinfo` `FIFTY_TWO_WEEK_HIGH`/`LOW`** for RELIANCE, HDFCBANK, INFY, TCS, ITC and BHARTIARTL. The low matched on all 6, and the high on 4. INFY (Dhan 1728 vs 1691.4) and ITC (426.4 vs 406.55) didn't, and Kite's quote showed neither high was set today.
- **Dhan `/charts/historical`** for those two shows the **same days** at Dhan's prices: INFY 1728.0 on 2026-02-03, ITC 426.4 on 2025-10-31. Kite's candles for those days are lower, so Kite has adjusted them, presumably for dividends paid since. The 22 Oct rows before and after the `--full` re-fetch were identical for both, so the adjustment was already in place when first fetched.
- **All 50 Nifty 50 stocks**, 52-week drop from Dhan's candles vs from `daily_bars`: **45 identical.** The 5 that differ are ITC −3.0 pts, ULTRACEMCO −1.7, INFY −1.4, TECHM −0.5 and HINDUNILVR −0.2 (the raw drop is the deeper one). The median was −22.4% on both. The last close was identical on all 50.

Conclusion: Kite's daily history is adjusted for splits, bonuses and large dividends, while Dhan's is the raw
traded price, the basis of NSE's and the screeners' 52-week high. Demergers are adjusted by neither (VEDL,
2026-04-30, −32.9% in one day after the re-fetch). Recorded in [`PROVIDER_GUIDE.md`](PROVIDER_GUIDE.md) and
[`DROP_FROM_HIGH.md`](DROP_FROM_HIGH.md).

---

## 2026-10-01: does the 1-minute comparison script line bars up by time?

Question: `scripts/compare_intraday_providers.py` compared bars by minute label, or
just first to last? **By label** (a dict keyed `YYYY-MM-DD HH:MM`, intersected
across brokers), never by position. But the comparison was not limited to the
continuous session, so bars outside 09:15-15:14 were counted as "only other". Fixed: the script now compares only
09:15-15:14, counts the rest separately (`bars_outside_session`), and has a
label-alignment check (shift the other broker's labels by -2..+2 minutes and
see which agrees best with Kite).

Run 2026-10-01 for session ending 2026-09-30, five stocks, 7 days, vs Kite,
09:15-15:14 only. Close-equal % by label shift:

| Broker | -2 | -1 | **0** | +1 | +2 | O / H / L / C equal at 0 |
|---|---|---|---|---|---|---|
| Dhan | 7.0 | 10.4 | **68.1** | 10.4 | 6.8 | 61.0 / 80.4 / 74.0 / 68.1 % |

Dhan labels a bar by its **open** minute, the same as Kite, so there is no
whole-minute offset. (Corrected 2026-11-07: the disagreement isn't a different price source. Trades at
a minute boundary land in the neighbouring minute, both ways, with no net delay; see that entry.)
Outside the session: Dhan 0 bars, Kite 0.
Against the official daily candle (in-session bars only), the volume held is
66-98% for Kite and Dhan: below 100% is expected because the
daily figure includes the 15:15-15:30 closing auction.

## 2026-09-30: heatmap cold start, Dhan vs Kite (Groww not measurable)

`scripts/compare_heatmap_startup.py`, in session (market OPEN), tokens already
cached, brokers run one after another. Each stage is timed the way
`LiveMarketDataService` runs it on its first visit to a board. Seconds. Three
runs of the index board and two of the Nifty 50 board; the figures were stable
to about 0.1 s unless noted.

| Stage | Dhan | Kite |
|---|---|---|
| connect (auth) | 0.7 | 0.7 |
| resolve ids (local file) | 0.00 | 0.00 |
| previous close (REST) | 1.05-1.16 | 1.03-1.08 |
| REST price snapshot | 1.08-1.16 | 1.01-1.09 |
| **Board ready from REST** | **2.9-3.0** | 2.8 |
| Socket open | 0.2 | 0.15 |
| First websocket tick after open | 0.25 | 0.25 |
| Every instrument priced by socket | 0.25 | 0.25 |

(First-tick figures are quantised to the script's 0.25 s poll.)

Priced, indices board (17): Dhan 17/17, Kite 17/17. Nifty 50 board:
50/50 on both.

### Findings

- **The "about 3 seconds" on the index page is Dhan's two REST calls.** Each
  takes ~1.1 s because Dhan limits quote calls to 1/s, and Kite's
  take about the same. The socket
  itself is ready in 0.2 s on both, so the wait is the REST calls, not the
  websocket.
- **Dhan's socket failed once in five runs** (`timed out during opening
  handshake`, 10 s, index board). The service's reconnect logic covers this;
  it would show up as a longer amber REST phase.
- **Groww could not be timed.** Its API token is rejected ("does not have the
  required permissions") on this machine today. That is an account problem,
  not a timing result.

### Not measured

Streamlit's own overhead, a cold token mint (the script starts with tokens
cached), after-hours behaviour (previous close then comes from daily candles,
which the older notes put at ~13 s for Dhan for 50
stocks), and the time before the page's first paint. Re-run after 15:30 to
cover the after-hours path.

### Conclusion

Keep Dhan as the default: it serves all 17 indices and its socket is as fast as
Kite's. Its slower REST start is better fixed by starting the board early
(see the roadmap item "Instant NSE Sectoral Indices page").

---

## 2026-09-27 (later): Dhan 1-minute history and TOTP login

Adds Dhan to the entry below, whose Dhan column was left open. The setup was
the same: `scripts/compare_intraday_providers.py`, five stocks, windows ending
2026-09-25 15:30. Kite and Groww were re-measured in the same run,
and every number matched the earlier run exactly.

**Login.** A fresh `DHAN_ACCESS_TOKEN` was pasted, and TOTP token generation
was then tested:
- `POST auth.dhan.co/app/generateAccessToken` with the client ID, PIN and TOTP code.
- The first code was rejected as `Invalid TOTP`, returned as HTTP `200`, despite 5 s left in the window. A retry at the start of the next window returned a new 24-hour token.
- The pasted token kept working after the new one was made.
- Details in [PROVIDER_GUIDE.md](PROVIDER_GUIDE.md#dhan-token-generation-tested-2026-09-27).

**1-minute results.**

| | Dhan | Kite (for reference) |
|---|---|---|
| Widest window per call | **90 days** (64 sessions); 91 → `400` | 60 days |
| Seconds per call (60–90 days) | 0.9–1.0 | ~1.0 |
| RELIANCE bars per day | 360, 09:15–15:14 | 360, 09:15–15:14 |
| Bars in common with Kite (5 stocks × 6 days) | 10,795 of 10,800 | — |
| Equal to Kite: O / H / L / C / V | 61.4% / 82.2% / 76.1% / 69.9% / **12.2%** | — |
| First bar = official open | 25/30 | 30/30 |
| Minute bars reach official high / low | 27/30, 26/30 | 29/30, 27/30 |
| Minute volume as % of the day's | 44–99% | 45–99% |

**Findings.**
- **Dhan has the same session shape as Kite,** including the 15:15 end, and totals the same daily volume. But its individual bars differ (cause found 2026-11-07: trades at a minute boundary land in the neighbouring minute, with no net delay).
- **Kite is still the only broker whose minute bars reproduce the official daily open every time.**

**Decision unchanged:** Kite for 1-minute history. (Superseded 2026-11-07: the unattended choice for
1-minute bars is Groww, not Dhan; Dhan is the unattended choice for daily candles.)

---

## 2026-09-27: 1-minute history, Kite vs Groww (Dhan pending)

**Question.** Which broker should supply 60 days of 1-minute bars for the 210
F&O stocks, using the fewest requests and the least time, and is its data
right?

**Setup.**
- Run on Sunday 2026-09-27, 22:1x IST, market closed.
- Stocks: RELIANCE, TCS, HDFCBANK, INFY and SBIN. Windows end 2026-09-25 15:30.
- Re-run with `python scripts/compare_intraday_providers.py --out results.json`. The probe was run twice and gave the same numbers both times.
- Endpoints:
  - Kite: `GET /instruments/historical/{token}/minute`
  - Groww: SDK `get_historical_candles(..., "1minute")`
  - Dhan: `POST /v2/charts/intraday`
- **Dhan was not tested.** The saved token had expired on 2026-09-26 (`DH-901`), and `.env` has no Dhan TOTP secret to make a new one.

### Widest window one call accepts

| Window asked | Kite | Groww |
|---|---|---|
| 7 days | ✅ | ✅ |
| 30 days | ✅ | ✅ |
| 31 days | ✅ | ❌ `GA001` |
| 60 days | ✅ (44 sessions, 0.83 s) | ❌ |
| 61 / 90 days | ❌ `400` | ❌ |

### Cost of 60 days × 210 stocks

| | Stocks per call | Days per call | Calls for 1-min bars | Time |
|---|---|---|---|---|
| **Kite** | 1 | 60 | **210** | 355 s for the real backfill (it also fetched daily candles: 420 calls in all) |
| Groww | 1 | 30 | 420 | ~0.5 s per call, ~4 min (not run) |
| Dhan | 1 | ? (docs say 5 years available) | ? | untested |

### Data quality: 5 stocks × the last 7 days

Each column is the share of 1-minute bars whose open (O), high (H), low (L),
close (C) or volume (V) equals Kite's:

| | Bars in common | O | H | L | C | V |
|---|---|---|---|---|---|---|
| Groww | 10,800 | 47.5% | 95.5% | 96.1% | 99.2% | **99.8%** |

**Against the official daily candle** (Kite `/day`: 25 stock-days on the first
run, 30 on the re-run). Does the day's first minute bar open at the official
open, do the minute bars reach the official high and low, and what share of
the day's volume do they hold?

| | Open | High | Low | Minute volume as % of the day's |
|---|---|---|---|---|
| **Kite** | **30/30** | 29/30 | 27/30 | 45–99% (see below) |
| Groww | 1/30 | 13/30 | 11/30 | 93–100% |

**Shape of RELIANCE's day:**
- **Kite:** 360 bars, 09:15–15:14.
- **Groww:** 363–373 bars. It includes pre-open minutes 09:00–09:08, which carry volume but `None` prices, and post-close bars up to 15:59. Nothing between 15:16 and 15:29.

### Findings

- **Kite is the only broker whose minute bars agree with the official daily candle.** Its first bar opens at the official open on every day, and it has the widest window, so it costs the fewest calls.
- **Groww's volumes and closes are right, but its opens aren't.** Its opens differ from Kite's on half the bars, and its first bar almost never opens at the official open. It needs twice as many calls, and one call timed out (30 s read timeout; fine on retry).
- **The trading session changed in August 2026.** The full 210-stock backfill shows 375 bars a day up to the switch and 360 after it. 207 stocks switched on 3 Aug and 3 stocks on 26 Aug, and none went back. Details in [`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md).
- **Kite's minute volume can miss much of a day.** On 31 Aug 2026 the average stock's minute bars held only 74% of its daily volume, and some as little as 22%. On 18 Sep the average was 78%. That's volume traded outside the continuous session, so take a day's volume from the daily candle.
- **No broker tested offers historical bars under 1 minute.**

### Conclusion

**Decision:** Kite for 1-minute history, via `scripts/backfill_intraday.py`
into `data/market.db`. The first full run fetched 210 stocks × 41 sessions,
3.1M bars, in 355 s without a failure. Daily bars from the same run matched
the closes `update_fno_history.py` had already stored, on all 4,410 shared rows.

**Not covered:**
- **Dhan.** Re-run the script with a fresh `DHAN_ACCESS_TOKEN`; it includes Dhan automatically.
- Days older than 60 sessions.
- Whether the August session change comes from an NSE circular (not checked).
