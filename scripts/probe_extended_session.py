"""Does any broker's live feed carry pre-open or post-close (closing auction) data? Read-only.

    python scripts/probe_extended_session.py --until 09:16     # start before 09:00
    python scripts/probe_extended_session.py --until 16:05     # start before 15:15
    python scripts/probe_extended_session.py --seconds 20      # quick check that it works

Leave it running through the window. Every second, for each configured broker
(Groww is skipped: its subscription ended), it samples the websocket's latest
price and day open/high/low/volume for a handful of liquid stocks, and every
30 s it also takes a REST price snapshot. A row is written only when something
changed, to ``data/extended_session_probe.csv`` (git-ignored scratch output):

    time,provider,source,symbol,ltp,open,high,low,volume

The windows that matter are pre-open (09:00-09:15) and the closing auction
session, CAS (15:15-15:30). After 15:30 is post-market settlement, of less
interest. The summary at the end answers, per broker: did the feed tick before
09:15, did it tick during CAS, did it tick after 15:30, and did volume move
during CAS? A broker that sends nothing in those windows simply does not
provide the data. Results go in
docs/PROVIDER_COMPARISON_LOG.md.

Never prints tokens. Places no orders.
"""
import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from market.config import HeatmapConfig  # noqa: E402
from market.market_hours import now_ist, session_state  # noqa: E402
from market.providers.registry import build_providers  # noqa: E402
from market.universe import DEFAULT_UNIVERSE_KEY, get_universe  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "extended_session_probe.csv")
SKIP = {"groww"}
SAMPLE = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "ITC", "LT"]
REST_EVERY = 30
CLOSE = dtime(15, 30)
CAS_START = dtime(15, 15)
OPEN = dtime(9, 15)

FIELDS = ["time", "provider", "source", "symbol", "ltp", "open", "high", "low", "volume"]


def parse_until(text: str) -> datetime:
    hour, minute = (int(part) for part in text.split(":"))
    return now_ist().replace(hour=hour, minute=minute, second=0, microsecond=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until", help="Stop at this IST time, HH:MM")
    parser.add_argument("--seconds", type=int, default=0, help="Or stop after this many seconds")
    parser.add_argument("--provider", help="Probe only this broker")
    args = parser.parse_args()
    if not args.until and not args.seconds:
        parser.error("give --until HH:MM or --seconds N")
    logging.basicConfig(level=logging.WARNING)

    stop_at = parse_until(args.until) if args.until else None
    wait = args.seconds or max((stop_at - now_ist()).total_seconds(), 0)
    deadline = time.monotonic() + wait

    names = [args.provider] if args.provider else [
        n for n in HeatmapConfig.from_env().providers if n not in SKIP]
    universe = get_universe(DEFAULT_UNIVERSE_KEY)
    symbols = [s for s in SAMPLE if s in universe.symbols]

    live = []
    for provider in build_providers(names):
        if not provider.is_configured():
            print(f"{provider.label}: not configured, skipped")
            continue
        try:
            provider.connect()
            resolved, _ = provider.resolve_instruments(symbols, segment=universe.segment)
            refs = list(resolved.values())
            feed = provider.open_feed(refs)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"{provider.label}: could not start ({type(exc).__name__}: {exc})")
            continue
        live.append((provider, refs, feed))
        print(f"{provider.label}: watching {len(refs)} stocks")
    if not live:
        print("No broker started.")
        return 1

    print(f"Session now: {session_state()}. Writing {OUT_PATH}. Ctrl+C to stop early.")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    fresh = not os.path.exists(OUT_PATH)
    last = {}
    stats = {p.label: {"rows": 0, "pre_open": 0, "cas": 0, "cas_volume": 0, "post_close": 0,
                       "first": None, "last": None} for p, _, _ in live}
    last_volume = {}
    next_rest = 0.0

    with open(OUT_PATH, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if fresh:
            writer.writerow(FIELDS)
        try:
            while time.monotonic() < deadline:
                now = now_ist()
                clock = now.time()
                do_rest = time.monotonic() >= next_rest
                if do_rest:
                    next_rest = time.monotonic() + REST_EVERY
                for provider, refs, feed in live:
                    label = provider.label
                    prices, bars = feed.latest_prices(), feed.day_bars()
                    samples = [("socket", prices)]
                    if do_rest:
                        try:
                            samples.append(("rest", provider.get_ltp_snapshot(refs)))
                        except Exception as exc:  # noqa: BLE001
                            print(f"{label}: REST snapshot failed ({type(exc).__name__})")
                    for source, snapshot in samples:
                        for symbol, ltp in snapshot.items():
                            bar = bars.get(symbol) if source == "socket" else None
                            key = (label, source, symbol)
                            state = (ltp, bar.open if bar else None, bar.high if bar else None,
                                     bar.low if bar else None, bar.volume if bar else None)
                            if last.get(key) == state:
                                continue
                            last[key] = state
                            writer.writerow([now.strftime("%H:%M:%S"), label, source, symbol, *state])
                            s = stats[label]
                            s["rows"] += 1
                            s["first"] = s["first"] or now.strftime("%H:%M:%S")
                            s["last"] = now.strftime("%H:%M:%S")
                            if clock < OPEN:
                                s["pre_open"] += 1
                            if CAS_START <= clock < CLOSE:
                                s["cas"] += 1
                            if clock >= CLOSE:
                                s["post_close"] += 1
                            if clock >= CAS_START:
                                volume = state[4]
                                if volume is not None and volume != last_volume.get(key):
                                    if key in last_volume and clock < CLOSE:
                                        s["cas_volume"] += 1
                                    last_volume[key] = volume
                    handle.flush()
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopped early.")
        finally:
            for _, _, feed in live:
                try:
                    feed.close()
                except Exception:  # noqa: BLE001
                    pass

    print("\nSummary (rows = a price or volume change was seen):")
    print(f"{'broker':>10} {'rows':>6} {'before 09:15':>13} {'CAS 15:15-30':>13} {'volume moved in CAS':>20} {'after 15:30':>12}  first..last")
    for label, s in stats.items():
        print(f"{label:>10} {s['rows']:>6} {s['pre_open']:>13} {s['cas']:>13} "
              f"{s['cas_volume']:>20} {s['post_close']:>12}  {s['first']}..{s['last']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
