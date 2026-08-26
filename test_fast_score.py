"""Synthetic validation of scanners/fast_score.py — no network required.

Builds weekly OHLCV series with known, hand-controlled properties and asserts
each gate fires (or doesn't) for the right reason.
"""
import os
import sys
from unittest.mock import MagicMock
class _FakeSS(dict):
    def __missing__(self, key): return None
class _MockST:
    session_state = _FakeSS()
    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _dec(fn): return fn
        return _dec
    def __getattr__(self, name): return MagicMock()
sys.modules["streamlit"] = _MockST()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scanners import fast_score as fs

N = 320                      # weekly bars (~6 years, > MIN_WEEKLY_BARS=200)
FAILS, PASSES = [], []

def check(name, cond, extra=""):
    (PASSES if cond else FAILS).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")

def make_series(growth_wk=0.004, pullback_at=None, pullback_depth=0.0,
                vol_ratio=0.8, n=N, final_kick=0.0, break_after=False,
                recent_growth_mult=1.0):
    """Weekly OHLCV with a controlled trend, optional pullback, volume shape."""
    idx = pd.date_range("2020-01-06", periods=n, freq="W-MON")
    close = np.zeros(n)
    px = 50.0
    for i in range(n):
        g = growth_wk * (recent_growth_mult if i >= n - 26 else 1.0)
        px *= (1.0 + g)
        close[i] = px
    low = close * 0.985
    if pullback_at is not None:
        i = n - 1 - pullback_at
        # push that week's low down to a chosen depth vs the 50w SMA
        sma = pd.Series(close).rolling(50).mean().iloc[i]
        low[i] = sma * (1.0 + pullback_depth / 100.0)
        if break_after and i + 2 < n:
            close[i + 1] = sma * 0.90        # decisive break below the line
            low[i + 1] = sma * 0.88
    if final_kick:
        close[-3:] = close[-3:] * np.linspace(1.0, 1.0 + final_kick, 3)
    volume = np.full(n, 1_000_000.0)
    volume[-4:] = 1_000_000.0 * vol_ratio    # last 4w vs the 26w base
    high = np.maximum(close, low) * 1.005
    return pd.DataFrame({"Close": close, "High": high, "Low": low,
                         "Volume": volume}, index=idx)


def make_bounce(n=N, base_g=0.0015, dip_start=10, dip_len=3, dip_g=-0.008,
                rally_g=0.009, vol_ratio=0.75, wobble=0.02, wob_period=8):
    """Gentle uptrend -> short dip that wicks the 50w line -> recovery rally.

    Two things matter about the shape. The dip must be SHORT: a deep
    multi-month correction turns the 26-week regression negative and the
    ratio gate then (correctly) rejects it -- see the "deep correction" case.

    And the series must WOBBLE. A monotonic rally has no down weeks at all,
    which pins RSI near 84 and MFI near 78, so every case would fail the
    exhaustion gates for a reason no real chart would produce. The wobble is
    a deterministic mean-reverting sine rather than a random walk: it adds
    genuine down weeks for RSI/MFI to read without moving the underlying
    regression slope the trend gates measure.
    """
    idx = pd.date_range("2020-01-06", periods=n, freq="W-MON")
    trend = np.zeros(n); px = 50.0; ds = n - 1 - dip_start
    for i in range(n):
        if ds <= i < ds + dip_len: g = dip_g
        elif i >= ds + dip_len:    g = rally_g
        else:                      g = base_g
        px *= (1.0 + g); trend[i] = px
    close = trend * (1.0 + wobble * np.sin(np.arange(n) * 2 * np.pi / wob_period))
    low = close.copy()
    if dip_len:
        low[ds:ds + dip_len] = close[ds:ds + dip_len] * 0.97
    low = low * 0.995
    volume = np.full(n, 1_000_000.0); volume[-4:] = 1_000_000.0 * vol_ratio
    high = np.maximum(close, low) * 1.005
    return pd.DataFrame({"Close": close, "High": high, "Low": low,
                         "Volume": volume}, index=idx)

print("\n── 1. Metric math ──────────────────────────────────────────────")

# A perfectly steady exponential trend must produce slope_ratio ~0.5:
# half the window covers roughly half the regression rise.
s = make_series(growth_wk=0.004)
r52 = fs._regression_rise_pct(pd.Series(s["Close"].values[-52:]))
r26 = fs._regression_rise_pct(pd.Series(s["Close"].values[-26:]))
ratio = r26 / r52
check("steady trend -> slope ratio near 0.50", 0.42 <= ratio <= 0.58, f"ratio={ratio:.3f}")

# An accelerating trend must push the ratio well above 0.5.
s_acc = make_series(growth_wk=0.002, recent_growth_mult=4.0)
r52a = fs._regression_rise_pct(pd.Series(s_acc["Close"].values[-52:]))
r26a = fs._regression_rise_pct(pd.Series(s_acc["Close"].values[-26:]))
check("accelerating trend -> ratio > 0.55", (r26a / r52a) > 0.55, f"ratio={r26a/r52a:.3f}")

# Regression rise must be robust to a single terminal spike (the whole reason
# we fit a line instead of using first/last closes).
spiked = s["Close"].values[-52:].copy()
raw_before = (spiked[-1] / spiked[0] - 1) * 100
fit_before = fs._regression_rise_pct(pd.Series(spiked))
spiked[-1] *= 1.35
raw_after = (spiked[-1] / spiked[0] - 1) * 100
fit_after = fs._regression_rise_pct(pd.Series(spiked))
check("regression resists a terminal spike better than raw change",
      abs(fit_after - fit_before) < abs(raw_after - raw_before),
      f"fit moved {fit_after-fit_before:.1f}pp vs raw {raw_after-raw_before:.1f}pp")

# MACD cross detection
gap = pd.Series([-3.0, -2.0, -1.0, -0.5, 0.4, 0.9, 1.4])
check("weeks since cross-up counted from the crossing bar",
      fs._weeks_since_cross_up(gap) == 2, f"got {fs._weeks_since_cross_up(gap)}")
check("no cross reported while gap still negative",
      fs._weeks_since_cross_up(pd.Series([-1.0, -0.8, -0.5])) is None)

print("\n── 2. Touch detection ──────────────────────────────────────────")
s_touch = make_series(pullback_at=10, pullback_depth=-1.0)
sma = s_touch["Close"].rolling(50).mean()
t = fs._find_touch(s_touch["Low"], s_touch["Close"], sma)
check("valid touch inside [-2%, +8%] is found", t is not None)
if t:
    check("weeks-since-touch matches where it was planted",
          t["wks_since_touch"] == 10, f"got {t['wks_since_touch']}")
    check("touch depth recovered accurately",
          abs(t["touch_pct"] - (-1.0)) < 0.15, f"got {t['touch_pct']:.2f}%")
    check("bounce % is positive after a real bounce",
          t["bounce_pct"] > 0, f"got {t['bounce_pct']:.1f}%")

# Too deep a break is not a touch
s_deep = make_series(pullback_at=10, pullback_depth=-9.0)
check("a -9% break is rejected as a touch",
      fs._find_touch(s_deep["Low"], s_deep["Close"],
                     s_deep["Close"].rolling(50).mean()) is None)

# Touch that was subsequently broken must void the setup
s_broke = make_series(pullback_at=10, pullback_depth=-1.0, break_after=True)
check("touch followed by a break below the line is voided",
      fs._find_touch(s_broke["Low"], s_broke["Close"],
                     s_broke["Close"].rolling(50).mean()) is None)

print("\n── 3. End-to-end gates ─────────────────────────────────────────")
good = make_bounce()
row = fs.evaluate_ticker("TEST", good)
check("textbook bounce qualifies", row is not None)
if row:
    check("score is within 0..15", 0 <= row["score"] <= 15, f"score={row['score']}")
    check("tier is one of the three", row["tier"] in
          (fs.TIER_EARLY, fs.TIER_FRESH, fs.TIER_FURTHER), f"tier={row['tier']}")
    check("all display fields present",
          all(k in row for k in ("accel_3w", "macd_delta_3w", "slope_ratio",
                                 "dist_200w", "vol_ratio", "sector")))
    check("recent touch is reported within the lookback",
          0 <= row["wks_since_touch"] <= fs.TOUCH_LOOKBACK_WKS,
          f"{row['wks_since_touch']}w")

# Tier assignment is unit-tested against the MACD gap directly rather than by
# trying to synthesise a full qualifying series per tier. A smooth generator
# cannot produce a credible "Further Along" case: to stay in that tier the
# MACD gap must remain positive for 8+ weeks while momentum re-accelerates,
# and any synthetic slowdown deep enough to re-accelerate from also dips the
# gap below signal, which re-crosses it back to "Fresh". Contorting the
# generator to dodge that would be testing the generator, not the scanner.
def _tier_for(gap_series):
    gap = pd.Series(gap_series, dtype=float)
    wk = fs._weeks_since_cross_up(gap)
    if gap.iloc[-1] < 0:
        return fs.TIER_EARLY
    return fs.TIER_FRESH if (wk is not None and wk <= fs.FRESH_CROSS_WKS) else fs.TIER_FURTHER

check("gap still negative -> Early",
      _tier_for([-3, -2.5, -2, -1.5, -1, -0.4]) == fs.TIER_EARLY)
check("crossed up 2 weeks ago -> Fresh",
      _tier_for([-1, -0.5, 0.3, 0.8, 1.2]) == fs.TIER_FRESH)
check(f"crossed up exactly {fs.FRESH_CROSS_WKS} weeks ago -> still Fresh",
      _tier_for([-1] + [0.5] * (fs.FRESH_CROSS_WKS + 1)) == fs.TIER_FRESH)
check(f"crossed up {fs.FRESH_CROSS_WKS + 1} weeks ago -> Further Along",
      _tier_for([-1] + [0.5] * (fs.FRESH_CROSS_WKS + 2)) == fs.TIER_FURTHER)
check("a gap positive across the whole window -> Further Along",
      _tier_for([0.4] * 30) == fs.TIER_FURTHER)
check("the three tiers are mutually exclusive and total",
      len({_tier_for([-1, -0.5]), _tier_for([-1, 0.5]), _tier_for([0.4] * 30)}) == 3)

# Gate: loud volume
check("loud volume (2.5x) is rejected",
      fs.evaluate_ticker("LOUD", make_bounce(vol_ratio=2.5)) is None)

# Gate: a deep multi-month correction turns the 26w regression negative
deep = make_bounce(base_g=0.0035, dip_len=9, dip_g=-0.013, rally_g=0.011, dip_start=16)
check("deep multi-month correction is rejected (26w slope goes negative)",
      fs.evaluate_ticker("DEEP", deep) is None)

# Gate: a constant-rate trend has no momentum inflection to catch. Its MACD
# gap approaches steady state from below, so the 3w delta is positive but
# vanishing -- exactly what MIN_MACD_DELTA_PCT exists to reject.
flat = make_bounce(dip_len=0, base_g=0.0015, rally_g=0.0015)
check("constant-rate trend with no MACD inflection is rejected",
      fs.evaluate_ticker("FLAT", flat) is None)
flat2 = make_bounce(dip_len=0, base_g=0.003, rally_g=0.003)
check("constant-rate trend rejected at a steeper rate too",
      fs.evaluate_ticker("FLAT2", flat2) is None)
check("a real bounce clears the MACD magnitude floor",
      row is not None and
      row["macd_delta_3w"] / row["close"] * 100 >= fs.MIN_MACD_DELTA_PCT,
      f"{row['macd_delta_3w']/row['close']*100:.3f}% of price" if row else "")

# Gate: downtrend
down = make_series(growth_wk=-0.003, pullback_at=6, pullback_depth=-1.0, vol_ratio=0.8)
check("downtrend is rejected", fs.evaluate_ticker("DOWN", down) is None)

# Gate: not enough history
check("under 200 weekly bars is rejected",
      fs.evaluate_ticker("SHORT", make_bounce(n=120)) is None)

# Gate: no pullback at all (price never near the 50w line)
far = make_series(growth_wk=0.012, vol_ratio=0.8)
check("never-pulled-back name is rejected", fs.evaluate_ticker("FAR", far) is None)

# Gate: sub-$5
cheap = make_bounce()
cheap[["Close", "Low"]] = cheap[["Close", "Low"]] * 0.002
check("sub-$5 price is rejected", fs.evaluate_ticker("CHEAP", cheap) is None)

# Ranking contract
multi = []
for ds in range(3, 30):
    r = fs.evaluate_ticker(f"T{ds}", make_bounce(dip_start=ds))
    if r: multi.append(r)
if multi:
    mdf = pd.DataFrame(multi)
    mdf["_tr"] = mdf["tier"].map(fs._TIER_RANK)
    mdf = mdf.sort_values(["score", "_tr", "slope_ratio"], ascending=[False, True, False])
    check("ranking is score-descending",
          list(mdf["score"]) == sorted(mdf["score"], reverse=True))

print("\n── 3b. Exhaustion gates (RSI / MFI / extension) ────────────────")
# The reason these exist: a name printing RSI 69.8 / MFI 70.8 -- "Overbought
# / Take Profit" -- reached the top of a real scan, because nothing in the
# scanner asked whether the move was already spent.
_ok = make_bounce()
_c = pd.to_numeric(_ok["Close"])
check("RSI on a normal bounce lands in a believable band",
      40 <= fs._rsi(_c).iloc[-1] <= 68, f"RSI={fs._rsi(_c).iloc[-1]:.1f}")
check("RSI is Wilder-smoothed, not a simple mean",
      abs(fs._rsi(_c).iloc[-1] -
          (100 - 100/(1 + (_c.diff().clip(lower=0).rolling(14).mean() /
                           (-_c.diff()).clip(lower=0).rolling(14).mean()).iloc[-1]))) > 0.01)
_flat = pd.Series(np.linspace(10, 200, 300))          # never a down week
check("a monotonic melt-up reads as overbought", fs._rsi(_flat).iloc[-1] > fs.MAX_RSI,
      f"RSI={fs._rsi(_flat).iloc[-1]:.1f}")
check("a monotonic melt-up is REJECTED by the RSI gate",
      fs.evaluate_ticker("HOT", make_bounce(wobble=0.0)) is None)

_n = len(_ok)
_mfi_hi = _ok.copy()
_mfi_hi["Volume"] = np.where(_ok["Close"].diff() > 0, 5_000_000.0, 200_000.0)
check("volume piled onto up-weeks pushes MFI into the take-profit zone",
      fs._mfi(pd.to_numeric(_mfi_hi["High"]), pd.to_numeric(_mfi_hi["Low"]),
              pd.to_numeric(_mfi_hi["Close"]), pd.to_numeric(_mfi_hi["Volume"])).iloc[-1]
      > fs.MAX_MFI)

_far = make_bounce(rally_g=0.05)                      # runs far above the 50w line
_fc = pd.to_numeric(_far["Close"]); _fsma = _fc.rolling(50).mean()
_ext = (_fc.iloc[-1] - _fsma.iloc[-1]) / _fsma.iloc[-1] * 100
check("a name that ran far above the 50w line is over the extension gate",
      _ext > fs.MAX_EXT_50W, f"ext={_ext:.1f}%")
check("...and is rejected", fs.evaluate_ticker("FAR50", _far) is None)

# The scoring contradiction: paying for the move without charging for it
_hot = dict(close=100.0, accel_3w=20.0, macd_delta_3w=1.5, slope_ratio=0.8,
            dist_200w=10.0, vol_ratio=0.6, rsi=67.0, bounce_pct=10.0)
_cool = {**_hot, "rsi": 55.0}
check("acceleration is capped once RSI leaves the buy band",
      fs._score_row(_hot)[1]["accel"] < fs._score_row(_cool)[1]["accel"],
      f"hot={fs._score_row(_hot)[1]['accel']} cool={fs._score_row(_cool)[1]['accel']}")
_spent = {**_cool, "bounce_pct": 80.0}
check("a bounce that already ran 80% loses its 'room left' points",
      fs._score_row(_spent)[1]["dist200"] < fs._score_row(_cool)[1]["dist200"],
      f"spent={fs._score_row(_spent)[1]['dist200']} fresh={fs._score_row(_cool)[1]['dist200']}")
check("bounce_pct now actually affects the total",
      fs._score_row(_spent)[0] < fs._score_row(_cool)[0])

print("\n── 4. Partial-week handling ────────────────────────────────────")
# The Friday-evening email is the whole reason this rule exists: it must
# treat the week that just closed as SETTLED, or every weekly email reports
# data a full week stale.
from unittest.mock import patch
_bar = pd.Timestamp("2026-08-24")          # Mon; week runs Aug 24-28
def _at(when):
    ts = pd.Timestamp(when)
    with patch.object(pd.Timestamp, "utcnow", staticmethod(lambda: ts)):
        return fs._is_partial_week(_bar)

check("Mon of the bar's own week is partial",       _at("2026-08-24 22:30"))
check("Thu of the bar's own week is partial",       _at("2026-08-27 22:30"))
check("Fri BEFORE the close is still partial",      _at("2026-08-28 15:00"))
check("Fri AFTER the close is SETTLED (the email slot)",
      not _at("2026-08-28 22:30"), "5:30pm CT = 22:30 UTC")
check("Sat is settled",                             not _at("2026-08-29 12:00"))
check("the following week is settled",              not _at("2026-08-31 12:00"))
_holiday_bar = pd.Timestamp("2026-08-25")  # Tue-labelled, holiday-shortened week
with patch.object(pd.Timestamp, "utcnow",
                  staticmethod(lambda: pd.Timestamp("2026-08-28 22:30"))):
    check("a Tue-labelled holiday week is normalised to its own Monday",
          not fs._is_partial_week(_holiday_bar))

live = make_series(growth_wk=0.004, pullback_at=6, pullback_depth=-1.0, vol_ratio=0.8)
live.index = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None).normalize(),
                           periods=len(live), freq="W-MON")
n_before = len(live)
check("current in-progress week is detected as partial",
      fs._is_partial_week(live.index[-1]), f"last bar {live.index[-1].date()}")
check("a bar from 3 weeks ago is NOT partial",
      not fs._is_partial_week(live.index[-4]))

print("\n── 5. Scoring + rendering ──────────────────────────────────────")
# The slope ratio is 26w rise / 52w rise, so a huge value means a near-zero
# denominator, not a stronger trend. It must NOT score as best-in-class.
_rp = lambda r: fs._score_row(dict(close=100.0, accel_3w=5.0, macd_delta_3w=0.5,
                                   slope_ratio=r, dist_200w=10.0, vol_ratio=0.8,
                                   rsi=55.0, bounce_pct=10.0))[1]["ratio"]
check("healthy accelerating ratio (0.98) scores max", _rp(0.98) == 3)
check("steady-ish ratio (0.62) scores max", _rp(0.62) == 3)
check("blown-up ratio 18.52 scores ZERO, not max", _rp(18.52) == 0, f"got {_rp(18.52)}")
check("ratio 4.70 is penalised as unstable", _rp(4.70) == 1, f"got {_rp(4.70)}")
check("ratio 2.69 sits mid-band", _rp(2.69) == 2, f"got {_rp(2.69)}")
check("decaying ratio 0.30 scores low", _rp(0.30) == 1, f"got {_rp(0.30)}")
check("the ratio component actually discriminates across a real spread",
      len({_rp(r) for r in (0.30, 0.48, 0.98, 2.69, 4.70, 18.52)}) >= 4)

base = dict(close=100.0, accel_3w=20.0, macd_delta_3w=1.5, slope_ratio=0.8,
            dist_200w=10.0, vol_ratio=0.6, rsi=55.0, bounce_pct=10.0)
total, parts = fs._score_row(base)
check("best-case inputs score 15/15", total == 15, f"got {total} {parts}")
worst = dict(close=100.0, accel_3w=-10.0, macd_delta_3w=0.01, slope_ratio=0.1,
             dist_200w=300.0, vol_ratio=1.09, rsi=67.0, bounce_pct=200.0)
tw, pw = fs._score_row(worst)
check("worst-case inputs score low", tw <= 3, f"got {tw} {pw}")
check("MACD scoring is price-normalised (not a price filter in disguise)",
      fs._score_row({**base, "close": 2000.0, "macd_delta_3w": 30.0})[1]["macd"] ==
      fs._score_row({**base, "close": 100.0, "macd_delta_3w": 1.5})[1]["macd"])

demo = pd.DataFrame([
    dict(rank=1, ticker="AAA", sector="Semis", tier=fs.TIER_FRESH, score=15,
         accel_3w=31.9, macd_delta_3w=4.74, slope_ratio=0.62, dist_200w=1.4, vol_ratio=0.88),
    dict(rank=2, ticker="BBB", sector="Finance", tier=fs.TIER_EARLY, score=8,
         accel_3w=-6.5, macd_delta_3w=1.99, slope_ratio=0.90, dist_200w=182.4, vol_ratio=0.50),
])
app_html = fs.app_table_html(demo)
mail_html = fs.email_table_html(demo)
check("app table renders both rows", app_html.count("AAA") == 1 and app_html.count("BBB") == 1)
check("app table has no unbalanced divs",
      app_html.count("<div") == app_html.count("</div>"),
      f"{app_html.count('<div')} open / {app_html.count('</div>')} close")
check("email table uses real <table> markup (Outlook-safe)",
      "<table" in mail_html and "display:flex" not in mail_html and "display:grid" not in mail_html)
check("email table balances <tr>/<td>",
      mail_html.count("<tr") == mail_html.count("</tr>") and
      mail_html.count("<td") == mail_html.count("</td>"))
check("extended name (182% over 200W) is colored as a warning, not green",
      fs._dist_color(182.4) == fs._C_NEG)
check("below the 200W line is colored green (room, not danger)",
      fs._dist_color(-21.9) == fs._C_DIST)
check("empty frame renders empty string, not a broken shell",
      fs.app_table_html(pd.DataFrame()) == "" and fs.email_table_html(pd.DataFrame()) == "")

print("\n── 6. Universe wiring ──────────────────────────────────────────")
u = fs.universe_for("FTF")
check("FTF stocks-only universe is ~450-500 names", 430 <= len(u) <= 540, f"got {len(u)}")
check("leveraged ETFs excluded by default", "TQQQ" not in u and "SOXL" not in u)
check("plain index ETFs excluded by default", "SPY" not in u and "XLK" not in u)
check("include_funds=True brings them back", "SPY" in fs.universe_for("FTF", include_funds=True))
check("no duplicate tickers", len(u) == len(set(u)))
_ORIG = ["COIN","DE","FCX","MSTR","JNJ","MELI","ALNY","MRK","SPGI","VRTX","V","MA",
         "XOM","AMGN","NFLX","MRVL","ISRG","DHI","SNPS","CDNS","NXPI","ORLY","ULTA",
         "PDD","NVR","PTC","CME"]
_absent = [t for t in _ORIG if t not in u]
check("every ticker from the reference scan is in the universe",
      not _absent, f"missing: {_absent}")
check("extras can be turned off",
      "COIN" not in fs.universe_for("FTF", include_extras=False))
unmapped = [t for t in u if fs.sector_of(t) == "Other"]
check("sector map covers >90% of the universe",
      len(unmapped) < len(u) * 0.10, f"{len(unmapped)} unmapped: {unmapped[:12]}")

print("\n" + "=" * 64)
print(f"RESULT: {len(PASSES)} passed, {len(FAILS)} failed")
if FAILS:
    print("FAILED:")
    for f in FAILS: print("  -", f)
sys.exit(1 if FAILS else 0)
