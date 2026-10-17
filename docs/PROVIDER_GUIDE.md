# Choosing a market-data provider

Which broker API to use for which job. Four are wired into this repo:
**Kite** (Zerodha), **Dhan**, **INDmoney** (API brand: INDstocks) and **Groww**.

Read this before starting a feature that touches market data. It is a decision
guide, not a reference. The per-broker details live in:

| Broker | Detailed notes | Code |
| --- | --- | --- |
| Kite | [`api/KITE_API.md`](api/KITE_API.md), [`KITE_PROMPT.md`](KITE_PROMPT.md) | `market/providers/kite.py` |
| Dhan | [`SECTOR_HEATMAP.md`](SECTOR_HEATMAP.md), vendor docs [`dhan-api-docs.md`](dhan-api-docs.md) | `market/providers/dhan.py` |
| INDmoney | [`api/INDMONEY_API.md`](api/INDMONEY_API.md), vendor docs [`indstocks-api-docs.md`](indstocks-api-docs.md) | `market/providers/indmoney.py` |
| Groww | [`api/GROWW_API_LIVE_DATA.md`](api/GROWW_API_LIVE_DATA.md), [`api/GROWW_API_FEED.md`](api/GROWW_API_FEED.md), [`api/GROWW_API_PORTFOLIO.md`](api/GROWW_API_PORTFOLIO.md), [`api/GROWW_API_ORDERS.md`](api/GROWW_API_ORDERS.md), [`api/GROWW_API_INSTRUMENTS.md`](api/GROWW_API_INSTRUMENTS.md) | `market/providers/groww.py`, `groww_api/` |

What each broker's own spec lists that we do not use (checked 2026-10-01, including a Dhan gainers/losers endpoint) is in [`API_ENDPOINT_AUDIT.md`](API_ENDPOINT_AUDIT.md). Measured head-to-head runs are in [`PROVIDER_COMPARISON_LOG.md`](PROVIDER_COMPARISON_LOG.md). There is also a worked example of picking a provider in
[`FNO_MOVERS.md`](FNO_MOVERS.md#which-provider-measured-2026-09-25).

**How much to trust each claim.** Each one is marked:

- **✅ verified**: seen against the live API from this repo, with a date.
- **📄 docs**: the vendor docs say so, but it hasn't been tested here.

INDmoney's docs are wrong in several places (see its section), so treat its 📄 claims with the most caution. The vendor mirror [`indstocks-api-docs.md`](indstocks-api-docs.md) has had its proven-wrong passages corrected or cut, marked `[pulse_tester]`.

*Last updated 2026-10-17 (INDmoney MCX quotes retested against Kite; Groww's free API plan tested: account and orders work, market data refused). Earlier: 2026-09-27, 1-minute history compared across all four brokers; Dhan TOTP token generation verified.*

---

## Quick pick: which provider for which job

| Job | First choice | Second choice | Avoid | Why |
| --- | --- | --- | --- | --- |
| **Live streaming** (heatmaps, tickers) | **Dhan** | Kite, INDmoney | Groww | Dhan and Kite sockets connect in under 5 s and push ticks ✅. INDmoney matched Dhan's tick rate ✅. Groww's handshake takes 1–145 s and hides dropped connections ✅ |
| **Fastest heatmap cold start** | **INDmoney** (full board from REST in ~1.4 s) | Kite, Dhan (~2.8-3.0 s) | Groww | INDmoney REST calls take ~0.35 s against ~1.1 s for the others ✅ 2026-09-30, but it serves 16 of 17 indices (no Oil & Gas). Dhan is still the pick when you need all 17. [log](PROVIDER_COMPARISON_LOG.md) |
| **End-of-day opens and closes for many stocks** (cron → store) | **INDmoney** | Kite | Groww (its daily candles have no `open`) | INDmoney matched Kite on 6,717 of 6,720 stock-days and was 7–8× faster ✅ 2026-09-25, [log](PROVIDER_COMPARISON_LOG.md) |
| **Today's snapshot for up to 1,000 stocks in one call** | Kite, Dhan, INDmoney (all 1,000 per call) | — | Groww (50 per call) | ✅ 2026-09-25, [`FNO_MOVERS.md`](FNO_MOVERS.md) |
| **1-minute history** (backfill of intraday bars) | **Kite** | Dhan (90 days per call) | INDmoney | Dhan: 90 days per call, but its prices differ from Kite's on 20–40% of bars and its volume on 88% ✅. Kite: 60 days per call and one call per stock. Its bars reproduce the official daily open, high and low ✅. Groww: 30 days per call, and its opens differ from Kite's on half the bars ✅. INDmoney: 7 days per call, volumes that don't match anyone, and invented flat bars after 15:15 ✅. 2026-09-27, [log](PROVIDER_COMPARISON_LOG.md), store in [`INTRADAY_HISTORY.md`](INTRADAY_HISTORY.md) |
| **Historical backfill** (months or years of daily candles) | **Kite** (its history is corporate-action adjusted ✅) | Dhan | — | Kite: any range, 3 req/s, continuous futures ✅. Dhan: 5 years intraday 📄. INDmoney: 5 symbols per call, but one call covers at most 1 year of daily data 📄 |
| **Option chain / Greeks** | **Dhan** or **Groww** | INDmoney | Kite | Dhan, Groww and INDmoney all return a chain with Greeks 📄. Kite has no chain API; you'd assemble it from quotes and calculate Greeks yourself 📄 |
| **MCX commodities** | **Dhan** (Kite as fallback) | Groww (positions) | **INDmoney** | Dhan and Kite returned identical MCX prices, OHLC and OI ✅ 2026-10-03. Dhan leads because it needs no morning login and keeps volume after the close; the MCX Futures page falls back to Kite. See [MCX on Dhan and Kite](#mcx-on-dhan-and-kite-tested-2026-10-03). INDmoney now prices MCX on REST, identical to Kite, but has no candles, no last-trade time and 19 of 28 commodities ✅ 2026-10-17, see [MCX on INDmoney](#mcx-on-indmoney-retested-2026-10-17) |
| **Portfolio / positions** | **Groww** (the existing dashboards use it) | Kite, Dhan | INDmoney for F&O | Groww's positions, holdings and margins work on its free API plan ✅ 2026-10-17, but pricing them needs its paid data plan. This account's INDmoney profile says F&O is not activated ✅ |
| **Unattended jobs** (no one at the machine) | **Groww**, **INDmoney** or **Dhan** | — | Kite | All three mint tokens from a stored TOTP secret: Groww and INDmoney ✅ 2026-09-25, Dhan ✅ 2026-09-27. Kite always needs a browser login |
| **Free market data** | **INDmoney** | — | — | Kite, Dhan and Groww all charge for data APIs. Groww's free plan refuses every price, candle, option-chain and Greeks call ✅ 2026-10-17 |

---

## Ratings

Scores run from 1 (poor) to 5 (best), for the uses in this repo.

| | Kite | Dhan | INDmoney | Groww |
| --- | :-: | :-: | :-: | :-: |
| Live streaming | 5 ✅ | 5 ✅ | 4 ✅ | 2 ✅ |
| Bulk snapshot (many stocks, one call) | 5 ✅ | 5 ✅ | 5 ✅ | 2 ✅ |
| Daily candles / backfill | 5 ✅ (adjusted) | 4 ✅ | 4 ✅ (raw, matches Kite) | 3 ✅ (no `open`) |
| 1-minute history (per-call window, quality) | 5 ✅ (60 days, matches official OHLC) | 3 ✅ (90 days; prices and volumes differ from Kite) | 1 ✅ (7 days, volumes wrong) | 3 ✅ (30 days, opens differ) |
| Option chain + Greeks | 1 📄 | 5 📄 | 4 📄 | 4 📄 |
| MCX commodities | 5 ✅ | 5 ✅ | 3 ✅ (quotes only, 19 of 28 commodities, no candles) | 3 (positions used by `apps/fno_dashboard.py`) |
| Unattended auth | 1 ✅ | 5 ✅ | 5 ✅ | 5 ✅ |
| Doc accuracy | 5 | 3 | 2 | 2 |
| Cost of data | paid | paid | **free** | paid |
| **Overall maturity** | **5** | **4** | **2** | **3** |

---

## Provider cards

### Kite (Zerodha Kite Connect)

- **Strengths:**
  - The most mature API, v3 for years ✅.
  - Clean, consistent docs.
  - 1,000 instruments per LTP/OHLC call ✅.
  - Daily candles for any range ✅.
  - A binary socket that went live in about 4 s ✅.
  - Covers NSE, BSE and MCX.
  - Public instrument dump that needs no login ✅.
- **Weaknesses:**
  - **The token dies at 06:00 IST every day.** Only a browser login makes a new one (`python scripts/kite_login.py`). Nothing can refresh it and nothing can automate it legitimately.
  - No option-chain endpoint.
  - Quotes are limited to 1 req/s, candles to 3 req/s and one instrument per call ✅.
  - 1-minute candles: **at most 60 days per call** (a 61-day window returns `400`) ✅ 2026-09-27. No sub-minute history.
- **Gotchas:**
  - `instrument_token` is **not** the NSE token (RELIANCE is `738561` on Kite and `2885` on NSE) ✅.
  - During market hours, `ohlc.close` is the **previous** close ✅. What it means after 15:30 hasn't been verified.
- **Use for:** backfills (daily and 1-minute), end-of-day capture on days you log in, MCX, streaming. Not for anything that must run without a person.

### Dhan (DhanHQ v2)

- **Strengths:**
  - The widest feature set: option chain with Greeks, expired-options data with IV and OI, 5 years of intraday history, and 20/200-level depth 📄.
  - Its socket connected in 0.17 s ✅.
  - The public instrument master needs no login ✅.
  - It's the default live provider for the heatmap.
  - It has a sandbox (`sandbox.dhan.co`) for orders, portfolio, funds and historical candles, but not live quotes or the socket 📄.
- **Weaknesses:**
  - **The access token lasts 24 hours.** The *API key and secret* last 12 months, but a login made with them needs a browser and still produces a 24-hour token. The TOTP route below makes a new 24-hour token with no browser.
  - Headless login needs TOTP. The **Setup TOTP** option couldn't be clicked on 2026-09-25, but TOTP was set up and verified working on 2026-09-27. See [Dhan token generation](#dhan-token-generation-tested-2026-09-27).
  - `GET /v2/RenewToken` claims to extend a *still-valid* token by 24 hours 📄. That would allow a daily renew cron without TOTP, but it hasn't been tested.
  - The vendor docs contradict themselves: the two rate-limit tables swap the 7,000 and 100,000 daily limits.
  - Quotes are limited to 1 req/s per client id ✅. Daily candles are one symbol per call ✅.
- **1-minute history** ✅ 2026-09-27, [log](PROVIDER_COMPARISON_LOG.md):
  - **At most 90 days per call** (91 returns `400`), about 1 s per call.
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
| Old token after a new one is made | **Still valid.** Unlike INDmoney, generating a token didn't revoke the previous one (checked immediately after) ✅ |
| First attempt | Rejected as `Invalid TOTP` with 5 s left in the window, when the clock correction came from an HTTP `Date` header (±1 s). With the NTP-corrected clock (2026-09-28), the first code was accepted and a new token took 1.6 s. A rejection is still retried once, in the next window, after re-measuring the clock. How many failures trigger a lockout isn't documented |

`.env` variables: `DHAN_CLIENT_ID`, `DHAN_PIN` (6 digits; `DHAN_MPIN` also accepted) and `DHAN_TOTP_SECRET` (base32, 32 characters; `DHAN_TOPT_SECRET` also accepted). **No access token goes in `.env`.** [`market/providers/dhan_session.py`](../market/providers/dhan_session.py) mints one, keeps it in the shared database (`data/market.db`, git-ignored) and shares it across processes under a lock (a lease row in the database). It replaces the token an hour before expiry, or when Dhan rejects it. Codes come from the NTP-corrected clock (`market/clock_offset.py`), and a rejection is retried once in the next window. Verified end to end: with no session file, `DhanProvider().connect()` minted a token on the first code in 17.5 s on 2026-09-27, when it still waited for a fresh window. With the clock correction it took **1.6 s** on 2026-09-28.

### INDmoney (INDstocks)

- **Strengths:**
  - **Free market data.**
  - 1,000 instruments per quote call, and `quotes/full` returns `day_open` and `prev_close` together ✅.
  - 5 requests per second.
  - Daily candles take **5 symbols per call**, so the Nifty 50 takes about 5 s ✅.
  - JSON socket with the same tick rate as Dhan ✅.
  - Headless login works ✅ 2026-09-25: `POST /generate/token` with the Client ID, MPIN and a TOTP code made from the stored secret. See [INDmoney token generation](#indmoney-token-generation-tested-2026-09-25).
- **Weaknesses:**
  - **The docs can't be trusted as written.** Checked live:
    - The index prefix is wrong in the docs.
    - Socket frames arrive JSON-encoded twice.
    - Quote-mode `close` is the live price, not the previous close.
    - One bad code makes the whole batch fail.
    - The changelog claims features that don't exist.

    See [`api/INDMONEY_API.md`](api/INDMONEY_API.md).
  - No sandbox. Nifty Oil & Gas returns no data ✅.
  - **1-minute history is unusable** ✅ 2026-09-27:
    - Every request returns only the **last 7 days** before `end_time`, whatever window you ask for.
    - Volumes matched Kite's on 0.2% of bars, and minute volumes summed to 49–107% of the day's volume.
    - After 15:15 it returns bars up to 15:30, a window in which Kite and Groww show no trading.
  - On this account F&O is not activated ✅.
  - MCX is effectively not available (below).
- **Gotchas:**
  - **Only one TOTP-generated token can be live at a time.** Each new one cancels the last 📄. If a cron job and the dashboard both generate tokens, they will keep logging each other out. So all processes share one token through the shared database (`data/market.db`, git-ignored) (`indmoney_session.py`, since 2026-09-28).
  - A historical request wider than the limit returns `200` with less data, not an error 📄.
- **Use for:** free bulk snapshots and end-of-day capture, and as a streaming fallback for NSE/BSE cash and indices. Not for MCX or F&O on this account.

#### INDmoney token generation (tested 2026-09-25)

| Finding | Docs say | Actually |
| --- | --- | --- |
| What a new token needs | `x-api-key` (Client ID) + `mpin` + `totp` | Same ✅. Leaving out either gives `400 Missing required fields: totp` or `...: mpin`. **All three are required.** Neither the MPIN alone nor the TOTP alone is enough |
| Refresh or renew endpoint | none documented | None exists: `/refresh/token`, `/token/refresh` and `/renew/token` all return 404 ✅ |
| Token lifetime | "24 hours from generation" | **Wrong.** A token made at 13:20 IST returned `expires_in: 1790386200`, which is **07:00 IST the next day** ✅. Treat it as a fixed daily cutoff, like Kite's 06:00 |
| Response field | `token` | `{"token": "...", "expires_in": <epoch seconds>}` ✅. `expires_in` is an absolute time, not a duration |
| The TOTP secret | shown once at setup | The dashboard calls it the **Setup Key**. After setup it only shows the Client ID ✅ |

`.env` variables: `IND_MONEY_CLIENT_ID`, `IND_MONEY_MPIN` and `IND_MONEY_TOTP_SECRET` (the Setup Key, base32). **No access token goes in `.env`** (since 2026-09-28). [`market/providers/indmoney_session.py`](../market/providers/indmoney_session.py) mints one and shares it through the shared database (`data/market.db`, git-ignored), on the Dhan pattern and the same [`token_store.py`](../market/providers/token_store.py) plumbing. Until then nothing in the repo could mint a token, so the pasted one died at 07:00 every day and INDmoney dropped out of every script. Verified 2026-09-28: with no session file, `IndMoneyProvider().connect()` minted a token on the first NTP-corrected code in 1.3 s (valid to 07:00 next day), and a second process reused it without minting.

**Clock drift breaks TOTP quietly.** This PC's clock is **21.0 s slow**. Three NTP servers agreed within 10 ms on 2026-09-28; the HTTP `Date` headers measured on 2026-09-25 said "about 16–20 s", because they only have 1-second resolution. That's enough to produce a wrong code, and 5 wrong INDmoney codes lock you out for 15 minutes. **Every TOTP code in this repo must come from `market.clock_offset.totp_code(secret)`**, never from `pyotp.TOTP(...).now()`. It measures the offset by NTP once per process (falling back to HTTP `Date`, then the saved value), saves it to the git-ignored the `clock_offset` row of `data/market.db`, and waits at most 3 s, only in a window's last seconds. Dhan, INDmoney and both Groww clients use it. Syncing the Windows clock (`w32tm /resync`, as admin) is still worth doing.

**Generate once, share the result.** Each new token cancels the last. The data endpoints only accept the access token, so the Client ID, MPIN and secret are used for one thing: making that token. It doesn't need a scheduled job. Any process can make one *when needed*, the way Groww's SDK does, provided all processes share one saved token:

This is what `indmoney_session.py` does:

1. Read the saved token.
2. If it's missing, past its `expires_in`, or rejected **twice** (one 403 can be transient), take a lock and make a new one from TOTP.
3. Save it and release the lock. Every other process picks it up on its next read.

Without the shared file and lock, two processes that each make their own token keep revoking each other's.

#### MCX on INDmoney (retested 2026-10-17)

INDmoney's docs added MCX quotes in October 2026 (changelog "Unreleased"). Retested on Saturday 17 Oct, so the values
are Friday's session; Kite was asked for the same contracts at the same time.

| Surface | Result |
| --- | --- |
| Instrument list, `source=mcx` (now documented) | ✅ 10,623 rows; **93 `FUTCOM`, 19 commodities** (Dhan: 168, 28). No CARDAMOM, COTTON, COTTONOIL, ELECDMBL, KAPAS, LEAD, LEADMINI, MENTHAOIL, STEELREBAR, SUNOIL, and only the nearer expiries of the rest (GOLD to Apr 27, CRUDEOIL to Mar 27). `SECURITY_ID` is the MCX token, the same id Dhan uses |
| REST `ltp`, `full`, `mkt` with `MCX_<id>` | ✅ ~0.35 s for all 93 in one call. **One id that `source=mcx` does not list fails the whole request** (`400 Invalid scrip codes or mode`) |
| `full` against Kite (82 contracts that traded) | ✅ last price, open, high, low and OI identical on all 82. `prev_close` differed on 6: illiquid contracts, and NATURALGAS, where INDmoney's 306 is Thursday's close (Kite's daily candle agrees) while Kite's quote had already rolled to Friday's 298.6. INDmoney was the consistent one |
| `full` fields | `live_price`, `day_open/high/low`, `prev_close`, `day_change(_percentage)`, `volume` (kept after the close, like Dhan), `open_interest`, `open_interest_change`, resolved circuits. **No last-trade time.** 11 untraded contracts come back with no price |
| `/market/historical/{1day,15minute,1minute}` with `MCX_` | ❌ `200` with empty `data` (an NSE control in the same run returned candles) |

So INDmoney can fill the MCX quote table for free, but not the charts, and the page's "trading now" test (newest last-trade time) has nothing to read. The MCX Futures page uses it as the third choice after Dhan and Kite, judging "live" from MCX's hours ([MCX_FUTURES.md](MCX_FUTURES.md#how-the-fallback-works)).

<details><summary>Earlier result (2026-09-25, market open)</summary>


| Surface | Result |
| --- | --- |
| Instrument list, `source=mcx` (**undocumented**) | ✅ 9,967 MCX rows (GOLD, SILVERM, CRUDEOIL, NATURALGAS, COPPER…), types `FUTCOM` and `OPTFUT` |
| REST quotes (`ltp`, `full`) with `MCX_`, `MCXFO_`, `MCXCOM_`, `MCX_COMM_` and others | ❌ `400 Invalid scrip codes or mode` (an NSE control request worked) |
| REST daily candles, same prefixes | ❌ `400 Invalid scrip codes` |
| Contracts search, `underlying=CRUDEOIL` | ❌ `400 Invalid or unknown underlying` |
| WebSocket `MCX:<id>`, `ltp` mode | ✅ CRUDEOIL Oct future priced (8939–8945), 6 ticks in 45 s |
| WebSocket `MCX:<id>`, `quote` mode | ⚠️ `open`, `high` and `low` are always **0**; only `close` (the live price) and volume are filled |
| WebSocket `MCXFO:` / `MCXCOM:` | ❌ silently ignored |

In short, you could get a live MCX price from the socket, but no opens, no previous close and no history.

</details>

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

**Free API plan, tested 2026-10-17** ✅: login, profile, margins, holdings, positions (CASH, FNO and COMMODITY),
order list, GTT/OCO smart-order list, the margin calculator and the instrument list all work. **Every market-data
call is refused** (`Access forbidden for this request.`): quotes, LTP, OHLC, candles, expiries, option chain and
Greeks. So on the free plan Groww is an account and order API only; the F&O dashboard then lists positions without
prices ([`api/GROWW_API_LIVE_DATA.md`](api/GROWW_API_LIVE_DATA.md)). No API gives order history beyond today or a
P&L report ([`api/GROWW_API_ORDERS.md`](api/GROWW_API_ORDERS.md)). The points below were measured on the paid plan
in September 2026; what to re-check when it is back is in [`GROWW_PAID_PLAN_CHECKS.md`](GROWW_PAID_PLAN_CHECKS.md).

- **Strengths:**
  - **TOTP login is fully automatic** (`GROWW_TOTP_SECRET`), like Dhan's and INDmoney's ✅.
  - The existing portfolio and F&O dashboards use it, including commodity positions.
  - Its past closes were identical to Kite's ✅.
  - The SDK has option-chain and Greeks calls 📄, and GTT/OCO smart orders (stop-loss and target that can last past a day) 📄.
- **Weaknesses:**
  - 50 instruments per LTP/OHLC call ✅.
  - Daily candles have `open = None`, so **you can't compute gaps from Groww candles** ✅.
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
| INDmoney | 1 `quotes/full` call (`day_open` + `prev_close`); candles 100 calls ≈ 25 s | 100 calls (1 year per call) | yes | **yes** ✅ (TOTP) |
| Dhan | 1 `marketfeed/ohlc` call; candles ~500 calls at ≤5/s | ~500 calls | yes | **yes** ✅ (TOTP, 2026-09-27) |
| Groww | 10 calls (50 per call) | ~500 calls ≈ 3.5 min | **no** | **yes** |

   **Recommendation (verified 2026-09-25):** run the cron after 16:00 IST with **INDmoney** first and **Kite** as fallback. INDmoney's candles matched Kite's on every open, high, low, close and volume except one corporate action, it's 7–8× cheaper to fetch, and it logs in without a person. See the [comparison log](PROVIDER_COMPARISON_LOG.md). Groww can't supply `open`, so it can't do gaps.

- On a missed day, the next run backfills from candles. Candles cost one request per stock (Kite and Dhan) no matter how many days they cover, so catching up costs the same as a single day.
- **Corporate actions:** INDmoney returns raw exchange prices, while Kite adjusts past prices after an ex-date (HINDPETRO, 14 Aug 2026: INDmoney shows a −4.8% gap, Kite +0.09%). Rows a daily cron stores are unadjusted with either broker, so repair a window with Kite (`scripts/kite.py history --full --history-days N`). See [Known limitations](FNO_MOVERS.md#known-limitations).
- **One `403 TokenException` from INDmoney can be transient.** Retry once before generating a new token, because generating one revokes the token everyone else is using.

1. **The WebSocket doesn't help here.** It streams live ticks and carries no history. Use it only for live boards.
2. **Instrument ids come from files, never runtime lookups.** Each broker's ids are generated into `data/` by a script under `scripts/`.

---

## Keeping this file honest

- When you verify a 📄 claim, mark it ✅ with the date. When a ✅ claim stops being true, fix it.
- Re-run the INDmoney MCX test when INDmoney's docs mention MCX, or every few months.
- Dhan: `RenewToken` is still untested. TOTP generation already makes it unnecessary.
- Keep each broker's details in its own page under [`api/`](api/). This page holds the conclusions only.
