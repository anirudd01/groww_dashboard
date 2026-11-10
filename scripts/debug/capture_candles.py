"""Capture raw candles from Kite, Groww and Dhan into one SQLite file, for side-by-side analysis.

    python scripts/debug/capture_candles.py [--end 2026-11-06] [--days 7] [--daily-days 30]
                                            [--symbols RELIANCE,TCS,...] [--db data/provider_compare.db]

Stores every candle each broker returns - nothing filtered, so Groww's pre-open (09:0x, volume only)
and 15:15-15:59 bars are kept - in table ``candles``:

    run_id, broker, interval ('1m' | '1d'), symbol, label ('YYYY-MM-DD HH:MM' IST, or 'YYYY-MM-DD'),
    open, high, low, close, volume

and the broker's untouched JSON body per request in ``raw_responses`` (for checking the parser).
Each run gets a new run_id (UTC time), so runs can be compared. Read-only against the brokers.
Needs today's Kite session (scripts/kite_login.py) and the Dhan/Groww credentials in .env.
Analyse with scripts/debug/analyze_candle_diffs.py. The .db is personal-free market data, but keep
it out of git (data/ files are not committed).
"""
import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"), override=True)

IST = timezone(timedelta(hours=5, minutes=30))
SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (run_id TEXT, broker TEXT, interval TEXT, symbol TEXT, label TEXT,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (run_id, broker, interval, symbol, label));
CREATE TABLE IF NOT EXISTS raw_responses (run_id TEXT, broker TEXT, interval TEXT, symbol TEXT, body TEXT);
"""


def args():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--end", help="last session (default: last weekday before today)")
    ap.add_argument("--days", type=int, default=7, help="calendar days of 1-minute bars (max 30: Groww's limit)")
    ap.add_argument("--daily-days", type=int, default=30, help="calendar days of daily candles")
    ap.add_argument("--symbols", default="RELIANCE,TCS,HDFCBANK,INFY,SBIN")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "provider_compare.db"))
    return ap.parse_args()


def main():
    a = args()
    if a.end:
        end_day = datetime.strptime(a.end, "%Y-%m-%d").date()
    else:
        end_day = datetime.now(IST).date() - timedelta(days=1)
        while end_day.weekday() >= 5:
            end_day -= timedelta(days=1)
    end = datetime.combine(end_day, datetime.min.time(), IST).replace(hour=16)
    m_start = (end - timedelta(days=a.days)).replace(hour=9, minute=0)
    d_start = (end - timedelta(days=a.daily_days)).replace(hour=9, minute=0)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    db = sqlite3.connect(a.db)
    db.executescript(SCHEMA)

    def store(broker, interval, sym, rows, body):
        db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                       [(run_id, broker, interval, sym, lab, *vals) for lab, vals in rows])
        db.execute("INSERT INTO raw_responses VALUES (?,?,?,?,?)", (run_id, broker, interval, sym, json.dumps(body)))
        print(f"  {broker:5} {interval} {sym:9} {len(rows):5} candles", flush=True)

    def lab(dt, daily):
        dt = dt.replace(tzinfo=IST) if dt.tzinfo is None else dt
        return dt.astimezone(IST).strftime("%Y-%m-%d" if daily else "%Y-%m-%d %H:%M")

    # Kite (reference): ids from the public NSE instrument list; exchange_token = Dhan security id
    from market.providers.kite import KiteProvider
    kp = KiteProvider()
    kp.connect()
    kh = kp.auth_headers()
    nse = list(csv.DictReader(io.StringIO(requests.get("https://api.kite.trade/instruments/NSE", timeout=60).text)))
    ref = {r["tradingsymbol"]: r for r in nse if r["segment"] == "NSE" and r["tradingsymbol"] in syms}

    from market.providers.dhan import DhanProvider
    dp = DhanProvider()
    dp.connect()
    dh = dp.auth_headers()
    from groww_api.client import GrowwAPIClient
    groww = GrowwAPIClient().session

    def retry(fn, *a, **k):
        """Brokers' history endpoints time out now and then (Groww often); 3 tries, 30 s each."""
        for attempt in range(3):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"    retry after {type(e).__name__}", flush=True)
                time.sleep(3)

    fmt = "%Y-%m-%d %H:%M:%S"
    for interval, start, kite_iv, groww_iv in (("1m", m_start, "minute", "1minute"), ("1d", d_start, "day", "1day")):
        daily = interval == "1d"
        print(f"{interval}: {start:%Y-%m-%d} .. {end:%Y-%m-%d}")
        for s in syms:
            r = retry(requests.get, f"https://api.kite.trade/instruments/historical/{ref[s]['instrument_token']}/{kite_iv}",
                             headers=kh, params={"from": start.strftime(fmt), "to": end.strftime(fmt)}, timeout=30)
            body = r.json()
            store("kite", interval, s, [(lab(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z"), daily), c[1:6])
                                        for c in (body.get("data") or {}).get("candles") or []], body)
            time.sleep(0.35)

            body = retry(groww.get_historical_candles, "NSE", "CASH", f"NSE-{s}", start.strftime(fmt), end.strftime(fmt),
                                                groww_iv, timeout=30)
            store("groww", interval, s, [(lab(datetime.fromisoformat(str(c[0])), daily), tuple(c[1:6]))
                                         for c in (body or {}).get("candles") or []], body)
            time.sleep(0.4)

            payload = {"securityId": ref[s]["exchange_token"], "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
                       "oi": False}
            if daily:
                url = "https://api.dhan.co/v2/charts/historical"
                payload.update(expiryCode=0, fromDate=start.strftime("%Y-%m-%d"),
                               toDate=(end + timedelta(days=1)).strftime("%Y-%m-%d"))
            else:
                url = "https://api.dhan.co/v2/charts/intraday"
                payload.update(interval="1", fromDate=start.strftime(fmt), toDate=end.strftime(fmt))
            body = retry(requests.post, url, headers=dh, json=payload, timeout=30).json()
            store("dhan", interval, s, [(lab(datetime.fromtimestamp(t, IST), daily), (o, h, l, c, v)) for t, o, h, l, c, v in
                                        zip(body.get("timestamp", []), body.get("open", []), body.get("high", []),
                                            body.get("low", []), body.get("close", []), body.get("volume", []))], body)
            time.sleep(0.25)
        db.commit()
    db.close()
    print(f"run {run_id} stored in {a.db}")


if __name__ == "__main__":
    main()
