"""Morning-range accumulator — the record the Spreads gate will rest on.

Every expected value below is computed by hand in the test, not read back
from the code under test. The bars are synthetic and their shape is chosen
so the right answer is obvious by inspection.
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanners import range_history as rh

FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def bars(day, interval_min, rows):
    """rows = [(hh, mm, open, high, low, close), ...] in ET."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp(f"{day} {h:02d}:{m:02d}", tz="US/Eastern") for h, m, *_ in rows])
    return pd.DataFrame(
        {"Open":  [r[2] for r in rows],
         "High":  [r[3] for r in rows],
         "Low":   [r[4] for r in rows],
         "Close": [r[5] for r in rows]}, index=idx)


print("\n── 1. The window is a function of the interval ─────────────────")
check("5m reads at noon", rh.WINDOWS["5m"] == 12 * 60)
check("15m and 30m also reach noon",
      rh.WINDOWS["15m"] == 720 and rh.WINDOWS["30m"] == 720)
check("60m stops at 11:30 — an hourly 11:30 bar runs to 12:30",
      rh.WINDOWS["60m"] == 11 * 60 + 30)
check("an unknown interval is refused, not guessed",
      "1m" not in rh.WINDOWS)
try:
    rh.session_records(bars("2026-08-24", 1, [(9, 30, 1, 1, 1, 1)]), "X", "1m")
    check("session_records raises on an interval with no window", False)
except ValueError as e:
    check("session_records raises on an interval with no window", "1m" in str(e))


print("\n── 2. One session, hand-computed ───────────────────────────────")
# Morning 09:30-11:55 ranges 100 -> 110. Noon read 108. Close 112.
rows = [(9, 30, 100, 102, 100, 101),
        (10, 0, 101, 106, 101, 105),
        (10, 30, 105, 110, 104, 109),
        (11, 0, 109, 109, 106, 107),
        (11, 30, 107, 109, 107, 108),
        (11, 55, 108, 108, 107, 108),
        (13, 0, 108, 113, 107, 112),
        (16, 0, 112, 112, 111, 112)]
recs = rh.session_records(bars("2026-08-24", 5, rows), "TEST", "5m",
                          today="2026-08-25")
check("one record per session", len(recs) == 1, str(len(recs)))
r = recs[0]
check("high is the max of the morning highs", r["high"] == 110.0, str(r["high"]))
check("low is the min of the morning lows", r["low"] == 100.0, str(r["low"]))
check("read is the LAST morning bar's close, not the 12:00 open",
      r["read"] == 108.0, str(r["read"]))
check("close is the last regular-session bar", r["close"] == 112.0)
check("position = (read - low) / range", abs(r["pos_pct"] - 80.0) < 1e-9,
      f'{r["pos_pct"]}')
check("range % is measured off the low",
      abs(r["range_pct"] - 10.0) < 1e-9, f'{r["range_pct"]}')
check("window_end is stamped on the record", r["window_end"] == 720)
check("interval is stamped on the record", r["interval"] == "5m")
check("closing above the high with noon high is CONTINUATION, not a breach",
      r["breach"] is False and r["closed_above_high"] is True)

# The mirror: same morning, close below the low.
rows_dn = rows[:-2] + [(13, 0, 108, 108, 96, 97), (16, 0, 97, 98, 96, 97)]
r2 = rh.session_records(bars("2026-08-24", 5, rows_dn), "TEST", "5m",
                        today="2026-08-25")[0]
check("noon in the upper half closing below the low IS a breach",
      r2["breach"] is True and r2["closed_below_low"] is True)

# Noon in the lower half: the breach is the other direction.
rows_lo = [(9, 30, 110, 110, 100, 101), (9, 45, 101, 104, 100, 102),
           (10, 0, 102, 103, 100, 102), (10, 30, 102, 103, 101, 102),
           (11, 0, 102, 103, 101, 102), (11, 30, 102, 103, 101, 102),
           (11, 55, 102, 102, 101, 101),
           (13, 0, 101, 115, 101, 114), (16, 0, 114, 115, 113, 114)]
r3 = rh.session_records(bars("2026-08-24", 5, rows_lo), "TEST", "5m",
                        today="2026-08-25")[0]
check("noon below the midpoint", r3["pos_pct"] < 50.0, f'{r3["pos_pct"]:.1f}%')
check("...closing above the high is the breach on that side",
      r3["breach"] is True and r3["closed_above_high"] is True)


print("\n── 3. An unfinished session is not a data point ────────────────")
# The exact bug that had to be fixed in the noon study: reading a "close"
# at 12:35 and storing it as the session close.
part = [(9, 30, 100, 102, 100, 101), (10, 0, 101, 106, 101, 105),
        (10, 30, 105, 110, 104, 109), (11, 0, 109, 109, 106, 107),
        (11, 30, 107, 109, 107, 108), (11, 55, 108, 108, 107, 108),
        (12, 35, 108, 109, 107, 108)]
check("today's half-session is dropped",
      rh.session_records(bars("2026-08-26", 5, part), "T", "5m",
                         today="2026-08-26") == [])
check("...but the same bars on a PAST date are a finished session",
      len(rh.session_records(bars("2026-08-26", 5, part), "T", "5m",
                             today="2026-08-27")) == 1)
thin = [(9, 30, 100, 101, 100, 100), (9, 35, 100, 101, 100, 100)]
check("a truncated 5m feed cannot pass as a narrow range",
      rh.session_records(bars("2026-08-24", 5, thin), "T", "5m",
                         today="2026-08-25") == [])
check("two bars ARE enough on an hourly grid",
      len(rh.session_records(bars("2026-08-24", 60, thin), "T", "60m",
                             today="2026-08-25")) == 1)
flat = [(9, 30, 100, 100, 100, 100), (10, 0, 100, 100, 100, 100),
        (10, 30, 100, 100, 100, 100), (11, 0, 100, 100, 100, 100),
        (11, 30, 100, 100, 100, 100), (11, 55, 100, 100, 100, 100),
        (16, 0, 100, 100, 100, 100)]
check("a zero-width range is dropped, not divided by",
      rh.session_records(bars("2026-08-24", 5, flat), "T", "5m",
                         today="2026-08-25") == [])
check("an empty frame is handled",
      rh.session_records(pd.DataFrame(), "T", "5m") == [])


print("\n── 4. The hourly window really does stop at 11:30 ──────────────")
# The 11:30 hourly bar spans 11:30-12:30. If it were included, the 118 high
# printed after noon would leak into a number that is supposed to be
# knowable AT the read. It must not appear.
hourly = [(9, 30, 100, 102, 100, 101),
          (10, 30, 101, 106, 100, 105),
          (11, 30, 105, 118, 105, 117),   # spans past noon — must be excluded
          (12, 30, 117, 118, 116, 117),
          (15, 30, 117, 118, 116, 117)]
hr = rh.session_records(bars("2026-08-24", 60, hourly), "T", "60m",
                        today="2026-08-25")[0]
check("the 11:30 bar is excluded from the morning range",
      hr["high"] == 106.0, f'high={hr["high"]} (118 would mean leakage)')
check("the read is the 10:30 bar's close", hr["read"] == 105.0)
check("window_end marks it as the 11:30 window", hr["window_end"] == 690)
check("the two windows are distinguishable on disk",
      rh.WINDOWS["5m"] != rh.WINDOWS["60m"])


print("\n── 5. Storage round-trips and repairs rather than duplicates ───")
_real_dir = rh.SNAP_DIR
tmp = tempfile.mkdtemp()
rh.SNAP_DIR = tmp
try:
    a = rh.session_records(bars("2026-08-24", 5, rows), "AAA", "5m", today="2026-08-25")
    b = rh.session_records(bars("2026-08-24", 5, rows), "BBB", "5m", today="2026-08-25")
    rh.save_records(a + b, source="accum")
    df = rh.load_records()
    check("both tickers stored", set(df["ticker"]) == {"AAA", "BBB"}, str(len(df)))
    check("source is recorded", set(df["source"]) == {"accum"})

    # Re-running the same day must repair it, not double it.
    rh.save_records(a, source="accum")
    df2 = rh.load_records()
    check("re-running a day does not duplicate its rows", len(df2) == 2, str(len(df2)))

    # A second interval for the same ticker-day is a separate observation.
    c = rh.session_records(bars("2026-08-24", 60, hourly), "AAA", "60m", today="2026-08-25")
    rh.save_records(c, source="backfill60m")
    df3 = rh.load_records()
    check("a different window is kept alongside, not overwritten",
          len(df3) == 3, str(len(df3)))
    check("sources stay separable", set(df3["source"]) == {"accum", "backfill60m"})
    check("filtering by source works", len(rh.load_records("accum")) == 2)

    cmp_df = rh.window_comparison(df3)
    check("the 11:30/12:00 comparison finds the overlap",
          len(cmp_df) == 1, str(len(cmp_df)))
    if len(cmp_df):
        # noon pos 80.0 (computed above); 11:30 pos = (105-100)/(106-100) = 83.33
        check("...and reports both positions",
              abs(cmp_df.iloc[0]["pos_noon"] - 80.0) < 1e-9
              and abs(cmp_df.iloc[0]["pos_1130"] - 500 / 6) < 1e-9,
              f'{cmp_df.iloc[0]["pos_noon"]:.2f} vs {cmp_df.iloc[0]["pos_1130"]:.2f}')

    check("a missing directory reads as empty, not as a crash",
          (setattr(rh, "SNAP_DIR", os.path.join(tmp, "nope")) or True)
          and rh.load_records().empty)
finally:
    rh.SNAP_DIR = _real_dir
    shutil.rmtree(tmp, ignore_errors=True)


print("\n── 6. Pooling counts DATES, not ticker-days ────────────────────")
# Six correlated semis breaching on one afternoon is ONE observation of
# "semis reversed", not six independent coin flips. Quoting ticker-days
# would shrink the interval by ~sqrt(6) for free.
same_day = pd.DataFrame([
    {"ticker": t, "date": "2026-08-24", "pos_pct": 80.0, "breach": True}
    for t in ("NVDA", "AVGO", "SMH", "SOXL", "TQQQ", "QQQ")
] + [
    {"ticker": t, "date": d, "pos_pct": 80.0, "breach": False}
    for d in ("2026-08-25", "2026-08-26")
    for t in ("NVDA", "AVGO", "SMH", "SOXL", "TQQQ", "QQQ")
])
st = rh.pooled_breach_rate(same_day)
check("ticker-day count is 18", st["n_rows"] == 18, str(st["n_rows"]))
check("date count is 3 — the number that matters", st["n_days"] == 3, str(st["n_days"]))
check("naive rate is 6/18 = 33.3%", abs(st["rate_pct"] - 100 / 3) < 1e-9,
      f'{st["rate_pct"]:.1f}%')
check("clustered rate is 1 bad day in 3 = 33.3%",
      abs(st["day_rate_pct"] - 100 / 3) < 1e-9, f'{st["day_rate_pct"]:.1f}%')
check("both counts are reported, so neither can be quoted by accident",
      {"n_rows", "n_days", "rate_pct", "day_rate_pct"} <= set(st))
check("an empty frame yields no rate rather than a zero",
      rh.pooled_breach_rate(pd.DataFrame())["rate_pct"] is None)
check("a zone with no rows yields no rate",
      rh.pooled_breach_rate(same_day, zone="call")["rate_pct"] is None)


print("\n── 7. Zones match the Spreads tab exactly ──────────────────────")
check("100% -> green", rh.zone_of(100.0) == "put_green")
check("70% -> green (inclusive)", rh.zone_of(70.0) == "put_green")
check("69.9% -> amber", rh.zone_of(69.9) == "put_amber")
check("59.9% -> blocked", rh.zone_of(59.9) == "put_block")
check("50% -> blocked, not a call", rh.zone_of(50.0) == "put_block")
check("49.9% -> call", rh.zone_of(49.9) == "call")
# The tab is the authority; drift between the two would silently mis-bucket
# every stored session.
os.environ.setdefault("MPLBACKEND", "Agg")
from unittest.mock import MagicMock


class _FakeSS(dict):
    def __missing__(self, k): return None


class _MockST:
    session_state = _FakeSS()
    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _d(fn): return fn
        return _d
    def __getattr__(self, n): return MagicMock()


sys.modules["streamlit"] = _MockST()
from scanners import spreads as sp
check("the study and the tab agree on every boundary",
      all(rh.zone_of(p) == sp.zone_for(p)
          for p in (0, 25, 49.9, 50, 55, 59.9, 60, 65, 69.9, 70, 85, 100)))


print("\n── 8. The universe covers what was asked for ───────────────────")
keys = {t["key"] for t in rh.UNIVERSE}
check("every twice/thrice-weekly name requested is present",
      {"NVDA", "TSLA", "GOOGL", "META", "AVGO", "MSFT", "SOXL", "TQQQ"} <= keys)
check("the daily names are still there", {"QQQ", "SPX", "IWM"} <= keys)
check("SPX fetches bars from ^SPX", rh.spot_symbol("SPX") == "^SPX")
check("everything else fetches its own symbol", rh.spot_symbol("NVDA") == "NVDA")
check("only QQQ and SPX are marked validated",
      {t["key"] for t in rh.UNIVERSE if t["validated"]} == {"QQQ", "SPX"})
check("leveraged funds are their own correlation group",
      {t["key"] for t in rh.UNIVERSE if t["group"] == "levered"} == {"TQQQ", "SOXL"})
check("the semis cluster is grouped together",
      {"NVDA", "AVGO", "SMH"} <= {t["key"] for t in rh.UNIVERSE if t["group"] == "semis"})
check("universe() filters by cadence",
      {t["key"] for t in rh.universe(rh.CADENCE_DAILY)} == {"QQQ", "SPX", "IWM"})
check("retention is None — these records cannot be re-fetched",
      rh.RETENTION_DAYS is None)


print("\n── 9. Coverage answers 'how far from a usable sample' ──────────")
cov_src = pd.DataFrame(
    [{"ticker": "NVDA", "date": f"2026-07-{d:02d}", "pos_pct": 85.0, "breach": False}
     for d in range(1, 11)]
    + [{"ticker": "NVDA", "date": f"2026-06-{d:02d}", "pos_pct": 30.0, "breach": False}
       for d in range(1, 6)])
cov = rh.coverage(cov_src)
row = cov[cov["ticker"] == "NVDA"].iloc[0]
check("sessions counts everything", row["sessions"] == 15, str(row["sessions"]))
check("green counts only the tradeable zone", row["green_sessions"] == 10,
      str(row["green_sessions"]))
check("progress is measured against the study's 43",
      abs(row["pct_of_target"] - round(10 / 43 * 100, 1)) < 1e-9,
      f'{row["pct_of_target"]}%')
check("an empty store gives an empty coverage table, not a crash",
      rh.coverage(pd.DataFrame()).empty)

print("\n" + "=" * 60)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
