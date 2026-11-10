"""Record what Dhan and Groww send around NSE's opening and closing auctions. Read-only.

    python scripts/debug/capture_auctions.py            # waits for the next window, records it, exits
    python scripts/debug/capture_auctions.py --now 120  # record 120 s straight away (a smoke test)

Runs on Railway: inside the dashboards service, started by the ``auction-capture`` cron service through
``scripts/job_trigger.py`` (POST /capture) at 08:55 and 14:55 IST on weekdays. Also runs locally by hand.

Windows (IST, trading days): 08:59-09:16 around the pre-open call auction (orders 09:00-09:08,
the price is discovered at about 09:08, trading starts 09:15), and 15:14-15:32 around the close.
Started outside both, it waits for the next one today; after 15:32 it exits.

Every 15 s, one pass records, for 10 liquid stocks and the Nifty index:

* Dhan REST ``/marketfeed/quote`` (one batched call): last price, OHLC close, last trade time;
* Groww ``get_ltp`` (one batched call) and ``get_quote`` for RELIANCE and NIFTY (two calls), which
  carry the last trade time;
* the latest prices held by a Dhan and a Groww websocket (one connection each, opened at the
  start; reading them costs nothing).

That is 4 REST calls per 15 s, about 280 for a whole window. Each pass is one JSON line in
``data/captures/auction-<date>-<open|close>.jsonl`` (on the server's volume) and, as a ``PASS {...}``
line, to the log; progress and errors go to the ``.log`` file beside it. Questions it answers: docs/PLAN_PRE_MARKET.md.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from market.market_hours import IST, now_ist  # noqa: E402
from market.providers.base import SEGMENT_CASH, SEGMENT_INDEX  # noqa: E402

STOCKS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ITC", "LT",
          "AXISBANK"]
INDEX = "NIFTY"
QUOTED_ON_GROWW = ["RELIANCE", INDEX]  # get_quote is one call per symbol: keep it to two
WINDOWS = {"open": (dtime(8, 59), dtime(9, 16)), "close": (dtime(15, 14), dtime(15, 32))}
EVERY_S = 15
OUT_DIR = os.path.join(ROOT, "data", "captures")

logger = logging.getLogger("capture")


def safe(label, fn, errors):
    """Run one broker call; a failure is recorded, never fatal."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the capture carries on
        errors[label] = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("%s failed: %s", label, errors[label])
        return None


class Brokers:
    def __init__(self):
        from market.providers.registry import build_providers

        self.dhan = self.groww = None
        self.refs = {}
        self.feeds = {}
        self.groww_api = None
        for provider in build_providers(["dhan", "groww"]):
            errors = {}
            if safe(f"{provider.name} connect", provider.connect, errors) is None and errors:
                continue
            refs, missing = safe(f"{provider.name} instruments", lambda: provider.resolve_instruments(
                STOCKS, segment=SEGMENT_CASH), errors) or ({}, STOCKS)
            index, _ = safe(f"{provider.name} index", lambda: provider.resolve_instruments(
                [INDEX], segment=SEGMENT_INDEX), errors) or ({}, [])
            if not refs and not index:
                continue
            self.refs[provider.name] = list(refs.values()) + list(index.values())
            setattr(self, provider.name, provider)
            logger.info("%s: %d instruments (missing %s)", provider.label, len(self.refs[provider.name]),
                        ", ".join(missing) or "none")
        if self.groww is not None:
            from groww_api import GrowwAPIClient

            # The SDK object behind our wrapper; only it has get_quote (with the trade time).
            wrapper = GrowwAPIClient.get_instance()
            self.groww_api = next((v for v in vars(wrapper).values() if type(v).__name__ == "GrowwAPI"), None)

    def open_feeds(self):
        for name in ("dhan", "groww"):
            provider = getattr(self, name)
            if provider is not None:
                errors = {}
                feed = safe(f"{name} websocket", lambda: provider.open_feed(self.refs[name]), errors)
                if feed is not None:
                    self.feeds[name] = feed
                    logger.info("%s websocket open", provider.label)

    def close_feeds(self):
        for feed in self.feeds.values():
            try:
                feed.close()
            except Exception:  # noqa: BLE001
                pass

    def sample(self) -> dict:
        errors, row = {}, {"at": now_ist().isoformat(timespec="seconds")}
        if self.dhan is not None:
            quotes = safe("dhan quote", lambda: self.dhan._post_marketfeed(
                "quote", self.refs["dhan"], strict=True), errors) or {}
            row["dhan_rest"] = {
                symbol: {"ltp": q.get("last_price"), "close": (q.get("ohlc") or {}).get("close"),
                         "open": (q.get("ohlc") or {}).get("open"), "ltt": q.get("last_trade_time"),
                         "volume": q.get("volume")}
                for symbol, q in quotes.items()}
        if self.groww is not None:
            row["groww_ltp"] = safe("groww ltp", lambda: self.groww.get_ltp_snapshot(
                [r for r in self.refs["groww"] if r.symbol != INDEX]), errors)
            row["groww_quote"] = {}
            for symbol in QUOTED_ON_GROWW:
                quote = safe(f"groww quote {symbol}", lambda: self.groww_api.get_quote(
                    exchange="NSE", segment="CASH", trading_symbol=symbol), errors)
                if quote:
                    ltt = quote.get("last_trade_time")
                    row["groww_quote"][symbol] = {
                        "ltp": quote.get("last_price"), "ohlc": quote.get("ohlc"),
                        "ltt": ltt, "ltt_ist": epoch_ist(ltt), "volume": quote.get("volume")}
        for name, feed in self.feeds.items():
            prices = safe(f"{name} websocket read", feed.latest_prices, errors)
            row[f"{name}_ws"] = {"alive": bool(feed.is_alive), "prices": prices}
        if errors:
            row["errors"] = errors
        return row


def epoch_ist(value):
    """Groww's trade time (epoch seconds, or milliseconds) as IST text; None when unreadable."""
    try:
        seconds = float(value)
        return datetime.fromtimestamp(seconds / 1000 if seconds > 1e11 else seconds, IST).isoformat(
            timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def next_window(now: datetime, only: str = None):
    """``(name, start, end)`` of the window now is in or comes next today; None when it is over.

    ``only`` limits it to one window, so a task started late never wanders into the other one
    (which has its own task)."""
    for name, (start, end) in WINDOWS.items():
        if only and name != only:
            continue
        start_at = now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        end_at = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        if now < end_at:
            return name, max(start_at, now), end_at
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", type=int, metavar="SECONDS", help="record this long right away (smoke test)")
    parser.add_argument("--window", choices=sorted(WINDOWS), help="only this window (what the scheduled tasks use)")
    args = parser.parse_args(argv)

    now = now_ist()
    if args.now:
        name, start, end = "test", now, now + timedelta(seconds=args.now)
    else:
        if now.weekday() >= 5:
            print("Weekend - nothing to capture.")
            return 0
        window = next_window(now, args.window)
        if window is None:
            print("The window is over for today." if args.window else "Both windows are over for today.")
            return 0
        name, start, end = window

    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.join(OUT_DIR, f"auction-{start:%Y-%m-%d}-{name}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s",
                        handlers=[logging.FileHandler(stem + ".log", encoding="utf-8"), logging.StreamHandler()])
    for noisy in ("market", "growwapi", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    wait = (start - now_ist()).total_seconds() - 60  # log in a minute early
    if wait > 0:
        logger.info("Waiting %.0f s for the %s window (%s-%s)", wait, name, f"{start:%H:%M}", f"{end:%H:%M}")
        time.sleep(wait)

    brokers = Brokers()
    brokers.open_feeds()
    while now_ist() < start:
        time.sleep(1)
    logger.info("Recording the %s window to %s.jsonl, every %d s until %s", name, stem, EVERY_S, f"{end:%H:%M}")
    passes = 0
    try:
        with open(stem + ".jsonl", "a", encoding="utf-8") as out:
            while now_ist() < end:
                began = time.monotonic()
                line = json.dumps(brokers.sample(), default=str)
                out.write(line + "\n")
                out.flush()
                # Also to the log: on Railway the container log is the easy way to read it back.
                logger.info("PASS %s", line)
                passes += 1
                time.sleep(max(0.0, EVERY_S - (time.monotonic() - began)))
    finally:
        brokers.close_feeds()
        logger.info("Done: %d passes", passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
