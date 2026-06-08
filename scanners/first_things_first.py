"""
scanners/first_things_first.py — "First Things First" high-conviction setup scanner

Applies 14 strict multi-timeframe conditions across weekly AND daily charts.
Universe: full S&P 500 + ETFs + 3× leveraged ETFs (~482 tickers via FTF_UNIVERSE).
Any stock passing ALL 13 conditions is surfaced in the FTF tab under Strategies.
Returns (results, diagnostics) — caller renders the empty state card if no results.

Weekly conditions (ALL must hold):
  W2  Not extended (price within 10% above SMA20W)
  W3  RSI 35–75 (allows strong-momentum stocks above 70)
  W4  MACD > Signal line
  W6  Price > SMA20W
  W9  Uptrend (price > SMA50W OR HH/HL confirmed)
  (W5 removed — weekly volume from resampled daily data is unreliable; D6 daily covers this)
  (W1 removed — redundant with W9)
  (W7 removed — W4 MACD>Signal is sufficient)
  (W8 removed)

Daily conditions (ALL must hold):
  D1  Not extended (price within 8% above SMA9D)
  D2  RSI 35–70
  D3  MACD > Signal line
  D4  Price > SMA9D
  D5  Histogram rising (hist[-1] > hist[-2]) — momentum accelerating, not fading
  D6  Volume > 0.7× 20-day average (relaxed from strict >1.0×)

Cross-timeframe:
  X1  ADX > 16 AND ADX rising (ADX[-1] > ADX[-4])
  X2  No bearish divergence (price trend UP but RSI trend DOWN → excluded)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import get_price_history
from utils import calc_ema, calc_sma, calc_rsi


# ── Indicator helpers ──────────────────────────────────────────────────────────

def _macd(close: pd.Series, fast=12, slow=26, sig=9):
    line   = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig,  adjust=False).mean()
    hist   = line - signal
    return line, signal, hist


def _adx_series(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    """Return full ADX series."""
    try:
        prev_cl = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_cl).abs(),
            (low  - prev_cl).abs(),
        ], axis=1).max(axis=1)
        atr  = tr.ewm(com=period - 1, adjust=False).mean()
        up   = high.diff();  down = -low.diff()
        pdm  = up.where((up > down) & (up > 0), 0.0)
        ndm  = down.where((down > up) & (down > 0), 0.0)
        safe = atr.replace(0, np.nan)
        pdi  = 100 * pdm.ewm(com=period - 1, adjust=False).mean() / safe
        ndi  = 100 * ndm.ewm(com=period - 1, adjust=False).mean() / safe
        denom = (pdi + ndi).replace(0, np.nan)
        dx   = (100 * (pdi - ndi).abs() / denom).fillna(0)
        return dx.ewm(com=period - 1, adjust=False).mean()
    except Exception:
        return pd.Series(dtype=float)


def _bearish_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 14) -> bool:
    """
    True if price is making higher highs but RSI is making lower highs
    over the last `lookback` bars — classic bearish divergence.
    """
    try:
        if len(close) < lookback or len(rsi) < lookback:
            return False
        price_trend_up = float(close.iloc[-1]) > float(close.iloc[-lookback])
        rsi_trend_down = float(rsi.iloc[-1])   < float(rsi.iloc[-lookback])
        return price_trend_up and rsi_trend_down
    except Exception:
        return False


# ── Weekly check ───────────────────────────────────────────────────────────────

def _resample_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Resample a daily OHLCV DataFrame to weekly bars (week ending Friday)."""
    df = df_daily.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Normalise column names to lower-case
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    agg = {"close": "last", "open": "first", "high": "max", "low": "min", "volume": "sum"}
    agg = {k: v for k, v in agg.items() if k in df.columns}
    weekly = df.resample("W-FRI").agg(agg).dropna(subset=["close"])
    return weekly


def _check_weekly(ticker: str, df_daily: pd.DataFrame) -> dict:
    """
    Evaluate all weekly conditions from a pre-fetched daily DataFrame
    (resampled to weekly bars in-memory — no separate API call).
    Returns dict with per-condition booleans and a 'pass' key.
    """
    result = {k: False for k in ["W2","W3","W4","W6","W9","pass"]}
    result["detail"] = {}
    result["error"] = None
    try:
        raw = _resample_weekly(df_daily)
        if raw is None or raw.empty or len(raw) < 26:
            result["error"] = f"insufficient_weekly_bars:{len(raw) if raw is not None else 0}"
            return result

        close_w = raw["close"].squeeze()
        high_w  = raw["high"].squeeze()
        low_w   = raw["low"].squeeze()
        vol_w   = raw["volume"].squeeze()

        px = float(close_w.iloc[-1])

        # SMA20W, SMA50W
        sma20_w = float(calc_sma(close_w, 20).dropna().iloc[-1])
        sma50_w = float(calc_sma(close_w, 50).dropna().iloc[-1]) if len(close_w) >= 50 else sma20_w

        # HH/HL: last 5 weekly bars vs prior 5
        hh_hl = False
        if len(high_w) >= 10:
            hh_hl = (float(high_w.iloc[-5:].max()) > float(high_w.iloc[-10:-5].max()) and
                     float(low_w.iloc[-5:].min())  > float(low_w.iloc[-10:-5].min()))

        # Tight Base: last 10 weekly bars range < 5% of SMA20W
        tight_base = False
        if len(close_w) >= 10 and sma20_w > 0:
            rng = float(close_w.iloc[-10:].max() - close_w.iloc[-10:].min())
            tight_base = (rng / sma20_w * 100) < 5.0

        # RSI — calc_rsi() returns a float directly
        rsi_w_v = float(calc_rsi(close_w))

        # MACD
        macd_w, sig_w, hist_w = _macd(close_w)
        m_w  = float(macd_w.dropna().iloc[-1])
        s_w  = float(sig_w.dropna().iloc[-1])
        h_w  = float(hist_w.dropna().iloc[-1])
        h_w_prev = float(hist_w.dropna().iloc[-2]) if len(hist_w.dropna()) >= 2 else h_w

        # Volume
        avg_vol_20w = float(vol_w.iloc[-21:-1].mean()) if len(vol_w) >= 21 else float(vol_w.mean())
        cur_vol_w   = float(vol_w.iloc[-1])
        vol_ratio_w = cur_vol_w / avg_vol_20w if avg_vol_20w > 0 else 1.0

        # Evaluate conditions
        result["W2"] = (sma20_w > 0) and (px <= sma20_w * 1.15)          # within 15%
        result["W3"] = 35 <= rsi_w_v <= 75
        result["W4"] = m_w > s_w
        result["W6"] = px > sma20_w
        result["W9"] = (px > sma50_w) or hh_hl

        result["detail"] = {
            "hh_hl": hh_hl, "tight_base": tight_base,
            "rsi_w": round(rsi_w_v, 1),
            "macd_w": round(m_w, 4), "sig_w": round(s_w, 4),
            "hist_w": round(h_w, 4), "hist_w_prev": round(h_w_prev, 4),
            "sma20_w": round(sma20_w, 2), "sma50_w": round(sma50_w, 2),
            "vol_ratio_w": round(vol_ratio_w, 2),
        }
        result["pass"] = all(result[k] for k in ["W2","W3","W4","W6","W9"])

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return result


# ── Daily check ────────────────────────────────────────────────────────────────

def _check_daily(ticker: str, price: float, df_daily: pd.DataFrame = None) -> dict:
    """Evaluate all daily + cross-timeframe conditions.
    Accepts a pre-fetched df_daily to avoid a redundant API call."""
    result = {k: False for k in ["D1","D2","D3","D4","D5","D6","X1","X2","pass"]}
    result["detail"] = {}
    try:
        df = df_daily if (df_daily is not None and not df_daily.empty) else get_price_history(ticker, period="6mo")
        if df is None or df.empty or len(df) < 30:
            return result

        close_d = df["Close"].squeeze()
        high_d  = df["High"].squeeze()  if "High"   in df.columns else None
        low_d   = df["Low"].squeeze()   if "Low"    in df.columns else None
        vol_d   = df["Volume"].squeeze() if "Volume" in df.columns else None

        px = float(close_d.iloc[-1])

        # EMAs / SMAs
        sma9_d  = float(calc_ema(close_d, 9).dropna().iloc[-1])
        sma20_d = float(calc_sma(close_d, 20).dropna().iloc[-1])

        # RSI — calc_rsi() returns a float; also build a Series for divergence check
        rsi_v  = float(calc_rsi(close_d))
        _delta = close_d.diff().dropna()
        _gain  = _delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        _loss  = (-_delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        _rs    = _gain / _loss.replace(0, float("nan"))
        rsi_d  = (100 - 100 / (1 + _rs)).fillna(50)

        # MACD
        macd_d, sig_d, hist_d = _macd(close_d)
        m_d = float(macd_d.dropna().iloc[-1])
        s_d = float(sig_d.dropna().iloc[-1])
        h_d = float(hist_d.dropna().iloc[-1])
        h_d_prev = float(hist_d.dropna().iloc[-2]) if len(hist_d.dropna()) >= 2 else h_d

        # Volume — D6: strictly above 20-day average (>1.0×)
        avg_vol = float(vol_d.iloc[-21:-1].mean()) if (vol_d is not None and len(vol_d) >= 21) else None
        cur_vol = float(vol_d.iloc[-1]) if vol_d is not None else None
        vol_above = (cur_vol > 0.7 * avg_vol) if (cur_vol and avg_vol) else False  # D6: relaxed >0.7×

        # Supply zone — display only (no longer a hard gate)
        high_20d = float(close_d.iloc[-20:].max()) if len(close_d) >= 20 else px
        pct_below_high = (high_20d - px) / high_20d * 100 if high_20d > 0 else 0

        # ADX
        adx_series = pd.Series(dtype=float)
        if high_d is not None and low_d is not None:
            adx_series = _adx_series(close_d, high_d, low_d)
        adx_v     = float(adx_series.dropna().iloc[-1])   if len(adx_series.dropna()) >= 1 else np.nan
        adx_prev  = float(adx_series.dropna().iloc[-4])   if len(adx_series.dropna()) >= 4 else np.nan
        adx_ok    = (not np.isnan(adx_v)) and adx_v > 16   # X1: just >16, rising = display only
        adx_rising= (not np.isnan(adx_prev)) and adx_v > adx_prev   # shown in table, not a gate

        # Bearish divergence
        div = _bearish_divergence(close_d, rsi_d, lookback=14)

        # Demand zone (preferred, not mandatory — used for display only)
        low_10d = float(close_d.iloc[-10:].min()) if len(close_d) >= 10 else px
        in_demand = px <= low_10d * 1.05   # within 5% above recent swing low

        result["D1"] = (sma9_d > 0) and (px <= sma9_d * 1.08)  # within 8% above SMA9
        result["D2"] = 35 <= rsi_v <= 70
        result["D3"] = m_d > s_d
        result["D4"] = px > sma9_d
        result["D5"] = h_d > h_d_prev                           # daily histogram rising — display only
        result["D6"] = vol_above                                 # volume > 0.7× 20-day avg
        # D7 removed — D6 now covers volume strictly (>1.0× vs old 0.8×)
        result["X1"] = adx_ok
        result["X2"] = not div

        result["detail"] = {
            "rsi_d":          round(rsi_v, 1),
            "macd_d":         round(m_d, 4),
            "sig_d":          round(s_d, 4),
            "hist_d":         round(h_d, 4),
            "hist_d_prev":    round(h_d_prev, 4),
            "sma9_d":         round(sma9_d, 2),
            "adx":            round(adx_v, 1) if not np.isnan(adx_v) else None,
            "adx_rising":     adx_rising,
            "bearish_div":    div,
            "in_demand":      in_demand,
            "pct_below_high": round(pct_below_high, 1),   # display only
        }
        daily_conditions = ["D1","D2","D3","D4","D5","D6","X1","X2"]  # D7 removed; D5 restored
        result["pass"] = all(result[k] for k in daily_conditions)

    except Exception:
        pass
    return result


# ── Main scanner ───────────────────────────────────────────────────────────────

def run_ftf_scan(
    tickers: list[str],
    status_fn=None,
) -> tuple[list[dict], dict]:
    """
    Run the First-Things-First scan across tickers.
    Returns (results, diagnostics) where:
      results     — list of dicts for qualifying tickers, sorted by ADX desc
      diagnostics — {total, weekly_pass, daily_pass} pass counts
    Each result dict contains: ticker, price, weekly_detail, daily_detail,
    weekly_flags, daily_flags.
    """
    qualified    = []
    weekly_pass  = 0
    data_ok      = 0
    w_errors     = {}   # ticker -> error string for first 5 weekly errors
    weekly_passers = []  # tickers that passed weekly but may have failed daily
    # Per-condition fail counters (how many tickers failed EACH condition)
    w_fails = {k: 0 for k in ["W2","W3","W4","W6","W9"]}
    d_fails = {k: 0 for k in ["D1","D2","D3","D4","D5","D6","X1","X2"]}

    for i, ticker in enumerate(tickers):
        if status_fn:
            status_fn(i, len(tickers), ticker)

        # One fetch: 2y daily data — reused for weekly resample + daily checks
        try:
            df_daily = get_price_history(ticker, period="2y", interval="1d")
            if df_daily is None or df_daily.empty or len(df_daily) < 30:
                continue
            close_col = next((c for c in df_daily.columns if c.lower() == "close"), None)
            if close_col is None:
                continue
            price = float(df_daily[close_col].dropna().iloc[-1])
            data_ok += 1
        except Exception:
            continue

        # Weekly check — resamples daily data in-memory, no extra API call
        wk = _check_weekly(ticker, df_daily)
        if wk.get("error") and len(w_errors) < 5:
            w_errors[ticker] = wk["error"]
        for k in w_fails:
            if not wk.get(k, False):
                w_fails[k] += 1
        if not wk["pass"]:
            continue
        weekly_pass += 1
        weekly_passers.append({
            "ticker": ticker, "price": round(price, 2),
            "w_detail": wk.get("detail", {}),
        })

        # Daily + cross-TF check — reuses the same daily DataFrame
        dy = _check_daily(ticker, price, df_daily=df_daily)
        for k in d_fails:
            if not dy.get(k, False):
                d_fails[k] += 1
        if not dy["pass"]:
            # store daily detail for debugging
            weekly_passers[-1]["d_detail"] = dy.get("detail", {})
            weekly_passers[-1]["d_flags_fail"] = [k for k in ["D1","D2","D3","D4","D6","X1","X2"] if not dy.get(k, False)]
            continue

        # Both pass — build condition flag strings
        w_flags = []
        w_map = {
            "W2": "Not Extended", "W3": "RSI ✓",
            "W4": "MACD>Sig",     "W6": "P>SMA20W", "W9": "Uptrend",
        }
        d_map = {
            "D1": "Not Ext'd",  "D2": "RSI ✓",   "D3": "MACD>Sig",
            "D4": "P>SMA9",     "D5": "Hist↑",    "D6": "Vol>0.7×",
            "X1": "ADX>16",     "X2": "No BearDiv",
        }
        for k, lbl in w_map.items():
            if wk.get(k):
                w_flags.append(lbl)
        d_flags = []
        for k, lbl in d_map.items():
            if dy.get(k):
                d_flags.append(lbl)

        qualified.append({
            "ticker":       ticker,
            "price":        round(price, 2),
            "w_detail":     wk.get("detail", {}),
            "d_detail":     dy.get("detail", {}),
            "w_flags":      w_flags,
            "d_flags":      d_flags,
        })

    # Sort by ADX descending (higher ADX = stronger trend)
    qualified.sort(
        key=lambda r: r["d_detail"].get("adx") or 0,
        reverse=True,
    )
    diagnostics = {
        "total":        len(tickers),
        "data_ok":      data_ok,
        "weekly_pass":  weekly_pass,
        "daily_pass":   len(qualified),
        "w_fails":      w_fails,   # {condition: n_tickers_that_failed}
        "d_fails":      d_fails,
        "w_errors":        w_errors,       # sample of weekly exceptions {ticker: error_str}
        "weekly_passers":  weekly_passers, # tickers that passed weekly (with detail)
    }
    return qualified, diagnostics
