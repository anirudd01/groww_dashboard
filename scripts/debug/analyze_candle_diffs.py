"""How, and by how much, Groww's and Dhan's candles differ from Kite's. Reads capture_candles.py output.

    python scripts/debug/analyze_candle_diffs.py [--db data/provider_compare.db] [--run RUN_ID] [--out report.txt]

For every field (open/high/low/close/volume), broker vs Kite, matched by label:
  - share exactly equal; size of the differences (rupees, basis points of price, percentiles);
    share within 1 / 5 / 10 paise (a decimals/rounding issue would sit inside a paisa or two);
    sign (is the broker mostly above or below Kite).
  - hypotheses, each as the share of the *mismatched* bars it explains exactly:
      open  = Kite's previous-minute close | Kite's next-minute open | broker's own previous close
      high/low = Kite's high/low of the minute before or after
      close = Kite's close of the minute before or after
      volume = Kite's volume of the minute before or after; per-day totals compared
  - 1-minute bars are compared inside 09:15-15:14 only; Groww's other bars (pre-open, 15:15-15:59)
    are summarised separately.
  - daily: each broker's daily candle vs Kite's, and Groww's daily candle vs what its own minute bars
    add up to, with and without its pre-open / closing-session bars.
"""
import argparse
import os
import sqlite3
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
F = ["open", "high", "low", "close", "volume"]
EPS = 1e-6


def pct(n, d):
    return f"{100 * n / d:5.1f}%" if d else "  n/a"


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))] if xs else float("nan")


def shift(label, m):
    return (datetime.strptime(label, "%Y-%m-%d %H:%M") + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M")


def in_session(label):
    return "09:15" <= label[11:] <= "15:14"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "provider_compare.db"))
    ap.add_argument("--run")
    ap.add_argument("--out")
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    run = a.run or db.execute("SELECT max(run_id) FROM candles").fetchone()[0]
    data = defaultdict(dict)  # (broker, interval, symbol) -> {label: (o,h,l,c,v)}
    for b, iv, s, lab, *vals in db.execute(
            "SELECT broker, interval, symbol, label, open, high, low, close, volume FROM candles WHERE run_id=?", (run,)):
        data[(b, iv, s)][lab] = tuple(vals)
    syms = sorted({k[2] for k in data})
    lines = []
    out = lines.append
    out(f"run {run}; symbols {', '.join(syms)}")

    for interval in ("1m", "1d"):
        out(f"\n================ {interval} ================")
        for broker in ("groww", "dhan"):
            out(f"\n--- {broker} vs kite ({interval}) ---")
            for fi, field in enumerate(F):
                n = eq = 0
                diffs, bps, above = [], [], 0
                within = [0, 0, 0]
                hyp = defaultdict(int)
                mism = 0
                for s in syms:
                    K, O = data[("kite", interval, s)], data[(broker, interval, s)]
                    for lab, kv in K.items():
                        if interval == "1m" and not in_session(lab):
                            continue
                        ov = O.get(lab)
                        if ov is None or ov[fi] is None:
                            continue
                        n += 1
                        d = float(ov[fi]) - float(kv[fi])
                        if abs(d) < EPS:
                            eq += 1
                            continue
                        mism += 1
                        diffs.append(abs(d))
                        above += d > 0
                        if field != "volume":
                            bps.append(abs(d) / float(kv[fi]) * 1e4)
                            for i, lim in enumerate((0.0101, 0.0501, 0.1001)):
                                within[i] += abs(d) <= lim
                        else:
                            bps.append(abs(d) / max(float(kv[fi]), 1) * 1e4)
                        if interval != "1m":
                            continue
                        prev_k, next_k = K.get(shift(lab, -1)), K.get(shift(lab, 1))
                        prev_o = O.get(shift(lab, -1))
                        x = float(ov[fi])

                        def hit(name, other_val):
                            if other_val is not None and abs(x - float(other_val)) < EPS:
                                hyp[name] += 1

                        if field == "open":
                            hit("= Kite prev-minute close", prev_k and prev_k[3])
                            hit("= Kite next-minute open", next_k and next_k[0])
                            hit("= own prev close", prev_o and prev_o[3])
                            hit("= Kite same-minute close", kv[3])
                        elif field in ("high", "low"):
                            hit(f"= Kite prev-minute {field}", prev_k and prev_k[fi])
                            hit(f"= Kite next-minute {field}", next_k and next_k[fi])
                            if field == "high":
                                hyp["above Kite high (wider bar)" if x > kv[1] else "below Kite high (narrower)"] += 1
                            else:
                                hyp["below Kite low (wider bar)" if x < kv[2] else "above Kite low (narrower)"] += 1
                        elif field == "close":
                            hit("= Kite prev-minute close", prev_k and prev_k[3])
                            hit("= Kite next-minute close", next_k and next_k[3])
                            hit("= Kite next-minute open", next_k and next_k[0])
                        else:
                            hit("= Kite prev-minute volume", prev_k and prev_k[4])
                            hit("= Kite next-minute volume", next_k and next_k[4])
                if not n:
                    out(f"{field:7} no common candles")
                    continue
                unit = "" if field == "volume" else "Rs"
                out(f"{field:7} n={n:6} equal {pct(eq, n)} | mismatched {mism}: "
                    f"median |diff| {unit}{q(diffs, .5):.4g}, p90 {unit}{q(diffs, .9):.4g}, max {unit}{max(diffs, default=0):.4g}; "
                    f"median {q(bps, .5):.2f} bps, p90 {q(bps, .9):.1f} bps; broker above Kite {pct(above, mism)}")
                if field != "volume" and mism:
                    out(f"        mismatches within 1 paisa {pct(within[0], mism)}, 5 paise {pct(within[1], mism)}, "
                        f"10 paise {pct(within[2], mism)}")
                for name, c in sorted(hyp.items(), key=lambda kv: -kv[1]):
                    out(f"        {name:32} explains {pct(c, mism)} of mismatches")

            if interval == "1m":  # per-day volume totals, in session
                ratios = []
                for s in syms:
                    K, O = data[("kite", "1m", s)], data[(broker, "1m", s)]
                    for day in sorted({lab[:10] for lab in K}):
                        kv = sum(v[4] or 0 for lab, v in K.items() if lab.startswith(day) and in_session(lab))
                        ov = sum(v[4] or 0 for lab, v in O.items() if lab.startswith(day) and in_session(lab))
                        if kv:
                            ratios.append(ov / kv)
                out(f"day volume 09:15-15:14, {broker}/kite: min {min(ratios):.3f} median {st.median(ratios):.3f} "
                    f"max {max(ratios):.3f}")

    # Groww's extra minute bars, and whether its daily candle is built from them
    out("\n================ Groww: bars outside 09:15-15:14, and its daily candle ================")
    outside = defaultdict(int)
    for s in syms:
        for lab, v in data[("groww", "1m", s)].items():
            if not in_session(lab):
                outside[(lab[11:], v[0] is None)] += 1
    out("labels outside the session (time, prices missing) -> count over all stock-days: " +
        ", ".join(f"{t}{' (no price)' if nop else ''}:{c}" for (t, nop), c in sorted(outside.items())))
    checks = defaultdict(lambda: [0, 0])
    for s in syms:
        G1, GD, KD = data[("groww", "1m", s)], data[("groww", "1d", s)], data[("kite", "1d", s)]
        for day in sorted({lab[:10] for lab in G1}):
            if day not in GD:
                continue
            gd = GD[day]
            bars = sorted((lab, v) for lab, v in G1.items() if lab.startswith(day))
            priced = [(lab, v) for lab, v in bars if v[0] is not None]
            sess = [(lab, v) for lab, v in priced if in_session(lab)]
            cand = {
                "daily open = first priced minute open (any time)": priced[0][1][0] if priced else None,
                "daily open = 09:15 bar open": sess[0][1][0] if sess else None,
                "daily open = Kite daily open": KD.get(day, (None,))[0],
                "daily high = max minute high incl. after 15:14": max(v[1] for _, v in priced) if priced else None,
                "daily high = max minute high 09:15-15:14": max(v[1] for _, v in sess) if sess else None,
                "daily low = min minute low incl. after 15:14": min(v[2] for _, v in priced) if priced else None,
                "daily low = min minute low 09:15-15:14": min(v[2] for _, v in sess) if sess else None,
                "daily close = last priced minute close": priced[-1][1][3] if priced else None,
                "daily volume = sum of all minute volumes": sum(v[4] or 0 for _, v in bars),
                "daily volume = sum 09:15-15:14": sum(v[4] or 0 for _, v in sess),
                "daily volume = Kite daily volume": KD.get(day, (None,) * 5)[4],
            }
            idx = {"open": 0, "high": 1, "low": 2, "close": 3, "volume": 4}
            for name, val in cand.items():
                field = name.split()[1]
                checks[name][1] += 1
                if val is not None and gd[idx[field]] is not None and abs(float(val) - float(gd[idx[field]])) < (0.5 if field == "volume" else EPS):
                    checks[name][0] += 1
    for name, (h, t) in checks.items():
        out(f"  {name:52} {h}/{t}")

    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
