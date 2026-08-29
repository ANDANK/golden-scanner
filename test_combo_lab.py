"""Indicator-combination lab — engine checks on hand-built data.

Every expected value is computed in the test, not read back from the code
under test. Where a synthetic series is used its shape is chosen so the
correct answer is obvious by inspection.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanners import combo_lab as cl

FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def ohlcv(closes, vols=None, highs=None, lows=None, opens=None):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "Open": np.asarray(opens, dtype=float) if opens is not None else c,
        "High": np.asarray(highs, dtype=float) if highs is not None else c * 1.01,
        "Low": np.asarray(lows, dtype=float) if lows is not None else c * 0.99,
        "Close": c,
        "Volume": np.asarray(vols, dtype=float) if vols is not None
        else np.full(n, 1_000_000.0),
    }, index=idx)


def wobble(n, drift=0.0005, amp=0.02, period=25, start=100.0):
    """Deterministic mean-reverting series. A monotonic ramp is useless here:
    it pins RSI near its ceiling and never produces a downward crossover."""
    t = np.arange(n)
    return start * np.exp(drift * t) * (1 + amp * np.sin(2 * np.pi * t / period))


def regime(n, leg=110, drift=0.0016, amp=0.02, period=22, start=100.0, phase=0):
    """Alternating up and down legs.

    A steadily rising series is the wrong fixture for this engine and quietly
    guts several of the checks below: EMA20 never falls back through EMA50, so
    C1/C2/C3 can never fire, and MACD never dips under zero, so A2 can never
    fire. Both then "pass" any test that merely counts them. Regime changes
    are what make those states reachable at all.
    """
    t = np.arange(n)
    sign = np.where(((t + phase) // leg) % 2 == 0, 1.0, -1.0)
    path = np.cumsum(drift * sign)
    return start * np.exp(path) * (1 + amp * np.sin(2 * np.pi * t / period))


print("\n── 1. The combination engine covers exactly what was asked ─────")
combos = cl.all_combinations()
labels = {cl.label(c) for c in combos}
check("3x4x4x2x2 minus the empty pick = 191", len(combos) == 191, str(len(combos)))
check("no duplicate labels", len(labels) == len(combos))
check("every single factor is present as its own baseline",
      all(s in labels for s in cl.FACTOR_STATES), str(len(cl.FACTOR_STATES)))
check("the full five-factor combo exists", "A1+B1+C1+D1+V1" in labels)
check("a four-factor combo exists", "A1+B1+C1+D1" in labels)
check("the unconstrained combination is NOT tested",
      "" not in labels and all(len(c) >= 1 for c in combos))
check("A1 and A2 never appear together (mutually exclusive states)",
      not any({"A1", "A2"} <= set(c) for c in combos))
check("no combo takes two RSI bands",
      not any(len({"B1", "B2", "B3"} & set(c)) > 1 for c in combos))
check("no combo takes two EMA positions",
      not any(len({"C1", "C2", "C3"} & set(c)) > 1 for c in combos))
counts = {}
for c in combos:
    counts[len(c)] = counts.get(len(c), 0) + 1
check("singles = 2+3+3+1+1 = 10", counts.get(1) == 10, str(counts.get(1)))
check("label joins with +", cl.label(("A1", "B2")) == "A1+B2")


print("\n── 2. Indicators match the repo's live implementations ─────────")
from scanners import fast_score as fs                       # noqa: E402
from scanners import first_things_first as ftf              # noqa: E402

s = pd.Series(wobble(300))
m1, s1, h1 = cl.macd(s)
m2, s2, h2 = fs._macd(s)
check("MACD is identical to fast_score's", np.allclose(m1, m2) and np.allclose(s1, s2))
check("RSI is identical to fast_score's", np.allclose(cl.rsi(s), fs._rsi(s)))
df = ohlcv(wobble(300))
check("ADX is identical to first_things_first's",
      np.allclose(cl.adx(df.High, df.Low, df.Close),
                  ftf._adx_series(df.Close, df.High, df.Low), equal_nan=True))
check("RSI stays inside 0-100", cl.rsi(s).between(0, 100).all())
check("ADX is non-negative", (cl.adx(df.High, df.Low, df.Close).dropna() >= 0).all())


print("\n── 3. The recency window, and where each test is evaluated ─────")
# A series that crosses up once, at a known bar, then stays above.
fast_s = pd.Series([1.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
slow_s = pd.Series([2.0, 2.0, 2.0, 1.5, 1.6, 1.7, 1.8, 1.9])
recent, at = cl._crossed_up_within(fast_s, slow_s, window=3)
check("no signal before the cross", not recent.iloc[:3].any())
check("the cross bar itself counts", bool(recent.iloc[3]))
check("still inside a 3-bar window two bars later", bool(recent.iloc[5]))
check("expired three bars later", not bool(recent.iloc[6]),
      f"recent[6]={recent.iloc[6]}")
check("the cross position is recorded", float(at.iloc[5]) == 3.0, str(at.iloc[5]))
_never, _ = cl._crossed_up_within(pd.Series([1.0] * 8), pd.Series([2.0] * 8), 3)
check("a series that never crosses yields nothing", not _never.any())

# The zero-line test must read the CROSS bar, not today. Build a MACD that
# crosses while below zero and then climbs through zero: it must stay A2.
n = 260
closes = np.concatenate([
    np.linspace(100, 70, 120),        # long decline -> MACD well below zero
    np.linspace(70, 78, 20),          # the turn: cross up, still below zero
    np.linspace(78, 120, 120),        # then a rally that lifts MACD over zero
])
frame = cl.indicator_frame(ohlcv(closes), "daily")
line, sig, _ = cl.macd(pd.Series(closes))
above = line > sig
cross_bars = np.flatnonzero((above & ~above.shift(1, fill_value=False)).to_numpy())
after_turn = [b for b in cross_bars if 115 <= b <= 145]
check("the turn produces a MACD cross", len(after_turn) > 0, str(cross_bars[:6]))
if after_turn:
    b = after_turn[0]
    check("...and the line was below zero at that cross", line.iloc[b] <= 0,
          f"macd={line.iloc[b]:.3f}")
    check("...so the bar is A2, not A1",
          bool(frame['A2'].iloc[b]) and not bool(frame['A1'].iloc[b]))
check("A1 and A2 are never both true on the same bar",
      not (frame["A1"] & frame["A2"]).any())


print("\n── 4. Buckets are exclusive, exhaustive where claimed ──────────")
_px4 = regime(600)
frame = cl.indicator_frame(ohlcv(_px4), "daily")
check("the fixture actually reaches the EMA states being tested",
      frame[["C1", "C2", "C3"]].any(axis=1).sum() > 0,
      str(int(frame[["C1", "C2", "C3"]].any(axis=1).sum())))
b = frame[["B1", "B2", "B3"]].sum(axis=1)
check("at most one RSI band per bar", int(b.max()) <= 1, str(int(b.max())))
c = frame[["C1", "C2", "C3"]].sum(axis=1)
check("at most one EMA position per bar", int(c.max()) <= 1, str(int(c.max())))

# RSI below 30 belongs to no band. That is the spec (bands start at 30), and
# it must be a deliberate gap rather than silently folded into B1.
r = cl.rsi(pd.Series(np.linspace(200, 40, 300)))
low = ohlcv(np.linspace(200, 40, 300))
lf = cl.indicator_frame(low, "daily")
oversold = cl.rsi(low["Close"]) < 30
if oversold.any():
    check("RSI < 30 is in NO band, not folded into B1",
          not lf.loc[oversold.to_numpy(), ["B1", "B2", "B3"]].to_numpy().any())
else:
    check("RSI < 30 is in NO band, not folded into B1", True, "no oversold bars")

# C is only ever true where an EMA cross actually happened recently.
e20 = cl.ema(pd.Series(_px4), 20)
e50 = cl.ema(pd.Series(_px4), 50)
recent_c, _ = cl._crossed_up_within(e20, e50, cl.CROSS_WINDOW["daily"])
any_c = frame[["C1", "C2", "C3"]].any(axis=1).to_numpy()
check("C is never true without a recent EMA cross",
      not (any_c & ~recent_c.to_numpy()).any())

# D is a plain band on ADX.
a = cl.adx(pd.Series(frame["close"]) * 1.01, pd.Series(frame["close"]) * 0.99,
           pd.Series(frame["close"]))
check("D1 is exactly the 20-50 ADX band",
      bool(frame["D1"].iloc[-1]) == bool(cl.ADX_MIN <= a.iloc[-1] <= cl.ADX_MAX))


print("\n── 5. Volume confirmation is measured, not assumed ─────────────")
vols = np.full(300, 1_000_000.0)
vols[250] = 5_000_000.0            # one genuine surge
vf = cl.indicator_frame(ohlcv(wobble(300), vols=vols), "daily")
check("the surge bar is V1", bool(vf["V1"].iloc[250]))
check("a flat-volume bar is not V1", not bool(vf["V1"].iloc[240]))
check("V1 is its own factor, so its contribution is measurable",
      "V1" in cl.FACTOR_STATES and ("V1",) in [tuple(c) for c in cl.all_combinations()])
check("the multiplier is the documented one", cl.VOL_MULT == 1.2)
# The warmup bars have no 20-bar average yet and must not count as confirmed.
check("no V1 before the volume average exists",
      not vf["V1"].iloc[:cl.VOL_LOOKBACK - 1].any())


print("\n── 6. No look-ahead: entry is the NEXT bar's open ──────────────")
opens = np.arange(100.0, 110.0)
f = pd.DataFrame({"open": opens, "close": opens})
fwd = cl.forward_returns(f, hold=2)
# Signal on bar 0 -> buy open[1]=101, sell open[3]=103.
check("entry is next open, exit `hold` bars later",
      abs(fwd[0] - (103.0 - 101.0) / 101.0) < 1e-12, f"{fwd[0]:.6f}")
check("a trade never uses the signal bar's own open", not np.isclose(fwd[0], 0.0))
check("trades running past the data are NaN, not truncated",
      np.isnan(fwd[-1]) and np.isnan(fwd[-2]) and np.isnan(fwd[-3]))
check("the number of usable bars is n - hold - 1",
      int(np.isfinite(fwd).sum()) == len(opens) - 2 - 1,
      str(int(np.isfinite(fwd).sum())))


print("\n── 7. Backtest arithmetic, hand-checked ────────────────────────")
# Two signals with known outcomes: +10% and -5%.
idx = pd.date_range("2021-01-01", periods=8, freq="B")
frame = pd.DataFrame({
    "open": [100.0, 100.0, 110.0, 110.0, 100.0, 95.0, 95.0, 95.0],
    "close": [100.0] * 8,
    "A1": [True, False, False, True, False, False, False, False],
    "A2": False, "B1": True, "B2": False, "B3": False,
    "C1": False, "C2": False, "C3": False, "D1": True, "V1": True,
}, index=idx)
tbl = cl.run_window({"T": frame}, None, idx[0], idx[-1], hold=1,
                    combos=[("A1",), ("A2",)])
row = tbl[tbl.combo == "A1"].iloc[0]
# signal bar 0 -> open[1]=100 -> open[2]=110 = +10%
# signal bar 3 -> open[4]=100 -> open[5]=95   = -5%
check("both signals became trades", int(row["trades"]) == 2, str(int(row["trades"])))
check("win rate is 1 of 2", abs(row["win_rate"] - 50.0) < 1e-9, f"{row['win_rate']}")
check("avg return = mean(+10%, -5%) = 2.5%",
      abs(row["avg_return"] - 2.5) < 1e-9, f"{row['avg_return']:.4f}")
check("total return sums the trades = 5%",
      abs(row["total_return"] - 5.0) < 1e-9, f"{row['total_return']:.4f}")
check("with no benchmark, excess equals raw return",
      abs(row["avg_excess"] - row["avg_return"]) < 1e-9)
check("drawdown is the -5% leg", abs(row["max_drawdown"] - (-5.0)) < 1e-9,
      f"{row['max_drawdown']:.4f}")
check("a combo with no signals reports zero trades, not a crash",
      int(tbl[tbl.combo == "A2"].iloc[0]["trades"]) == 0)
check("two trades is flagged low-N", bool(row["low_n"]))
check("MIN_TRADES is the documented 30", cl.MIN_TRADES == 30)

# Benchmark subtraction.
bench = pd.DataFrame({"open": [100.0, 100.0, 101.0, 101.0, 101.0,
                               101.0, 101.0, 101.0],
                      "close": [100.0] * 8}, index=idx)
tbl_b = cl.run_window({"T": frame}, bench, idx[0], idx[-1], hold=1,
                      combos=[("A1",)])
rb = tbl_b[tbl_b.combo == "A1"].iloc[0]
check("excess is measured against the benchmark, not zero",
      rb["avg_excess"] < rb["avg_return"],
      f"excess {rb['avg_excess']:.3f} vs raw {rb['avg_return']:.3f}")


print("\n── 8. Windows are respected, warmup is not ─────────────────────")
long_idx = pd.date_range("2021-01-01", periods=200, freq="B")
big = pd.DataFrame({
    "open": np.linspace(100, 200, 200), "close": np.linspace(100, 200, 200),
    "A1": True, "A2": False, "B1": True, "B2": False, "B3": False,
    "C1": False, "C2": False, "C3": False, "D1": True, "V1": True,
}, index=long_idx)
early = cl.run_window({"T": big}, None, long_idx[0], long_idx[49], 5,
                      combos=[("A1",)]).iloc[0]
late = cl.run_window({"T": big}, None, long_idx[100], long_idx[-1], 5,
                     combos=[("A1",)]).iloc[0]
check("a window only counts signals inside it",
      int(early["trades"]) == 50, str(int(early["trades"])))
check("the later window is a different, smaller sample",
      int(late["trades"]) < 100 and int(late["trades"]) > 0,
      str(int(late["trades"])))
check("the two windows do not share trade counts",
      int(early["trades"]) + int(late["trades"]) <= len(long_idx))


print("\n── 9. Ranking cannot be led by a lucky three-trade combo ───────")
tbl = pd.DataFrame({
    "combo": ["lucky", "solid", "bad"],
    "n_factors": [3, 1, 2],
    "avg_excess": [50.0, 2.0, -1.0],
    "trades": [3, 500, 400],
    "win_rate": [100.0, 55.0, 45.0],
    "low_n": [True, False, False],
})
ranked = cl.rank_table(tbl)
check("the 3-trade 100% combo does not head the table",
      ranked.iloc[0]["combo"] == "solid", ranked.iloc[0]["combo"])
check("low-N rows are kept, not silently dropped",
      "lucky" in set(ranked["combo"]))
check("low-N sorts below everything rankable",
      list(ranked["combo"]).index("lucky") > list(ranked["combo"]).index("bad"))


print("\n── 10. Consensus is what answers the actual question ───────────")
def mk(edges, ns):
    return pd.DataFrame({"combo": ["everywhere", "onewindow", "thin", "mixed"],
                         "n_factors": [2, 2, 2, 2],
                         "avg_excess": edges, "trades": ns,
                         "win_rate": [55.0] * 4})


tables = {
    "Daily Recent 1y": mk([1.0, 9.0, 9.0, 1.0], [100, 100, 5, 100]),
    "Daily Prior 2y": mk([1.5, -3.0, 9.0, 2.0], [100, 100, 5, 100]),
    "Weekly Recent 1y": mk([0.8, -2.0, 9.0, -1.0], [100, 100, 5, 100]),
    "Weekly Prior 2y": mk([1.2, -1.0, 9.0, 2.0], [100, 100, 5, 100]),
}
cons = cl.consensus(tables)
by = cons.set_index("combo")
check("positive in all four -> Holds everywhere",
      by.loc["everywhere", "verdict"] == "Holds everywhere")
check("a single big window is NOT enough",
      by.loc["onewindow", "verdict"] == "Inconsistent",
      by.loc["onewindow", "verdict"])
check("a huge edge on 5 trades is Not enough data, whatever its size",
      by.loc["thin", "verdict"] == "Not enough data",
      by.loc["thin", "verdict"])
check("three of four -> Mostly holds",
      by.loc["mixed", "verdict"] == "Mostly holds", by.loc["mixed", "verdict"])
check("the consistent combo sorts first, not the biggest number",
      cons.iloc[0]["combo"] == "everywhere", cons.iloc[0]["combo"])
check("worst_edge exposes the weakest window",
      abs(by.loc["everywhere", "worst_edge"] - 0.8) < 1e-9)
check("mean_edge ignores under-sampled windows",
      np.isnan(by.loc["thin", "mean_edge"]))
check("windows_tested counts only adequate samples",
      int(by.loc["thin", "windows_tested"]) == 0)
check("an empty input yields an empty frame, not a crash",
      cl.consensus({}).empty)


print("\n── 11. End to end on synthetic data ────────────────────────────")
frames = {}
rng = np.random.default_rng(7)
for k in range(6):
    px = regime(700, leg=90 + k * 15, drift=0.0014 + k * 0.0002,
                period=18 + k * 3, phase=k * 30)
    # Varying volume matters: with a flat volume series V1 can never fire and
    # half the combination space would be empty for a reason that says
    # nothing about the engine.
    vol = 1_000_000 * (1 + 0.6 * rng.random(len(px)))
    frames[f"T{k}"] = cl.indicator_frame(ohlcv(px, vols=vol), "daily")
frames = {k: v for k, v in frames.items() if v is not None}
check("synthetic tickers produce usable frames", len(frames) == 6, str(len(frames)))
_totals = {st: int(sum(int(f[st].sum()) for f in frames.values()))
           for st in cl.FACTOR_STATES}
check("the fixture reaches every state except the structurally rare C2",
      all(_totals[st] > 0 for st in cl.FACTOR_STATES if st != "C2"), str(_totals))
# C2 is "price between EMA20 and EMA50" within CROSS_WINDOW bars of the two
# CROSSING. At a crossover the two lines are by definition equal, so the band
# between them is a sliver that price is almost never inside. This is a
# property of the definition, not of the data, and the engine must surface it
# as a low sample rather than hide it.
check("C2 is rare by construction, not silently absent",
      _totals["C2"] < _totals["C1"], f'C2={_totals["C2"]} C1={_totals["C1"]}')
idx = next(iter(frames.values())).index
full = cl.run_window(frames, None, idx[60], idx[-1], hold=10)
check("every combination gets a row", len(full) == 191, str(len(full)))
check("a broad slice of the space fires on realistic data",
      (full["trades"] > 0).sum() > 60, str(int((full['trades'] > 0).sum())))
_singles = full[full.n_factors == 1].set_index("combo")["trades"]
check("every single-factor baseline except C2 produced trades",
      (_singles.drop("C2") > 0).all(), str(_singles.to_dict()))
check("a structurally rare state is flagged low-N, never dropped",
      "C2" in full["combo"].values
      and bool(full.set_index("combo").loc["C2", "low_n"]))
check("no combo reports more trades than bars available",
      full["trades"].max() <= len(idx) * len(frames))
fired = full[full["trades"] > 0]
check("win rates stay in 0-100", fired["win_rate"].between(0, 100).all())
check("drawdown is never positive (it is bounded above by zero)",
      (fired["max_drawdown"] <= 1e-9).all(),
      f"max seen {fired['max_drawdown'].max():.4f}")
# An all-winners combo must still report drawdown 0, never a positive number.
_up = pd.DataFrame({"open": np.linspace(100, 200, 60),
                    "close": np.linspace(100, 200, 60),
                    "A1": True, "A2": False, "B1": True, "B2": False,
                    "B3": False, "C1": False, "C2": False, "C3": False,
                    "D1": True, "V1": True},
                   index=pd.date_range("2021-01-01", periods=60, freq="B"))
_r = cl.run_window({"U": _up}, None, _up.index[0], _up.index[-1], 5,
                   combos=[("A1",)]).iloc[0]
check("an all-winning combo reports drawdown 0, not a positive number",
      abs(_r["max_drawdown"]) < 1e-9, f"{_r['max_drawdown']:.6f}")
check("adding a factor never increases the sample",
      full[full.combo == "A1+B1"]["trades"].iloc[0]
      <= full[full.combo == "A1"]["trades"].iloc[0])
check("...and that holds for the five-factor case too",
      full[full.combo == "A1+B1+C1+D1+V1"]["trades"].iloc[0]
      <= full[full.combo == "A1+B1+C1+D1"]["trades"].iloc[0])
check("avg_hold reports the holding period actually used",
      (fired["avg_hold"] == 10).all())

print("\n" + "=" * 62)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
