"""Morning-range / noon-position study — logic checks on hand-built sessions.

Built with explicit price paths rather than random data so every expected
answer is derived by hand, not by trusting the code under test.
"""
import importlib.util
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "nr", os.path.join(ROOT, "scripts", "headless_noon_reversal.py"))
nr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nr)

FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def _path(seq, n):
    """Walk `seq`, then HOLD the final value for the rest of the bars.

    Not np.resize: that tiles the sequence, so the last bar came out as
    whichever element the modulo landed on rather than the price the test
    meant to place at noon — every position read 100%.
    """
    seq = list(map(float, seq))
    if len(seq) >= n:
        return np.array(seq[:n])
    return np.array(seq + [seq[-1]] * (n - len(seq)))


def day(date, morning, afternoon, close_time="16:00"):
    t1 = pd.date_range(f"{date} 09:30", f"{date} 11:55", freq="5min", tz="US/Eastern")
    t2 = pd.date_range(f"{date} 12:00", f"{date} {close_time}", freq="5min", tz="US/Eastern")
    px = np.concatenate([_path(morning, len(t1)), _path(afternoon, len(t2))])
    idx = t1.append(t2)
    return pd.DataFrame({"Open": px, "High": px, "Low": px,
                         "Close": px, "Volume": 1e6}, index=idx)


print("\n── Morning window boundaries ────────────────────────────────")
d = day("2026-06-01", [100, 110, 90, 105], [105])
s = nr.sessions(d)[0]
check("high/low from 09:30–11:55 only", s["high"] == 110 and s["low"] == 90, f"{s['low']}..{s['high']}")
check("noon price is the last morning bar", s["noon"] == 105, str(s["noon"]))
s2 = nr.sessions(day("2026-06-02", [100, 105, 95, 100], [500, 100]))[0]
check("an afternoon spike cannot enter the morning range", s2["high"] <= 105, f"high={s2['high']}")

print("\n── The directional trigger ──────────────────────────────────")
s3 = nr.sessions(day("2026-06-03", [100, 110, 90, 108], [108, 85]))[0]
check("noon above midpoint detected", s3["above_mid"], f"pos={s3['pos_pct']:.1f}%")
check("close below morning low = reversal", s3["reversal"] and s3["closed_below_low"])
check("...and is not also counted as continuation", not s3["continuation"])

s4 = nr.sessions(day("2026-06-04", [100, 110, 90, 92], [92, 115]))[0]
check("noon below midpoint detected", not s4["above_mid"], f"pos={s4['pos_pct']:.1f}%")
check("close above morning high = mirror reversal", s4["reversal"] and s4["closed_above_high"])

s5 = nr.sessions(day("2026-06-05", [100, 110, 90, 108], [108, 120]))[0]
check("same-side breakout is continuation, not reversal",
      s5["continuation"] and not s5["reversal"])

s6 = nr.sessions(day("2026-06-08", [100, 110, 90, 108], [108, 100]))[0]
check("close back inside the range is neither",
      s6["closed_inside"] and not s6["reversal"] and not s6["continuation"])

print("\n── Session close only — a touch must not count ──────────────")
s7 = nr.sessions(day("2026-06-09", [100, 110, 90, 108], [108, 80, 100]))[0]
check("traded through the low, closed inside -> no reversal",
      not s7["reversal"] and s7["closed_inside"], f"close={s7['close']}")

print("\n── Position % arithmetic ────────────────────────────────────")
s8 = nr.sessions(day("2026-06-10", [100, 110, 90, 100], [100]))[0]
check("noon exactly at the midpoint -> 50%", abs(s8["pos_pct"] - 50) < 1e-9, f"{s8['pos_pct']}")
check("exactly 50% counts as NOT above (strict >)", not s8["above_mid"])
check("noon at the high -> 100%",
      abs(nr.sessions(day("2026-06-11", [100, 110, 90, 110], [110]))[0]["pos_pct"] - 100) < 1e-9)
check("noon at the low -> 0%",
      abs(nr.sessions(day("2026-06-15", [100, 110, 90, 90], [90]))[0]["pos_pct"]) < 1e-9)

print("\n── Early-close days are flagged, not silently mixed in ──────")
check("13:00 finish flagged",
      nr.sessions(day("2026-06-12", [100, 110, 90, 105], [105], close_time="13:00"))[0]["early_close"])
check("16:00 finish not flagged", not s["early_close"])

print("\n── Summary maths ────────────────────────────────────────────")
rows = [s3, s4, s5, s6]
su = nr.summarise(rows)
check("sessions counted", su["n_sessions"] == 4)
check("above-midpoint block counts only its own days", su["above_mid"]["n"] == 3, f"n={su['above_mid']['n']}")
check("one reversal among them", su["above_mid"]["reversal"] == 1, str(su["above_mid"]["reversal"]))
check("one continuation among them", su["above_mid"]["continuation"] == 1)
check("below-midpoint block is separate", su["below_mid"]["n"] == 1 and su["below_mid"]["reversal"] == 1)
check("percentages match the counts",
      abs(su["above_mid"]["reversal_pct"] - 100 / 3) < 1e-9)
check("deciles partition every session", sum(x["n"] for x in su["deciles"]) == 4)
check("a 100% position lands in the top decile",
      any(x["band"] == "90-100%" and x["n"] >= 1 for x in su["deciles"]))

print("\n── Degenerate sessions are dropped, not divided by zero ─────")
flat = day("2026-06-16", [100], [100])
check("a flat morning (high == low) is skipped", nr.sessions(flat) == [])
stub = day("2026-06-17", [100, 101], [101])
stub = stub.iloc[:3]
check("a truncated feed is skipped", nr.sessions(stub) == [])

print("\n" + "=" * 58)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
