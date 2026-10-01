"""Compare 1-minute history across Kite, Groww, INDmoney and Dhan. Read-only.

    python scripts/compare_intraday_providers.py [--end 2026-09-25] [--out results.json]

For five liquid stocks it measures, per broker:
  1. the widest 1-minute window one call accepts (sweeps 7..90 days),
  2. seconds per call and stocks per call,
  3. every 1-minute OHLCV over the last 7 days against Kite, matched by
     **minute label** (never by position) and only inside the continuous
     session, 09:15-15:14. Bars at other times (pre-open, the 15:15-15:30
     closing auction window, post-close) are counted, not compared,
  4. whether each day's minute bars reproduce the official daily open/high/low
     (Kite's daily candle) and how much of the day's volume they hold,
  5. bars per day and the first/last bar time,
  6. label alignment: the bar-label shift (-2..+2 minutes) at which each broker
     agrees best with Kite. 0 means the same open-time labelling; anything else
     means a mismatch is a time offset, not a price difference.

A broker whose token is missing or rejected is skipped with a note, so the
script runs with whatever is logged in. Needs a Kite session (the reference).
Results are logged in docs/PROVIDER_COMPARISON_LOG.md. Never prints tokens.
"""
import argparse, csv, io, json, os, sys, time
from collections import Counter
from datetime import datetime, timedelta, timezone
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except ImportError:
    pass

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--end", default=None, help="last session date to test (default: most recent weekday before today)")
ap.add_argument("--out", help="also write the full results as JSON to this path")
ARGS = ap.parse_args()

IST = timezone(timedelta(hours=5, minutes=30))
#: The continuous session, by bar label. Kite and Dhan bars stop at 15:14; the
#: 15:15-15:30 closing-auction (CAS) window has no ordinary bars.
SESSION_FIRST, SESSION_LAST = "09:15", "15:14"


def in_session(ts):
    """True for a 'YYYY-MM-DD HH:MM' label inside the continuous session."""
    return SESSION_FIRST <= ts[11:] <= SESSION_LAST


def shifted(ts, minutes):
    return (datetime.strptime(ts, "%Y-%m-%d %H:%M") + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


SYMS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "SBIN"]
WINDOWS = [7, 8, 15, 30, 31, 60, 61, 90, 91]
if ARGS.end:
    end_day = datetime.strptime(ARGS.end, "%Y-%m-%d").date()
else:
    end_day = datetime.now(IST).date() - timedelta(days=1)
    while end_day.weekday() >= 5:
        end_day -= timedelta(days=1)
END = datetime.combine(end_day, datetime.min.time(), IST).replace(hour=15, minute=30)

from market.providers.kite import KiteProvider  # noqa: E402

_kite = KiteProvider()
_kite.connect()  # today's saved login (python scripts/kite_login.py)
KH = _kite.auth_headers()
nse = list(csv.DictReader(io.StringIO(requests.get("https://api.kite.trade/instruments/NSE", timeout=60).text)))
ref = {r["tradingsymbol"]: r for r in nse if r["segment"] == "NSE" and r["tradingsymbol"] in SYMS}
KT = {s: ref[s]["instrument_token"] for s in SYMS}
NT = {s: ref[s]["exchange_token"] for s in SYMS}  # NSE token = INDmoney / Dhan security id


def key(dt):
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M")


def span(start, end):
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


# -- fetchers: (syms, start, end) -> (status, {sym: {ts: (o,h,l,c,v)}}) -------------
def kite(syms, start, end):
    out, status = {}, 200
    for s in syms:
        a, b = span(start, end)
        r = requests.get(f"https://api.kite.trade/instruments/historical/{KT[s]}/minute", headers=KH,
                         params={"from": a, "to": b}, timeout=60)
        time.sleep(0.35)
        status = r.status_code if not r.ok else status
        out[s] = {key(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z")): tuple(c[1:6])
                  for c in (r.json().get("data") or {}).get("candles") or []} if r.ok else {}
    return status, out


IH = {}  # filled by available() from the shared INDmoney session


def indmoney(syms, start, end):
    out = {s: {} for s in syms}
    for k in range(0, len(syms), 5):
        batch = syms[k:k + 5]
        r = requests.get("https://api.indstocks.com/market/historical/1minute", headers=IH, timeout=60, params={
            "scrip-codes": ",".join(f"NSE_{NT[s]}" for s in batch),
            "start_time": int(start.timestamp() * 1000), "end_time": int(end.timestamp() * 1000)})
        time.sleep(0.25)
        if not r.ok:
            return r.status_code, out
        by_code = {f"NSE_{NT[s]}": s for s in batch}
        for code, block in (r.json().get("data") or {}).items():
            for c in (block or {}).get("candles") or []:
                ts = c["ts"] / 1000 if c["ts"] > 1e11 else c["ts"]
                out[by_code[code]][key(datetime.fromtimestamp(ts, IST))] = (c["o"], c["h"], c["l"], c["c"], c["v"])
    return 200, out


GROWW = None


def groww(syms, start, end):
    out = {}
    for s in syms:
        body = None
        for attempt in range(3):  # 2026-09-27: one 30 s read timeout, fine on retry
            try:
                body = GROWW.get_historical_candles("NSE", "CASH", f"NSE-{s}", *span(start, end), "1minute", timeout=60)
                break
            except Exception as e:  # noqa: BLE001
                code = getattr(e, "code", None)
                if code:
                    return code, out
                time.sleep(3)
        bars = {}
        for c in (body or {}).get("candles") or []:
            if c[1] is None:  # pre-open minutes carry volume only
                continue
            dt = datetime.fromisoformat(str(c[0]))
            bars[key(dt.replace(tzinfo=IST) if dt.tzinfo is None else dt)] = tuple(c[1:6])
        out[s] = bars
        time.sleep(0.4)
    return 200, out


DH = {}  # filled by available() from the shared Dhan session


def dhan(syms, start, end):
    out = {}
    for s in syms:
        a, b = span(start, end)
        r = requests.post("https://api.dhan.co/v2/charts/intraday", headers=DH,
                          json={"securityId": NT[s], "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
                                "interval": "1", "oi": False, "fromDate": a, "toDate": b}, timeout=60)
        time.sleep(0.25)
        if not r.ok:
            return r.status_code, out
        d = r.json()
        out[s] = {key(datetime.fromtimestamp(t, IST)): (o, h, l, c, v) for t, o, h, l, c, v in
                  zip(d.get("timestamp", []), d.get("open", []), d.get("high", []), d.get("low", []),
                      d.get("close", []), d.get("volume", []))}
    return 200, out


def available():
    """Which brokers can be tested right now."""
    ok = {"kite": kite}
    from market.providers.indmoney import IndMoneyProvider
    ind_provider = IndMoneyProvider()
    if not ind_provider.is_configured():
        print("indmoney: skipped (set IND_MONEY_CLIENT_ID, IND_MONEY_MPIN and IND_MONEY_TOTP_SECRET in .env)")
    else:
        try:
            ind_provider.connect()  # saved token, or a new one from TOTP
            IH.update(ind_provider.auth_headers())
            ok["indmoney"] = indmoney
        except RuntimeError as e:
            print("indmoney: skipped", str(e)[:160])
    global GROWW
    try:
        from groww_api.client import GrowwAPIClient
        GROWW = GrowwAPIClient().session
        if GROWW:
            ok["groww"] = groww
    except Exception as e:  # noqa: BLE001
        print("groww: skipped", repr(e)[:100])
    from market.providers.dhan import DhanProvider
    dhan_provider = DhanProvider()
    if not dhan_provider.is_configured():
        print("dhan: skipped (set DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in .env)")
    else:
        try:
            dhan_provider.connect()  # saved token, or a new one from TOTP
            DH.update(dhan_provider.auth_headers())
            ok["dhan"] = dhan
        except RuntimeError as e:
            print("dhan: skipped", str(e)[:160])
    return ok


def summarise(bars):
    days = sorted({t[:10] for t in bars})
    return {"candles": len(bars), "days": len(days), "first": days[0] if days else None}


R = {"run_ist": datetime.now(IST).isoformat(timespec="seconds"), "end": END.isoformat(), "symbols": SYMS}
P = available()
print("testing:", ", ".join(P), "| window ends", END)

# 1-2. widest window, seconds per call (RELIANCE only; INDmoney's call is the 5-stock batch)
R["sweep"] = {}
for name, fn in P.items():
    R["sweep"][name] = {}
    for w in WINDOWS:
        start = (END - timedelta(days=w)).replace(hour=9, minute=15)
        syms = SYMS if name == "indmoney" else ["RELIANCE"]
        t0 = time.time()
        status, out = fn(syms, start, END)
        R["sweep"][name][w] = {"status": status, **summarise(out.get("RELIANCE", {})), "sec": round(time.time() - t0, 2)}
    print(name, {w: (v["status"], v["days"]) for w, v in R["sweep"][name].items()})

# 3. field-by-field agreement with Kite, last 7 days
start = (END - timedelta(days=7)).replace(hour=9, minute=15)
bars = {name: fn(SYMS, start, END)[1] for name, fn in P.items()}
R["vs_kite"] = {}
for name in P:
    if name == "kite":
        continue
    n, eq, only_k, only_o, outside = 0, [0] * 5, 0, 0, 0
    for s in SYMS:
        full = bars[name].get(s, {})
        outside += sum(not in_session(t) for t in full)
        k = {t: v for t, v in bars["kite"].get(s, {}).items() if in_session(t)}
        o = {t: v for t, v in full.items() if in_session(t)}
        only_k += len(k.keys() - o.keys()); only_o += len(o.keys() - k.keys())
        for t in k.keys() & o.keys():
            n += 1
            for i in range(5):
                eq[i] += abs(float(k[t][i]) - float(o[t][i] or 0)) < 0.001
    R["vs_kite"][name] = {"common": n, "only_kite": only_k, "only_other": only_o, "bars_outside_session": outside,
                          **{f: round(e / n * 100, 1) if n else None for f, e in zip("OHLCV", eq)}}
    print(name, "vs kite (% equal):", R["vs_kite"][name])

# 3b. label alignment: which shift of the other broker's labels agrees best with Kite
R["alignment"] = {}
for name in P:
    if name == "kite":
        continue
    scores = {}
    for m in (-2, -1, 0, 1, 2):
        hit = tot = 0
        for s in SYMS:
            k = {t: v for t, v in bars["kite"].get(s, {}).items() if in_session(t)}
            o = bars[name].get(s, {})
            for t, v in k.items():
                w = o.get(shifted(t, m))
                if w is not None:
                    tot += 1
                    hit += abs(float(v[3]) - float(w[3])) < 0.001
        scores[m] = round(hit / tot * 100, 1) if tot else None
    best = max((m for m in scores if scores[m] is not None), key=lambda m: scores[m], default=None)
    R["alignment"][name] = {"close_equal_pct_by_shift": scores, "best_shift_minutes": best}
    print(name, "label alignment (close-equal % by shift):", scores, "-> best shift", best)

# 4. minute bars vs the official daily candle
daily = {}
for s in SYMS:
    r = requests.get(f"https://api.kite.trade/instruments/historical/{KT[s]}/day", headers=KH, timeout=30,
                     params={"from": start.strftime("%Y-%m-%d 00:00:00"), "to": END.strftime("%Y-%m-%d 23:59:59")})
    daily[s] = {c[0][:10]: c for c in r.json()["data"]["candles"]}
    time.sleep(0.35)
R["vs_daily"] = {}
for name in P:
    n, o_, h_, l_, vol = 0, 0, 0, 0, []
    for s in SYMS:
        for d, c in daily[s].items():
            day = sorted((t, v) for t, v in bars[name].get(s, {}).items() if t.startswith(d) and in_session(t))
            if not day:
                continue
            n += 1
            o_ += abs(day[0][1][0] - c[1]) < 0.001
            h_ += abs(max(v[1] for _, v in day) - c[2]) < 0.001
            l_ += abs(min(v[2] for _, v in day) - c[3]) < 0.001
            vol.append(round(sum(int(v[4] or 0) for _, v in day) / c[5] * 100, 1))
    # Volume below 100% is expected: the daily candle also holds the 15:15-15:30 auction volume.
    R["vs_daily"][name] = {"stock_days": n, "open": o_, "high": h_, "low": l_,
                           "volume_pct_range": [min(vol), max(vol)] if vol else None}
    print(name, "vs official daily:", R["vs_daily"][name])

# 5. bars per day, first/last bar
R["shape"] = {}
for name in P:
    b = bars[name].get("RELIANCE", {})
    per_day = Counter(t[:10] for t in b)
    R["shape"][name] = {"bars_per_day": dict(sorted(per_day.items())),
                        "first": min((t[11:] for t in b), default=None), "last": max((t[11:] for t in b), default=None)}
    print(name, "RELIANCE bars/day", list(per_day.values()), "first", R["shape"][name]["first"], "last", R["shape"][name]["last"])

if ARGS.out:
    json.dump(R, open(ARGS.out, "w"), indent=1, default=str)
    print("wrote", ARGS.out)
