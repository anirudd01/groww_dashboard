# Choosing a market-data provider

Which broker API to use for which job. Three are wired into this repo:
**Kite** (Zerodha), **Dhan** and **Groww**.

Read this before starting a feature that touches market data. It is a decision
guide, not a reference. The per-broker details live in:

| Broker | Detailed notes | Code |
| --- | --- | --- |
| Kite | [`api/KITE_API.md`](api/KITE_API.md), [`KITE_PROMPT.md`](KITE_PROMPT.md) | `market/providers/kite.py` |
| Dhan | [`SECTOR_HEATMAP.md`](SECTOR_HEATMAP.md), vendor docs [`dhan-api-docs.md`](dhan-api-docs.md) | `market/providers/dhan.py` |
| Groww | [`api/GROWW_API_LIVE_DATA.md`](api/GROWW_API_LIVE_DATA.md), [`api/GROWW_API_FEED.md`](api/GROWW_API_FEED.md), [`api/GROWW_API_PORTFOLIO.md`](api/GROWW_API_PORTFOLIO.md), [`api/GROWW_API_ORDERS.md`](api/GROWW_API_ORDERS.md), [`api/GROWW_API_INSTRUMENTS.md`](api/GROWW_API_INSTRUMENTS.md) | `market/providers/groww.py`, `groww_api/` |

What each broker's own spec lists that we do not use (checked 2026-10-01, including a Dhan gainers/losers endpoint) is in [`API_ENDPOINT_AUDIT.md`](API_ENDPOINT_AUDIT.md). Measured head-to-head runs are in [`PROVIDER_COMPARISON_LOG.md`](PROVIDER_COMPARISON_LOG.md). There is also a worked example of picking a provider in
[`FNO_MOVERS.md`](FNO_MOVERS.md#which-provider-measured-2026-09-25).

**How much to trust each claim.** Each one is marked:

- **✅ verified**: seen against the live API from this repo, with a date.
- **📄 docs**: the vendor docs say so, but it hasn't been tested here.

*Last updated 2026-11-07 (daily and 1-minute candles compared across Kite, Groww and Dhan: which provider for which field). 2026-10-18: Groww's paid data plan tested: prices, NSE candles, option chain and Greeks work; MCX has prices but no candles or Greeks). 2026-10-17: Groww's free API plan tested. Earlier: 2026-09-27, 1-minute history compared across the brokers; Dhan TOTP token generation verified.*

---

## Quick pick: which provider for which job

| Job | First choice | Second choice | Avoid | Why |
| --- | --- | --- | --- | --- |
| **Live streaming** (heatmaps, tickers) | **Dhan** | Kite | Groww | Dhan and Kite sockets connect in under 5 s and push ticks ✅. Groww's handshake takes 1–145 s and hides dropped connections ✅ |
| **Fastest heatmap cold start** | **Kite**, **Dhan** (full board from REST in ~2.8-3.0 s) | — | Groww | REST calls take ~1.1 s ✅ 2026-09-30. Dhan and Kite both serve all 17 indices. [log](PROVIDER_COMPARISON_LOG.md) |
| **End-of-day opens and closes for many stocks** (cron → store) | **Dhan** (logs in unattended) | Kite (needs a daily browser login) | Groww (its daily candle has no `open`, and its high/low/volume include pre-open and closing-session trades) | Dhan's daily candle equals Kite's on every field for 88/88 stock-days; the only differences are Kite's corporate-action adjustments, Dhan being raw ✅ 2026-11-07, [log](PROVIDER_COMPARISON_LOG.md); see [End-of-day capture](#end-of-day-capture-opens-closes-gaps-movers) |
| **Today's snapshot for up to 1,000 stocks in one call** | Kite, Dhan (both 1,000 per call) | — | Groww (50 per call) | ✅ 2026-09-25, [`FNO_MOVERS.md`](FNO_MOVERS.md) |
| **1-minute history** (backfill of intraday bars) | **Kite** (all fields) | **Groww** for close and volume, unattended | Dhan | Kite: 60 days per call; its bars reproduce the official daily open, high and low ✅. Groww: 30 days per call; vs Kite, close 99.3% and volume 99.8% equal, high/low ~96%, open only 61% - a convention, not an error: Kite's 09:15 open is the pre-open price (Groww keeps it in a 09:08 bar), and on ~40% of minutes Kite's open repeats the previous close where Groww uses the minute's first trade. Labels line up exactly. Take the day's official open from Groww's pre-open bar or Dhan's daily candle. Keep the pre-open and 15:15–15:59 bars out of `minute_bars` ✅. Dhan: 90 days per call, official open in its 09:15 bar, labels aligned and no net delay, but trades at a minute boundary land in the neighbouring minute, so close is 62.5% and volume 13.7% exactly equal (volume off by a median 0.4%) ✅. 2026-11-07, [log](PROVIDER_COMPARISON_LOG.md), store in [`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md) |
| **Pre-open and closing auction bars** | **Groww** (only source) | — | — | Groww sends 09:00–09:08 (volume only) and 15:15–15:59; Kite and Dhan send nothing outside 09:15–15:14 ✅ 2026-11-07 |
| **Historical backfill** (months or years of daily candles) | **Kite** (its history is corporate-action adjusted ✅) | Dhan | — | Kite: up to 2000 days per call (5 years in one call per stock; 7 years returns 400) ✅ 2026-10-23, 3 req/s, continuous futures ✅. Kite adjusts for splits, bonuses and large dividends, not demergers; Dhan's candles are the raw traded prices ✅ 2026-10-23, see [DROP_FROM_HIGH.md](DROP_FROM_HIGH.md#checked-against-dhan-2026-10-23). Dhan: 5 years intraday 📄. |
| **Option chain / Greeks** | **Dhan** or **Groww** | — | Kite | Dhan and Groww both return a chain with Greeks 📄. Groww's work for NSE ✅ 2026-10-18 but **not for MCX** (no chain, `get_greeks` errors) ✅. Kite has no chain API; you'd assemble it from quotes and calculate Greeks yourself 📄 |
| **MCX commodities** | **Dhan** (Kite as fallback) | Groww (positions and prices; no MCX candles ✅ 2026-10-18) | — | Dhan and Kite returned identical MCX prices, OHLC and OI ✅ 2026-10-03. Dhan leads because it needs no morning login and keeps volume after the close; the MCX Futures page falls back to Kite. See [MCX on Dhan and Kite](#mcx-on-dhan-and-kite-tested-2026-10-03). |
| **Portfolio / positions** | **Groww** (the existing dashboards use it) | Kite, Dhan | — | Groww's positions, holdings and margins work on its free API plan ✅ 2026-10-17; with the paid data plan F&O and MCX positions are priced, MCX in batches of 50 ✅ 2026-10-18. |
| **Unattended jobs** (no one at the machine) | **Groww** or **Dhan** | — | Kite | Both mint tokens from a stored TOTP secret: Groww ✅ 2026-09-25, Dhan ✅ 2026-09-27. Kite always needs a browser login |

---

## Ratings

Scores run from 1 (poor) to 5 (best), for the uses in this repo.

| | Kite | Dhan | Groww |
| --- | :-: | :-: | :-: |
| Live streaming | 5 ✅ | 5 ✅ | 2 ✅ |
| Bulk snapshot (many stocks, one call) | 5 ✅ | 5 ✅ | 2 ✅ |
| Daily candles / backfill | 5 ✅ (adjusted) | 4 ✅ | 3 ✅ (no `open`) |
| 1-minute history (per-call window, quality) | 5 ✅ (60 days, matches official OHLC) | 3 ✅ (90 days; prices and volumes differ from Kite) | 3 ✅ (30 days, opens differ) |
| Option chain + Greeks | 1 📄 | 5 📄 | 4 📄 |
| MCX commodities | 5 ✅ | 5 ✅ | 3 (positions used by `apps/fno_dashboard.py`) |
| Unattended auth | 1 ✅ | 5 ✅ | 5 ✅ |
| Doc accuracy | 5 | 3 | 2 |
| Cost of data | paid | paid | paid |
| **Overall maturity** | **5** | **4** | **3** |

---

## Provider cards

### Kite (Zerodha Kite Connect)

- **Strengths:**
  - The most mature API, v3 for years ✅.
  - Clean, consistent docs.
  - 1,000 instruments per LTP/OHLC call ✅.
  - Daily candles up to 2000 days per call: 5 years of a stock in one request ✅ 2026-10-23.
  - A binary socket that went live in about 4 s ✅.
  - Covers NSE, BSE and MCX.
  - Public instrument dump that needs no login ✅.
- **Weaknesses:**
  - **The token dies at 06:00 IST every day.** Only a browser login makes a new one (`python scripts/kite_login.py`). Nothing can refresh it and nothing can automate it legitimately.
  - No option-chain endpoint.
  - Quotes are limited to 1 req/s, candles to 3 req/s and one instrument per call ✅.
  - 1-minute candles: **at most 60 days per call** (a 61-day window returns `400`) ✅ 2026-09-27. No sub-minute history.
  - Daily history is **adjusted for large dividends** as well as splits and bonuses, so an old high reads lower than the price that traded (INFY's 3 Feb 2026 high: Kite 1691.4, Dhan 1728.0; ITC −4.7%). 45 of 50 Nifty 50 stocks were unaffected over 52 weeks ✅ 2026-10-23. Demergers are **not** adjusted (VEDL, 30 Apr 2026).
- **Gotchas:**
  - `instrument_token` is **not** the NSE token (RELIANCE is `738561` on Kite and `2885` on NSE) ✅.
  - During market hours, `ohlc.close` is the **previous** close ✅. What it means after 15:30 hasn't been verified.
- **Use for:** backfills (daily and 1-minute), end-of-day capture on days you log in, MCX, streaming. Not for anything that must run without a person.

### Dhan (DhanHQ v2)

- **Strengths:**
  - The widest feature set: option chain with Greeks, expired-options data with IV and OI, 5 years of intraday history, and 20/200-level depth 📄.
  - Its socket connected in 0.17 s ✅.
  - **Trade history with charges and the ledger by API** (`/v2/trades/{from}/{to}/{page}`, `/v2/ledger`) ✅ 2026-10-18,
    no Data API plan needed. They feed the Trade Journal ([`DHAN_JOURNAL.md`](DHAN_JOURNAL.md)); Groww has no equivalent.
  - Data API plan active on this account since 2026-10-18 (valid to 2026-11-19) ✅.
  - The public instrument master needs no login ✅.
  - It's the default live provider for the heatmap.
  - It has a sandbox (`sandbox.dhan.co`) for orders, portfolio, funds and historical candles, but not live quotes or the socket 📄. Its token comes from Dhan Cloud (`cloud.dhanhq.co`, formerly the developer portal `developer.dhanhq.co`) 📄.
- **Weaknesses:**
  - **The access token lasts 24 hours.** The *API key and secret* last 12 months, but a login made with them needs a browser and still produces a 24-hour token. The TOTP route below makes a new 24-hour token with no browser.
  - Headless login needs TOTP. The **Setup TOTP** option couldn't be clicked on 2026-09-25, but TOTP was set up and verified working on 2026-09-27. See [Dhan token generation](#dhan-token-generation-tested-2026-09-27).
  - `GET /v2/RenewToken` claims to extend a *still-valid* token by 24 hours 📄. That would allow a daily renew cron without TOTP, but it hasn't been tested.
  - Daily limits: since the 2026-10-09 docs export both rate-limit tables agree on **Order APIs 100,000 a day and Data APIs 7,000 a day** (5 req/s) 📄. Earlier exports swapped the two, and the v2.2 release note still says 1,00,000 daily Data API requests, so treat 7,000 as the safe figure. Option chain: 1 request per 3 s *and* at most 10 unique underlyings per 8 s 📄.
  - Quotes are limited to 1 req/s per client id ✅. Daily candles are one symbol per call ✅.
- **1-minute history** ✅ 2026-09-27, [log](PROVIDER_COMPARISON_LOG.md):
  - **At most 90 days per call** (91 returns `400`), about 1 s per call. Documented since the 2026-10-09 export 📄.
  - Intervals are 1, 5, 15, **25** and 60 minutes; the 2026-10-09 export replaced 30 with 25 📄.
  - Same bar times as Kite (09:15–15:14).
  - Against Kite: opens match on 61% of bars, closes on 70%, volumes on only 12%.
  - Its first bar opened at the official open on 25 of 30 stock-days (Kite: 30/30).
  - Use it for depth beyond 60 days, not as the reference.
- **Use for:** live streaming, option chains, deep history, unattended jobs (TOTP below).

#### Dhan token generation (tested 2026-09-27)

| Finding | Result |
| --- | --- |
| Endpoint | `POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=..&pin=..&totp=..`, with no headers and no body ✅ |
| What it needs | Client ID + the 6-digit Dhan PIN + a TOTP code. The Client ID is inside every access token (`dhanClientId` claim), so an expired token is enough to recover it ✅ |
| Success response | `200` with `accessToken`, `expiryTime` (24 h after generation, IST, no zone), `dhanClientId`, `dhanClientName`, `dhanClientUcc`, `givenPowerOfAttorney` ✅ |
| Failure response | **Also `200`**, with `{"status": "error", "message": "Invalid TOTP"}`. Check the body, not the status code ✅ |
| Old token after a new one is made | **Still valid.** Generating a token didn't revoke the previous one (checked immediately after) ✅ |
| First attempt | Rejected as `Invalid TOTP` with 5 s left in the window, when the clock correction came from an HTTP `Date` header (±1 s). With the NTP-corrected clock (2026-09-28), the first code was accepted and a new token took 1.6 s. A rejection is still retried once, in the next window, after re-measuring the clock. How many failures trigger a lockout isn't documented |

`.env` variables: `DHAN_CLIENT_ID`, `DHAN_PIN` (6 digits; `DHAN_MPIN` also accepted) and `DHAN_TOTP_SECRET` (base32, 32 characters; `DHAN_TOPT_SECRET` also accepted). **No access token goes in `.env`.** [`market/providers/dhan_session.py`](../market/providers/dhan_session.py) mints one, keeps it in the shared database (`data/market.db`, git-ignored) and shares it across processes under a lock (a lease row in the database). It replaces the token an hour before expiry, or when Dhan rejects it. Codes come from the NTP-corrected clock (`market/clock_offset.py`), and a rejection is retried once in the next window. Verified end to end: with no session file, `DhanProvider().connect()` minted a token on the first code in 17.5 s on 2026-09-27, when it still waited for a fresh window. With the clock correction it took **1.6 s** on 2026-09-28.

**Clock drift breaks TOTP quietly.** This PC's clock is **21.0 s slow**. Three NTP servers agreed within 10 ms on 2026-09-28; the HTTP `Date` headers measured on 2026-09-25 said "about 16–20 s", because they only have 1-second resolution. That's enough to produce a wrong code. **Every TOTP code in this repo must come from `market.clock_offset.totp_code(secret)`**, never from `pyotp.TOTP(...).now()`. It measures the offset by NTP once per process (falling back to HTTP `Date`, then the saved value), saves it to the git-ignored the `clock_offset` row of `data/market.db`, and waits at most 3 s, only in a window's last seconds. Dhan and both Groww clients use it. Syncing the Windows clock (`w32tm /resync`, as admin) is still worth doing.

#### MCX on Dhan and Kite (tested 2026-10-03)

Tested on a Saturday, so the values are the last session's (Thursday 1 Oct; MCX was shut on 2 Oct). Six contracts were checked
side by side: GOLD DEC, SILVER DEC, CRUDEOIL OCT, NATURALGAS OCT, COPPER OCT and STEELREBAR OCT. Used by the MCX Futures page
([`MCX_FUTURES.md`](MCX_FUTURES.md)).

| Surface | Dhan | Kite |
| --- | --- | --- |
| Contract list | ✅ public master: 164 `FUTCOM` rows, 28 commodities (`EXCH_ID=MCX`) | ✅ public `/instruments/MCX` (1.3 MB): 170 `FUT` rows, 30 names. All 164 Dhan contracts matched on commodity + expiry |
| Quote | ✅ `/marketfeed/quote` with `MCX_COMM`, all ~160 live contracts in one call | ✅ `/quote` with `MCX:CRUDEOIL26OCTFUT` keys |
| Last price, OHLC, OI | Identical on both, to the paisa | Identical |
| `ohlc.close` | The **previous** session's close, still so on Saturday | Same |
| Volume after the close | ✅ the session's volume | ❌ `0` (and `net_change` `0`) |
| Untraded contract | `last_trade_time` `01/01/1980` | `1970-01-01 05:30:00` |
| Minute candles + OI | ✅ `/charts/intraday`, `oi: true` | ✅ `/instruments/historical/{token}/15minute?oi=1`. Same last bar as Dhan |
| Daily candles | Continuous series: a year back for CRUDEOIL OCT, OI drops at each roll | Contract's own history only (from listing, 21 Apr 2026) unless `continuous=1` |
| Daily close | 8,916 for CRUDEOIL OCT on 1 Oct, against a last trade of 9,008 | Same 8,916, so it is MCX's daily close, not a Dhan quirk |

Liquidity does not follow the calendar: GOLD OCT (expiring 5 Oct) carried 169 lots of OI against 15,955 on GOLD DEC. Pick the
contract by open interest, not by nearest expiry.

### Groww

**Paid data plan since 2026-10-18** ✅: quotes, LTP and OHLC for CASH, FNO and MCX, NSE candles, the NSE option
chain and NSE Greeks all answer, about 0.35 s per call. **MCX gets prices only:** no candles (an empty answer) and
no option chain or Greeks ([`api/GROWW_API_LIVE_DATA.md`](api/GROWW_API_LIVE_DATA.md)). On the free plan
(2026-10-17) only the account side worked: login, profile, margins, holdings, positions, orders, smart-order lists,
the margin calculator and the instrument list. No API gives order history beyond today or a P&L report
([`api/GROWW_API_ORDERS.md`](api/GROWW_API_ORDERS.md)). Results and open checks:
[`GROWW_PAID_PLAN_CHECKS.md`](GROWW_PAID_PLAN_CHECKS.md).

- **Strengths:**
  - **TOTP login is fully automatic** (`GROWW_TOTP_SECRET`), like Dhan's ✅.
  - The existing portfolio and F&O dashboards use it, including commodity positions.
  - Its past closes were identical to Kite's ✅.
  - NSE option chain and Greeks ✅ 2026-10-18, and GTT/OCO smart orders (stop-loss and target that can last past a day) 📄.
  - Batched LTP works for MCX too (`MCX_<symbol>`, 50 per call) ✅ 2026-10-18.
- **Weaknesses:**
  - 50 instruments per LTP/OHLC call ✅.
  - Daily candles have `open = None`, so **you can't compute gaps from Groww candles** ✅ (still so 2026-10-18).
  - **No MCX candles, MCX option chain or MCX Greeks** ✅ 2026-10-18. `get_quote`'s `market_cap` is `None` ✅.
  - A position's `net_price` is not the open quantity's cost after a partial exit; derive it from the fills and
    `realised_pnl` ✅ 2026-10-18 ([`api/GROWW_API_PORTFOLIO.md`](api/GROWW_API_PORTFOLIO.md)).
  - Rate limits: 10 market-data calls per second (300 a minute), 10 orders per second, 150 tokens a day 📄
    (about 0.4 s per candle call measured).
  - Units differ from the docs ✅ 2026-10-17: MCX tick sizes in the instrument list are in paise, commodity margins
    in paise, and "used" margins are negative ([`api/GROWW_API_INSTRUMENTS.md`](api/GROWW_API_INSTRUMENTS.md),
    [`api/GROWW_API_PORTFOLIO.md`](api/GROWW_API_PORTFOLIO.md#margins)).
  - 1-minute history ✅ 2026-09-27:
    - **At most 30 days per call.** A 31-day request fails with `GA001`.
    - Volumes match Kite's on 99.8% of bars and closes on 99.2%, but **opens on only ~48%**.
    - Its minute bars don't reproduce the official daily open.
    - It includes pre-open minutes (09:00–09:08) that have volume but `None` prices, plus post-close bars up to 15:59.
    - One call hit a 30 s read timeout and was fine on retry.
  - The socket is the weakest of the four ✅:
    - Slow, retrying handshake.
    - `get_ltp()` returns a buffer that never empties, so an old price looks live.
    - No signal when the connection drops.
    - No `close()`, so connections leak.
    - No MCX stream: the SDK's LTP and depth topics accept CASH and FNO only.

    See [`api/GROWW_API_FEED.md`](api/GROWW_API_FEED.md).
  - Restarting repeatedly triggers REST throttling.
- **Use for:** portfolio and positions, and unattended jobs that only need closes. Not for live streaming or gap calculations.

---

## End-of-day capture (opens, closes, gaps, movers)

The goal is to store daily open and close for about 500 instruments, then work out gap-ups and gap-downs and the top gainers and losers over any window.

1. **Store daily candles, not rankings.** One row per stock per day: `date,symbol,open,high,low,close,volume`. Every ranking, gap or custom window is calculated when read.
   - The `daily_bars` table in `data/market.db` already uses this layout. Extend it and `scripts/kite.py history` rather than starting a second store.
   - It is all SQLite: at 500 stocks × 250 days that is about 125k rows, and the intraday bars sit in the same file: [`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md).
2. **Formulas.**
   - `gap % = open(d) / close(d-1) - 1`
   - `move over window = close(end) / close(start) - 1`

   `d-1` is the previous row *in the file* for that symbol, which skips holidays automatically.
3. **Which provider for the cron job:**

| Provider | Cost for 500 stocks, one day | Cost for a 1-year backfill | Has `open`? | Unattended? |
| --- | --- | --- | --- | --- |
| Kite | 1 `quote/ohlc` call in session; after close, ~500 candle calls ≈ 3 min | ~500 calls ≈ 3 min | yes | **no** (needs that morning's login) |
| Dhan | 1 `marketfeed/ohlc` call; candles ~500 calls at ≤5/s | ~500 calls | yes | **yes** ✅ (TOTP, 2026-09-27) |
| Groww | 10 calls (50 per call) | ~500 calls ≈ 3.5 min | **no** | **yes** |

   **Recommendation:** run the cron after 16:00 IST with **Dhan**: it logs in without a person, and its daily candles equal Kite's field for field (2026-11-07, [comparison log](PROVIDER_COMPARISON_LOG.md)). The one difference is the price basis: Kite adjusts past prices for corporate actions and Dhan doesn't, so don't mix the two in one stock's history. Groww can't supply `open`, so it can't do gaps.

- On a missed day, the next run backfills from candles. Candles cost one request per stock (Kite and Dhan) no matter how many days they cover, so catching up costs the same as a single day.
- **Corporate actions:** Dhan returns raw exchange prices (✅ 2026-10-23), while Kite adjusts past prices after an ex-date. Rows a daily cron stores are unadjusted with either broker, so repair a window with Kite (`scripts/kite.py history --full --history-days N`). See [Known limitations](FNO_MOVERS.md#known-limitations).

1. **The WebSocket doesn't help here.** It streams live ticks and carries no history. Use it only for live boards.
2. **Instrument ids come from files, never runtime lookups.** Each broker's ids are generated into `data/` by a script under `scripts/`.

---

## Keeping this file honest

- When you verify a 📄 claim, mark it ✅ with the date. When a ✅ claim stops being true, fix it.
- Dhan: `RenewToken` is still untested. TOTP generation already makes it unnecessary.
- Keep each broker's details in its own page under [`api/`](api/). This page holds the conclusions only.
