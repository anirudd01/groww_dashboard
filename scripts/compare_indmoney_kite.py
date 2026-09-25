"""Compare INDmoney and Kite daily data for the F&O universe. Read-only.

    python scripts/compare_indmoney_kite.py [--days 45] [--out results.json]

Needs a valid Kite session (python scripts/kite_login.py) and
IND_MONEY_ACCESS_TOKEN in .env. Checks the instrument mapping, every daily
candle field, one live bulk snapshot per broker, and the gaps and movers
derived from each. Prints a summary and optionally writes the full JSON.
Never prints tokens. Results are logged in docs/PROVIDER_COMPARISON_LOG.md.
"""
import argparse, csv, io, json, os, re, sys, time, statistics
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
import requests

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--days", type=int, default=45, help="calendar days of daily candles (default 45)")
ap.add_argument("--out", help="also write the full results as JSON to this path")
ARGS = ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = ARGS.out
IST = timezone(timedelta(hours=5, minutes=30))
env = open(os.path.join(ROOT, ".env"), encoding="utf-8").read()
ind_tok = re.search(r"^IND_MONEY_ACCESS_TOKEN=(.*)$", env, re.M).group(1).strip().strip('"\'')
ks = json.load(open(os.path.join(ROOT, ".kite_session.json")))
KH = {"X-Kite-Version": "3", "Authorization": f"token {ks['api_key']}:{ks['access_token']}"}
IH = {"Authorization": ind_tok}
KB, IB = "https://api.kite.trade", "https://api.indstocks.com"
universe = json.load(open(os.path.join(ROOT, "data", "fno_universe.json")))["tokens"]   # symbol -> kite instrument_token
SYMS = sorted(universe)
R = {"run_started_ist": datetime.now(IST).isoformat(timespec="seconds"), "universe": len(SYMS)}
print("universe:", len(SYMS))

_last = defaultdict(float)
def gate(bucket, gap):
    w = _last[bucket] + gap - time.time()
    if w > 0: time.sleep(w)
    _last[bucket] = time.time()

stats = defaultdict(lambda: {"calls": 0, "errors": 0, "retries_429": 0, "retries_403": 0, "seconds": 0.0, "error_samples": []})
def call(provider, bucket, gap, url, headers, params=None):
    s = stats[f"{provider}:{bucket}"]
    for attempt in range(3):
        gate(f"{provider}:{bucket}", gap)
        t0 = time.time()
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
        except Exception as e:
            s["calls"] += 1; s["errors"] += 1; s["seconds"] += time.time() - t0
            s["error_samples"].append(repr(e)[:120]); continue
        s["calls"] += 1; s["seconds"] += time.time() - t0
        if r.status_code == 429:
            s["retries_429"] += 1; time.sleep(1.5); continue
        if r.status_code == 403 and provider == "indmoney" and attempt == 0:
            # 2026-09-25: one INDmoney batch got 403 TokenException mid-run while
            # the same token kept working, so retry once before believing it.
            s["retries_403"] += 1; time.sleep(1.5); continue
        if not r.ok:
            s["errors"] += 1
            if len(s["error_samples"]) < 5: s["error_samples"].append(f"{r.status_code} {r.text[:120]}")
        return r
    return None

# ---------------------------------------------------------------- 1. mapping
t0 = time.time()
kite_nse = list(csv.DictReader(io.StringIO(requests.get(KB + "/instruments/NSE", timeout=60).text)))
k_by_token = {r["instrument_token"]: r for r in kite_nse}
ind_eq = list(csv.DictReader(io.StringIO(requests.get(IB + "/market/instruments", headers=IH,
                                                      params={"source": "equity"}, timeout=60).text)))
ind_nse = {}
for r in ind_eq:
    if r["EXCH"] == "NSE" and r.get("SERIES", "").strip() in ("EQ", "BE", ""):
        ind_nse.setdefault(r["TRADING_SYMBOL"].strip(), r)
mapping, unmapped, id_mismatch = {}, [], []
for sym in SYMS:
    k = k_by_token.get(universe[sym])
    i = ind_nse.get(sym)
    if not i:
        # fall back to SYMBOL_NAME match, NSE EQ
        i = next((r for r in ind_eq if r["EXCH"] == "NSE" and r["SYMBOL_NAME"].strip() == sym), None)
    if not i:
        unmapped.append(sym); continue
    mapping[sym] = i["SECURITY_ID"]
    if k and k["exchange_token"] != i["SECURITY_ID"]:
        id_mismatch.append((sym, k["exchange_token"], i["SECURITY_ID"]))
R["mapping"] = {"indmoney_found": len(mapping), "unmapped": unmapped, "nse_token_mismatch": id_mismatch,
                "seconds": round(time.time() - t0, 1)}
print("mapping:", R["mapping"])

# ---------------------------------------------------------------- 2. daily candles
today = datetime.now(IST).date()
start = today - timedelta(days=ARGS.days)
kite_c, ind_c = {}, {}
t0 = time.time()
for sym in SYMS:
    r = call("kite", "historical", 0.35, f"{KB}/instruments/historical/{universe[sym]}/day", KH,
             {"from": f"{start} 00:00:00", "to": f"{today} 23:59:59"})
    rows = {}
    if r is not None and r.ok:
        for c in (r.json().get("data") or {}).get("candles") or []:
            rows[c[0][:10]] = {"o": c[1], "h": c[2], "l": c[3], "c": c[4], "v": c[5]}
    kite_c[sym] = rows
R["kite_candles_seconds"] = round(time.time() - t0, 1)
print("kite candles done", R["kite_candles_seconds"], "s")

def ind_date(ts):
    ts = ts / 1000 if ts > 1e11 else ts
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()

t0 = time.time()
shape_seen = None
syms_m = [s for s in SYMS if s in mapping]
st_ms = int(datetime.combine(start, datetime.min.time(), IST).timestamp() * 1000)
en_ms = int((datetime.now(IST) + timedelta(minutes=1)).timestamp() * 1000)
for k in range(0, len(syms_m), 5):
    batch = syms_m[k:k + 5]
    codes = ",".join(f"NSE_{mapping[s]}" for s in batch)
    r = call("indmoney", "historical", 0.25, f"{IB}/market/historical/1day", IH,
             {"scrip-codes": codes, "start_time": st_ms, "end_time": en_ms})
    if r is None or not r.ok:
        for s in batch: ind_c[s] = {}
        continue
    body = r.json()
    data = body.get("data")
    if shape_seen is None:
        shape_seen = (type(data).__name__, list(data)[:3] if isinstance(data, dict) else None)
    for s in batch:
        key = f"NSE_{mapping[s]}"
        entry = data.get(key) if isinstance(data, dict) else None
        candles = entry.get("candles") if isinstance(entry, dict) else entry
        rows = {}
        for c in candles or []:
            rows[ind_date(c["ts"])] = {"o": c.get("o"), "h": c.get("h"), "l": c.get("l"), "c": c.get("c"), "v": c.get("v")}
        ind_c[s] = rows
R["indmoney_candles_seconds"] = round(time.time() - t0, 1)
R["indmoney_hist_shape"] = shape_seen
print("indmoney candles done", R["indmoney_candles_seconds"], "s; shape", shape_seen)

TICK = 0.05
today_s = today.isoformat()
fields = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
cmp = {f: {"compared": 0, "exact": 0, "within_1_tick": 0, "worse": 0, "max_abs_diff": 0.0, "worst": []} for f in fields}
only_k, only_i, both_days = [], [], 0
empty_k = [s for s in SYMS if not kite_c.get(s)]
empty_i = [s for s in syms_m if not ind_c.get(s)]
for s in syms_m:
    kd, idd = kite_c.get(s, {}), ind_c.get(s, {})
    for d in sorted(set(kd) | set(idd)):
        if d == today_s: continue
        if d not in idd: only_k.append((s, d)); continue
        if d not in kd: only_i.append((s, d)); continue
        both_days += 1
        for f in fields:
            a, b = kd[d][f], idd[d][f]
            if a is None or b is None: continue
            x = cmp[f]; x["compared"] += 1
            diff = abs(float(a) - float(b))
            if f == "v":
                rel = diff / max(float(a), 1)
                if diff == 0: x["exact"] += 1
                elif rel <= 0.001: x["within_1_tick"] += 1
                else: x["worse"] += 1; x["worst"].append((round(rel * 100, 3), s, d, a, b))
            else:
                if diff < 1e-6: x["exact"] += 1
                elif diff <= TICK + 1e-6: x["within_1_tick"] += 1
                else: x["worse"] += 1; x["worst"].append((round(diff, 2), s, d, a, b))
            x["max_abs_diff"] = max(x["max_abs_diff"], diff)
for f in cmp:
    cmp[f]["worst"] = sorted(cmp[f]["worst"], reverse=True)[:8]
dates_k = sorted({d for s in SYMS for d in kite_c.get(s, {}) if d != today_s})
dates_i = sorted({d for s in syms_m for d in ind_c.get(s, {}) if d != today_s})
R["candles"] = {"window": [start.isoformat(), today_s], "symbol_days_compared": both_days,
                "trading_days_kite": len(dates_k), "trading_days_indmoney": len(dates_i),
                "first_last_kite": [dates_k[:1], dates_k[-1:]], "first_last_indmoney": [dates_i[:1], dates_i[-1:]],
                "dates_only_kite": sorted(set(dates_k) - set(dates_i)), "dates_only_indmoney": sorted(set(dates_i) - set(dates_k)),
                "symbol_days_only_kite": len(only_k), "symbol_days_only_indmoney": len(only_i),
                "samples_only_kite": only_k[:10], "samples_only_indmoney": only_i[:10],
                "symbols_no_kite_candles": empty_k, "symbols_no_indmoney_candles": empty_i,
                "fields": cmp}
# today's in-progress candle
tk = sum(1 for s in syms_m if today_s in kite_c.get(s, {}))
ti = sum(1 for s in syms_m if today_s in ind_c.get(s, {}))
R["candles"]["today_candle_present"] = {"kite": tk, "indmoney": ti}
print("candles:", json.dumps({k: v for k, v in R["candles"].items() if k != "fields"}, default=str)[:900])
print("fields:", {f: {k: v for k, v in x.items() if k != "worst"} for f, x in cmp.items()})

# ---------------------------------------------------------------- 3. live snapshot
t_k = time.time()
rk = call("kite", "quote", 1.05, f"{KB}/quote/ohlc", KH, [("i", f"NSE:{s}") for s in SYMS])
t_i = time.time()
ri = call("indmoney", "quote", 0.25, f"{IB}/market/quotes/full", IH,
          {"scrip-codes": ",".join(f"NSE_{mapping[s]}" for s in syms_m)})
t_end = time.time()
kq = (rk.json().get("data") or {}) if rk is not None and rk.ok else {}
iq = (ri.json().get("data") or {}) if ri is not None and ri.ok else {}
snap = {"kite_http": getattr(rk, "status_code", None), "indmoney_http": getattr(ri, "status_code", None),
        "kite_returned": len(kq), "indmoney_returned": len(iq),
        "kite_call_s": round(t_i - t_k, 2), "indmoney_call_s": round(t_end - t_i, 2),
        "taken_at_ist": datetime.now(IST).isoformat(timespec="seconds")}
pc = {"exact": 0, "diff": []}; op = {"exact": 0, "diff": []}; lt = []
for s in syms_m:
    a, b = kq.get(f"NSE:{s}"), iq.get(f"NSE_{mapping[s]}")
    if not a or not b: continue
    if abs(a["ohlc"]["close"] - b["prev_close"]) < 1e-6: pc["exact"] += 1
    else: pc["diff"].append((s, a["ohlc"]["close"], b["prev_close"]))
    if abs(a["ohlc"]["open"] - b["day_open"]) < 1e-6: op["exact"] += 1
    else: op["diff"].append((s, a["ohlc"]["open"], b["day_open"]))
    if a["last_price"]: lt.append(abs(a["last_price"] - b["live_price"]) / a["last_price"] * 100)
snap["prev_close"] = {"exact": pc["exact"], "differ": len(pc["diff"]), "samples": pc["diff"][:8]}
snap["day_open"] = {"exact": op["exact"], "differ": len(op["diff"]), "samples": op["diff"][:8]}
snap["ltp_pct_diff"] = {"n": len(lt), "median": round(statistics.median(lt), 4) if lt else None,
                        "p95": round(sorted(lt)[int(len(lt) * .95) - 1], 4) if lt else None,
                        "max": round(max(lt), 4) if lt else None}
snap["kite_missing"] = [s for s in SYMS if f"NSE:{s}" not in kq][:20]
snap["indmoney_missing"] = [s for s in syms_m if f"NSE_{mapping[s]}" not in iq][:20]
# Also: does candle-derived previous close agree with snapshot prev close?
cand_prev = {}
for name, src in (("kite", kite_c), ("indmoney", ind_c)):
    ok = tot = 0
    for s in syms_m:
        days = sorted(d for d in src.get(s, {}) if d != today_s)
        b = iq.get(f"NSE_{mapping[s]}")
        if not days or not b: continue
        tot += 1; ok += abs(src[s][days[-1]]["c"] - b["prev_close"]) < 1e-6
    cand_prev[name] = f"{ok}/{tot}"
snap["last_stored_candle_close_equals_prev_close"] = cand_prev
R["snapshot"] = snap
print("snapshot:", json.dumps(snap, default=str)[:1500])

# ---------------------------------------------------------------- 4. gaps & movers
def series(src, s):
    return [(d, v) for d, v in sorted(src.get(s, {}).items()) if d != today_s]
def gaps(src):
    out = {}
    for s in syms_m:
        rows = series(src, s)
        for (d0, a), (d1, b) in zip(rows, rows[1:]):
            if a["c"] and b["o"] is not None:
                out[(s, d1)] = (b["o"] / a["c"] - 1) * 100
    return out
gk, gi = gaps(kite_c), gaps(ind_c)
common = set(gk) & set(gi)
gd = [abs(gk[x] - gi[x]) for x in common]
R["gaps"] = {"pairs": len(common), "max_pct_point_diff": round(max(gd), 4) if gd else None,
             "over_0.01pp": sum(1 for v in gd if v > 0.01),
             "same_sign": sum(1 for x in common if (gk[x] > 0) == (gi[x] > 0) or abs(gk[x]) < 1e-9)}
def movers(src, n_days):
    res = {}
    for s in syms_m:
        rows = series(src, s)
        if len(rows) > n_days:
            res[s] = (rows[-1][1]["c"] / rows[-1 - n_days][1]["c"] - 1) * 100
    top = sorted(res, key=res.get, reverse=True)[:10]; bot = sorted(res, key=res.get)[:10]
    return top, bot
mv = {}
for n in (1, 3, 5, 7, 20):
    (kt, kb), (it, ib) = movers(kite_c, n), movers(ind_c, n)
    mv[f"{n}d"] = {"top10_identical": kt == it, "bottom10_identical": kb == ib,
                   "top10_kite": kt[:5], "top10_indmoney": it[:5]}
R["movers"] = mv
print("gaps:", R["gaps"]); print("movers:", {k: (v["top10_identical"], v["bottom10_identical"]) for k, v in mv.items()})

R["cost"] = {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in stats.items()}
R["run_finished_ist"] = datetime.now(IST).isoformat(timespec="seconds")
print("cost:", json.dumps(R["cost"])[:800])
if OUT:
    json.dump(R, open(OUT, "w"), indent=1, default=str)
    print("wrote", OUT)
