"""Diagnostic for the sector heatmap's data pipeline.

Verifies, without starting Streamlit, for each configured broker:
  1. credentials present and authentication
  2. every constituent resolves to a broker instrument id
  3. every constituent has a previous close
  4. whether the broker's websocket actually delivers ticks

Usage:
    python scripts/check_heatmap_universe.py [--seconds 20] [--provider dhan]
"""

import argparse
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
from market.live_feed import LiveMarketDataService  # noqa: E402
from market.market_hours import (  # noqa: E402
    SESSION_OPEN,
    SESSION_PRE_MARKET,
    session_state,
)
from market.models import SOURCE_WEBSOCKET  # noqa: E402
from market.providers.registry import build_providers  # noqa: E402
from market.universe import DEFAULT_UNIVERSE_KEY, INDEX_UNIVERSE_KEY, get_universe  # noqa: E402


def probe_provider(provider, universe) -> bool:
    """Exercise a single broker's REST paths. Returns True if usable."""
    print(f"\n=== {provider.label} ===")
    if not provider.is_configured():
        print("SKIP  no credentials configured")
        return False
    try:
        provider.connect()
        print("OK    authentication")
    except Exception as e:
        print(f"FAIL  authentication: {e}")
        return False

    try:
        resolved, missing = provider.resolve_instruments(
            universe.symbols, segment=universe.segment
        )
    except Exception as e:
        print(f"FAIL  instrument resolution: {e}")
        return False
    print(f"{'OK   ' if not missing else 'WARN '} instrument ids: "
          f"{len(resolved)}/{len(universe)} resolved")
    if missing:
        print("      ids come from a generated file, not a live download - "
              "run 'python scripts/fetch_instrument_master.py' to refresh it")
    for symbol in missing:
        print(f"      unresolved: {symbol}")
    if not resolved:
        return False

    refs = list(resolved.values())
    # Mirror the service's own choice of source: the broker's OHLC field only
    # means "previous close" while the market is open, so checking that path
    # after 15:30 would verify the wrong endpoint and report a false OK.
    in_session = session_state() in (SESSION_OPEN, SESSION_PRE_MARKET)
    source = "OHLC endpoint" if in_session else "daily candles"
    try:
        if in_session:
            closes = provider.get_previous_close(refs)
        else:
            closes = provider.get_prior_session_close(refs)
    except Exception as e:
        print(f"FAIL  previous close ({source}): {e}")
        return False
    no_close = sorted({r.symbol for r in refs} - set(closes))
    print(f"{'OK   ' if not no_close else 'WARN '} previous closes: "
          f"{len(closes)}/{len(refs)} resolved from {source}")
    for symbol in no_close[:10]:
        print(f"      missing previous close: {symbol}")

    try:
        prices = provider.get_ltp_snapshot(refs)
        print(f"OK    REST LTP snapshot: {len(prices)}/{len(refs)}")
    except Exception as e:
        print(f"WARN  REST LTP snapshot failed: {e}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE_KEY)
    parser.add_argument(
        "--board",
        choices=("sectors", "indices"),
        help="Shorthand for --universe: 'indices' checks the NSE sectoral index board",
    )
    parser.add_argument("--provider", help="Test only this broker (dhan/groww)")
    parser.add_argument("--seconds", type=int, default=20, help="How long to watch the feed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("growwapi.groww.nats_client").setLevel(logging.CRITICAL)

    config = HeatmapConfig.from_env()
    universe = get_universe(
        INDEX_UNIVERSE_KEY if args.board == "indices" else args.universe
    )
    order = [args.provider] if args.provider else list(config.providers)

    print(f"Market session : {session_state()}")
    print(f"Provider order : {', '.join(order)}")
    print(f"Universe       : {universe.label} ({len(universe)} constituents)")

    providers = build_providers(order)
    if not any(probe_provider(p, universe) for p in providers):
        print("\nFAIL  no broker could supply reference data")
        return 1

    print(f"\n=== Live service ({args.seconds}s) ===")
    service = LiveMarketDataService(
        universe=universe, config=config, providers=build_providers(order)
    ).start()

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(2)
            status = service.snapshot().status
            print(
                f"  state={status.state:<14} provider={status.provider or '-':<8} "
                f"source={status.source:<10} priced={status.priced_count}/"
                f"{status.requested_count} "
                f"last_tick={status.last_tick_at.strftime('%H:%M:%S') if status.last_tick_at else '-'}"
            )
    finally:
        status = service.snapshot().status
        service.stop()

    if status.source == SOURCE_WEBSOCKET:
        print(f"\nOK    {status.provider} websocket is delivering live ticks")
        return 0
    if status.priced_count:
        print(f"\nWARN  prices are coming from the REST fallback, not the websocket."
              f"\n      {status.detail}")
        return 0
    print(f"\nFAIL  no prices from any source. {status.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
