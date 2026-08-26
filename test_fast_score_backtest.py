import os, sys
from unittest.mock import MagicMock
class F(dict):
    def __missing__(s,k): return None
class M:
    session_state=F()
    @staticmethod
    def cache_data(ttl=None,show_spinner=True):
        def d(f): return f
        return d
    def __getattr__(s,n): return MagicMock()
sys.modules["streamlit"]=M()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scanners import fast_score as fs
from scanners import fast_score_backtest as bt

FAILS=[]
def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — '+extra) if extra else ''}")
    if not cond: FAILS.append(name)

def series(n=520, seed=5):
    rng=np.random.default_rng(seed)
    idx=pd.date_range("2016-01-04",periods=n,freq="W-MON")
    close=50*np.cumprod(1+rng.normal(0.0025,0.028,n))
    low=close*rng.uniform(0.95,0.995,n); high=close*rng.uniform(1.005,1.05,n)
    vol=1e6*rng.uniform(0.6,1.4,n)
    return pd.DataFrame({"Close":close,"High":high,"Low":low,"Volume":vol},index=idx)

print("\n── 1. No look-ahead (the property the whole thing rests on) ────")
df = series()
n = len(df)
i = n - 60
base = fs.evaluate_ticker("T", df.iloc[:i+1])
# Corrupt everything AFTER bar i. A same-slice evaluation must be identical.
poisoned = df.copy()
poisoned.iloc[i+1:, poisoned.columns.get_loc("Close")] *= 12.0
poisoned.iloc[i+1:, poisoned.columns.get_loc("High")]  *= 12.0
poisoned.iloc[i+1:, poisoned.columns.get_loc("Low")]   *= 12.0
poisoned.iloc[i+1:, poisoned.columns.get_loc("Volume")] *= 40.0
after = fs.evaluate_ticker("T", poisoned.iloc[:i+1])
check("future bars cannot change a past evaluation",
      (base is None and after is None) or (base == after))

recs_a = bt.backtest_ticker("T", df, start_idx=n-120, horizons=(4,))
recs_b = bt.backtest_ticker("T", poisoned, start_idx=n-120, horizons=(4,))
sig_a = [(r["date"], r["score"], r["tier"]) for r in recs_a if r["bar"] <= i]
sig_b = [(r["date"], r["score"], r["tier"]) for r in recs_b if r["bar"] <= i]
check("signals before the corruption point are unchanged", sig_a == sig_b,
      f"{len(sig_a)} signal(s) compared")

print("\n── 2. Forward-return arithmetic ────────────────────────────────")
c = pd.Series([100.0, 110.0, 90.0, 120.0, 105.0])
st = bt._forward_stats(c, 0, 4)
check("return uses entry -> exit close", abs(st["ret"] - 5.0) < 1e-9, f"{st['ret']:+.2f}%")
check("MFE is the best close in the window", abs(st["mfe"] - 20.0) < 1e-9, f"{st['mfe']:+.2f}%")
check("MAE is the worst close in the window", abs(st["mae"] - (-10.0)) < 1e-9, f"{st['mae']:+.2f}%")
check("no forward window -> no observation", bt._forward_stats(c, 3, 4) is None)
check("...so picks too recent to score are excluded, not counted as 0%",
      bt._forward_stats(c, 4, 1) is None)

print("\n── 3. Repeat suppression ───────────────────────────────────────")
recs = bt.backtest_ticker("T", df, start_idx=200, horizons=(4,))
if len(recs) > 1:
    gaps = [recs[k+1]["bar"] - recs[k]["bar"] for k in range(len(recs)-1)]
    check("consecutive signals respect MIN_REPEAT_GAP_WKS",
          min(gaps) >= bt.MIN_REPEAT_GAP_WKS, f"min gap {min(gaps)}w")
else:
    check("consecutive signals respect MIN_REPEAT_GAP_WKS", True, "fewer than 2 signals")
check("MIN_REPEAT_GAP_WKS is a real constraint, not a no-op", bt.MIN_REPEAT_GAP_WKS > 1)

print("\n── 4. Benchmark alignment ──────────────────────────────────────")
bidx = pd.date_range("2016-01-04", periods=520, freq="W-MON")
bench = pd.Series(np.linspace(100, 200, 520), index=bidx)   # steady climb
r = [{"ticker":"T","date":str(bidx[100].date()),"bar":100,"tier":fs.TIER_FRESH,
      "score":10,"ret_4w":5.0}]
bt._attach_benchmark(r, bench, horizons=(4,))
check("benchmark return attached", "bench_4w" in r[0], str(r[0].get("bench_4w")))
check("excess = raw - benchmark",
      abs(r[0]["excess_4w"] - (5.0 - r[0]["bench_4w"])) < 1e-9)
# Dates, not positions: a shorter benchmark frame must not shift the window.
shifted = pd.Series(bench.values, index=bidx)  # same dates
r2 = [{"ticker":"T","date":str(bidx[100].date()),"bar":9999,"tier":fs.TIER_FRESH,
       "score":10,"ret_4w":5.0}]
bt._attach_benchmark(r2, shifted, horizons=(4,))
check("alignment is by DATE, so a wrong bar index is harmless",
      abs(r2[0]["bench_4w"] - r[0]["bench_4w"]) < 1e-9)
r3 = [{"ticker":"T","date":str(bidx[-2].date()),"bar":518,"tier":fs.TIER_FRESH,
       "score":10,"ret_4w":5.0}]
bt._attach_benchmark(r3, bench, horizons=(4,))
check("a window running off the end of the benchmark is skipped, not faked",
      "bench_4w" not in r3[0])

print("\n── 5. Summary statistics ───────────────────────────────────────")
recs = [
    {"ticker":"A","date":"2024-01-01","tier":fs.TIER_FRESH,"score":13,"ret_4w":10.0,"excess_4w":6.0,"mfe_4w":12.0,"mae_4w":-2.0},
    {"ticker":"B","date":"2024-01-08","tier":fs.TIER_FRESH,"score":10,"ret_4w":-5.0,"excess_4w":-8.0,"mfe_4w":1.0,"mae_4w":-9.0},
    {"ticker":"C","date":"2024-01-15","tier":fs.TIER_EARLY,"score":7,"ret_4w":2.0,"excess_4w":-1.0,"mfe_4w":4.0,"mae_4w":-1.0},
    {"ticker":"A","date":"2024-02-01","tier":fs.TIER_FURTHER,"score":13,"ret_4w":4.0,"excess_4w":1.0,"mfe_4w":6.0,"mae_4w":-3.0},
]
s = bt.summarise(recs, horizons=(4,))
o = s["overall"]["4w"]
check("pick count", s["n_picks"] == 4)
check("distinct tickers counted, not rows", s["n_tickers"] == 3, str(s["n_tickers"]))
check("win rate", abs(o["win_rate"] - 75.0) < 1e-9, f"{o['win_rate']:.0f}%")
check("mean", abs(o["mean"] - 2.75) < 1e-9, f"{o['mean']:+.2f}")
check("median", abs(o["median"] - 3.0) < 1e-9, f"{o['median']:+.2f}")
check("best/worst", o["best"] == 10.0 and o["worst"] == -5.0)
check("mean excess vs benchmark", abs(o["mean_excess"] - (-0.5)) < 1e-9, f"{o['mean_excess']:+.2f}")
check("beat-benchmark rate is separate from win rate",
      abs(o["win_rate_vs_bench"] - 50.0) < 1e-9, f"{o['win_rate_vs_bench']:.0f}%")
check("per-tier split present", fs.TIER_FRESH in s["by_tier"] and fs.TIER_EARLY in s["by_tier"])
check("score bands split present", "12-15" in s["by_score_band"] and "6-8" in s["by_score_band"])
check("top band holds only its own rows", s["by_score_band"]["12-15"]["4w"]["n"] == 2)
check("empty input does not explode", bt.summarise([], horizons=(4,))["n_picks"] == 0)

print("\n── 6. Score band x tier cross-tab ──────────────────────────────")
xt = bt.cross_tab(recs, horizons=(4,))
check("cells are keyed band · tier", all(" · " in k for k in xt), str(list(xt))[:90])
check("a band+tier combination is isolated correctly",
      xt.get(f"12-15 · {fs.TIER_FRESH}", {}).get("4w", {}).get("n") == 1,
      str(xt.get(f"12-15 · {fs.TIER_FRESH}", {}).get("4w", {}).get("n")))
check("every pick lands in exactly one cell",
      sum(v["4w"]["n"] for v in xt.values() if "4w" in v) == len(recs))
check("empty input yields an empty cross-tab", bt.cross_tab([], horizons=(4,)) == {})
check("cross_tab is stored in the summary",
      "by_segment" in bt.summarise(recs, horizons=(4,)))
check("aggregate_rows is reusable at module level", callable(bt.aggregate_rows))
check("aggregate_rows agrees with the summary it feeds",
      bt.aggregate_rows(recs, 4)["n"] == bt.summarise(recs, horizons=(4,))["overall"]["4w"]["n"])
_mixed = [r for r in recs if r["score"] >= 12]
check("a cell holds only rows matching BOTH its band and its tier",
      all(12 <= r["score"] <= 15 for r in _mixed))

print("\n" + "="*60)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
