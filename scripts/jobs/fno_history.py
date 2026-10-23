"""Build / extend the F&O daily-close history the movers dashboard reads.

    python scripts/kite.py history                         # catch up every F&O stock (30 days for a new one)
    python scripts/kite.py history --history-days 400      # backfill ~a year (same cost)
    python scripts/kite.py history --full --history-days 1830   # 5 years, adjusted (the drawdown page)
    python scripts/kite.py history --symbols RELIANCE,TCS
    python scripts/kite.py history --full --history-days 60   # re-fetch stored days too (after a split)
    python scripts/kite.py history --fix-splits            # find suspected splits/bonuses and re-fetch just those stocks

Run it once to backfill, then once a day after 16:00 IST (or weekly - one run
fills every missing day). It needs today's Kite session
(``python scripts/kite_login.py``).

Cost: **one request per stock, however many days**. Kite's daily-candle
endpoint takes one instrument per call but any date range, so a 7-day catch-up
and a 5-year backfill both cost ~215 requests - about 75 s at Kite's 3 req/s.
One call covers at most ``MAX_DAYS_PER_CALL`` days (a longer range is refused
with HTTP 400 "interval exceeds max limit: 2000 days", tested 2026-10-23), so
``--history-days`` stops there. That per-stock cost is the whole reason to store
the history: afterwards the dashboard needs no API call for past days, and one
bulk quote for today.

Besides the F&O stocks, the Nifty 50 and Nifty Next 50 members without futures
get daily bars too (the drawdown page's Nifty 100). They are not added to
``fno_universe``, so no F&O page lists them.

Writes to the shared database data/market.db (both only ever written here):
  fno_universe set     F&O stocks + Kite instrument tokens (from public dumps)
  daily_bars table     symbol, date, open, high, low, close, volume (the table the 1-minute
                       backfill fills too, so there is one daily history)

Today's candle is stored only after 16:00 IST; before that its "close" is just
the live price. Every run re-fetches from each stock's last stored day, so a
value that settled late is corrected on the next run.

Read-only: no orders, no account data.
"""

import logging
import time
from datetime import date, timedelta

import requests

from market.fno_movers import (
    UNIVERSE_SET,
    build_universe,
    candle_rows,
    extra_history_tokens,
    load_closes,
    load_confirmed_moves,
    save_closes,
    save_universe,
    suspected_corporate_actions,
    upsert_closes,
)
from market.market_hours import now_ist
from market.universe import universes

logger = logging.getLogger("fno_history")

#: Indices whose non-F&O members also get daily bars (the drawdown page's Nifty 100).
EXTRA_INDICES = ("NIFTY50", "NIFTYNEXT50")


def index_symbols(key: str):
    """An index's stored members; none when ``--master`` has not stored that list."""
    universe = universes().get(key)
    return universe.symbols if universe else []

DUMP_URL = "https://api.kite.trade/instruments/{exchange}"
#: Today's candle is trusted as the close only after this IST time.
SETTLED_AFTER = (16, 0)
#: Kite's longest day-candle range per request.
MAX_DAYS_PER_CALL = 2000


def download_dump(exchange: str) -> str:
    response = requests.get(DUMP_URL.format(exchange=exchange), headers={"X-Kite-Version": "3"}, timeout=120)
    response.raise_for_status()
    return response.content.decode("utf-8-sig")


def fetch_candles(provider, token: str, start: str, end: str):
    """One stock's daily candles, retried twice on a network error."""
    params = {"from": f"{start} 00:00:00", "to": f"{end} 23:59:59"}
    for attempt in range(3):
        try:
            status, body = provider._get(f"/instruments/historical/{token}/day", params, "historical")
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logger.debug("retrying after %s", exc)
            time.sleep(2)
            continue
        if status == 200:
            return (body.get("data") or {}).get("candles") or []
        raise RuntimeError(f"HTTP {status}: {body.get('error_type', '')} {body.get('message', '')}".strip())
    return []


def run(args) -> int:
    full, days = args.full, args.history_days
    from market.providers.kite import KiteProvider

    if days >= MAX_DAYS_PER_CALL:
        logger.error("--history-days %d: Kite returns at most %d days per call; use %d or fewer.",
                     days, MAX_DAYS_PER_CALL, MAX_DAYS_PER_CALL - 1)
        return 1

    logger.info("Downloading Kite's public NFO and NSE instrument lists ...")
    try:
        nse_csv = download_dump("NSE")
        tokens, unmatched = build_universe(download_dump("NFO"), nse_csv)
    except requests.RequestException as exc:
        logger.error("Could not download the instrument lists: %s", exc)
        return 1
    if not tokens:
        logger.error("No F&O stocks found - refusing to overwrite the stored %s", UNIVERSE_SET)
        return 1
    save_universe(tokens, unmatched)
    logger.info("  %d F&O stocks -> %s (%d index futures skipped: %s)",
                len(tokens), UNIVERSE_SET, len(unmatched), ", ".join(unmatched))

    members = [s for key in EXTRA_INDICES for s in index_symbols(key)]
    extras, not_found = extra_history_tokens(nse_csv, tokens, members)
    if extras:
        logger.info("  + %d %s members without F&O, for the drawdown page: %s",
                    len(extras), "/".join(EXTRA_INDICES), ", ".join(extras))
    if not_found:
        logger.warning("  Not in Kite's NSE list, skipped: %s", ", ".join(not_found))
    tokens = {**tokens, **extras}

    if args.symbols:
        wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in tokens]
        if unknown:
            logger.warning("Not F&O stocks or index members, skipped: %s", ", ".join(unknown))
        tokens = {s: tokens[s] for s in wanted if s in tokens}

    provider = KiteProvider()
    if not provider.is_configured():
        logger.error("No Kite session for today - run 'python scripts/kite_login.py' first.")
        return 1
    try:
        provider.connect()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    now = now_ist()
    today = now.date()
    settled = (now.hour, now.minute) >= SETTLED_AFTER
    exclude = None if settled else today.isoformat()

    rows = load_closes()
    suspects = []
    if args.fix_splits:
        suspects = suspected_corporate_actions(rows, load_confirmed_moves())
        if not suspects:
            logger.info("No suspected splits or bonuses in the stored closes - nothing to re-fetch.")
            return 0
        names = sorted({a.symbol for a in suspects})
        logger.info("Suspected: %s. Re-fetching those stocks over the whole stored range.",
                    "; ".join(f"{a.symbol} {a.date} ({a.change_pct:+.1f}%)" for a in suspects))
        tokens = {s: t for s, t in tokens.items() if s in names}
        full = True
        days = min((today - date.fromisoformat(min(day for day, _ in rows))).days + 1, MAX_DAYS_PER_CALL - 1)
    last_by_symbol = {}
    for day, symbol in rows:
        if day > last_by_symbol.get(symbol, ""):
            last_by_symbol[symbol] = day

    logger.info("Fetching daily candles for %d stocks (~%.0f s) ...", len(tokens), len(tokens) * 0.36)
    started = time.monotonic()
    stored_before = set(rows)
    last_day_before = max((day for day, _ in rows), default="-")
    fetched, changed, failed = 0, 0, []
    for i, (symbol, token) in enumerate(sorted(tokens.items()), 1):
        last = last_by_symbol.get(symbol)
        start = last if last and not full else (today - timedelta(days=days)).isoformat()
        try:
            candles = fetch_candles(provider, token, start, today.isoformat())
        except Exception as exc:  # noqa: BLE001 - one stock must not stop the run
            failed.append(symbol)
            logger.warning("  %s: %s", symbol, exc)
            continue
        new_rows = candle_rows(symbol, candles, exclude_date=exclude)
        fetched += len(new_rows)
        changed += upsert_closes(rows, new_rows)
        if i % 50 == 0:
            logger.info("  %d/%d", i, len(tokens))

    save_closes(rows)
    if args.fix_splits:
        still = {(a.symbol, a.date) for a in suspected_corporate_actions(rows, load_confirmed_moves())}
        for action in suspects:
            outcome = ("still a fall of %+.1f%% after re-fetching: a real move (or a demerger or buyback), left as is"
                       % action.change_pct if (action.symbol, action.date) in still
                       else "adjusted: Kite's candles now show it as a corporate action")
            logger.info("  %s %s: %s", action.symbol, action.date, outcome)
    days = sorted({d for d, _ in rows})
    added = len(set(rows) - stored_before)
    logger.info(
        "Done in %.0f s: %d candles fetched -> %d new, %d revised, %d already stored. "
        "%d stocks x %d days in data/market.db (%s .. %s)",
        time.monotonic() - started, fetched, added, changed - added, fetched - changed,
        len({s for _, s in rows}), len(days), days[0] if days else "-", days[-1] if days else "-",
    )
    if fetched and not changed:
        # The intraday job writes the same daily_bars rows, so a day it already stored
        # shows up here as "already stored", not as new.
        logger.info("Nothing new: the history already ran to %s (scripts/kite.py intraday also fills "
                    "daily_bars).", last_day_before)
    if not settled:
        logger.info("Today's candle was left out (before %02d:%02d IST it is only the live price).", *SETTLED_AFTER)
    if failed:
        logger.warning("%d stock(s) failed and can be retried by re-running: %s", len(failed), ", ".join(failed))
        return 2
    return 0

