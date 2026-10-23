# Provider comparison log

Dated, measured comparisons between broker APIs. Add new runs at the top and
never edit old ones. If a later run contradicts an earlier one, say so in the
new entry. Conclusions go into [`PROVIDER_GUIDE.md`](PROVIDER_GUIDE.md); this
file holds the evidence.

Re-run:

```bash
python scripts/kite_login.py                          # if today's Kite session is missing
python scripts/compare_indmoney_kite.py --out results.json         # daily data
python scripts/compare_intraday_providers.py --out results.json    # 1-minute data, all four brokers
python scripts/compare_heatmap_startup.py --out results.json       # heatmap cold start, both boards
```

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
continuous session, so bars outside 09:15-15:14 (INDmoney's invented flat bars
to 15:30) were counted as "only other". Fixed: the script now compares only
09:15-15:14, counts the rest separately (`bars_outside_session`), and has a
label-alignment check (shift the other broker's labels by -2..+2 minutes and
see which agrees best with Kite).

Run 2026-10-01 for session ending 2026-09-30, five stocks, 7 days, vs Kite,
09:15-15:14 only. Close-equal % by label shift:

| Broker | -2 | -1 | **0** | +1 | +2 | O / H / L / C equal at 0 |
|---|---|---|---|---|---|---|
| Dhan | 7.0 | 10.4 | **68.1** | 10.4 | 6.8 | 61.0 / 80.4 / 74.0 / 68.1 % |
| INDmoney | 6.2 | 9.8 | **67.8** | 9.7 | 6.3 | 60.1 / 78.8 / 73.0 / 67.8 % |

Both brokers label a bar by its **open** minute, the same as Kite, so there is no
time offset. The 20-40% disagreement is a genuine price-source difference
(e.g. RELIANCE 09:15 open: Kite and Dhan 1182.0, INDmoney 1184.2). Outside the
session: Dhan 0 bars, INDmoney 405 (15:15-15:30, flat, volume 0), Kite 0.
Against the official daily candle (in-session bars only), the volume held is
66-98% for Kite and Dhan, 45-96% for INDmoney: below 100% is expected because the
daily figure includes the 15:15-15:30 closing auction.

## 2026-09-30: heatmap cold start, Dhan vs INDmoney vs Kite (Groww not measurable)

`scripts/compare_heatmap_startup.py`, in session (market OPEN), tokens already
cached, brokers run one after another. Each stage is timed the way
`LiveMarketDataService` runs it on its first visit to a board. Seconds. Three
runs of the index board and two of the Nifty 50 board; the figures were stable
to about 0.1 s unless noted.

| Stage | Dhan | INDmoney | Kite |
|---|---|---|---|
| connect (auth) | 0.7 | 0.7 | 0.7 |
| resolve ids (local file) | 0.00 | 0.00 | 0.00 |
| previous close (REST) | 1.05-1.16 | **0.34-0.42** | 1.03-1.08 |
| REST price snapshot | 1.08-1.16 | **0.34-0.38** | 1.01-1.09 |
| **Board ready from REST** | **2.9-3.0** | **1.4-1.5** | 2.8 |
| Socket open | 0.2 | 0.2 | 0.15 |
| First websocket tick after open | 0.25 | 0.25 | 0.25 |
| Every instrument priced by socket | 0.25 | 1.0 (Nifty 50 only) | 0.25 |

(First-tick figures are quantised to the script's 0.25 s poll.)

Priced, indices board (17): Dhan 17/17, Kite 17/17, **INDmoney 16/17 on every
run** (Nifty Oil & Gas still not served, re-confirmed today). Nifty 50 board:
50/50 on all three.

### Findings

- **The "about 3 seconds" on the index page is Dhan's two REST calls.** Each
  takes ~1.1 s because Dhan limits quote calls to 1/s, and Kite's
  take about the same. INDmoney's take ~0.35 s each (5/s limit). The socket
  itself is ready in 0.2 s on all three, so the wait is the REST calls, not the
  websocket.
- **INDmoney is about twice as fast to a full board** (1.4-1.5 s vs 2.9-3.0 s),
  at the price of one index on the index board.
- **INDmoney's first REST price call sometimes returns a partial answer.** On
  the first run it priced 3 of 17 indices, then 16 of 17 on later runs. This is
  the known partial first response in `api/INDMONEY_API.md`; the service asks
  again for what is missing.
- **Dhan's socket failed once in five runs** (`timed out during opening
  handshake`, 10 s, index board). The service's reconnect logic covers this;
  it would show up as a longer amber REST phase.
- **Groww could not be timed.** Its API token is rejected ("does not have the
  required permissions") on this machine today. That is an account problem,
  not a timing result.

### Not measured

Streamlit's own overhead, a cold token mint (the script starts with tokens
cached), after-hours behaviour (previous close then comes from daily candles,
which the older notes put at ~5 s for INDmoney and ~13 s for Dhan for 50
stocks), and the time before the page's first paint. Re-run after 15:30 to
cover the after-hours path.

### Conclusion

Keep Dhan as the default: it serves all 17 indices and its socket is as fast as
the others. Its slower REST start is better fixed by starting the board early
(see the roadmap item "Instant NSE Sectoral Indices page") than by switching
brokers, which would cost the Oil & Gas tile. If the gap matters more than that
tile, INDmoney is the faster choice for the index board.

---

## 2026-09-27 (later): Dhan 1-minute history and TOTP login

Adds Dhan to the entry below, whose Dhan column was left open. The setup was
the same: `scripts/compare_intraday_providers.py`, five stocks, windows ending
2026-09-25 15:30. Kite, Groww and INDmoney were re-measured in the same run,
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
- **Dhan's bar times agree with Kite's, but its prices and volumes don't.** It has the same session shape, including the 15:15 end, and totals the same daily volume. But its individual bars differ.
- **Dhan and INDmoney disagree with Kite by almost exactly the same amounts.** INDmoney's O/H/L/C agreement with Kite was 60.9/81.5/75.8/70.6%. That suggests both aggregate bars differently from Kite, for example by where they cut each minute. They weren't compared with each other directly.
- **Kite is still the only broker whose minute bars reproduce the official daily open every time.**

**Decision unchanged:** Kite for 1-minute history. Dhan is the option for
depth beyond 60 days per call, and now for unattended jobs, since its TOTP
login works.

---

## 2026-09-27: 1-minute history, Kite vs Groww vs INDmoney (Dhan pending)

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
  - INDmoney: `GET /market/historical/1minute`
  - Dhan: `POST /v2/charts/intraday`
- **Dhan was not tested.** The saved token had expired on 2026-09-26 (`DH-901`), and `.env` has no Dhan TOTP secret to make a new one.
- The INDmoney token was minted from TOTP for this run. This PC's clock was 20 s behind INDmoney's server; the code was generated from server time.

### Widest window one call accepts

| Window asked | Kite | Groww | INDmoney |
|---|---|---|---|
| 7 days | ✅ | ✅ | ✅ |
| 30 days | ✅ | ✅ | only the last 7 days |
| 31 days | ✅ | ❌ `GA001` | only the last 7 days |
| 60 days | ✅ (44 sessions, 0.83 s) | ❌ | only the last 7 days |
| 61 / 90 days | ❌ `400` | ❌ | only the last 7 days, still `200` |

INDmoney always returns the 7 days before `end_time`, whatever window was
asked for. That matches its docs' warning that a wider request "returns the
maximum window, not an error".

### Cost of 60 days × 210 stocks

| | Stocks per call | Days per call | Calls for 1-min bars | Time |
|---|---|---|---|---|
| **Kite** | 1 | 60 | **210** | 355 s for the real backfill (it also fetched daily candles: 420 calls in all) |
| Groww | 1 | 30 | 420 | ~0.5 s per call, ~4 min (not run) |
| INDmoney | 5 | 7 | 378 (42 batches × 9 windows) | ~0.6 s per call, ~4 min (not run) |
| Dhan | 1 | ? (docs say 5 years available) | ? | untested |

### Data quality: 5 stocks × the last 7 days

Each column is the share of 1-minute bars whose open (O), high (H), low (L),
close (C) or volume (V) equals Kite's:

| | Bars in common | O | H | L | C | V |
|---|---|---|---|---|---|---|
| Groww | 10,800 | 47.5% | 95.5% | 96.1% | 99.2% | **99.8%** |
| INDmoney | 9,000 | 60.9% | 81.5% | 75.8% | 70.6% | **0.2%** |

INDmoney's timestamps aren't simply shifted: moving them a minute either way
made agreement worse (≈11–19%).

**Against the official daily candle** (Kite `/day`: 25 stock-days on the first
run, 30 on the re-run). Does the day's first minute bar open at the official
open, do the minute bars reach the official high and low, and what share of
the day's volume do they hold?

| | Open | High | Low | Minute volume as % of the day's |
|---|---|---|---|---|
| **Kite** | **30/30** | 29/30 | 27/30 | 45–99% (see below) |
| Groww | 1/30 | 13/30 | 11/30 | 93–100% |
| INDmoney | 3/25 | 21/25 | 19/25 | 49–107% |

**Shape of RELIANCE's day:**
- **Kite:** 360 bars, 09:15–15:14.
- **Groww:** 363–373 bars. It includes pre-open minutes 09:00–09:08, which carry volume but `None` prices, and post-close bars up to 15:59. Nothing between 15:16 and 15:29.
- **INDmoney:** 376 bars, 09:15–15:30.

### Findings

- **Kite is the only broker whose minute bars agree with the official daily candle.** Its first bar opens at the official open on every day, and it has the widest window, so it costs the fewest calls.
- **Groww's volumes and closes are right, but its opens aren't.** Its opens differ from Kite's on half the bars, and its first bar almost never opens at the official open. It needs twice as many calls, and one call timed out (30 s read timeout; fine on retry).
- **INDmoney's 1-minute data is unusable.** Volumes don't match anyone. It also returns bars from 15:16 to 15:30, a window in which Kite and Groww show no trades at all. Unlike its daily data (2026-09-25 entry below), this can't replace Kite.
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

---

## 2026-09-25: INDmoney vs Kite, daily data for the F&O universe

**Question.** Can INDmoney replace Kite as the first choice for the daily
open/close capture used for gaps and gainers/losers? INDmoney is free, can log
in without a person, and is faster. But its docs have been wrong before, so
it needed checking against Kite.

**Setup.**
- Run on 2026-09-25, 13:3x IST, market open.
- Universe: the 210 NSE F&O stocks in the `fno_universe` set in `data/market.db`.
- Window: daily candles from 2026-08-11 to 2026-09-24, which is 32 trading days. Today's candle was still forming, so it was left out.
- Kite: `GET /instruments/historical/{token}/day` (one stock per call) and `GET /quote/ohlc`.
- INDmoney: `GET /market/historical/1day` (5 stocks per call) and `GET /market/quotes/full`.
- Both read-only. INDmoney's token had been generated from TOTP that day.

### Results

| Check | Result |
|---|---|
| Instrument mapping | **210/210** stocks found on INDmoney. INDmoney's `SECURITY_ID` equals Kite's `exchange_token` (the NSE token) for all 210 |
| Trading days returned | 32 on both, with the same dates. Neither broker had a day the other lacked |
| Stock-days compared | **6,720** (210 × 32) |
| Open, high, low, close | **6,717 identical to the paisa.** 3 differ, all HINDPETRO (below) |
| Volume | **6,720/6,720 identical** |
| Snapshot, previous close (`ohlc.close` vs `prev_close`) | **210/210 identical** |
| Snapshot, today's open (`ohlc.open` vs `day_open`) | **210/210 identical** |
| Snapshot, last price | median difference 0.000%, 95th percentile 0.037%, max 0.062%. The two calls were ~0.4 s apart, so this is price movement, not error |
| Last stored candle close = snapshot previous close | Kite 210/210, INDmoney 205/205 on the first pass |
| Gap % (`open ÷ previous close − 1`), 6,355 pairs | Identical except **1**: HINDPETRO on 14 Aug |
| Top 10 and bottom 10 movers over 1, 3, 5, 7 and 20 days | **Identical lists** on every window |

### Cost and reliability

| | Kite | INDmoney |
|---|---|---|
| Candles for 210 stocks × 45 days | 213 calls, **174 s** | 42 calls, **23 s** |
| Errors during the run | 3 read timeouts from `api.kite.trade`, each fine on retry | 1 `403 TokenException` on one batch of 5 |
| Bulk snapshot, 210 stocks | 1 call, 0.36 s | 1 call, 0.53 s |

**The INDmoney 403 was transient.** The same token worked for every call
before and after it. Re-requesting that batch (BHARATFORG, BHARTIARTL, BHEL,
BIOCON, BLUESTARCO) returned `200`, and all 160 of its stock-days then
matched Kite exactly. So a single `TokenException` on INDmoney doesn't always
mean the token is dead. Retry once before generating a new token, because
generating one revokes the token every other process is using.
`scripts/compare_indmoney_kite.py` now retries it once.

### The one real difference: corporate-action adjustment

HINDPETRO, the four sessions before its 14 August ex-date:

| Date | Kite open / close | INDmoney open / close | Volume (both) |
|---|---|---|---|
| 2026-08-10 | 375.65 / 373.90 | 395.00 / 393.15 | 6,272,362 |
| 2026-08-13 | 373.50 / 373.65 | 392.75 / 392.90 | 9,450,914 |
| **2026-08-14** | 374.00 / 373.50 | 374.00 / 373.50 | 8,013,809 |
| 2026-08-17 onwards | identical | identical | identical |

- **Kite adjusts past prices; INDmoney keeps the raw exchange prices.** Kite scaled every price before the ex-date by about 0.951, and volume is unchanged. That looks like an adjustment for a large dividend or a similar corporate action, not a split, since a split would change volume too.
- **This affects gaps directly.** INDmoney shows HINDPETRO gapping **−4.8%** on 14 August, when the stock only lost its entitlement. Kite shows **+0.09%**.
- **Stored history ends up unadjusted with either broker.** A daily cron stores each day's candle as it is *that* day, and Kite only adjusts retroactively. So ex-dates show up as false gaps whichever broker the cron uses.
- **The fix is a re-fetch from Kite.** `update_fno_history.py --full --days N` re-fetches the adjusted window from Kite. See [`FNO_MOVERS.md`](FNO_MOVERS.md#known-limitations).

### Conclusion

**INDmoney's daily data matches Kite's.** Every open, high, low, close and
volume matched over 32 days and 210 stocks, and so did the live snapshot. The
only difference was Kite's corporate-action adjustment. INDmoney is also 7–8×
cheaper to fetch, free, and logs in without a person.

**Decision:**
- **Daily capture:** INDmoney first, Kite as fallback.
- **Backfills and repairs:** use Kite, whose history is corporate-action adjusted.

Mixing the two is safe: they differ only on pre-ex-date prices, and the Kite
re-fetch overwrites those anyway.

**Not covered by this run:**
- Stocks outside the F&O list.
- After-hours behaviour of `/quotes/full`.
- Any day on which INDmoney is down.
- Whether INDmoney ever publishes a day's candle later than Kite.

Re-run after 16:00 IST on a trading day to check those last two.
