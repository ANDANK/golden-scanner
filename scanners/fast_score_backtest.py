# scanners/fast_score_backtest.py — walk-forward backtest of the Fast Score scanner
#
# THE ONE DESIGN DECISION THAT MATTERS
# -----------------------------------
# Every historical evaluation calls the LIVE scanner —
# fast_score.evaluate_ticker() — against a SLICE of the weekly bars ending at
# the week being tested. Nothing about the gates or the score is reimplemented
# here.
#
# That buys two things a reimplementation cannot:
#
#   1. No look-ahead. evaluate_ticker() only ever reads the frame it is handed
#      and reports on its final bar, so a slice ending at week i physically
#      cannot see week i+1. Every regression, MACD, RSI, MFI, SMA and volume
#      ratio is recomputed from that slice alone.
#   2. No drift. Change a gate or a threshold in fast_score.py and this
#      backtest tests the changed scanner on the next run. A hand-rolled
#      vectorised copy would be faster and would quietly start measuring a
#      scanner that no longer exists.
#
# It costs ~3.75 ms per evaluation, so a 456-ticker, 3-year run is roughly
# 71k evaluations ≈ 4-5 minutes. That is why this runs headless in GitHub
# Actions and the app reads the committed result, rather than scanning live
# in a Streamlit page (see CLAUDE.md → Data snapshots).
#
# WHAT IT MEASURES
#   For every (ticker, week) the scanner would have flagged, the forward
#   return at each horizon, the best and worst close in between (MFE/MAE),
#   and the same-window SPY return so the number can be read as excess
#   rather than as "a bull market happened".
#
# WHAT IT CANNOT MEASURE — read before trusting a headline number
#   * Survivorship. The universe is today's list, so companies that were
#     delisted, acquired or went to zero are simply absent. This biases
#     results OPTIMISTIC and no amount of care here removes it.
#   * Index membership drift. Names added to the S&P recently are backtested
#     over years when they were not in it.
#   * Execution. Entries assume the weekly close of the signal bar, with no
#     slippage, spread, commission or gap risk.
#   * Overlap. One ticker qualifying for six weeks running is six correlated
#     observations, not six independent ones — see MIN_REPEAT_GAP_WKS.

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import get_price_history, prefetch_tickers
from scanners import fast_score as fs

HORIZONS_WKS = (4, 8, 12)      # forward windows reported, in weeks
BENCHMARK = "SPY"
# A name that keeps qualifying week after week is the same setup observed
# repeatedly, not a fresh signal. Re-entries closer together than this are
# dropped so a single long-running setup cannot dominate the statistics.
MIN_REPEAT_GAP_WKS = 8
DEFAULT_TEST_YEARS = 3
FETCH_PERIOD = "10y"


def _forward_stats(close: pd.Series, i: int, horizon: int) -> dict | None:
    """Return / MFE / MAE from the close at bar i to bar i+horizon."""
    if i + horizon >= len(close):
        return None
    entry = float(close.iloc[i])
    if not np.isfinite(entry) or entry <= 0:
        return None
    window = close.iloc[i + 1: i + horizon + 1]
    if window.empty:
        return None
    exit_px = float(close.iloc[i + horizon])
    return {
        "ret": (exit_px - entry) / entry * 100.0,
        "mfe": (float(window.max()) - entry) / entry * 100.0,
        "mae": (float(window.min()) - entry) / entry * 100.0,
    }


def backtest_ticker(ticker: str, weekly: pd.DataFrame,
                    start_idx: int, horizons=HORIZONS_WKS) -> list[dict]:
    """Replay the live scanner over every settled week from start_idx on.

    One row per week the scanner would have flagged, carrying the metrics it
    saw at the time plus the forward outcome it could not see.
    """
    if weekly is None or weekly.empty:
        return []
    df = weekly.dropna(subset=["Close"])
    close = pd.to_numeric(df["Close"], errors="coerce")
    n = len(df)
    max_h = max(horizons)
    out: list[dict] = []
    last_hit = -10 ** 9

    # Stop max_h short of the end: a pick with no forward window yet is not an
    # observation, and including it as a 0% return would drag every average
    # toward zero.
    for i in range(max(start_idx, fs.MIN_WEEKLY_BARS - 1), n - max_h):
        if i - last_hit < MIN_REPEAT_GAP_WKS:
            continue
        row = fs.evaluate_ticker(ticker, df.iloc[: i + 1])
        if not row:
            continue
        last_hit = i
        rec = {
            "ticker": ticker,
            "date": str(pd.Timestamp(df.index[i]).date()),
            "bar": i,
            "tier": row["tier"],
            "score": row["score"],
            "close": row["close"],
            "rsi": row["rsi"],
            "mfi": row["mfi"],
            "ext_50w": row["ext_50w"],
            "dist_200w": row["dist_200w"],
            "slope_ratio": row["slope_ratio"],
            "vol_ratio": row["vol_ratio"],
        }
        for h in horizons:
            st = _forward_stats(close, i, h)
            if st:
                rec[f"ret_{h}w"] = st["ret"]
                rec[f"mfe_{h}w"] = st["mfe"]
                rec[f"mae_{h}w"] = st["mae"]
        out.append(rec)
    return out


def _benchmark_series(period: str = FETCH_PERIOD) -> pd.Series | None:
    try:
        bm = get_price_history(BENCHMARK, period, fs.FETCH_INTERVAL)
        if bm is None or bm.empty or "Close" not in bm:
            return None
        return pd.to_numeric(bm["Close"], errors="coerce").dropna()
    except Exception:
        return None


def _attach_benchmark(records: list[dict], bench: pd.Series | None,
                      horizons=HORIZONS_WKS) -> None:
    """Add the same-window benchmark return and the excess over it.

    Aligned by DATE, not by bar index: a ticker's frame and SPY's frame can
    differ in length (late listings, halts), so matching on position would
    silently compare mismatched windows.
    """
    if bench is None or bench.empty:
        return
    bdates = pd.Index([pd.Timestamp(d).normalize() for d in bench.index])
    for r in records:
        d = pd.Timestamp(r["date"]).normalize()
        pos = bdates.searchsorted(d)
        if pos >= len(bench):
            continue
        entry = float(bench.iloc[pos])
        if not np.isfinite(entry) or entry <= 0:
            continue
        for h in horizons:
            if f"ret_{h}w" not in r or pos + h >= len(bench):
                continue
            bret = (float(bench.iloc[pos + h]) - entry) / entry * 100.0
            r[f"bench_{h}w"] = bret
            r[f"excess_{h}w"] = r[f"ret_{h}w"] - bret


SCORE_BANDS = {"12-15": (12, 15), "9-11": (9, 11), "6-8": (6, 8), "0-5": (0, 5)}


def aggregate_rows(rows: list[dict], h: int) -> dict | None:
    """Statistics for one group of picks at one horizon. Module-level so the
    app can cross-tabulate stored picks without re-running the backtest."""
    vals = [r[f"ret_{h}w"] for r in rows if f"ret_{h}w" in r]
    if not vals:
        return None
    ex = [r[f"excess_{h}w"] for r in rows if f"excess_{h}w" in r]
    mae = [r[f"mae_{h}w"] for r in rows if f"mae_{h}w" in r]
    mfe = [r[f"mfe_{h}w"] for r in rows if f"mfe_{h}w" in r]
    arr = np.array(vals, dtype=float)
    return {
        "n": len(vals),
        "win_rate": float((arr > 0).mean() * 100.0),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "stdev": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "best": float(arr.max()),
        "worst": float(arr.min()),
        "mean_excess": float(np.mean(ex)) if ex else None,
        "win_rate_vs_bench": float((np.array(ex) > 0).mean() * 100.0) if ex else None,
        "mean_mfe": float(np.mean(mfe)) if mfe else None,
        "mean_mae": float(np.mean(mae)) if mae else None,
        # Whether the excess is distinguishable from zero at all. Without
        # this a table of point estimates invites the reader to treat any
        # positive number as an edge -- which is precisely how a +5.88%
        # reading on 13 picks got reported as a finding, then collapsed to
        # +1.17% and statistical nothing once the sample grew to 65.
        **_significance(ex),
    }


def _significance(ex: list[float]) -> dict:
    """Standard error, t-statistic and 95% CI for a mean excess return."""
    if len(ex) < 2:
        return {"excess_se": None, "excess_t": None,
                "excess_ci_lo": None, "excess_ci_hi": None, "excess_sig": False}
    arr = np.array(ex, dtype=float)
    m = float(arr.mean())
    se = float(arr.std(ddof=1) / np.sqrt(len(arr)))
    if se <= 0:
        return {"excess_se": 0.0, "excess_t": None,
                "excess_ci_lo": m, "excess_ci_hi": m, "excess_sig": False}
    t = m / se
    return {
        "excess_se": se, "excess_t": float(t),
        "excess_ci_lo": float(m - 1.96 * se), "excess_ci_hi": float(m + 1.96 * se),
        "excess_sig": bool(abs(t) > 1.96),
    }


def cross_tab(records: list[dict], horizons=HORIZONS_WKS) -> dict:
    """Score band x tier. The combination a trader actually acts on -- "a 13
    that just crossed" is a different proposition from "a 13 that crossed four
    months ago" -- and neither the band nor the tier alone can show it.

    Cells go thin fast: splitting ~200 picks twelve ways leaves single digits
    in the interesting corners, so every caller must surface n alongside the
    number or the table invites exactly the conclusion it cannot support.
    """
    out: dict[str, dict] = {}
    for band, (lo, hi) in SCORE_BANDS.items():
        for tier in (fs.TIER_EARLY, fs.TIER_FRESH, fs.TIER_FURTHER):
            rows = [r for r in records
                    if lo <= r.get("score", -1) <= hi and r.get("tier") == tier]
            if not rows:
                continue
            per = {}
            for h in horizons:
                a = aggregate_rows(rows, h)
                if a:
                    per[f"{h}w"] = a
            if per:
                out[f"{band} · {tier}"] = per
    return out


def summarise(records: list[dict], horizons=HORIZONS_WKS) -> dict:
    """Aggregate rows into overall / per-tier / per-score-band statistics."""
    _agg = aggregate_rows
    bands = SCORE_BANDS
    out = {
        "n_picks": len(records),
        "n_tickers": len({r["ticker"] for r in records}),
        "date_min": min((r["date"] for r in records), default=None),
        "date_max": max((r["date"] for r in records), default=None),
        "horizons": list(horizons),
        "overall": {}, "by_tier": {}, "by_score_band": {},
        "by_segment": cross_tab(records, horizons),
    }
    for h in horizons:
        a = _agg(records, h)
        if a:
            out["overall"][f"{h}w"] = a
        for tier in (fs.TIER_EARLY, fs.TIER_FRESH, fs.TIER_FURTHER):
            a = _agg([r for r in records if r["tier"] == tier], h)
            if a:
                out["by_tier"].setdefault(tier, {})[f"{h}w"] = a
        for label, (lo, hi) in bands.items():
            a = _agg([r for r in records if lo <= r["score"] <= hi], h)
            if a:
                out["by_score_band"].setdefault(label, {})[f"{h}w"] = a
    return out


def run_backtest(universe: list[str], test_years: int = DEFAULT_TEST_YEARS,
                 horizons=HORIZONS_WKS, progress_cb=None) -> tuple[list[dict], dict]:
    """Full walk-forward backtest. Returns (pick records, summary)."""
    tickers = list(dict.fromkeys(universe))
    total = len(tickers)
    test_weeks = int(test_years * 52)

    for i in range(0, total, fs.PREFETCH_CHUNK):
        chunk = tickers[i:i + fs.PREFETCH_CHUNK]
        if progress_cb:
            progress_cb(i, total, f"Downloading weekly bars ({i + len(chunk)}/{total})…")
        try:
            prefetch_tickers(chunk, FETCH_PERIOD, fs.FETCH_INTERVAL)
        except Exception:
            pass

    records: list[dict] = []
    for i, t in enumerate(tickers):
        if progress_cb:
            progress_cb(i, total, f"Backtesting {t} ({i + 1}/{total})…")
        try:
            weekly = get_price_history(t, FETCH_PERIOD, fs.FETCH_INTERVAL)
            if weekly is None or weekly.empty:
                continue
            n = len(weekly.dropna(subset=["Close"]))
            start_idx = max(fs.MIN_WEEKLY_BARS - 1, n - test_weeks)
            records.extend(backtest_ticker(t, weekly, start_idx, horizons))
        except Exception:
            continue

    _attach_benchmark(records, _benchmark_series(), horizons)
    records.sort(key=lambda r: (r["date"], r["ticker"]))
    return records, summarise(records, horizons)
