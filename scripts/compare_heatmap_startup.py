"""Time how long each broker takes to bring up a heatmap board. Read-only.

    python scripts/compare_heatmap_startup.py [--board sectors|indices|both]
        [--provider dhan] [--seconds 20] [--out results.json]

Mirrors what LiveMarketDataService does on its first visit to a board, one stage
at a time, for each configured broker:

  1. connect       authentication
  2. resolve       instrument ids (read from the local data/*_instruments.json)
  3. prev close    the same source the service picks: the OHLC endpoint in the
                   session, daily candles outside it
  4. REST LTP      one batched price snapshot
  5. socket open   connect and subscribe
  6. first tick    from socket open to the first price
  7. all priced    from socket open to every resolved instrument having a price
                   (or --seconds, whichever comes first)

"Board ready" is connect + resolve + prev close + REST LTP: the earliest the
service could paint a fully coloured board from REST. Run it in and out of
market hours: prev close comes from a different (slower) source after 15:30.
Prints a summary; never prints tokens. Results are logged in
docs/PROVIDER_COMPARISON_LOG.md.
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from market.config import HeatmapConfig  # noqa: E402
from market.market_hours import SESSION_OPEN, SESSION_PRE_MARKET, session_state  # noqa: E402
from market.providers.registry import available_provider_names, build_providers  # noqa: E402
from market.universe import DEFAULT_UNIVERSE_KEY, INDEX_UNIVERSE_KEY, get_universe  # noqa: E402

BOARDS = {"sectors": DEFAULT_UNIVERSE_KEY, "indices": INDEX_UNIVERSE_KEY}


def timed(stage: dict, name: str, fn):
    started = time.monotonic()
    try:
        return fn()
    finally:
        stage[name] = round(time.monotonic() - started, 2)


def measure(provider, universe, watch_seconds: int) -> dict:
    row = {"provider": provider.label, "instruments": len(universe), "stages_s": {}}
    stages = row["stages_s"]
    if not provider.is_configured():
        row["error"] = "no credentials configured"
        return row

    feed = None
    try:
        timed(stages, "connect", provider.connect)
        resolved, missing = timed(
            stages, "resolve",
            lambda: provider.resolve_instruments(universe.symbols, segment=universe.segment),
        )
        row["resolved"], row["unresolved"] = len(resolved), sorted(missing)
        if not resolved:
            row["error"] = "nothing resolved"
            return row
        refs = list(resolved.values())

        in_session = session_state() in (SESSION_OPEN, SESSION_PRE_MARKET)
        row["prev_close_source"] = "OHLC endpoint" if in_session else "daily candles"
        closes = timed(
            stages, "prev_close",
            lambda: provider.get_previous_close(refs) if in_session
            else provider.get_prior_session_close(refs),
        )
        row["prev_close_priced"] = len(closes)
        prices = timed(stages, "rest_ltp", lambda: provider.get_ltp_snapshot(refs))
        row["rest_priced"] = len(prices)
        row["board_ready_s"] = round(
            sum(stages[k] for k in ("connect", "resolve", "prev_close", "rest_ltp")), 2
        )

        opened = time.monotonic()
        feed = timed(stages, "socket_open", lambda: provider.open_feed(refs))
        first = full = None
        seen = {}
        while time.monotonic() - opened < watch_seconds:
            seen = feed.latest_prices()
            elapsed = time.monotonic() - opened
            if seen and first is None:
                first = round(elapsed - stages["socket_open"], 2)
            if len(seen) >= len(refs):
                full = round(elapsed - stages["socket_open"], 2)
                break
            time.sleep(0.25)
        stages["first_tick"], stages["all_priced"] = first, full
        row["socket_priced"] = len(seen)
        row["day_bars"] = len(feed.day_bars())
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if feed is not None:
            try:
                feed.close()
            except Exception:  # noqa: BLE001
                pass
    return row


def show(board: str, rows: list) -> None:
    print(f"\n=== {board} board ({rows[0]['instruments']} instruments)" if rows else board)
    header = ("broker", "connect", "resolve", "prev close", "REST LTP", "ready",
              "sock open", "1st tick", "all priced", "REST/sock/total")
    print("  ".join(f"{h:>10}" for h in header))
    for r in rows:
        if "stages_s" not in r or "error" in r and "board_ready_s" not in r:
            print(f"{r['provider']:>10}  {r.get('error', '')}")
            continue
        s = r["stages_s"]

        def cell(key):
            value = s.get(key)
            return "-" if value is None else f"{value:.2f}"

        counts = f"{r.get('rest_priced', 0)}/{r.get('socket_priced', 0)}/{r['instruments']}"
        print("  ".join(f"{v:>10}" for v in (
            r["provider"], cell("connect"), cell("resolve"), cell("prev_close"),
            cell("rest_ltp"), f"{r['board_ready_s']:.2f}", cell("socket_open"),
            cell("first_tick"), cell("all_priced"), counts)))
        if r.get("unresolved"):
            print(f"{'':>10}  unresolved: {', '.join(r['unresolved'])}")
        if r.get("error"):
            print(f"{'':>10}  error: {r['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=[*BOARDS, "both"], default="both")
    parser.add_argument("--provider", choices=available_provider_names(),
                        help="Time only this broker")
    parser.add_argument("--seconds", type=int, default=20, help="How long to wait for ticks")
    parser.add_argument("--out", help="Write the full results as JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    names = [args.provider] if args.provider else list(HeatmapConfig.from_env().providers)
    boards = list(BOARDS) if args.board == "both" else [args.board]
    print(f"Session: {session_state()}. Brokers run one after another, so the "
          f"process-wide rate limits do not skew a later broker.")

    results = {}
    for board in boards:
        universe = get_universe(BOARDS[board])
        rows = []
        for provider in build_providers(names):
            print(f"  timing {provider.label} on {board} ...", flush=True)
            rows.append(measure(provider, universe, args.seconds))
        results[board] = rows
        show(board, rows)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"session": session_state(), "results": results}, handle, indent=2)
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
