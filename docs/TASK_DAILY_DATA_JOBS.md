# Task: unattended daily data jobs on Railway (Dhan + Groww, Kite optional)

Handover for a new session, written 2026-11-07. Read this, then `context.md` (repo root) only if the task
touches the insight pages. Ask before committing; nothing from the 2026-11-07 session is committed yet.

## Progress 2026-11-08 (not committed, not deployed)

- **Jobs built** (`python scripts/daily.py [dhan-daily] [groww-intraday] [movers]`):
  - `scripts/jobs/dhan_daily.py`: Dhan daily candles -> `daily_bars`, F&O + Nifty 100 extras, one call per
    stock for any range (5 years in 0.5 s). `--full --daily-days N` deletes and refetches the window.
  - `scripts/jobs/groww_intraday.py`: Groww 1-minute -> `minute_bars`, 09:15-15:14 only, 09:15 open replaced by
    the daily candle's open. Each fetched day replaces that day's stored bars.
  - Converters and tests: `market/intraday_store.py` (`dhan_daily_rows`, `groww_minute_rows`, `replace_days`),
    `tests/test_daily_sources.py`.
- **Dhan quirk:** Dhan sometimes sends two candles for a day. Identical ones are kept once (CANBK, TMPV, ...).
  MOTHERSON up to 2024-04-29 has two series about 2:3 apart, then only the lower one continues; the converter keeps
  the candle nearest the next later day's close, so the series has no false jump.
- **Dhan ids:** `scripts/jobs/dhan_instruments.py` now also resolves the F&O list; all 218 resolve. ICICIPRULI
  (old name of ICICILIFE, still in the stored Nifty list) has no id and keeps its Kite rows.
- **Backfill done on the local DB:**
  - `daily_bars_kite` = backup of the Kite history (259,444 rows). `deploy/stage_public.py` drops it from the push.
  - `daily_bars` refetched from Dhan (`--full --daily-days 1900`): 2021-08-26 .. 2026-11-06, raw prices. The old
    Kite history was itself mixed (INFY adjusted only on the days the last incremental run re-fetched).
  - `minute_bars` refetched from Groww (`--full --intraday-days 102`).
- **Kite:** the user decided it stays out of the scheduled job; a backup source later only if gaps show up.
- **Trigger:** `scripts/job_trigger.py` (POST /run, GET /status, header `X-Job-Secret`), started by `start.sh`
  only when `JOB_TRIGGER_SECRET` is set; listens on `::` port `JOB_TRIGGER_PORT` (8090). Tests:
  `tests/test_job_trigger.py`. The bundle now ships `scripts/daily.py`, `scripts/job_trigger.py` and the four job
  modules it needs (named one by one; the insight scripts never ship).
- **Railway facts checked 2026-11-08:** cron schedules are UTC, minimum 5 minutes, may drift a few minutes, an
  overlapping run is skipped, and the service must exit when done. Environments created after 2025-10-16 resolve
  `*.railway.internal` to IPv4 and IPv6 (older ones IPv6 only); listen on `::`.
- **Server steps (user approved 2026-11-08):**
  - Done: `JOB_TRIGGER_SECRET` (64 chars, also in local `.env`) and `JOB_TRIGGER_PORT=8090` set on `dashboards`
    with `skipDeploys`, so they take effect on the next deploy.
  - Done: `--push-db` deploy (seed `20261108T043618Z-...`); the server DB matches the local one.
  - Done: `daily-jobs` cron service (id `72922919-93eb-4e4c-9a7a-54a4b49ec3d9`; alpine image, busybox wget,
    `45 10 * * 1-5`, secret as the reference `${{dashboards.JOB_TRIGGER_SECRET}}`, restart policy NEVER). It POSTs
    `http://dashboards.railway.internal:8090/run`, logs each attempt, retries up to 6 times and exits.
  - Gotcha: `serviceCreate` with an image deploys at once, before the start command is set, so the first deployment
    ran bare alpine. After changing the start command, deploy (`serviceInstanceDeployV2`); a cron deployment then
    waits for its schedule, and `railway cron run --service daily-jobs --yes` runs it now.
  - Verified 2026-11-08 (Sunday): cron -> private network (IPv4) -> trigger -> all three jobs ok, exit 0, 2.5 min.
  - Checks: `railway ssh ... --service dashboards -- ...` then GET `http://127.0.0.1:8090/status` with the header;
    the run log is also in `/app/data/jobs/last_run.log` and the container log (`[jobs]` lines).
- **Answered 2026-11-09/10:** Dhan's `/charts/historical` does NOT have today's candle at 16:15 IST. Each run
  stores the previous day's candle, so `daily_bars` is one day behind. Not fixed yet (options: a later cron, or a
  second evening run).
- **2026-11-10, NSE holiday (Diwali Balipratipada):** the run's movers job failed (Dhan sent no NSE prices), and
  the heatmap's live feed reconnected 700+ times (silence in "session hours"; holidays were not known). Changes,
  built and tested locally, not deployed yet:
  - `market/exchange_status.py`: "did NSE / MCX trade today?" from a liquid instrument's last trade time
    (Dhan quote). No broker has a market-status endpoint for Indian exchanges (Dhan's covers US stocks only;
    Groww has none). Asked from 09:16 for NSE and 09:01 for MCX, each answer kept for 5 minutes, and a failed
    check means "not known" (behave as normal), never "closed". Verified live on the holiday evening:
    NSE no trade today, MCX trading.
  - Live feed: no silence reconnects or failover on a day NSE is not trading; after 3 reconnects with no price,
    one try every 5 minutes; REST polled every 5 minutes (not 3 s) outside pre-market and the session; a board
    with no viewer for 10 minutes stops its feed (the next viewer restarts it).
  - `scripts/daily.py --scheduled` (what the trigger now runs): skips the run as a success only when three fresh
    checks a minute apart all say NSE did not trade; a failed job is re-run at most twice, 10 minutes apart.
  - Still to do on Railway (needs approval): cut the cron's trigger attempts from 6 to 3, then deploy.
- **Planned, not built:** pre-open prices from 09:08 (`docs/PLAN_PRE_MARKET.md`).

## Where things stood on 2026-11-07

**Public app (live):** https://dashboards-production-1d39.up.railway.app

- **Railway layout:**
  - Project `pulse-dashboards` (id `1c7d8cd5-0de0-4e4e-ad19-8680cc04030a`), environment `production`
    (`3f85b448-d1e3-407e-a5f4-fce5edde5d8c`), service `dashboards` (`4fcb8e29-2e76-42f2-b313-2860f975c61a`).
  - SQLite at `/app/data/market.db` on a volume.
  - Never touch the other projects in the workspace (carwash-whatsapp-bot, docHelper, licence app).
- **Deploy:**
  - `python deploy/railway_deploy.py` deploys code only.
  - `--push-db` also replaces the server DB with a cleaned copy of the local one (see `deploy/stage_public.py`
    and `deploy/railway/start.sh`, which installs a pushed DB once per `SEED_ID`).
  - The upload uses `RAILWAY_PULSE_PROJECT_TOKEN` from `.env`.
- **Tokens and CLI login in `.env`:**
  - `RAILWAY_API_TOKEN` is a workspace token. The CLI's `whoami`/`ssh` reject it, so use GraphQL
    (`https://backboard.railway.com/graphql/v2`, Bearer) for project admin.
  - The user is logged in with `railway login`, so `railway ssh` works with the laptop key `laptop-pulse`.
    Run it with env `-u RAILWAY_TOKEN -u RAILWAY_API_TOKEN`, and in Git Bash set `MSYS_NO_PATHCONV=1`:
    `railway ssh --project <id> --service dashboards --environment production -- <cmd>`.
- **Public mode** (`PULSE_PUBLIC_MODE=1`, `utils/public_mode.py`):
  - No Dhan journal or API explorer pages.
  - Refresh buttons are throttled server-wide, and the provider picker is hidden.
  - The bundle and DB copy exclude the journal tables, broker sessions, xlsx reports and insight HTML.
- **Kite login:**
  - The hidden page `/kite-login` (`apps/kite_login_dashboard.py`) is behind `PULSE_ADMIN_PASSWORD`. It uses a
    one-time state code and only saves a session for `KITE_USER_ID`.
  - The Kite app's redirect URL points there.
  - `scripts/kite_login.py` tags its link `dest=local`; the page then just shows the line to paste into the script.
- **Server variables:**
  - Dhan, Groww and Kite credentials; `PULSE_MARKET_PROVIDERS=dhan,groww,kite`; public mode; the admin password.
  - The user is sealing the secret ones in the Railway dashboard.
- **Removed and settled:**
  - INDmoney was removed everywhere (a new token revokes the old one, verified live 2026-11-07); the README
    keeps the decision note.
  - All three brokers need IP whitelisting for orders. This app places none.
  - Groww and Dhan keep an old token valid after minting a new one (verified 2026-11-07), so the server and the
    laptop can share them.
- **Data, as of 2026-11-07:**
  - Server DB = local DB pushed that evening: daily and 1-minute bars to 2026-11-06, Dhan movers to 2026-11-06
    (2026-11-05 movers were never captured).
  - Today the user runs the jobs locally (`scripts/dhan.py`, `scripts/kite_login.py` + `scripts/kite.py`) and then
    `deploy/railway_deploy.py --push-db`.

## Broker comparison (evidence: `docs/PROVIDER_COMPARISON_LOG.md`, entry 2026-11-07)

- **Daily candles:** Dhan equals Kite field for field, except that Kite adjusts history for corporate actions
  and Dhan shows raw prices (INFY, 18 days to 2026-10-21). Groww's daily candle is not the official one.
- **1-minute bars:** Groww matches Kite best (volume 99.8% equal, close 92.7%, same labels).
  - Its opens differ, and its first bar never opens at the official open.
  - It sends a pre-open bar (09:08, volume only) and bars from 15:15 to 15:59 (closing auction session, CAS,
    and after). Drop those for `minute_bars`, or keep them separately.
  - Dhan's 1-minute bars are poor (close 58.6%, volume 12.9%).
- Raw candles from all three are captured with `scripts/debug/capture_candles.py` into
  `data/provider_compare.db`. `scripts/debug/analyze_candle_diffs.py` measures how big the differences are
  and what explains them; full results are in the log entry.
- **Why they differ:**
  - No rounding issue.
  - Kite adjusts minute and daily history for corporate actions (INFY before 2026-11-03, x0.978).
  - Groww's bars carry the same labels, closes and volumes as Kite's. Open differences are conventions:
    - Kite's 09:15 open is the pre-open price, which Groww puts in its 09:08 bar.
    - On ~40% of minutes Kite's open repeats the previous close, while Groww's open is always the
      minute's first trade. That also explains half the high/low gaps.
  - Dhan's minute bars have the official 09:15 open and no net delay, but trades at a minute boundary land
    in the neighbouring minute (per-minute volume off by a median 0.4%, errors cancel between minutes).
  - Groww's daily candle has no open, and its high/low/volume include the pre-open and closing-session bars.
- **Consequences for the jobs:**
  - Store the day's open, high, low and volume from Dhan's daily candle.
  - Use Groww minute bars for intraday shape, closes and volumes.
  - If a stock's history mixes Kite-adjusted and raw rows, re-fetch it from one source.

## What to build

**Decided by the user (2026-11-07):**
- **Dhan for daily candles.**
- **Groww for 1-minute candles.**
- **Kite only when there is a login that day** (optional extra or cross-check).

The comparison is done and logged. Don't redo it unless something changes; the evidence is in
`docs/PROVIDER_COMPARISON_LOG.md`, entry 2026-11-07.

1. **Daily history basis follows from that decision: raw prices (Dhan).**
   - Kite = adjusted, Dhan = raw. Mixing them creates false jumps at corporate actions.
   - Refetch ~5 years of `daily_bars` from Dhan (`/v2/charts/historical`), so every row is raw, like NSE's
     52-week figures. The drawdown page already flags suspected splits.
   - Check with the user before overwriting the stored Kite history.
2. **Jobs:**
   - Dhan daily candles -> `daily_bars`.
   - Groww 1-minute -> `minute_bars`: keep 09:15-15:14 only, and take the day's open from the daily candle.
   - Dhan movers (exists: `scripts/jobs/dhan_movers.py`).
   - Kite runs only if a valid session exists that day.
   - Check that the Dhan instrument ids cover all ~218 F&O stocks; today's `dhan_instruments` set covers
     Nifty 50, Next 50 and the sectoral indices. The F&O list is `fno_universe` (Kite tokens).
3. **Trigger API inside the `dashboards` container** (the volume can attach to only one service):
   - A small HTTP endpoint started by `start.sh` next to Streamlit, listening only on Railway's private network
     (`dashboards.railway.internal:<port>`), never on the public domain, and requiring a shared secret header.
   - A call starts the jobs in a background thread and returns at once; a second call while running is refused.
   - It logs a result per job.
4. **Railway cron service:**
   - A tiny service on a cron schedule (UTC; 16:15 IST = `45 10 * * 1-5`) that calls the endpoint and exits.
   - It needs the shared secret as a variable.
   - Check how Railway cron services and private networking behave today before building.
5. **Flip the sync (low priority):** the user plans to move the database to Supabase soon, so build only a minimal
   pull, or skip it. The server becomes the source of truth for market data.
   - Write a pull script (`railway ssh` + `sqlite3 .backup`, then copy the file down, e.g. base64 or a
     temporary download) that refreshes the local DB's market tables.
   - Keep the local-only tables (`dhan_fills`, `dhan_ledger`, `dhan_trip_tags`, local sessions) untouched.
   - `--push-db` then becomes a rare, deliberate action.
6. **Groww's extra data (later):** a page for the pre-open (09:00-09:08) and the closing auction session.

## Rules that still apply

- Windows 11, Git Bash. Never print or commit secrets.
- Don't touch the insight pages and scripts (`scripts/journal_insights.py`, `scripts/groww_*_insights*.py`,
  `data/*.html`); they must stay byte-identical.
- Tests: `.venv/Scripts/python.exe -m unittest discover -s tests -t .`. There are 2 known failures in
  `tests.test_mcx_futures.TestPage` (a test contract expired on 2026-10-19).
- Deployed changes are verified on the live site. `scratchpad` Playwright with `channel: 'msedge'` works for
  screenshots; plain headless Edge doesn't render Streamlit.
